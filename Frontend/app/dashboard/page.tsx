"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@clerk/nextjs";
import { toast } from "sonner";
import {
  ArrowRight, Banknote, CalendarClock, Inbox, Ticket, TicketX, Wallet,
} from "lucide-react";

import { api, setAuthToken } from "@/lib/api";
import { useConfig } from "@/lib/config";
import {
  EVENT_REQUEST_STATUS, FULFILLMENT_STATUS, LISTING_STATUS, statusMeta,
} from "@/lib/status";
import { formatEventDate, inr, relativeTo } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { RepriceDialog } from "@/components/ui/RepriceDialog";

declare global {
  interface Window { Razorpay: any; }
}

export default function DashboardPage() {
  const { getToken } = useAuth();
  const { config } = useConfig();

  const [listings, setListings] = useState<any[]>([]);
  const [purchases, setPurchases] = useState<any[]>([]);
  const [sales, setSales] = useState<any[]>([]);
  const [requests, setRequests] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      setAuthToken(await getToken());
      // Settled, not all — a seller with no payout account shouldn't lose the
      // whole dashboard because one endpoint 404s.
      const [l, p, s, r] = await Promise.allSettled([
        api.get("/listings/my/all"),
        api.get("/bookings/my/all"),
        api.get("/sellers/me/sales"),
        api.get("/events/requests/mine"),
      ]);
      if (l.status === "fulfilled") setListings(l.value.data ?? []);
      if (p.status === "fulfilled") setPurchases(p.value.data ?? []);
      if (s.status === "fulfilled") setSales(s.value.data ?? []);
      if (r.status === "fulfilled") setRequests(r.value.data ?? []);
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  useEffect(() => { load(); }, [load]);

  const payDeposit = async (listingId: string) => {
    try {
      setAuthToken(await getToken());
      const { data: fee } = await api.post(`/listings/${listingId}/initiate-fee`);

      const rzp = new window.Razorpay({
        key: fee.razorpay_key_id,
        amount: Math.round(fee.amount * 100),
        order_id: fee.razorpay_order_id,
        name: "TicketVault",
        description: "Refundable security deposit",
        theme: { color: "#f59e0b" },
        handler: async (res: any) => {
          try {
            setAuthToken(await getToken());
            await api.post(`/listings/${listingId}/verify-fee`, {
              razorpay_order_id: res.razorpay_order_id,
              razorpay_payment_id: res.razorpay_payment_id,
              razorpay_signature: res.razorpay_signature,
            });
            toast.success("Your listing is live");
            await load();
          } catch (e: any) {
            toast.error("Deposit not confirmed", { description: e.message });
          }
        },
      });
      rzp.open();
    } catch (e: any) {
      toast.error("Couldn't start the payment", { description: e.message });
    }
  };

  const unlist = async (listingId: string) => {
    try {
      setAuthToken(await getToken());
      const { data } = await api.post(`/listings/${listingId}/unlist`);
      // Withdrawing now returns the deposit, since no buyer was let down.
      // Saying so matters: the seller is parting with a listing and needs to
      // know they are not also parting with their money.
      toast.success("Listing removed", {
        description: data?.deposit_refunded_paise
          ? `Your ${inr(data.deposit_refunded_paise / 100)} deposit is on its way back.`
          : undefined,
      });
      await load();
    } catch (e: any) {
      toast.error("Couldn't unlist", { description: e.message });
    }
  };

  // Sales the seller must act on. This count is the reason the dashboard
  // exists — previously a seller had no signal at all that a ticket had sold.
  const actionNeeded = sales.filter(
    (s) => (s.fulfillment_status ?? "not_started") === "awaiting_transfer"
  ).length;

  if (loading) {
    return (
      <div className="container max-w-5xl space-y-4 py-14">
        <Skeleton className="h-12 w-64" />
        <Skeleton className="h-24" />
        <Skeleton className="h-64" />
      </div>
    );
  }

  return (
    <div className="container max-w-5xl py-14">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow mb-2">Your account</p>
          <h1 className="font-display text-5xl tracking-display">DASHBOARD</h1>
        </div>
        <Button asChild variant="outline" size="sm">
          <Link href="/dashboard/payout">
            <Wallet />
            Payout details
          </Link>
        </Button>
      </div>

      {actionNeeded > 0 && (
        <div className="mt-8 flex flex-wrap items-center gap-4 rounded-lg border border-primary/40 bg-primary/5 p-5">
          <CalendarClock className="size-5 shrink-0 text-primary" />
          <div className="min-w-0 flex-1">
            <p className="font-medium">
              {actionNeeded} ticket{actionNeeded === 1 ? "" : "s"} waiting to be transferred
            </p>
            <p className="text-sm text-muted-foreground">
              Transfer within {config.transfer_sla_hours} hours or your deposit is forfeited.
            </p>
          </div>
          <Button asChild size="sm">
            <a href="#sales">Review <ArrowRight /></a>
          </Button>
        </div>
      )}

      <Tabs defaultValue="purchases" className="mt-10">
        <TabsList>
          <TabsTrigger value="purchases">Purchases ({purchases.length})</TabsTrigger>
          <TabsTrigger value="sales">
            Sales ({sales.length}){actionNeeded > 0 ? " ●" : ""}
          </TabsTrigger>
          <TabsTrigger value="listings">Listings ({listings.length})</TabsTrigger>
          {requests.length > 0 && (
            <TabsTrigger value="requests">Event requests ({requests.length})</TabsTrigger>
          )}
        </TabsList>

        {/* ---- Purchases ---- */}
        <TabsContent value="purchases">
          {purchases.length === 0 ? (
            <EmptyState
              icon={Ticket}
              title="No purchases yet"
              description="Tickets you buy will appear here, with the transfer status of each."
              actionLabel="Browse tickets"
              actionHref="/marketplace"
            />
          ) : (
            <div className="space-y-3">
              {purchases.map((b) => {
                const meta = statusMeta(FULFILLMENT_STATUS, b.fulfillment_status ?? "not_started");
                const ev = b.listings?.events;
                return (
                  <Link
                    key={b.id}
                    href={`/bookings/${b.id}/confirm`}
                    className="flex items-center gap-4 rounded-lg border border-border bg-card p-5 transition-colors hover:border-zinc-700"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2.5">
                        <p className="font-display text-xl tracking-display">
                          {ev?.title ?? "Ticket"}
                        </p>
                        <Badge variant={meta.tone}>{meta.label}</Badge>
                      </div>
                      <p className="mt-1 truncate text-xs text-muted-foreground">
                        {ev?.venue}
                        {ev?.date ? ` · ${formatEventDate(ev.date).full}` : ""}
                      </p>
                      {meta.buyerHint && (
                        <p className="mt-1.5 text-sm text-muted-foreground">{meta.buyerHint}</p>
                      )}
                    </div>
                    <div className="shrink-0 text-right">
                      {/* Show what came back, not what was charged. After a
                          failed transfer the amount paid is the least useful
                          number on the row. */}
                      {b.refund?.refunded_paise ? (
                        <>
                          <p className="tnum font-mono text-lg text-success">
                            +{inr(b.refund.refunded_paise / 100)}
                          </p>
                          <p className="text-[11px] text-muted-foreground">refunded</p>
                          {b.refund.compensation_paise > 0 && (
                            <p className="tnum text-[11px] text-primary">
                              +{inr(b.refund.compensation_paise / 100)} compensation
                            </p>
                          )}
                        </>
                      ) : (
                        <p className="tnum font-mono text-lg">{inr(b.total_price)}</p>
                      )}
                      <ArrowRight className="ml-auto mt-1 size-4 text-muted-foreground" />
                    </div>
                  </Link>
                );
              })}
            </div>
          )}
        </TabsContent>

        {/* ---- Sales ---- */}
        <TabsContent value="sales" id="sales">
          {sales.length === 0 ? (
            <EmptyState
              icon={Banknote}
              title="Nothing sold yet"
              description="When someone buys one of your tickets, it shows up here and you'll transfer it from your ticketing app."
              actionLabel="List a ticket"
              actionHref="/sell"
            />
          ) : (
            <div className="space-y-3">
              {sales.map((s) => {
                const status = s.fulfillment_status ?? "not_started";
                const meta = statusMeta(FULFILLMENT_STATUS, status);
                const ev = s.listings?.events;
                const urgent = status === "awaiting_transfer";
                return (
                  <Link
                    key={s.id}
                    href={`/dashboard/sales/${s.id}`}
                    className={`flex items-center gap-4 rounded-lg border bg-card p-5 transition-colors ${
                      urgent ? "border-primary/50 hover:border-primary" : "border-border hover:border-zinc-700"
                    }`}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2.5">
                        <p className="font-display text-xl tracking-display">
                          {ev?.title ?? "Ticket"}
                        </p>
                        <Badge variant={meta.tone}>{meta.label}</Badge>
                      </div>
                      {meta.sellerHint && (
                        <p className="mt-1.5 text-sm text-muted-foreground">{meta.sellerHint}</p>
                      )}
                      {urgent && s.transfer_deadline && (
                        <p className="tnum mt-1 font-mono text-xs text-primary">
                          Due {relativeTo(s.transfer_deadline)}
                        </p>
                      )}
                    </div>
                    <div className="shrink-0 text-right">
                      <p className="tnum font-mono text-lg">{inr(s.listings?.price ?? 0)}</p>
                      <ArrowRight className="ml-auto mt-1 size-4 text-muted-foreground" />
                    </div>
                  </Link>
                );
              })}
            </div>
          )}
        </TabsContent>

        {/* ---- Listings ---- */}
        <TabsContent value="listings">
          {listings.length === 0 ? (
            <EmptyState
              icon={TicketX}
              title="No listings"
              description="List a ticket you can't use and we'll handle the payment, the transfer, and the payout."
              actionLabel="Sell a ticket"
              actionHref="/sell"
            />
          ) : (
            <div className="space-y-3">
              {listings.map((l) => {
                const meta = statusMeta(LISTING_STATUS, l.status);
                const needsDeposit = l.status === "pending_fee" || l.status === "pending_deposit";
                const deposit = Number(l.price ?? 0) * config.listing_fee_rate;

                return (
                  <div
                    key={l.id}
                    className="flex flex-wrap items-center gap-4 rounded-lg border border-border bg-card p-5"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2.5">
                        <p className="font-display text-xl tracking-display">
                          {l.events?.title ?? "Listing"}
                        </p>
                        <Badge variant={meta.tone}>{meta.label}</Badge>
                      </div>
                      <p className="mt-1 truncate text-xs text-muted-foreground">
                        {l.events?.venue}
                        {l.cities?.name ? ` · ${l.cities.name}` : ""}
                      </p>
                      {meta.sellerHint && (
                        <p className="mt-1.5 text-sm text-muted-foreground">{meta.sellerHint}</p>
                      )}
                    </div>

                    <p className="tnum shrink-0 font-mono text-lg">{inr(l.price)}</p>

                    <div className="flex shrink-0 gap-2">
                      {needsDeposit && (
                        <Button size="sm" onClick={() => payDeposit(l.id)}>
                          Pay {inr(deposit)} deposit
                        </Button>
                      )}
                      {/* Live listings only. A sold or reserved ticket has a
                          buyer who agreed to a price, so it cannot move. */}
                      {l.status === "active" && (
                        <RepriceDialog listing={l} onDone={load} />
                      )}
                      {(l.status === "active" || needsDeposit) && (
                        <Button size="sm" variant="ghost" onClick={() => unlist(l.id)}>
                          Remove
                        </Button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </TabsContent>

        {/* ---- Event requests ---- */}
        {requests.length > 0 && (
          <TabsContent value="requests">
            <div className="space-y-3">
              {requests.map((r) => {
                const meta = statusMeta(EVENT_REQUEST_STATUS, r.status);
                return (
                  <div key={r.id} className="rounded-lg border border-border bg-card p-5">
                    <div className="flex flex-wrap items-center gap-2.5">
                      <p className="font-display text-xl tracking-display">{r.title}</p>
                      <Badge variant={meta.tone}>{meta.label}</Badge>
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {r.venue}
                      {r.cities?.name ? ` · ${r.cities.name}` : ""}
                      {r.date ? ` · ${formatEventDate(r.date).full}` : ""}
                    </p>
                    {r.review_note && (
                      <p className="mt-3 rounded-md border border-border bg-secondary/40 p-3 text-sm text-muted-foreground">
                        <span className="text-foreground">Reviewer:</span> {r.review_note}
                      </p>
                    )}
                    {r.status === "approved" && r.event_id && (
                      <Button asChild size="sm" className="mt-4">
                        <Link href="/sell">List a ticket for this <ArrowRight /></Link>
                      </Button>
                    )}
                  </div>
                );
              })}
            </div>
          </TabsContent>
        )}
      </Tabs>

      {purchases.length === 0 && sales.length === 0 && listings.length === 0 && (
        <div className="mt-10 flex items-center gap-3 rounded-lg border border-dashed border-border p-5 text-sm text-muted-foreground">
          <Inbox className="size-4 shrink-0" />
          Nothing here yet. Buy a ticket or list one to get started.
        </div>
      )}
    </div>
  );
}
