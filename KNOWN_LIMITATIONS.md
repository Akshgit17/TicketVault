# Known limitations

Everything on this page is a deliberate decision with a reason, not something
that was missed. It is written down because a limitation you can name and
justify is engineering judgement, and the same limitation found by someone else
is a mistake.

Where a constraint is external, the source and date are given so the claim can
be checked rather than taken on trust.

---

## Money

### Seller payouts are simulated. Refunds are real.

The distinction matters, so it is worth being exact about which is which.

**Real:** every refund. The buyer's refund after a failed transfer, and the
seller's deposit return after a successful one, are genuine Razorpay refunds
with real refund ids that appear in the Razorpay dashboard.

**Simulated:** the outbound payment of sale proceeds to a seller. The payout
row, the fee split, the ledger entries and the state transitions are all real.
Only the bank leg is stood in for, using a transfer id prefixed `sim_` so that
nobody reading the ledger can mistake it for money that moved.

**Why it cannot be fixed here.** Paying a third party requires Razorpay Route.
Since the RBI rules of September 2025, Route requires domestic turnover above
₹40 lakh, and it was withdrawn from non compliant merchants on 1 January 2026
([Razorpay Route FAQs](https://razorpay.com/docs/payments/route/faqs/)).
Razorpay's own documented fallback is to settle into the primary account and pay
vendors manually.

There is also a structural reason no amount of test mode cleverness helps: **a
refund can only return money to whoever paid it.** The buyer paid, so a refund
reaches the buyer. Nothing in the refund API can reach the seller.

`SIMULATE_PAYOUTS` in `app/config.py` switches this off the day Route becomes
available, and the live path stays under test via the `live_route` fixture so it
does not rot while unused.

### Buyer compensation is recorded, not disbursed

When a seller's deposit is forfeited, the buyer's refund of the ticket price is
real money. The compensation on top is a ledger entry only.

Same root cause: Razorpay will not refund more than was captured on a payment,
so paying a buyer *extra* is an outbound transfer, which needs Route. The
obligation is accounted for and auditable. Settling it is a manual step.

The API exposes `refund_is_real: true` and `compensation_paid: false` as
separate fields specifically so the UI cannot accidentally imply the
compensation has landed.

### The deposit rate is economically aggressive

20% of the asking price, paid upfront. On a ₹5,000 ticket that is ₹1,000 out of
pocket before the seller has earned anything, and in a real market that would
suppress supply.

It is defensible at this scale because the deposit has to be large enough to
fund a meaningful buyer compensation. A price scaled cap, something like
`min(20%, ₹500)`, is the intended fix.

---

## Fulfilment

### Ticket transfer is coordinated, not verified

No public or partner API exists for BookMyShow or District transfers, verified
1 August 2026. The platform can orchestrate a transfer, record that the seller
said they performed it, and record that the buyer said they received it. It
cannot independently prove either.

This is a real world constraint rather than an implementation gap, and it is why
the deposit exists: when you cannot verify, you make failure expensive instead.

Related: `transfer_supported` is set to `TRUE` for the entire catalogue, which
is an assumption rather than a measurement. Whether transfer is actually
available for a given event, and how close to the date it opens, was never
empirically tested. Doing so would have meant buying real tickets on multiple
accounts, which is both expensive and probably a terms of service violation.

### There are no notifications

No email, no SMS, no push. A seller learns their ticket sold by happening to log
in, and a buyer is given a deadline they are never told about.

This is the most consequential gap in the project, because it undermines the
fairness of the SLA. **A deadline nobody is told about cannot be enforced
fairly at any length**, which is why `FULFILLMENT_SLA_HOURS` defaults to a
deliberately generous 24 hours rather than the 6 the design originally called
for. Email is the single highest value thing to build next.

### A false dispute freezes a seller's money, but cannot take it

Worth being precise, because the obvious reading is worse than the truth.

**A buyer's dispute does not forfeit anything.** Forfeiture has exactly one
automatic trigger: the seller misses the transfer deadline, which is a fact the
system observes rather than a claim anybody makes. A dispute sets the booking to
`disputed`, freezes the payout, and writes an audit row. No money moves.

So the attack a false claim actually enables is **delay of settlement**, not
theft: a malicious buyer can stall an honest seller's payout until an admin
looks at it.

Four things reduce that:

1. **Freezing is reversible, paying out is not.** Erring towards the freeze is
   the correct default when the alternative cannot be undone.
2. **There is an admin dispute queue** at `/admin`, with both outcomes wired to
   the money. Upholding refunds the buyer and forfeits the deposit; rejecting
   lifts the freeze and the payout runs on the next job tick. Both require a
   written reason, stored in `booking_events`, because this is the one place a
   human overrides the state machine.
3. **Prior disputes by the same buyer are counted and surfaced**, flagged from
   the third onwards. A first dispute is unremarkable; a fourth from one account
   is the story. Counted rather than blocked, because a buyer with a genuine
   second problem must still be able to report it.
4. **Whether the seller supplied transfer evidence is shown on the dispute.**
   Seller has proof and the buyer disputes: genuinely contested, needs a human.
   Seller has no proof: the buyer's account is the only account there is.

**What is still missing is an SLA on resolution.** Nothing escalates or times
out a dispute, so a queue nobody checks is a payout nobody receives. With one
admin and a handful of transactions that is manageable; at any real volume it
would need a deadline and an escalation path.

### One failure does not permanently remove a seller

A failed listing returns to "deposit due" rather than being cancelled, so the
seller can relist by paying a fresh deposit. There is no strike count and no
escalation, so a seller willing to keep losing deposits can keep failing. Each
individual buyer is fully backed, which is the property that actually matters,
but a repeat offender is not stopped.

Seller reputation and payout holds were Phase 4 of the plan and were cut.

---

## Pricing model

### The model is trained on synthetic outcomes

There are no completed transactions, so there are no real labels.

| Real | Synthetic |
|---|---|
| Event catalogue, venues, cities, city tiers | Whether a listing sold |
| Face values | What it sold for |
| Curated popularity tiers | |

Labels come from a documented demand function in `ml/generate_dataset.py`. Every
weight is a stated hypothesis about how concert resale behaves, and every one is
arguable. Nothing there is presented as measurement.

The pipeline is production shaped. Every recommendation served is already logged
to `pricing_recommendations` with the band shown, the probability shown, and
what the seller actually chose, which is the dataset that replaces this one.

### Quantile coverage is short of target

The P25 to P75 band contains 44.4% of held out sales against a target of 50%,
meaning the band is slightly too narrow and overclaims its own confidence.

Left rather than tuned, because tuning a quantile against synthetic labels
optimises against your own assumptions rather than against reality.

### Unsold listings are treated as negative examples

They are actually **right censored**: a listing that has not sold has not sold
*yet*, which is not the same as having failed to sell. The statistically correct
treatment is a discrete time survival model. The simpler binary classifier was
trained instead, and this is the reason its labels are imperfect.

### The popularity signal would be biased if it were live

The design calls for Last.fm listener counts as a hype feature. Last.fm's
userbase skews heavily Western, so it systematically understates Indian acts: a
playback singer who sells out an arena in Hyderabad can show fewer listeners
than a mid tier Western indie band. For a catalogue of Indian concerts that is
the typical case, not an edge case, and a model trained on raw listener counts
would price the highest demand shows in the country too low.

The mitigation, and the reason the curated `popularity_tier` is a first class
feature rather than a fallback, is that a human can correct the external signal.
Last.fm ingestion itself is designed but not implemented.

Note also that Spotify was the obvious first choice and is unusable: the
`popularity` field was removed for new and development mode apps in the
[February 2026 API changes](https://developer.spotify.com/documentation/web-api/references/changes/february-2026).

### The price cap is fixed, not learned

120% of face value, hardcoded as a database constraint.

This is deliberate and is not a limitation to be fixed. A learned ceiling is a
ceiling nobody validated, and every trust guarantee in the product rests on that
number holding. The model recommends within the cap and never sets it.

---

## Security and operations

### The scheduler runs inside the API process

APScheduler runs in every API instance, so at two or more replicas the
fulfilment jobs fire concurrently. The guards make that safe rather than merely
unlikely: compare and swap updates on status, a unique constraint on
`payouts.booking_id`, and idempotency keys on every ledger row.

The correct shape is external cron calling `POST /jobs/fulfillment` with
`CRON_SECRET`, which already exists and works. In process scheduling was chosen
so that a demo does not require a cron daemon.

### The buyer's phone number is shared with the seller in plaintext

The transfer mechanism requires it: the seller types the buyer's registered
mobile into BookMyShow to send the ticket. It is stored unencrypted and shown to
the seller for the duration of the sale.

Consent is explicit and timestamped rather than buried in terms, and the number
is withheld from the seller until that consent exists. Encryption at rest and
automatic expiry after the sale completes are designed and not implemented.

### There is no rate limiting

Single instance deployment, no `slowapi`. Auth adjacent and upload endpoints are
the ones that would need it first.

### QR upload is retained as proof of ownership

The transfer model does not need a QR image, and the original plan called for
deleting that path entirely. It survives because `POST /listings/create` still
requires the file, and it is reframed honestly: the image is never sent to the
buyer, it only evidences to the platform that the ticket exists.

Removing it means making `qr_file` optional server side, which is small but was
not worth the regression risk late in the project.

### The test suite runs against a fake Supabase client

159 tests, none of which touch a real database. That makes them fast and
deterministic in CI, and it trades away integration coverage: schema drift
between `Database/` and what the tests assume would not be caught.

Several bugs in this project were only found by running against real Postgres,
which is direct evidence of what this trade costs.

---

## What would come next

In order, if the project continued:

1. **Email notifications.** Everything about the SLA's fairness depends on this.
2. **A dispute queue** with evidence from both sides, closing the false claim
   attack on the deposit.
3. **Seller reputation and strikes**, so repeat failures escalate.
4. **A live test database in CI**, to catch what the fake client cannot.
5. **Retrain on real transactions** once `pricing_recommendations` has enough
   rows, replacing the synthetic labels entirely.
