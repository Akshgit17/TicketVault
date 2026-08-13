"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import { toast } from "sonner";
import {
  ArrowLeft, Calendar, CheckCircle2, Copy, MapPin, Send, ShieldCheck, TriangleAlert,
} from "lucide-react";

import { api, setAuthToken } from "@/lib/api";
import { useConfig } from "@/lib/config";
import { FULFILLMENT_STATUS, statusMeta } from "@/lib/status";
import { formatEventDate, inr } from "@/lib/utils";
import { BookingTimeline } from "@/components/ui/BookingTimeline";
import { CountdownTimer } from "@/components/ui/CountdownTimer";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * The seller's side of a sale — and the only caller of
 * POST /bookings/mark-transferred.
 *
 * Until this page existed the backend could accept a transfer confirmation
 * that no user could ever trigger: a seller had no screen anywhere telling
 * them their ticket had sold.
 */
export default function SaleDetailPage({ params }: { params: { id: string } }) {
  const { getToken } = useAuth();
  const router = useRouter();
  const { config } = useConfig();

  const [sale, setSale] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [acting, setActing] = useState(false);
  const [proofUrl, setProofUrl] = useState("");

  const load = useCallback(async () => {
    try {
      setAuthToken(await getToken());
      const { data } = await api.get("/sellers/me/sales");
      setSale((data ?? []).find((s: any) => s.id === params.id) ?? null);
    } catch (e: any) {
      toast.error("Couldn't load this sale", { description: e.message });
    } finally {
      setLoading(false);
    }
  }, [getToken, params.id]);

  useEffect(() => { load(); }, [load]);

  const markTransferred = async () => {
    setActing(true);
    try {
      setAuthToken(await getToken());
      await api.post("/bookings/mark-transferred", {
        booking_id: params.id,
        proof_url: proofUrl.trim() || null,
      });
      toast.success("Marked as transferred", {
        description: "The buyer will confirm receipt, then you get paid.",
      });
      await load();
    } catch (e: any) {
      toast.error("Couldn't mark it transferred", { description: e.message });
    } finally {
      setActing(false);
    }
  };

  if (loading) {
    return (
      <div className="container max-w-2xl space-y-4 py-14">
        <Skeleton className="h-10 w-2/3" />
        <Skeleton className="h-40" />
      </div>
    );
  }

  if (!sale) {
    return (
      <div className="container max-w-2xl py-20 text-center">
        <p className="font-display text-3xl tracking-display">SALE NOT FOUND</p>
        <Button variant="outline" className="mt-6" onClick={() => router.push("/dashboard")}>
          Back to dashboard
        </Button>
      </div>
    );
  }

  const status: string = sale.fulfillment_status ?? "not_started";
  const meta = statusMeta(FULFILLMENT_STATUS, status);
  const event = sale.listings?.events;
  const d = event ? formatEventDate(event.date) : null;

  const price = Number(sale.listings?.price ?? 0);
  const deposit = price * config.listing_fee_rate;
  const commission = price * config.seller_success_fee_rate;
  const mobile: string | null = sale.buyer_platform_mobile ?? null;

  return (
    <div className="container max-w-2xl py-14">
      <Button
        variant="ghost" size="sm" className="mb-6 -ml-3"
        onClick={() => router.push("/dashboard")}
      >
        <ArrowLeft />
        Back to dashboard
      </Button>

      <p className="eyebrow mb-2">Your sale</p>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="font-display text-4xl tracking-display">
          {event?.title ?? "Ticket sold"}
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

      {/* What the seller gets back, and when. */}
      <div className="mt-5 rounded-lg border border-border bg-card p-5">
        <p className="eyebrow mb-4">You&apos;ll receive</p>
        <dl className="space-y-2.5 text-sm">
          <div className="flex justify-between">
            <dt className="text-muted-foreground">Sale price</dt>
            <dd className="tnum font-mono">{inr(price)}</dd>
          </div>
          {commission > 0 && (
            <div className="flex justify-between">
              <dt className="text-muted-foreground">
                Our commission ({Math.round(config.seller_success_fee_rate * 100)}%)
              </dt>
              <dd className="tnum font-mono text-muted-foreground">
                -{inr(commission)}
              </dd>
            </div>
          )}
          <div className="flex justify-between">
            <dt className="text-muted-foreground">Deposit returned</dt>
            <dd className="tnum font-mono">{inr(deposit)}</dd>
          </div>
          <div className="perforation my-1" />
          <div className="flex justify-between">
            <dt className="font-medium">Total</dt>
            <dd className="tnum font-mono text-lg text-primary">
              {inr(price - commission + deposit)}
            </dd>
          </div>
        </dl>
        <p className="mt-3 text-xs text-muted-foreground">
          Released {config.settlement_hold_hours} hours after the buyer confirms
          they got the ticket.
        </p>

        {/* Split honestly: one of these two amounts is real money movement and
            the other is a ledger entry, and the seller should not have to
            guess which. */}
        {config.simulated_payouts && (
          <p className="mt-3 border-t border-border pt-3 text-xs text-muted-foreground">
            <span className="text-foreground">Deposit returns are real.</span> They
            go back through Razorpay to the card you paid with. Sale proceeds
            are currently <span className="text-foreground">recorded but not
            transferred</span>; paying a seller needs Razorpay Route, which is
            gated behind RBI turnover requirements.
          </p>
        )}
      </div>

      {sale.transfer_deadline && status === "awaiting_transfer" && (
        <CountdownTimer
          deadline={sale.transfer_deadline}
          label="Transfer before"
          className="mt-4"
        />
      )}

      <Separator perforated className="my-8" />

      {status === "awaiting_transfer" && (
        <section className="rounded-lg border border-primary/40 bg-primary/5 p-6">
          <h2 className="font-display text-2xl tracking-display">TRANSFER THE TICKET</h2>

          {!mobile ? (
            <div className="mt-4 flex gap-3 rounded-md border border-border bg-secondary/40 p-4 text-sm">
              <ShieldCheck className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
              <p className="text-muted-foreground">
                Waiting for the buyer to share the mobile number their ticketing
                account is registered to. We&apos;ll notify you, and your deadline
                doesn&apos;t start until they do.
              </p>
            </div>
          ) : (
            <>
              <ol className="mt-5 space-y-4">
                {[
                  "Open the app you bought the ticket in (BookMyShow or District).",
                  "Find this booking and choose “Transfer Ticket”.",
                  "Enter the buyer's number below.",
                  "Come back here and mark it transferred.",
                ].map((step, i) => (
                  <li key={i} className="flex gap-3 text-sm">
                    <span className="tnum flex size-6 shrink-0 items-center justify-center rounded-full border border-border font-mono text-xs">
                      {i + 1}
                    </span>
                    <span className="pt-0.5 text-muted-foreground">{step}</span>
                  </li>
                ))}
              </ol>

              <div className="mt-5 rounded-md border border-border bg-background p-4">
                <p className="eyebrow mb-2">Buyer&apos;s registered number</p>
                <div className="flex items-center gap-3">
                  <span className="tnum font-mono text-xl">{mobile}</span>
                  <Button
                    variant="ghost" size="sm" className="ml-auto"
                    onClick={() => {
                      navigator.clipboard.writeText(mobile);
                      toast.success("Copied");
                    }}
                  >
                    <Copy />
                    Copy
                  </Button>
                </div>
                <p className="mt-2 text-xs text-muted-foreground">
                  Use this only for this transfer.
                </p>
              </div>

              <div className="mt-5 space-y-2">
                <Label htmlFor="proof">Screenshot link (optional)</Label>
                <Input
                  id="proof" type="url" value={proofUrl}
                  onChange={(e) => setProofUrl(e.target.value)}
                  placeholder="https://..."
                />
                <p className="text-xs text-muted-foreground">
                  Proof of the transfer protects you if the buyer disputes it.
                </p>
              </div>

              <Button className="mt-5 w-full" loading={acting} onClick={markTransferred}>
                <Send />
                I&apos;ve transferred the ticket
              </Button>

              <p className="mt-3 flex items-start gap-2 text-xs text-muted-foreground">
                <TriangleAlert className="mt-0.5 size-3.5 shrink-0" />
                Only tap this once the transfer has actually gone through. If the
                buyer doesn&apos;t receive it, your {inr(deposit)} deposit is
                forfeited.
              </p>
            </>
          )}
        </section>
      )}

      {status === "transfer_initiated" && (
        <section className="rounded-lg border border-border bg-card p-6 text-center">
          <p className="font-display text-2xl tracking-display">WAITING ON THE BUYER</p>
          <p className="mx-auto mt-2 max-w-sm text-sm text-muted-foreground">
            They&apos;re checking their ticketing app. Once they confirm, your
            payout and deposit are released.
          </p>
        </section>
      )}

      {(status === "transfer_confirmed" || status === "released") && (
        <section className="rounded-lg border border-success/40 bg-success/5 p-6 text-center">
          <CheckCircle2 className="mx-auto size-8 text-success" />
          <p className="mt-3 font-display text-2xl tracking-display">
            {status === "released" ? "PAID OUT" : "BUYER CONFIRMED"}
          </p>
          <p className="mt-2 text-sm text-muted-foreground">{meta.sellerHint}</p>
        </section>
      )}

      {status === "failed" && (
        <section className="rounded-lg border border-destructive/40 bg-destructive/5 p-6 text-center">
          <TriangleAlert className="mx-auto size-8 text-destructive" />
          <p className="mt-3 font-display text-2xl tracking-display">TRANSFER FAILED</p>
          <p className="mt-2 text-sm text-muted-foreground">{meta.sellerHint}</p>
        </section>
      )}
    </div>
  );
}
