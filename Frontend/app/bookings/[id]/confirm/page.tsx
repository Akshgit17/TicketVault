"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import { toast } from "sonner";
import {
  Calendar, CheckCircle2, MapPin, Phone, ShieldCheck, TriangleAlert,
} from "lucide-react";

import { api, setAuthToken } from "@/lib/api";
import { useConfig } from "@/lib/config";
import { FULFILLMENT_STATUS, statusMeta } from "@/lib/status";
import { formatEventDate, inr } from "@/lib/utils";
import { BookingTimeline } from "@/components/ui/BookingTimeline";
import { CountdownTimer } from "@/components/ui/CountdownTimer";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle,
} from "@/components/ui/dialog";

export default function BookingTransferPage({ params }: { params: { id: string } }) {
  const { getToken } = useAuth();
  const router = useRouter();
  const { config } = useConfig();

  const [booking, setBooking] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [acting, setActing] = useState(false);

  const [mobile, setMobile] = useState("");
  const [consent, setConsent] = useState(false);

  const [disputeOpen, setDisputeOpen] = useState(false);
  const [disputeReason, setDisputeReason] = useState("");

  const load = useCallback(async () => {
    try {
      setAuthToken(await getToken());
      const { data } = await api.get(`/bookings/${params.id}`);
      setBooking(data);
    } catch (e: any) {
      toast.error("Couldn't load this booking", { description: e.message });
    } finally {
      setLoading(false);
    }
  }, [getToken, params.id]);

  useEffect(() => { load(); }, [load]);

  const status: string = booking?.fulfillment_status ?? "not_started";
  const meta = statusMeta(FULFILLMENT_STATUS, status);
  const event = booking?.listings?.events;
  const hasMobile = Boolean(booking?.mobile_consent_at);

  const submitMobile = async () => {
    setActing(true);
    try {
      setAuthToken(await getToken());
      await api.post("/bookings/transfer-mobile", {
        booking_id: params.id,
        mobile,
        consent: true,
      });
      toast.success("Number shared with the seller");
      await load();
    } catch (e: any) {
      toast.error("Couldn't save that number", { description: e.message });
    } finally {
      setActing(false);
    }
  };

  const confirmReceipt = async () => {
    setActing(true);
    try {
      setAuthToken(await getToken());
      await api.post("/bookings/confirm", { booking_id: params.id });
      toast.success("Confirmed. Enjoy the show", {
        description: `The seller is paid in ${config.settlement_hold_hours} hours. Tell us before then if anything's wrong.`,
      });
      await load();
    } catch (e: any) {
      toast.error("Couldn't confirm", { description: e.message });
    } finally {
      setActing(false);
    }
  };

  const reportProblem = async () => {
    setActing(true);
    try {
      setAuthToken(await getToken());
      await api.post("/bookings/dispute", {
        booking_id: params.id,
        reason: disputeReason.trim() || "Buyer reported a problem with the transfer",
      });
      toast.success("Reported", { description: "We've paused the payout and will look into it." });
      setDisputeOpen(false);
      await load();
    } catch (e: any) {
      toast.error("Couldn't report that", { description: e.message });
    } finally {
      setActing(false);
    }
  };

  if (loading) {
    return (
      <div className="container max-w-2xl space-y-4 py-14">
        <Skeleton className="h-10 w-2/3" />
        <Skeleton className="h-40" />
        <Skeleton className="h-32" />
      </div>
    );
  }

  if (!booking) {
    return (
      <div className="container max-w-2xl py-20 text-center">
        <p className="font-display text-3xl tracking-display">BOOKING NOT FOUND</p>
        <Button variant="outline" className="mt-6" onClick={() => router.push("/dashboard")}>
          Back to dashboard
        </Button>
      </div>
    );
  }

  const d = event ? formatEventDate(event.date) : null;

  return (
    <div className="container max-w-2xl py-14">
      <p className="eyebrow mb-2">Your purchase</p>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="font-display text-4xl tracking-display">
          {event?.title ?? "Your ticket"}
        </h1>
        <Badge variant={meta.tone}>{meta.label}</Badge>
      </div>

      {d && (
        <div className="mt-3 flex flex-wrap gap-4 text-sm text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <Calendar className="size-3.5" />
            <span className="tnum">{d.full}</span>
          </span>
          <span className="flex items-center gap-1.5">
            <MapPin className="size-3.5" />
            {event.venue}
          </span>
        </div>
      )}

      <div className="mt-8 rounded-lg border border-border bg-card p-6">
        <BookingTimeline status={status} />
      </div>

      {/* Escrow reassurance — the single most useful thing to say to someone
          who has just paid a stranger for a ticket. */}
      <div className="mt-5 flex gap-3 rounded-lg border border-border bg-secondary/30 p-4">
        <ShieldCheck className="mt-0.5 size-4 shrink-0 text-primary" />
        <div className="text-sm">
          <p className="font-medium">
            {inr(booking.total_price)} is held by TicketVault
          </p>
          <p className="mt-1 text-muted-foreground">{meta.buyerHint}</p>
        </div>
      </div>

      {booking.transfer_deadline && status === "awaiting_transfer" && (
        <CountdownTimer
          deadline={booking.transfer_deadline}
          label="Seller must transfer within"
          className="mt-4"
        />
      )}

      <Separator perforated className="my-8" />

      {/* Step 1 — the number the seller needs to perform the transfer. */}
      {!hasMobile && status !== "released" && status !== "failed" && (
        <section className="rounded-lg border border-primary/40 bg-primary/5 p-6">
          <div className="flex items-center gap-2">
            <Phone className="size-4 text-primary" />
            <h2 className="font-display text-2xl tracking-display">
              ONE THING WE NEED
            </h2>
          </div>
          <p className="mt-2 text-sm text-muted-foreground">
            The seller transfers the ticket to your ticketing account, so they
            need the mobile number it&apos;s registered to. Nothing can happen
            until we have it.
          </p>

          <div className="mt-5 space-y-2">
            <Label htmlFor="mobile">Registered mobile number</Label>
            <Input
              id="mobile" type="tel" inputMode="numeric" value={mobile}
              onChange={(e) => setMobile(e.target.value)}
              placeholder="98765 43210" className="tnum font-mono"
            />
          </div>

          <label className="mt-4 flex cursor-pointer items-start gap-3 text-sm">
            <input
              type="checkbox" checked={consent}
              onChange={(e) => setConsent(e.target.checked)}
              className="mt-0.5 size-4 shrink-0 accent-amber-500"
            />
            <span className="text-muted-foreground">
              I agree to share this number with the seller for this transfer.
              They will see it until the sale completes.
            </span>
          </label>

          <Button
            className="mt-5 w-full"
            disabled={!consent || mobile.replace(/\D/g, "").length < 10}
            loading={acting}
            onClick={submitMobile}
          >
            Share with seller
          </Button>
        </section>
      )}

      {/* Step 2 — waiting on the seller. */}
      {hasMobile && status === "awaiting_transfer" && (
        <section className="rounded-lg border border-border bg-card p-6 text-center">
          <p className="font-display text-2xl tracking-display">WAITING ON THE SELLER</p>
          <p className="mx-auto mt-2 max-w-sm text-sm text-muted-foreground">
            We&apos;ve sent them your number. If they don&apos;t transfer in time,
            you&apos;re refunded in full and paid{" "}
            {inr(booking.total_price * config.buyer_compensation_rate)} on top. That
            happens automatically, without you chasing anyone.
          </p>
        </section>
      )}

      {/* Step 3 — the confirmation decision. */}
      {status === "transfer_initiated" && (
        <section className="rounded-lg border border-border bg-card p-6">
          <h2 className="font-display text-2xl tracking-display">
            DID THE TICKET ARRIVE?
          </h2>
          <p className="mt-2 text-sm text-muted-foreground">
            Open your ticketing app and check for the ticket. Confirm only once
            you can actually see it. This is what releases the seller&apos;s money.
          </p>

          <div className="mt-6 flex flex-col gap-3 sm:flex-row">
            <Button className="flex-1" loading={acting} onClick={confirmReceipt}>
              <CheckCircle2 />
              Yes, it&apos;s in my account
            </Button>
            <Button
              variant="outline" className="flex-1 border-destructive/40 text-destructive hover:bg-destructive/10"
              onClick={() => setDisputeOpen(true)}
            >
              <TriangleAlert />
              No, report a problem
            </Button>
          </div>
        </section>
      )}

      {(status === "transfer_confirmed" || status === "released") && (
        <section className="rounded-lg border border-success/40 bg-success/5 p-6 text-center">
          <CheckCircle2 className="mx-auto size-8 text-success" />
          <p className="mt-3 font-display text-2xl tracking-display">
            {status === "released" ? "ALL DONE" : "CONFIRMED"}
          </p>
          <p className="mt-2 text-sm text-muted-foreground">{meta.buyerHint}</p>
          {status === "transfer_confirmed" && (
            <Button
              variant="ghost" size="sm" className="mt-4 text-destructive"
              onClick={() => setDisputeOpen(true)}
            >
              Something&apos;s wrong with the ticket
            </Button>
          )}
        </section>
      )}

      {status === "failed" && (
        <section className="rounded-lg border border-destructive/40 bg-destructive/5 p-6">
          <div className="text-center">
            <TriangleAlert className="mx-auto size-8 text-destructive" />
            <p className="mt-3 font-display text-2xl tracking-display">TRANSFER FAILED</p>
            <p className="mt-2 text-sm text-muted-foreground">
              The seller did not transfer the ticket in time, so you have been
              refunded automatically.
            </p>
          </div>

          {/* What they get back, and whether it has actually moved. A buyer
              who has just lost a ticket should not have to guess at either. */}
          {booking.refund && (
            <div className="mt-6 rounded-lg border border-border bg-background p-5">
              <p className="eyebrow mb-4">Your money back</p>
              <dl className="space-y-3 text-sm">
                {booking.refund.refunded_paise > 0 && (
                  <div className="flex items-start justify-between gap-4">
                    <dt>
                      <span className="text-foreground">Ticket refund</span>
                      <span className="mt-0.5 block text-xs text-muted-foreground">
                        Sent to your original payment method. Banks take 5 to 7
                        working days.
                      </span>
                    </dt>
                    <dd className="tnum shrink-0 font-mono text-lg text-success">
                      {inr(booking.refund.refunded_paise / 100)}
                    </dd>
                  </div>
                )}

                {booking.refund.compensation_paise > 0 && (
                  <>
                    <div className="perforation" />
                    <div className="flex items-start justify-between gap-4">
                      <dt>
                        <span className="text-foreground">Compensation</span>
                        <span className="mt-0.5 block text-xs text-muted-foreground">
                          Paid out of the seller&apos;s forfeited deposit, because
                          they let you down.
                        </span>
                      </dt>
                      <dd className="tnum shrink-0 font-mono text-lg text-primary">
                        {inr(booking.refund.compensation_paise / 100)}
                      </dd>
                    </div>
                  </>
                )}
              </dl>

              {booking.refund.razorpay_refund_id && (
                <p className="tnum mt-4 border-t border-border pt-3 font-mono text-[11px] text-muted-foreground">
                  Refund reference {booking.refund.razorpay_refund_id}
                </p>
              )}
            </div>
          )}
        </section>
      )}

      <Dialog open={disputeOpen} onOpenChange={setDisputeOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>REPORT A PROBLEM</DialogTitle>
            <DialogDescription>
              Tell us what went wrong. We&apos;ll hold the seller&apos;s payout
              while we look into it.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2 p-5">
            <Label htmlFor="reason">What happened?</Label>
            <Textarea
              id="reason" value={disputeReason}
              onChange={(e) => setDisputeReason(e.target.value)}
              placeholder="e.g. Nothing arrived in my BookMyShow account, or the ticket is for the wrong date."
            />
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDisputeOpen(false)}>Cancel</Button>
            <Button variant="destructive" loading={acting} onClick={reportProblem}>
              Report problem
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
