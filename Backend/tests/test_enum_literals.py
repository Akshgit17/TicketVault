"""
Every enum value the code writes must exist in the database.

WHY THIS TEST EXISTS
--------------------
The dispute resolution endpoint once wrote `confirmation_status =
'disputed_upheld'`. That column is a Postgres ENUM with four members and no
such value, so the statement threw. It threw LAST, after the buyer's refund,
the deposit forfeit and the listing reset had all committed, leaving the money
moved and the dispute still open.

Nothing caught it. The test suite runs against a fake Supabase client that
accepts any string, so even a route-level test would have passed. Real Postgres
was the only thing that would have objected, and the suite never touches it.

So this checks statically instead: parse the enum members out of the SQL, find
every string literal the application assigns to those columns, and assert the
two agree. It is the cheapest available substitute for the type checking a real
database would do, and it covers the whole class of bug rather than the one
instance.
"""
import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
SQL_DIR = BACKEND.parent / "Database"
APP = BACKEND / "app"

# Columns whose name uniquely identifies their enum type. `status` is
# deliberately absent: it names several different enums across tables, so a
# literal cannot be attributed to one of them by name alone.
COLUMN_TO_ENUM = {
    "confirmation_status": "confirmation_status",
    "fulfillment_status": "fulfillment_status",
}


def _sql_text() -> str:
    """schema.sql plus every migration, since migrations add enum members."""
    parts = []
    for path in sorted(SQL_DIR.rglob("*.sql")):
        parts.append(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(parts)


def _enum_members(enum_name: str) -> set[str]:
    sql = _sql_text()
    members: set[str] = set()

    # CREATE TYPE x AS ENUM ('a', 'b', ...)
    for block in re.findall(
        rf"CREATE\s+TYPE\s+{enum_name}\s+AS\s+ENUM\s*\((.*?)\)",
        sql, re.IGNORECASE | re.DOTALL,
    ):
        members.update(re.findall(r"'([^']+)'", block))

    # ALTER TYPE x ADD VALUE [IF NOT EXISTS] 'c'
    for value in re.findall(
        rf"ALTER\s+TYPE\s+{enum_name}\s+ADD\s+VALUE\s+(?:IF\s+NOT\s+EXISTS\s+)?'([^']+)'",
        sql, re.IGNORECASE,
    ):
        members.add(value)

    return members


def _assigned_literals(column: str) -> dict[str, list[str]]:
    """Every `"column": "literal"` the app assigns, mapped to where it appears."""
    found: dict[str, list[str]] = {}
    pattern = re.compile(rf'["\']{column}["\']\s*:\s*["\']([a-z_]+)["\']')

    for path in APP.rglob("*.py"):
        for line_no, line in enumerate(
            path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1
        ):
            for literal in pattern.findall(line):
                found.setdefault(literal, []).append(
                    f"{path.relative_to(BACKEND)}:{line_no}"
                )
    return found


@pytest.mark.parametrize("column,enum_name", COLUMN_TO_ENUM.items())
def test_enum_is_declared_in_sql(column, enum_name):
    """Guards the parser itself: a typo here would make the real test vacuous."""
    assert _enum_members(enum_name), f"no members parsed for enum {enum_name}"


@pytest.mark.parametrize("column,enum_name", COLUMN_TO_ENUM.items())
def test_every_written_value_exists_in_the_enum(column, enum_name):
    members = _enum_members(enum_name)
    written = _assigned_literals(column)

    invalid = {
        literal: places
        for literal, places in written.items()
        if literal not in members
    }

    assert not invalid, (
        f"{column} is a Postgres enum whose members are {sorted(members)}.\n"
        "These writes would be rejected by the database:\n"
        + "\n".join(f"  '{lit}' at {', '.join(places)}" for lit, places in invalid.items())
    )


def test_ledger_kinds_in_code_match_the_enum():
    """
    The ledger kinds are constants rather than inline literals, so they need
    their own check. Migration 010 added four members and the code would fail
    silently against a database where that migration had not run.
    """
    import app.services.ledger as ledger

    members = _enum_members("ledger_kind")
    assert members, "no ledger_kind members parsed"

    used = {
        value
        for name, value in vars(ledger).items()
        if name.startswith("KIND_") and isinstance(value, str)
    }

    missing = used - members
    assert not missing, (
        f"ledger.py uses kinds the database does not define: {sorted(missing)}. "
        f"Declared: {sorted(members)}"
    )
