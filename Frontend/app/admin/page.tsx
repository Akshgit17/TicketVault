"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { toast } from "sonner";
import {
  CalendarCheck, CalendarX2, CheckCircle2, ExternalLink, Inbox, Scale,
  ShieldAlert, ShieldCheck, XCircle,
} from "lucide-react";

import { CancelEventDialog, EditEventDialog } from "@/components/ui/EventAdminDialogs";

import { api, setAuthToken } from "@/lib/api";
import { EVENT_REQUEST_STATUS, LISTING_STATUS, statusMeta } from "@/lib/status";
import { formatEventDate, inr } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle,
} from "@/components/ui/dialog";

/**
 * Admin surface. The nav link is hidden for non-admins, but that is cosmetic —
 * authorisation is enforced by the backend on every /admin call, which returns
 * 404 (not 403) so the surface is not confirmed to exist.
 */
export default function AdminPage() {
  const { getToken } = useAuth();

  const [denied, setDenied] = useState(false);
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState<any>(null);
  const [requests, setRequests] = useState<any[]>([]);
  const [listings, setListings] = useState<any[]>([]);
  const [bookings, setBookings] = useState<any[]>([]);

  const [disputes, setDisputes] = useState<any[]>([]);
  const [events, setEvents] = useState<any[]>([]);
  const [cities, setCities] = useState<any[]>([]);

  const [rejecting, setRejecting] = useState<any>(null);
  const [rejectNote, setRejectNote] = useState("");
  const [acting, setActing] = useState(false);

  // { dispute, resolution } while the admin is confirming a decision.
  const [resolving, setResolving] = useState<any>(null);
  const [resolveNote, setResolveNote] = useState("");

  const load = useCallback(async () => {
    try {
      setAuthToken(await getToken());
      const { data } = await api.get("/admin/stats");
      setStats(data);
      setDenied(false);

      const [r, l, b, d, ev, ct] = await Promise.allSettled([
        api.get("/admin/event-requests", { params: { status: "pending" } }),
        api.get("/admin/listings", { params: { limit: 50 } }),
        api.get("/admin/bookings", { params: { limit: 50 } }),
        api.get("/admin/disputes"),
        api.get("/admin/events", { params: { limit: 200 } }),
        api.get("/cities"),
      ]);
      if (r.status === "fulfilled") setRequests(r.value.data ?? []);
      if (l.status === "fulfilled") setListings(l.value.data ?? []);
      if (b.status === "fulfilled") setBookings(b.value.data ?? []);
      if (d.status === "fulfilled") setDisputes(d.value.data ?? []);
      if (ev.status === "fulfilled") setEvents(ev.value.data ?? []);
      if (ct.status === "fulfilled") setCities(ct.value.data ?? []);
    } catch {
      setDenied(true);
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  useEffect(() => { load(); }, [load]);

  const approve = async (id: string) => {
    setActing(true);
    try {
      setAuthToken(await getToken());
      await api.post(`/admin/event-requests/${id}/approve`);
      toast.success("Event added to the catalogue");
      await load();
    } catch (e: any) {
      toast.error("Couldn't approve", { description: e.message });
    } finally {
      setActing(false);
    }
  };

  const reject = async () => {
    if (!rejecting) return;
    setActing(true);
    try {
      setAuthToken(await getToken());
      await api.post(`/admin/event-requests/${rejecting.id}/reject`, {
        review_note: rejectNote.trim(),
      });
      toast.success("Request rejected", { description: "The seller will see your reason." });
      setRejecting(null);
      setRejectNote("");
      await load();
    } catch (e: any) {
      toast.error("Couldn't reject", { description: e.message });
    } finally {
      setActing(false);
    }
  };

  const resolveDispute = async () => {
    if (!resolving) return;
    setActing(true);
    try {
      setAuthToken(await getToken());
      await api.post(`/admin/disputes/${resolving.dispute.booking_id}/resolve`, {
        resolution: resolving.resolution,
        note: resolveNote.trim(),
      });
      toast.success(
        resolving.resolution === "uphold"
          ? "Buyer refunded and compensated"
          : "Dispute closed, payout released"
      );
      setResolving(null);
      setResolveNote("");
      await load();
    } catch (e: any) {
      toast.error("Couldn't resolve", { description: e.message });
    } finally {
      setActing(false);
    }
  };

  if (loading) {
    return (
      <div className="container max-w-6xl space-y-4 py-14">
        <Skeleton className="h-12 w-64" />
        <Skeleton className="h-24" />
        <Skeleton className="h-64" />
      </div>
    );
  }

  if (denied) {
    return (
      <div className="container max-w-lg py-24">
        <EmptyState
          icon={ShieldAlert}
          title="Not available"
          description="This area isn't available for your account."
          actionLabel="Back to home"
          actionHref="/"
        />
      </div>
    );
  }

  const TILES = [
    { label: "Open disputes",    value: disputes.length, accent: true, urgent: true },
    { label: "Pending requests", value: stats?.pending_event_requests ?? 0, accent: true },
    { label: "Active listings",  value: stats?.active_listings ?? 0 },
    { label: "Users",            value: stats?.total_users ?? 0 },
  ];

  return (
    <div className="container max-w-6xl py-14">
      <div className="flex items-center gap-2.5">
        <ShieldCheck className="size-5 text-primary" />
        <p className="eyebrow">Admin</p>
      </div>
      <h1 className="mt-2 font-display text-5xl tracking-display">CONTROL ROOM</h1>

      <div className="mt-8 grid gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-2 lg:grid-cols-4">
        {TILES.map((t) => (
          <div key={t.label} className="bg-card p-5">
            <p className="eyebrow mb-2">{t.label}</p>
            <p
              className={`tnum font-mono text-3xl ${
                t.value > 0
                  ? t.urgent
                    ? "text-destructive"
                    : t.accent
                      ? "text-primary"
                      : ""
                  : ""
              }`}
            >
              {t.value}
            </p>
          </div>
        ))}
      </div>

      <Tabs defaultValue="disputes" className="mt-10">
        <TabsList>
          <TabsTrigger value="disputes">
            Disputes ({disputes.length}){disputes.length > 0 ? " ●" : ""}
          </TabsTrigger>
          <TabsTrigger value="concerts">Concerts ({events.length})</TabsTrigger>
          <TabsTrigger value="requests">Event requests ({requests.length})</TabsTrigger>
          <TabsTrigger value="listings">Listings ({listings.length})</TabsTrigger>
          <TabsTrigger value="bookings">Bookings ({bookings.length})</TabsTrigger>
        </TabsList>

        {/* ---- Dispute queue ---- */}
        <TabsContent value="disputes">
          {disputes.length === 0 ? (
            <EmptyState
              icon={Scale}
              title="Nothing disputed"
              description="No buyer has reported a problem. Seller payouts are running normally."
            />
          ) : (
            <div className="space-y-4">
              <p className="text-sm text-muted-foreground">
                A dispute freezes the seller&apos;s payout until it is resolved
                here. Freezing is reversible, paying out is not, so leaving one
                open costs an honest seller time but never money.
              </p>

              {disputes.map((d) => {
                const serial = d.buyer_prior_disputes >= 3;
                return (
                  <div key={d.booking_id} className="rounded-lg border border-border bg-card p-5">
                    <div className="flex flex-wrap items-start justify-between gap-4">
                      <div className="min-w-0">
                        <p className="font-display text-2xl tracking-display">
                          {d.event ?? "Booking"}
                        </p>
                        <p className="mt-1 text-sm text-muted-foreground">
                          Buyer {d.buyer?.email ?? "?"} · Seller {d.seller?.email ?? "?"}
                        </p>
                        <p className="tnum mt-1 font-mono text-xs text-muted-foreground">
                          {d.booking_id.slice(0, 8)} · {inr(d.total_price)} ·{" "}
                          {d.deposit_paise ? `deposit ${inr(d.deposit_paise / 100)}` : "no deposit"}
                        </p>
                      </div>

                      <div className="flex shrink-0 gap-2">
                        <Button
                          size="sm"
                          variant="outline"
                          className="border-destructive/40 text-destructive hover:bg-destructive/10"
                          onClick={() => { setResolving({ dispute: d, resolution: "uphold" }); setResolveNote(""); }}
                        >
                          Uphold
                        </Button>
                        <Button
                          size="sm"
                          onClick={() => { setResolving({ dispute: d, resolution: "reject" }); setResolveNote(""); }}
                        >
                          Reject
                        </Button>
                      </div>
                    </div>

                    {/* The two signals that decide most cases. */}
                    <div className="mt-4 grid gap-3 sm:grid-cols-2">
                      <div
                        className={`rounded-md border p-3 text-sm ${
                          d.seller_provided_proof
                            ? "border-border bg-secondary/30"
                            : "border-primary/40 bg-primary/5"
                        }`}
                      >
                        <p className="font-medium">
                          {d.seller_provided_proof
                            ? "Seller provided proof"
                            : "No proof from the seller"}
                        </p>
                        <p className="mt-1 text-xs text-muted-foreground">
                          {d.seller_provided_proof
                            ? "Genuinely contested. Read both sides before deciding."
                            : "The buyer's account is the only account there is."}
                        </p>
                        {d.transfer_proof_url && (
                          <a
                            href={d.transfer_proof_url}
                            target="_blank"
                            rel="noopener noreferrer nofollow"
                            className="mt-2 inline-flex items-center gap-1.5 text-xs text-primary hover:underline"
                          >
                            <ExternalLink className="size-3" />
                            View proof
                          </a>
                        )}
                      </div>

                      <div
                        className={`rounded-md border p-3 text-sm ${
                          serial
                            ? "border-destructive/40 bg-destructive/5"
                            : "border-border bg-secondary/30"
                        }`}
                      >
                        <p className="font-medium">
                          {d.buyer_prior_disputes === 1
                            ? "First dispute from this buyer"
                            : `${d.buyer_prior_disputes} disputes from this buyer`}
                        </p>
                        <p className="mt-1 text-xs text-muted-foreground">
                          {serial
                            ? "A pattern worth checking before you uphold."
                            : "Nothing unusual."}
                        </p>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </TabsContent>

        {/* ---- Concerts ---- */}
        <TabsContent value="concerts">
          {events.length === 0 ? (
            <EmptyState
              icon={CalendarX2}
              title="No concerts"
              description="The catalogue is empty. Run the seed SQL to populate events."
            />
          ) : (
            <>
              <p className="mb-4 text-sm text-muted-foreground">
                Every concert, including past and cancelled ones. Moving a date
                is a postponement and keeps existing tickets valid. Cancelling
                refunds every buyer and returns every deposit.
              </p>

              <div className="rounded-lg border border-border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Concert</TableHead>
                      <TableHead>When</TableHead>
                      <TableHead>Tickets</TableHead>
                      <TableHead>State</TableHead>
                      <TableHead className="text-right">Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {events.map((e) => {
                      const isPast = new Date(e.date) <= new Date();
                      const cancelled = Boolean(e.cancelled_at);
                      return (
                        <TableRow key={e.id} className={cancelled ? "opacity-55" : ""}>
                          <TableCell className="max-w-[240px]">
                            <p className="truncate">{e.title}</p>
                            <p className="truncate text-xs text-muted-foreground">
                              {e.venue}
                              {e.cities?.name ? ` · ${e.cities.name}` : ""}
                            </p>
                          </TableCell>

                          <TableCell className="tnum whitespace-nowrap text-xs">
                            {formatEventDate(e.date).full}
                            {e.postponed_from && (
                              <span className="block text-[11px] text-primary">
                                moved from {formatEventDate(e.postponed_from).full}
                              </span>
                            )}
                          </TableCell>

                          <TableCell className="tnum whitespace-nowrap text-xs text-muted-foreground">
                            {e.active_listings ?? 0} live
                            {(e.sold_listings ?? 0) > 0 && `, ${e.sold_listings} sold`}
                          </TableCell>

                          <TableCell>
                            {cancelled ? (
                              <Badge variant="destructive">cancelled</Badge>
                            ) : isPast ? (
                              <Badge variant="neutral">finished</Badge>
                            ) : e.transfer_supported ? (
                              <Badge variant="success">live</Badge>
                            ) : (
                              <Badge variant="neutral">no transfer</Badge>
                            )}
                          </TableCell>

                          <TableCell className="text-right">
                            {cancelled ? (
                              <span
                                className="text-xs text-muted-foreground"
                                title={e.cancellation_reason ?? undefined}
                              >
                                {e.cancellation_reason
                                  ? `"${String(e.cancellation_reason).slice(0, 30)}"`
                                  : "cancelled"}
                              </span>
                            ) : (
                              <div className="flex justify-end gap-1">
                                <EditEventDialog event={e} cities={cities} onDone={load} />
                                <CancelEventDialog event={e} onDone={load} />
                              </div>
                            )}
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </div>
            </>
          )}
        </TabsContent>

        {/* ---- Approval queue ---- */}
        <TabsContent value="requests">
          {requests.length === 0 ? (
            <EmptyState
              icon={Inbox}
              title="Queue is clear"
              description="No sellers are waiting on an event to be added."
            />
          ) : (
            <div className="space-y-4">
              {requests.map((r) => {
                const meta = statusMeta(EVENT_REQUEST_STATUS, r.status);
                return (
                  <div key={r.id} className="rounded-lg border border-border bg-card p-5">
                    <div className="flex flex-wrap items-start justify-between gap-4">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2.5">
                          <p className="font-display text-2xl tracking-display">{r.title}</p>
                          <Badge variant={meta.tone}>{meta.label}</Badge>
                        </div>
                        <p className="mt-1.5 text-sm text-muted-foreground">
                          {r.venue}
                          {r.cities?.name ? ` · ${r.cities.name}` : ""}
                          {r.date ? ` · ${formatEventDate(r.date).full}` : ""}
                        </p>
                        <p className="mt-1 text-xs text-muted-foreground">
                          Requested by {r.users?.name ?? "—"} ({r.users?.email ?? "—"})
                        </p>
                      </div>

                      <div className="flex shrink-0 gap-2">
                        <Button size="sm" loading={acting} onClick={() => approve(r.id)}>
                          <CheckCircle2 />
                          Approve
                        </Button>
                        <Button
                          size="sm" variant="outline"
                          className="border-destructive/40 text-destructive hover:bg-destructive/10"
                          onClick={() => setRejecting(r)}
                        >
                          <XCircle />
                          Reject
                        </Button>
                      </div>
                    </div>

                    {(r.evidence_url || r.notes) && (
                      <div className="mt-4 space-y-2 rounded-md border border-border bg-secondary/30 p-4 text-sm">
                        {r.evidence_url && (
                          <a
                            href={r.evidence_url}
                            target="_blank"
                            rel="noopener noreferrer nofollow"
                            className="inline-flex items-center gap-1.5 text-primary hover:underline"
                          >
                            <ExternalLink className="size-3.5" />
                            Evidence link
                          </a>
                        )}
                        {r.notes && <p className="text-muted-foreground">{r.notes}</p>}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </TabsContent>

        {/* ---- Listings ---- */}
        <TabsContent value="listings">
          {listings.length === 0 ? (
            <EmptyState icon={CalendarCheck} title="No listings" description="Nothing has been listed yet." />
          ) : (
            <div className="rounded-lg border border-border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Event</TableHead>
                    <TableHead>Seller</TableHead>
                    <TableHead>Price</TableHead>
                    <TableHead>Face</TableHead>
                    <TableHead>Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {listings.map((l) => {
                    const meta = statusMeta(LISTING_STATUS, l.status);
                    return (
                      <TableRow key={l.id}>
                        <TableCell className="max-w-[240px] truncate">
                          {l.events?.title ?? "—"}
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {l.users?.email ?? "—"}
                        </TableCell>
                        <TableCell className="tnum font-mono">{inr(l.price)}</TableCell>
                        <TableCell className="tnum font-mono text-muted-foreground">
                          {inr(l.original_price)}
                        </TableCell>
                        <TableCell><Badge variant={meta.tone}>{meta.label}</Badge></TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </TabsContent>

        {/* ---- Bookings ---- */}
        <TabsContent value="bookings">
          {bookings.length === 0 ? (
            <EmptyState icon={CalendarCheck} title="No bookings" description="Nothing has been bought yet." />
          ) : (
            <div className="rounded-lg border border-border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Event</TableHead>
                    <TableHead>Amount</TableHead>
                    <TableHead>Payment</TableHead>
                    <TableHead>Fulfilment</TableHead>
                    <TableHead>Placed</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {bookings.map((b) => (
                    <TableRow key={b.id}>
                      <TableCell className="max-w-[240px] truncate">
                        {b.listings?.events?.title ?? "—"}
                      </TableCell>
                      <TableCell className="tnum font-mono">{inr(b.total_price)}</TableCell>
                      <TableCell>
                        <Badge variant={b.payment_status === "paid" ? "success" : "neutral"}>
                          {b.payment_status}
                        </Badge>
                      </TableCell>
                      <TableCell className="font-mono text-xs text-muted-foreground">
                        {b.fulfillment_status ?? "not_started"}
                      </TableCell>
                      <TableCell className="tnum text-xs text-muted-foreground">
                        {b.created_at ? formatEventDate(b.created_at).full : "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </TabsContent>
      </Tabs>

      {/* Both outcomes move money, so the dialog states exactly what will
          happen rather than asking for a bare confirmation. */}
      <Dialog open={Boolean(resolving)} onOpenChange={(o) => !o && setResolving(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {resolving?.resolution === "uphold" ? "UPHOLD DISPUTE" : "REJECT DISPUTE"}
            </DialogTitle>
            <DialogDescription>{resolving?.dispute?.event}</DialogDescription>
          </DialogHeader>

          <div className="space-y-4 p-5">
            <div
              className={`rounded-md border p-4 text-sm ${
                resolving?.resolution === "uphold"
                  ? "border-destructive/40 bg-destructive/5"
                  : "border-border bg-secondary/30"
              }`}
            >
              {resolving?.resolution === "uphold" ? (
                <ul className="space-y-1.5 text-muted-foreground">
                  <li>
                    Buyer refunded{" "}
                    <span className="tnum text-foreground">
                      {inr(resolving?.dispute?.total_price ?? 0)}
                    </span>
                  </li>
                  <li>Seller&apos;s deposit forfeited, part of it paid to the buyer</li>
                  <li>Listing taken off sale until a new deposit is paid</li>
                </ul>
              ) : (
                <ul className="space-y-1.5 text-muted-foreground">
                  <li>The freeze lifts and the seller is paid on the next job run</li>
                  <li>The buyer keeps the ticket and receives nothing back</li>
                </ul>
              )}
            </div>

            <div className="space-y-2">
              <Label htmlFor="resolve-note">Reason</Label>
              <Textarea
                id="resolve-note"
                value={resolveNote}
                onChange={(e) => setResolveNote(e.target.value)}
                placeholder="What decided it. This is the audit record."
              />
            </div>
          </div>

          <DialogFooter>
            <Button variant="ghost" onClick={() => setResolving(null)}>Cancel</Button>
            <Button
              variant={resolving?.resolution === "uphold" ? "destructive" : "default"}
              loading={acting}
              disabled={resolveNote.trim().length < 3}
              onClick={resolveDispute}
            >
              {resolving?.resolution === "uphold" ? "Refund the buyer" : "Release the payout"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Rejection always carries a reason. Without one the seller gets a
          support ticket instead of a corrected resubmission. */}
      <Dialog open={Boolean(rejecting)} onOpenChange={(o) => !o && setRejecting(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>REJECT REQUEST</DialogTitle>
            <DialogDescription>
              {rejecting?.title}. The seller sees this reason, so make it
              actionable.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2 p-5">
            <Label htmlFor="note">Reason</Label>
            <Textarea
              id="note" value={rejectNote}
              onChange={(e) => setRejectNote(e.target.value)}
              placeholder="e.g. We couldn't verify this event exists. Send a link to the official booking page."
            />
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setRejecting(null)}>Cancel</Button>
            <Button
              variant="destructive" loading={acting}
              disabled={!rejectNote.trim()} onClick={reject}
            >
              Reject request
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
