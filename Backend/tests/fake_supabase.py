"""
In-memory stand-in for the supabase-py client.

Supports the PostgREST builder subset the app actually uses:
    table().select()/insert()/update().eq()/neq()/in_()/order()/limit()/single().execute()

Filtered updates are applied atomically under a lock, which is what makes the
compare-and-swap pattern in bookings.py testable without a live database.

LIMITATION: this validates application-level logic only. It does not reproduce
Postgres isolation semantics — true concurrency guarantees still need a real
database, which arrives with the Phase 1.1 test-database work.
"""
import copy
import threading
from typing import Any

from postgrest.exceptions import APIError


class FakeAPIError(APIError):
    """
    Subclasses the real APIError so production `except APIError` blocks catch
    it. A standalone exception class would let constraint-violation handling
    pass tests while failing in production.
    """

    def __init__(self, message: str):
        super().__init__({"message": message, "code": "23505"})   # unique_violation


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, db: "FakeSupabase", table: str):
        self._db = db
        self._table = table
        self._op = "select"
        self._payload: Any = None
        self._filters: list[tuple[str, str, Any]] = []
        self._single = False
        self._limit: int | None = None

    # ── builder ───────────────────────────────────────────────────────────────
    def select(self, *_args, **_kwargs):
        self._op = "select"
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def upsert(self, payload, on_conflict=None):
        self._op = "upsert"
        self._payload = payload
        self._on_conflict = on_conflict
        return self

    def eq(self, col, val):
        self._filters.append((col, "eq", val))
        return self

    def neq(self, col, val):
        self._filters.append((col, "neq", val))
        return self

    def in_(self, col, vals):
        self._filters.append((col, "in", vals))
        return self

    def lt(self, col, val):
        self._filters.append((col, "lt", val))
        return self

    def gte(self, col, val):
        self._filters.append((col, "gte", val))
        return self

    def is_(self, col, val):
        """
        PostgREST `is` — used for NULL checks, as in .is_("col", "null").

        The deposit guards depend on this: "update only if not already
        returned" is what stops a retried job refunding twice.
        """
        self._filters.append((col, "is", val))
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, n):
        self._limit = n
        return self

    def single(self):
        self._single = True
        return self

    # ── execution ─────────────────────────────────────────────────────────────
    def _matches(self, row) -> bool:
        for col, op, val in self._filters:
            actual = row.get(col)
            if op == "eq" and actual != val:
                return False
            if op == "neq" and actual == val:
                return False
            if op == "in" and actual not in val:
                return False
            if op == "lt" and not (actual is not None and actual < val):
                return False
            if op == "gte" and not (actual is not None and actual >= val):
                return False
            if op == "is":
                # PostgREST spells these as the strings "null" / "true" / "false".
                expected = {"null": None, "true": True, "false": False}.get(val, val)
                if actual is not expected:
                    return False
        return True

    def execute(self):
        with self._db.lock:
            rows = self._db.tables.setdefault(self._table, [])

            if self._op == "select":
                hits = [copy.deepcopy(r) for r in rows if self._matches(r)]
                if self._limit is not None:
                    hits = hits[: self._limit]
                if self._single and not hits:
                    raise FakeAPIError("JSON object requested, multiple (or no) rows returned")
                return _Result(hits[0] if self._single else hits)

            if self._op in ("insert", "upsert"):
                payloads = (
                    self._payload if isinstance(self._payload, list) else [self._payload]
                )
                created = []
                for p in payloads:
                    row = copy.deepcopy(p)
                    row.setdefault("id", f"{self._table}-{len(rows) + 1}")
                    self._db._enforce_unique(self._table, row, exclude_id=None)
                    rows.append(row)
                    created.append(copy.deepcopy(row))
                return _Result(created)

            if self._op == "update":
                updated = []
                for row in rows:
                    if not self._matches(row):
                        continue
                    candidate = {**row, **self._payload}
                    self._db._enforce_unique(
                        self._table, candidate, exclude_id=row.get("id")
                    )
                    row.update(self._payload)
                    updated.append(copy.deepcopy(row))
                return _Result(updated)

            raise AssertionError(f"unsupported op {self._op}")


class FakeSupabase:
    """
    `unique` maps table name -> list of column names that must be unique when
    non-null, mirroring the partial unique indexes in migration 001.
    """

    def __init__(self, tables: dict[str, list[dict]] | None = None):
        self.tables = copy.deepcopy(tables or {})
        self.lock = threading.RLock()
        self.unique = {
            "bookings": ["razorpay_payment_id", "razorpay_order_id"],
            "listings": ["fee_razorpay_payment_id", "qr_fingerprint"],
        }

    def table(self, name: str) -> _Query:
        return _Query(self, name)

    def _enforce_unique(self, table: str, candidate: dict, exclude_id):
        for col in self.unique.get(table, []):
            val = candidate.get(col)
            if val is None:
                continue
            for other in self.tables.get(table, []):
                if other.get("id") == exclude_id:
                    continue
                if other.get(col) == val:
                    raise FakeAPIError(
                        f'duplicate key value violates unique constraint "uq_{table}_{col}"'
                    )

    def rows(self, table: str) -> list[dict]:
        return self.tables.setdefault(table, [])

    def get(self, table: str, row_id: str) -> dict | None:
        return next((r for r in self.rows(table) if r.get("id") == row_id), None)
