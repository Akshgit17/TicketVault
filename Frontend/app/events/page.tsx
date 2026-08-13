"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { CalendarX2, Search } from "lucide-react";

import { api } from "@/lib/api";
import { useCityStore } from "@/store/city";
import { EventCard, type EventSummary } from "@/components/ui/EventCard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";

/**
 * Every upcoming concert, whether or not anyone has listed a ticket.
 *
 * Distinct from /marketplace, which lists TICKETS FOR SALE. Conflating the two
 * is what made "View all" under "Upcoming shows" land on a page that was often
 * emptier than the section it came from: a catalogue of 35 concerts linking
 * through to zero listings.
 *
 * A concert with nothing listed still belongs here. Someone browsing wants to
 * know the show exists so they can come back, and a seller wants to find it to
 * list against. The card says plainly which it is rather than hiding the ones
 * with no stock.
 */
export default function EventsPage() {
  const { selected, setCity } = useCityStore();
  const [events, setEvents] = useState<EventSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");

  useEffect(() => {
    setLoading(true);
    const params: Record<string, string | boolean | number> = {
      with_availability: true,
      limit: 100,
    };
    if (selected?.id) params.city_id = selected.id;

    api
      .get("/events", { params })
      .then(({ data }) => setEvents(data ?? []))
      .catch(() => setEvents([]))
      .finally(() => setLoading(false));
  }, [selected?.id]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return events;
    return events.filter((e) => {
      const title = (e.title ?? e.name ?? "").toLowerCase();
      return title.includes(q) || (e.venue ?? "").toLowerCase().includes(q);
    });
  }, [events, query]);

  const withTickets = filtered.filter((e) => (e.listing_count ?? 0) > 0).length;

  return (
    <div className="container py-14">
      <div className="mb-8 flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="eyebrow mb-2">What&apos;s on</p>
          <h1 className="font-display text-5xl tracking-display">ALL CONCERTS</h1>

          <p className="mt-1.5 text-sm text-muted-foreground">
            {loading ? (
              "Loading concerts…"
            ) : (
              <>
                {filtered.length} upcoming{" "}
                {selected ? (
                  <>
                    in <span className="text-foreground">{selected.name}</span>
                    {". "}
                    <button
                      onClick={() => setCity(null)}
                      className="text-primary underline-offset-4 hover:underline"
                    >
                      Show every city
                    </button>
                  </>
                ) : (
                  <>
                    across <span className="text-foreground">every city</span>
                    {". "}
                  </>
                )}
                {filtered.length > 0 && (
                  <span className="block sm:inline">
                    {withTickets} with tickets on sale.
                  </span>
                )}
              </>
            )}
          </p>
        </div>

        <div className="relative w-full sm:w-72">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search artist or venue"
            className="pl-9"
            aria-label="Search concerts"
          />
        </div>
      </div>

      {loading ? (
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-72" />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={CalendarX2}
          title={query ? "Nothing matches that" : "No upcoming concerts"}
          description={
            query
              ? "Try a different artist or venue."
              : selected
                ? `Nothing scheduled in ${selected.name} right now. Other cities may have shows.`
                : "The catalogue is empty. Run the seed SQL to populate events."
          }
          actionLabel={selected ? "Show every city" : undefined}
          actionHref={selected ? "/events" : undefined}
        />
      ) : (
        <>
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
            {filtered.map((e, i) => (
              <EventCard key={e.id} event={e} priority={i < 4} />
            ))}
          </div>

          <div className="mt-12 rounded-lg border border-dashed border-border p-6 text-center">
            <p className="text-sm text-muted-foreground">
              Can&apos;t find the show you&apos;re after?
            </p>
            <Button asChild variant="outline" size="sm" className="mt-3">
              <Link href="/sell">Request it when you list a ticket</Link>
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
