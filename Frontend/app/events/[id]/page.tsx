"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useRouter } from "next/navigation";
import { Calendar, MapPin, Tag } from "lucide-react";
import { BuyTicketModal } from "@/components/ui/BuyTicketModal";

export default function EventPage({ params }: { params: { id: string } }) {
  const router = useRouter();
  const [event, setEvent]       = useState<any>(null);
  const [listings, setListings] = useState<any[]>([]);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState("");
  const [selectedListing, setSelectedListing] = useState<any>(null);

  useEffect(() => {
    (async () => {
      setLoading(true);
      setError("");
      try {
        // Both endpoints are public — no auth needed
        const [evRes, listRes] = await Promise.all([
          api.get(`/events/${params.id}`),
          api.get("/listings", { params: { event_id: params.id } }),
        ]);
        setEvent(evRes.data);
        setListings(listRes.data);
      } catch (e: any) {
        setError(e.message ?? "Failed to load event.");
      } finally {
        setLoading(false);
      }
    })();
  }, [params.id]);

  if (loading) return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <div className="w-8 h-8 border-2 border-amber-400 border-t-transparent rounded-full animate-spin" />
    </div>
  );

  if (error) return (
    <div className="flex items-center justify-center min-h-[60vh] text-red-400">
      <p>{error}</p>
    </div>
  );

  if (!event) return null;
  const eventLabel = event.title ?? event.name ?? "Untitled Event";

  const date = new Date(event.date).toLocaleDateString("en-IN", {
    weekday: "long", day: "numeric", month: "long", year: "numeric",
  });
  const time = new Date(event.date).toLocaleTimeString("en-IN", {
    hour: "2-digit", minute: "2-digit",
  });

  return (
    <div>
      {/* Hero */}
      <div className="relative h-72 md:h-96 overflow-hidden">
        {event.image_url
          ? <img src={event.image_url} alt={eventLabel} className="w-full h-full object-cover opacity-40" />
          : <div className="w-full h-full bg-zinc-900" />
        }
        <div className="absolute inset-0 bg-gradient-to-t from-zinc-950 to-transparent" />
        <div className="absolute bottom-0 left-0 w-full max-w-7xl mx-auto px-4 pb-8">
          <h1 className="font-display text-5xl md:text-7xl tracking-wide text-zinc-100">
            {eventLabel}
          </h1>
          <div className="flex flex-wrap gap-4 mt-3 text-zinc-400 text-sm">
            <span className="flex items-center gap-1"><Calendar className="w-4 h-4" />{date} · {time}</span>
            <span className="flex items-center gap-1"><MapPin className="w-4 h-4" />{event.venue}</span>
            {event.cities?.name && <span className="flex items-center gap-1"><Tag className="w-4 h-4" />{event.cities.name}</span>}
          </div>
        </div>
      </div>

      {/* Listings */}
      <div className="max-w-7xl mx-auto px-4 py-12">
        <h2 className="font-display text-3xl tracking-wide text-zinc-100 mb-6">
          AVAILABLE TICKETS
        </h2>

        {listings.length === 0 ? (
          <div className="text-center py-16 border border-zinc-800 rounded-xl">
            <p className="text-zinc-600 font-display text-2xl tracking-wide">NO TICKETS LISTED</p>
            <p className="text-zinc-600 text-sm mt-2">Be the first to sell a ticket for this event.</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {listings.map((listing) => {
              const discount = listing.original_price > listing.price
                ? Math.round((1 - listing.price / listing.original_price) * 100)
                : 0;
              return (
                <div key={listing.id} className="relative rounded-xl border border-zinc-800 bg-zinc-900 p-4 flex flex-col gap-3">
                  {discount > 0 && (
                    <span className="absolute top-3 right-3 bg-amber-500 text-zinc-950 text-xs font-mono px-2 py-0.5 rounded-full">
                      -{discount}%
                    </span>
                  )}
                  <div>
                    <p className="text-zinc-400 text-xs">Qty: {listing.quantity} ticket{listing.quantity > 1 ? "s" : ""}</p>
                  </div>
                  <div className="flex items-end justify-between mt-auto pt-2 border-t border-zinc-800">
                    <div>
                      <p className="text-zinc-500 text-xs line-through font-mono">₹{listing.original_price?.toLocaleString()}</p>
                      <p className="text-amber-400 text-lg font-mono font-medium">₹{listing.price?.toLocaleString()}</p>
                      <p className="text-zinc-600 text-xs">per ticket</p>
                    </div>
                    <button
                      onClick={() => setSelectedListing(listing)}
                      className="px-4 py-1.5 rounded-lg bg-zinc-100 text-zinc-950 text-sm font-medium hover:bg-amber-400 transition-colors"
                    >
                      Buy
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Buy Modal */}
      {selectedListing && (
        <BuyTicketModal
          listing={selectedListing}
          event={event}
          onClose={() => setSelectedListing(null)}
        />
      )}
    </div>
  );
}
