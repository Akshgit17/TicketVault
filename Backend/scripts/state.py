"""
Walkthrough state inspector.

Prints where every listing and booking currently sits in the lifecycle, so
"why hasn't the transfer task appeared?" can be answered by looking rather than
guessing.

    cd Backend && ../venv/Scripts/python.exe scripts/state.py

Read-only. Uses the service-role client, so it sees through RLS.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import supabase  # noqa: E402


def rows(table, select="*", **filters):
    q = supabase.table(table).select(select)
    for k, v in filters.items():
        q = q.eq(k, v)
    return q.execute().data or []


def main() -> None:
    users = rows("users", "id, name, email, is_admin")
    print(f"\nUSERS ({len(users)})")
    for u in users:
        flag = " [admin]" if u.get("is_admin") else ""
        print(f"  {u['email']:<34} {u['name']}{flag}")

    listings = rows(
        "listings",
        "id, status, price, deposit_paid_paise, deposit_returned_at, "
        "deposit_forfeited_at, fee_razorpay_payment_id, events(title)",
    )
    print(f"\nLISTINGS ({len(listings)})")
    for l in listings:
        ev = (l.get("events") or {}).get("title", "?")[:32]
        dep = l.get("deposit_paid_paise")
        dep_s = f"{dep/100:.0f}" if dep else "-"
        outcome = (
            "returned" if l.get("deposit_returned_at")
            else "forfeited" if l.get("deposit_forfeited_at")
            else "held"
        )
        print(f"  {l['id'][:8]}  {l['status']:<16} Rs{float(l['price']):<8.0f} "
              f"deposit Rs{dep_s:<8} {outcome:<10} {ev}")

    bookings = rows(
        "bookings",
        "id, payment_status, fulfillment_status, total_price, transfer_deadline, "
        "buyer_platform_mobile, mobile_consent_at, listing_id",
    )
    print(f"\nBOOKINGS ({len(bookings)})")
    for b in bookings:
        mobile = "shared" if b.get("mobile_consent_at") else "NOT SHARED"
        print(f"  {b['id'][:8]}  pay={b['payment_status']:<10} "
              f"fulfil={b.get('fulfillment_status'):<20} Rs{float(b['total_price']):<8.0f} "
              f"mobile={mobile}")
        if b.get("transfer_deadline"):
            print(f"            deadline {b['transfer_deadline']}")

    ledger = rows("ledger_entries", "kind, direction, amount_paise")
    print(f"\nLEDGER ({len(ledger)} entries)")
    totals: dict[str, int] = {}
    for e in ledger:
        totals[e["kind"]] = totals.get(e["kind"], 0) + int(e["amount_paise"])
    for kind, paise in sorted(totals.items()):
        print(f"  {kind:<16} Rs{paise/100:,.2f}")

    recs = rows("pricing_recommendations", "source, chosen_price_paise, accepted")
    print(f"\nPRICING RECOMMENDATIONS ({len(recs)})")
    for r in recs:
        print(f"  source={r['source']:<10} chose Rs{int(r['chosen_price_paise'] or 0)/100:,.0f} "
              f"accepted={r['accepted']}")

    # The single most useful line: what should happen next.
    print("\nNEXT STEP")
    if not listings:
        print("  Seller: create a listing at /sell")
    elif any(l["status"] in ("pending_fee", "pending_deposit") for l in listings):
        print("  Seller: pay the deposit (listing is not live yet)")
    elif not bookings:
        print("  Buyer: buy the listing from /marketplace")
    else:
        for b in bookings:
            f = b.get("fulfillment_status")
            short = b["id"][:8]

            # Terminal fulfilment states are checked FIRST, before payment
            # status. A refunded booking is finished, not stuck: reading
            # payment_status alone reported "payment not completed" for a
            # booking that had correctly reached the end of the unhappy path.
            if f == "released":
                print(f"  {short}: done, seller paid and deposit returned.")
            elif f == "failed":
                print(f"  {short}: done, transfer failed. Buyer refunded and "
                      f"compensated from the forfeited deposit.")
            elif b["payment_status"] != "paid":
                print(f"  Buyer: payment not completed on {short}")
            elif not b.get("mobile_consent_at"):
                print(f"  Buyer: share mobile on /bookings/{b['id']}/confirm")
            elif f == "awaiting_transfer":
                print(f"  Seller: mark transferred at /dashboard/sales/{b['id']}")
            elif f == "transfer_initiated":
                print(f"  Buyer: confirm receipt on /bookings/{b['id']}/confirm")
            elif f == "transfer_confirmed":
                print(f"  {short}: waiting on the release job (runs every 30s).")
            elif f == "not_started":
                print(f"  {short} is on the LEGACY path: the event is not "
                      f"transfer_supported, so no transfer task will appear.")
    print()


if __name__ == "__main__":
    main()
