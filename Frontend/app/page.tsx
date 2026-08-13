import Link from "next/link";
import { ArrowRight, BadgeIndianRupee, CalendarX2, Lock, Repeat } from "lucide-react";

import { EventCard, type EventSummary } from "@/components/ui/EventCard";
import { EventCarousel } from "@/components/ui/EventCarousel";
import { EmptyState } from "@/components/ui/empty-state";
import { Button } from "@/components/ui/button";

export const revalidate = 0;

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/**
 * Events come from the API, not from a direct Supabase call.
 *
 * The homepage used to query Supabase with the anon key, which meant two
 * different data paths to the same table — the API's filters (past events,
 * search, pagination) applied on every page except this one.
 */
async function getEvents(): Promise<EventSummary[]> {
  try {
    const res = await fetch(`${API}/events?limit=12&with_availability=true`, {
      cache: "no-store",
    });
    if (!res.ok) return [];
    return await res.json();
  } catch {
    // Backend down: render the page without the catalogue rather than a 500.
    return [];
  }
}

const HOW_IT_WORKS = [
  {
    icon: Lock,
    title: "Your money waits",
    body: "Payment is held in escrow the moment you buy. The seller does not see a rupee of it until the ticket is in your account.",
  },
  {
    icon: BadgeIndianRupee,
    title: "The seller has skin in the game",
    body: "Every seller pays a refundable deposit before their listing goes live. Deliver, and they get it back. Don't, and it pays your refund plus compensation.",
  },
  {
    icon: Repeat,
    title: "The ticket actually moves",
    body: "Tickets are transferred inside the official ticketing app, so the seller permanently loses their copy. A screenshot can be sold twice. A transfer cannot.",
  },
];

export default async function HomePage() {
  const events = await getEvents();
  const featured = events.slice(0, 6);
  const upcoming = events.slice(0, 8);

  return (
    <div>
      {featured.length > 0 ? (
        <EventCarousel events={featured} />
      ) : (
        <section className="border-b border-border">
          <div className="container flex min-h-[52vh] flex-col justify-center py-20">
            <p className="eyebrow mb-4">Concert resale, done properly</p>
            <h1 className="max-w-3xl font-display text-6xl leading-[0.92] tracking-display sm:text-7xl md:text-8xl">
              TICKETS THAT<br />ACTUALLY ARRIVE
            </h1>
            <p className="mt-6 max-w-md text-muted-foreground">
              Escrowed payments, deposit-backed sellers, and real in-app ticket
              transfers.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Button asChild size="lg">
                <Link href="/marketplace">Browse tickets <ArrowRight /></Link>
              </Button>
              <Button asChild size="lg" variant="outline">
                <Link href="/sell">Sell a ticket</Link>
              </Button>
            </div>
          </div>
        </section>
      )}

      {/* Upcoming */}
      <section className="container py-20">
        <div className="mb-8 flex items-end justify-between gap-4">
          <div>
            <p className="eyebrow mb-2">On sale now</p>
            <h2 className="font-display text-4xl tracking-display">UPCOMING SHOWS</h2>
          </div>
          {/* /events, not /marketplace. This section lists CONCERTS, so "view
              all" must lead to all concerts. Pointing it at the marketplace
              sent people to a list of tickets for sale, which is frequently
              emptier than the section they clicked from. */}
          <Button asChild variant="ghost" size="sm">
            <Link href="/events">
              View all <ArrowRight />
            </Link>
          </Button>
        </div>

        {upcoming.length === 0 ? (
          <EmptyState
            icon={CalendarX2}
            title="No upcoming events"
            description="The catalogue is empty, or the API isn't reachable. Run the seed SQL to populate events."
            actionLabel="Go to marketplace"
            actionHref="/marketplace"
          />
        ) : (
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
            {upcoming.map((e, i) => (
              <EventCard key={e.id} event={e} priority={i < 4} />
            ))}
          </div>
        )}
      </section>

      {/* How it works — replaces the old trust strip, which advertised QR
          fingerprinting, a 10-minute lock and a 2-hour confirmation window.
          None of those describe how the platform works any more. */}
      <section id="how-it-works" className="border-y border-border bg-card/40">
        <div className="container py-20">
          <p className="eyebrow mb-2">How it works</p>
          <h2 className="max-w-2xl font-display text-4xl leading-tight tracking-display">
            THE PART EVERY OTHER RESALE GROUP GETS WRONG
          </h2>

          <div className="mt-12 grid gap-px overflow-hidden rounded-lg border border-border bg-border md:grid-cols-3">
            {HOW_IT_WORKS.map(({ icon: Icon, title, body }, i) => (
              <div key={title} className="bg-background p-7">
                <div className="mb-5 flex items-center justify-between">
                  <div className="flex size-9 items-center justify-center rounded-md border border-border bg-secondary/40">
                    <Icon className="size-4 text-primary" />
                  </div>
                  <span className="tnum font-mono text-xs text-border">
                    0{i + 1}
                  </span>
                </div>
                <h3 className="font-display text-2xl tracking-display">{title}</h3>
                <p className="mt-2.5 text-sm leading-relaxed text-muted-foreground">
                  {body}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Seller CTA */}
      <section className="container py-24">
        <div className="ticket-notch relative overflow-hidden rounded-lg border border-border bg-card px-8 py-14 text-center">
          <p className="eyebrow mb-3">Got a ticket you can&apos;t use?</p>
          <h2 className="mx-auto max-w-2xl font-display text-4xl leading-tight tracking-display sm:text-5xl">
            LIST IT IN UNDER TWO MINUTES
          </h2>
          <p className="mx-auto mt-4 max-w-md text-sm text-muted-foreground">
            We&apos;ll suggest a price based on what tickets for that show
            actually sell for, and cap it so buyers know they&apos;re never
            being gouged.
          </p>
          <Button asChild size="lg" className="mt-8">
            <Link href="/sell">Start selling <ArrowRight /></Link>
          </Button>
        </div>
      </section>
    </div>
  );
}
