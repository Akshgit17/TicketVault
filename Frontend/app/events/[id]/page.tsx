"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Calendar, MapPin, ShieldCheck, TicketX } from "lucide-react";

import { api } from "@/lib/api";
import { formatEventDate, inr, relativeTo } from "@/lib/utils";
import { BuyTicketModal } from "@/components/ui/BuyTicketModal";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";

export default function EventPage({ params }: { params: { id: string } }) {
  const [event, setEvent] = useState<any>(null);
  const [listings, setListings] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<any>(null);

  useEffect(() => {
    (async () => {
      setLoading(true);
      setError("");
      try {
        // Both endpoints are public — no auth needed.
        const [ev, ls] = await Promise.all([
          api.get(`/events/${params.id}`),
          api.get("/listings", { params: { event_id: params.id } }),
        ]);
        setEvent(ev.data);
        // Cheapest first: the price is what people are here to compare.
        setListings((ls.data ?? []).sort((a: any, b: any) => a.price - b.price));
      } catch (e: any) {
        setError(e.message ?? "Failed to load event.");
      } finally {
        setLoading(false);
      }
    })();
  }, [params.id]);

  if (loading) {
    return (
      <div>
        <Skeleton className="h-80 rounded-none" />
        <div className="container max-w-5xl space-y-4 py-12">
          <Skeleton className="h-8 w-56" />
          <Skeleton className="h-32" />
        </div>
      </div>
    );
  }

  if (error || !event) {
    return (
      <div className="container max-w-lg py-24">
        <EmptyState
          icon={TicketX}
          title="Event not found"
          description={error || "We couldn't find that event."}
          actionLabel="Browse events"
          actionHref="/marketplace"
        />
      </div>
    );
  }

  const title = event.title ?? event.name ?? "Untitled event";
  const d = formatEventDate(event.date);
  const cheapest = listings[0]?.price;

  return (
    <div>
      <section className="relative h-80 overflow-hidden md:h-96">
        {event.image_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={event.image_url} alt="" className="size-full object-cover opacity-45" />
        ) : (
          <div className="size-full bg-gradient-to-br from-zinc-800 to-zinc-950" />
        )}
        <div className="absolute inset-0 bg-gradient-to-t from-background via-background/60 to-transparent" />

        <div className="absolute inset-x-0 bottom-0">
          <div className="container max-w-5xl pb-10">
            <div className="mb-3 flex flex-wrap gap-2">
              <Badge>{relativeTo(event.date)}</Badge>
              {event.cities?.name && <Badge variant="neutral">{event.cities.name}</Badge>}
            </div>
            <h1 className="font-display text-5xl leading-[0.95] tracking-display md:text-7xl">
              {title}
            </h1>
            <div className="mt-4 flex flex-wrap gap-5 text-sm text-muted-foreground">
              <span className="flex items-center gap-1.5">
                <Calendar className="size-4" />
                <span className="tnum">{d.full} · {d.time}</span>
              </span>
              <span className="flex items-center gap-1.5">
                <MapPin className="size-4" />
                {event.venue}
              </span>
            </div>
          </div>
        </div>
      </section>

      <div className="container max-w-5xl py-12">
        <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="eyebrow mb-2">
              {listings.length} available
              {cheapest ? ` · from ${inr(cheapest)}` : ""}
            </p>
            <h2 className="font-display text-3xl tracking-display">TICKETS</h2>
          </div>
          <Button asChild variant="outline" size="sm">
            <Link href="/sell">Sell yours</Link>
          </Button>
        </div>

        {listings.length === 0 ? (
          <EmptyState
            icon={TicketX}
            title="No tickets listed yet"
            description="Nobody is selling for this show right now. If you have a spare, you'd be the first."
            actionLabel="List a ticket"
            actionHref="/sell"
          />
        ) : (
          <div className="space-y-3">
            {listings.map((l) => {
              const saving =
                l.original_price > l.price
                  ? Math.round((1 - l.price / l.original_price) * 100)
                  : 0;

              return (
                <div
                  key={l.id}
                  className="flex flex-wrap items-center gap-5 rounded-lg border border-border bg-card p-5"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2.5">
                      <p className="tnum font-mono text-2xl text-primary">{inr(l.price)}</p>
                      {saving > 0 && <Badge variant="success">{saving}% below face</Badge>}
                    </div>
                    <p className="tnum mt-1 font-mono text-xs text-muted-foreground">
                      Face value {inr(l.original_price)}
                    </p>
                  </div>

                  <div className="flex items-center gap-4">
                    <span className="hidden items-center gap-1.5 text-xs text-muted-foreground sm:flex">
                      <ShieldCheck className="size-3.5 text-primary" />
                      Escrow protected
                    </span>
                    <Button onClick={() => setSelected(l)}>Buy</Button>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        <div className="mt-8 flex gap-3 rounded-lg border border-border bg-secondary/30 p-5 text-sm">
          <ShieldCheck className="mt-0.5 size-4 shrink-0 text-primary" />
          <p className="text-muted-foreground">
            Your payment is held until the seller transfers the ticket to your
            ticketing account and you confirm you&apos;ve got it. If they
            don&apos;t deliver, you&apos;re refunded in full and compensated from
            their deposit.
          </p>
        </div>
      </div>

      {selected && (
        <BuyTicketModal
          listing={selected}
          event={event}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  );
}
