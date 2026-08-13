"""
Backfill escrow_release_at for bookings confirmed under the old rule.

Escrow used to be scheduled for event date + 24h. It now runs from buyer
confirmation + SETTLEMENT_HOLD_HOURS (see fulfillment.confirm_transfer_received).
Bookings confirmed before that change still carry the old, far-future value and
would sit unreleased for weeks.

Only touches bookings that are already `transfer_confirmed` — i.e. the buyer has
said the ticket arrived. Nothing else is modified.

    cd Backend && ../venv/Scripts/python.exe scripts/backfill_escrow_release.py
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import SETTLEMENT_HOLD_HOURS  # noqa: E402
from app.database import supabase  # noqa: E402
from app.services import fulfillment  # noqa: E402

UTC = timezone.utc


def main() -> None:
    rows = (
        supabase.table("bookings")
        .select("id, transfer_confirmed_at, escrow_release_at")
        .eq("fulfillment_status", fulfillment.TRANSFER_CONFIRMED)
        .execute()
    ).data or []

    if not rows:
        print("No confirmed bookings awaiting release.")
        return

    for b in rows:
        confirmed = b.get("transfer_confirmed_at")
        base = (
            datetime.fromisoformat(str(confirmed).replace("Z", "+00:00"))
            if confirmed else datetime.now(UTC)
        )
        release = base + timedelta(hours=SETTLEMENT_HOLD_HOURS)

        supabase.table("bookings").update({
            "escrow_release_at": release.isoformat(),
        }).eq("id", b["id"]).eq(
            "fulfillment_status", fulfillment.TRANSFER_CONFIRMED
        ).execute()

        due = "DUE NOW" if release <= datetime.now(UTC) else f"due {release.isoformat()}"
        print(f"  {b['id'][:8]}  {b['escrow_release_at']} -> {release.isoformat()}  ({due})")

    print(f"\nBackfilled {len(rows)} booking(s) at SETTLEMENT_HOLD_HOURS={SETTLEMENT_HOLD_HOURS}.")


if __name__ == "__main__":
    main()
