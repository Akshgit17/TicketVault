"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Calendar, MapPin, Search, TicketX } from "lucide-react";

import { api } from "@/lib/api";
import { useCityStore } from "@/store/city";
import { inr, relativeTo } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";

interface Listing {
  id: string;
  price: number;
  original_price: number;
  quantity: number;
  event_id?: string;
  events?: { id: string; title?: string; name?: string; venue: string; date: string } | null;
  cities?: { name: string } | null;
}

export default function MarketplacePage() {
  // The navbar selector is the single source of the active city — this page no
  // longer keeps a second, separately-managed filter that could disagree with it.
  const { selected, setCity } = useCityStore();
  const [listings, setListings] = useState<Listing[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");

  useEffect(() => {
    setLoading(true);
    const params: Record<string, string> = {};
    if (selected?.id) params.city_id = selected.id;

    api
      .get("/listings", { params })
      .then(({ data }) => setListings(data ?? []))
      .catch(() => setListings([]))
      .finally(() => setLoading(false));
  }, [selected?.id]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return listings;
    return listings.filter((l) => {
      const title = (l.events?.title ?? l.events?.name ?? "").toLowerCase();
      return title.includes(q) || (l.events?.venue ?? "").toLowerCase().includes(q);
    });
  }, [listings, query]);

  return (
    <div className="container py-14">
      <div className="mb-8 flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="eyebrow mb-2">Browse tickets</p>
          <h1 className="font-display text-5xl tracking-display">MARKETPLACE</h1>

          {/* The count carries the SCOPE, rather than a separate line of
              instructions telling people a city picker exists.
              "4 tickets in Mumbai" answers "am I seeing everything?" in the
              sentence they were already going to read, and microcopy that
              explains the UI usually means the UI is not explaining itself. */}
          <p className="mt-1.5 text-sm text-muted-foreground">
            {loading ? (
              "Loading tickets…"
            ) : (
              <>
                {filtered.length} ticket{filtered.length === 1 ? "" : "s"}{" "}
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
                    across{" "}
                    <span className="text-foreground">every city</span>. Pick one
                    above to narrow it down.
                  </>
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
            aria-label="Search listings"
          />
        </div>
      </div>

      {loading ? (
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-44" />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={TicketX}
          title={query ? "Nothing matches that" : "No tickets here yet"}
          description={
            query
              ? "Try a different artist or venue."
              : selected
                ? `No one is selling in ${selected.name} right now. Other cities may have tickets.`
                : "There are no active listings at the moment. Check back soon."
          }
          actionLabel={selected ? "Browse all cities" : "Back to home"}
          actionHref={selected ? "/marketplace" : "/"}
        />
      ) : (
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((l) => {
            const eventId = l.event_id ?? l.events?.id;
            const title = l.events?.title ?? l.events?.name ?? "Untitled event";
            const saving =
              l.original_price > l.price
                ? Math.round((1 - l.price / l.original_price) * 100)
                : 0;

            return (
              <Link
                key={l.id}
                href={eventId ? `/events/${eventId}` : "/marketplace"}
                className="group flex flex-col rounded-lg border border-border bg-card p-5 transition-colors hover:border-zinc-700"
              >
                <div className="flex items-start justify-between gap-3">
                  <h3 className="font-display text-xl leading-tight tracking-display line-clamp-2">
                    {title}
                  </h3>
                  {saving > 0 && <Badge variant="success">{saving}% off</Badge>}
                </div>

                <div className="mt-2.5 space-y-1 text-xs text-muted-foreground">
                  {l.events?.date && (
                    <p className="flex items-center gap-1.5">
                      <Calendar className="size-3 shrink-0" />
                      <span className="tnum">{relativeTo(l.events.date)}</span>
                    </p>
                  )}
                  <p className="flex items-center gap-1.5">
                    <MapPin className="size-3 shrink-0" />
                    <span className="truncate">
                      {l.events?.venue}
                      {l.cities?.name ? ` · ${l.cities.name}` : ""}
                    </span>
                  </p>
                </div>

                <div className="perforation my-4" />

                <div className="mt-auto flex items-end justify-between">
                  <div>
                    {saving > 0 && (
                      <p className="tnum font-mono text-xs text-muted-foreground line-through">
                        {inr(l.original_price)}
                      </p>
                    )}
                    <p className="tnum font-mono text-xl text-primary">{inr(l.price)}</p>
                  </div>
                  <Button
                    variant="secondary"
                    size="sm"
                    tabIndex={-1}
                    className="pointer-events-none"
                  >
                    View
                  </Button>
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
