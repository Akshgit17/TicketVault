import Link from "next/link";
import { createClient } from "@supabase/supabase-js";
import { EventCard } from "@/components/ui/EventCard";
import { ArrowRight } from "lucide-react";

// SSR: direct Supabase call for homepage performance
const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
);

export const revalidate = 0; // always fetch fresh events in dev/use-now scenarios

export default async function HomePage() {
  const { data: events, error } = await supabase
    .from("events")
    .select("*, cities(name, slug)")
    .order("date", { ascending: true })
    .order("title", { ascending: true })
    .limit(6);

  return (
    <div className="relative">
      {/* Hero */}
      <section className="relative min-h-[88vh] flex items-center justify-center overflow-hidden">
        <div
          className="absolute inset-0 bg-cover bg-center opacity-30"
          style={{ backgroundImage: "url('https://images.unsplash.com/photo-1470229722913-7c0e2dbbafd3?w=1600')" }}
        />
        <div className="absolute inset-0 bg-gradient-to-b from-zinc-950/60 via-zinc-950/40 to-zinc-950" />

        <div className="relative z-10 text-center px-4 animate-fade-up">
          <p className="text-amber-400 font-mono text-xs tracking-[0.3em] uppercase mb-4">
            QR-Verified · Anti-Fraud
          </p>
          <h1 className="font-display text-7xl md:text-9xl tracking-widest text-zinc-100 leading-none mb-6">
            TICKET<br />VAULT
          </h1>
          <p className="text-zinc-400 text-lg max-w-md mx-auto mb-10">
            Buy and sell concert tickets with confidence. Every QR verified. Every ticket guaranteed.
          </p>
          <div className="flex flex-col sm:flex-row gap-3 justify-center">
            <Link href="/marketplace" className="px-8 py-3 bg-amber-500 text-zinc-950 font-medium rounded-lg hover:bg-amber-400 transition-colors">
              Browse Tickets
            </Link>
            <Link href="/sell" className="px-8 py-3 border border-zinc-600 text-zinc-300 rounded-lg hover:border-zinc-400 hover:text-zinc-100 transition-colors">
              Sell a Ticket
            </Link>
          </div>
        </div>
      </section>

      {/* Events */}
      <section className="max-w-7xl mx-auto px-4 py-16">
        <div className="flex items-center justify-between mb-8">
          <h2 className="font-display text-4xl tracking-wide text-zinc-100">EVENTS</h2>
          <Link href="/marketplace" className="flex items-center gap-1 text-sm text-zinc-500 hover:text-zinc-300 transition-colors">
            View all <ArrowRight className="w-4 h-4" />
          </Link>
        </div>

        {error && (
          <p className="text-zinc-500 text-sm">Could not load events. Check Supabase connection.</p>
        )}

        {!error && (!events || events.length === 0) && (
          <p className="text-zinc-500 text-sm">No events found. Run the seed SQL or scraper to populate events.</p>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {(events ?? []).map((e) => <EventCard key={e.id} event={e} />)}
        </div>
      </section>

      {/* Trust strip */}
      <section className="border-y border-zinc-800 py-10">
        <div className="max-w-7xl mx-auto px-4 grid grid-cols-1 sm:grid-cols-3 gap-6 text-center">
          {[
            ["QR Fingerprinting", "Every ticket decoded & hashed. Duplicates rejected instantly."],
            ["10-Min Lock", "Tickets locked during checkout. No double-selling, ever."],
            ["2-Hr Confirmation", "Verify your ticket. Auto-confirmed if you don't dispute."],
          ].map(([title, desc]) => (
            <div key={title}>
              <p className="font-display tracking-wide text-amber-400 text-lg mb-1">{title}</p>
              <p className="text-zinc-500 text-sm">{desc}</p>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
