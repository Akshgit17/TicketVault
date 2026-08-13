/**
 * Single place that turns backend enum values into language a user should see.
 *
 * Without this, statuses like `pending_deposit` and `awaiting_transfer` leak
 * straight into the UI — which is both ugly and actively confusing, since the
 * user has no idea what the system wants from them. Every status also carries
 * an explicit *next action*, because a status the user cannot act on is just
 * an apology.
 */

export type BadgeTone = "default" | "neutral" | "success" | "destructive" | "outline";

export interface StatusMeta {
  label: string;
  tone: BadgeTone;
  /** Shown under the status. Written for the person reading it, not the system. */
  buyerHint?: string;
  sellerHint?: string;
}

/**
 * Keyed on `bookings.fulfillment_status` — the values the backend actually
 * writes (see app/services/fulfillment.py), not the aspirational names from
 * the design doc.
 */
export const FULFILLMENT_STATUS: Record<string, StatusMeta> = {
  not_started: {
    label: "Held in escrow",
    tone: "default",
    buyerHint: "Your payment is held. This event doesn't support in-app transfer yet.",
    sellerHint: "Payment received and held by TicketVault.",
  },
  awaiting_transfer: {
    label: "Transfer needed",
    tone: "default",
    buyerHint: "The seller is sending the ticket to your account.",
    sellerHint: "Transfer the ticket now. The clock is running.",
  },
  transfer_initiated: {
    label: "Transfer sent",
    tone: "default",
    buyerHint: "The seller says they've sent it. Check your ticketing app, then confirm.",
    sellerHint: "Waiting for the buyer to confirm they received it.",
  },
  transfer_confirmed: {
    label: "Confirmed",
    tone: "success",
    buyerHint: "Confirmed. Tell us before payout if anything's wrong.",
    sellerHint: "Confirmed by the buyer. Payout and deposit return are on the way.",
  },
  released: {
    label: "Completed",
    tone: "success",
    buyerHint: "All done. Enjoy the show.",
    sellerHint: "Paid out, and your deposit has been returned.",
  },
  failed: {
    label: "Transfer failed",
    tone: "destructive",
    buyerHint: "The transfer didn't happen. You've been refunded and compensated.",
    sellerHint: "You missed the deadline. The deposit was forfeited.",
  },
};

export const BOOKING_STATUS: Record<string, StatusMeta> = {
  pending_payment: {
    label: "Payment pending",
    tone: "neutral",
    buyerHint: "Finish payment to hold this ticket.",
    sellerHint: "Waiting for the buyer to pay.",
  },
  paid_in_escrow: {
    label: "Held in escrow",
    tone: "default",
    buyerHint: "Your money is held safely. The seller has been notified.",
    sellerHint: "Payment received and held. Transfer the ticket to get paid.",
  },
  awaiting_transfer: {
    label: "Awaiting transfer",
    tone: "default",
    buyerHint: "The seller is transferring the ticket to your account.",
    sellerHint: "Transfer the ticket now. You have a deadline.",
  },
  transfer_initiated: {
    label: "Transfer sent",
    tone: "default",
    buyerHint: "The seller says they've sent it. Check your ticketing app.",
    sellerHint: "Waiting for the buyer to confirm they received it.",
  },
  transfer_confirmed: {
    label: "Transfer confirmed",
    tone: "success",
    buyerHint: "Confirmed. Tell us before payout if anything is wrong.",
    sellerHint: "Confirmed by the buyer. Your payout is being released.",
  },
  released: {
    label: "Completed",
    tone: "success",
    buyerHint: "This booking is complete.",
    sellerHint: "Paid out, and your deposit has been returned.",
  },
  refunded: {
    label: "Refunded",
    tone: "neutral",
    buyerHint: "You've been fully refunded.",
    sellerHint: "This sale was refunded to the buyer.",
  },
  disputed: {
    label: "Problem reported",
    tone: "destructive",
    buyerHint: "We're looking into it. You'll hear from us.",
    sellerHint: "The buyer reported a problem with this transfer.",
  },
  cancelled: {
    label: "Cancelled",
    tone: "neutral",
  },
  // Legacy statuses from the pre-transfer flow, kept so old rows still render.
  confirmed: { label: "Confirmed", tone: "success" },
  pending:   { label: "Pending",   tone: "neutral" },
};

export const LISTING_STATUS: Record<string, StatusMeta> = {
  pending_deposit: {
    label: "Deposit due",
    tone: "neutral",
    sellerHint: "Pay the refundable deposit to publish this listing.",
  },
  pending_fee: {
    label: "Deposit due",
    tone: "neutral",
    sellerHint: "Pay the refundable deposit to publish this listing.",
  },
  active:    { label: "Live",      tone: "success", sellerHint: "Visible to buyers." },
  reserved:  { label: "Reserved",  tone: "default", sellerHint: "A buyer is checking out." },
  locked:    { label: "Reserved",  tone: "default", sellerHint: "A buyer is checking out." },
  sold:      { label: "Sold",      tone: "success" },
  completed: { label: "Completed", tone: "success" },
  cancelled: { label: "Unlisted",  tone: "neutral" },
};

export const EVENT_REQUEST_STATUS: Record<string, StatusMeta> = {
  pending:  { label: "Awaiting review", tone: "neutral", sellerHint: "An admin is reviewing your event." },
  approved: { label: "Approved",        tone: "success", sellerHint: "Your event is live. You can list tickets now." },
  rejected: { label: "Rejected",        tone: "destructive" },
};

const FALLBACK: StatusMeta = { label: "Unknown", tone: "neutral" };

/** Never returns undefined — an unmapped status must not blank the UI. */
export function statusMeta(
  map: Record<string, StatusMeta>,
  status: string | null | undefined
): StatusMeta {
  if (!status) return FALLBACK;
  return map[status] ?? { label: humanise(status), tone: "neutral" };
}

function humanise(raw: string) {
  return raw.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
