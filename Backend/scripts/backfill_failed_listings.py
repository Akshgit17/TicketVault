"""
Repair listings left on the market by the old failure policy.

A failed transfer used to send the listing back to `active` while its deposit
stayed forfeited, so the ticket was on sale backed by nothing: the next buyer
would be refunded but never compensated, and the seller had nothing left at
risk. Failures now return the listing to `pending_deposit` instead, but rows
created before that change are still sitting on the market unbacked.

Finds them and applies the current policy. Read-only unless it finds one.

    cd Backend && ../venv/Scripts/python.exe scripts/backfill_failed_listings.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import supabase  # noqa: E402


def main() -> None:
    # Unbacked means: on sale, but the deposit that should cover it is gone.
    unbacked = (
        supabase.table("listings")
        .select("id, status, price, deposit_forfeited_at, events(title)")
        .eq("status", "active")
        .not_.is_("deposit_forfeited_at", "null")
        .execute()
    ).data or []

    if not unbacked:
        print("No unbacked listings. Nothing to do.")
        return

    print(f"Found {len(unbacked)} listing(s) on sale with a forfeited deposit:\n")
    for l in unbacked:
        title = (l.get("events") or {}).get("title", "?")
        print(f"  {l['id'][:8]}  Rs{float(l['price']):.0f}  {title}")

        supabase.table("listings").update({
            "status":                  "pending_fee",
            "locked_by":               None,
            "lock_expiry":             None,
            "deposit_paid_paise":      None,
            "deposit_forfeited_at":    None,
            "deposit_forfeit_reason":  None,
            "fee_razorpay_payment_id": None,
        }).eq("id", l["id"]).eq("status", "active").execute()

    print(
        f"\nReturned {len(unbacked)} listing(s) to pending_deposit. "
        "The seller can relist by paying a new deposit."
    )


if __name__ == "__main__":
    main()
