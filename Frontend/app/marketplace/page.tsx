"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useCityStore } from "@/store/city";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { MapPin, Calendar } from "lucide-react";

export default function MarketplacePage() {
  const { selectedCity } = useCityStore();
  const router = useRouter();
  const [listings, setListings] = useState<any[]>([]);
  const [cities, setCities]     = useState<any[]>([]);
  const [filterCity, setFilterCity] = useState("");
  const [loading, setLoading]   = useState(true);

  // Load cities for filter dropdown
  useEffect(() => {
    api.get("/cities").then(({ data }) => setCities(data));
  }, []);

  // Set filter from global city selector
  useEffect(() => {
    if (!selectedCity || cities.length === 0) return;
    const found = cities.find((c: any) => c.name === selectedCity);
    if (found) setFilterCity(found.id);
  }, [selectedCity, cities]);

  // Load listings
  useEffect(() => {
    setLoading(true);
    const params: Record<string, string> = {};
    if (filterCity) params.city_id = filterCity;
    api.get("/listings", { params })
      .then(({ data }) => setListings(data))
      .finally(() => setLoading(false));
  }, [filterCity]);

  return (
    <div className="max-w-7xl mx-auto px-4 py-12">
      <div className="flex flex-col sm:flex-row sm:items-end justify-between mb-8 gap-4">
        <div>
          <h1 className="font-display text-5xl tracking-wide text-zinc-100">MARKETPLACE</h1>
          <p className="text-zinc-500 mt-1 text-sm">{listings.length} listing{listings.length !== 1 ? "s" : ""} available</p>
        </div>
        <select
          value={filterCity}
          onChange={e => setFilterCity(e.target.value)}
          className="px-4 py-2 rounded-lg bg-zinc-800 border border-zinc-700 text-zinc-300 text-sm focus:outline-none focus:border-zinc-500"
        >
          <option value="">All cities</option>
          {cities.map((c: any) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </div>

      {loading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array(6).fill(0).map((_, i) => <div key={i} className="h-48 rounded-xl bg-zinc-800 animate-pulse" />)}
        </div>
      ) : listings.length === 0 ? (
        <div className="text-center py-24 text-zinc-600 border border-zinc-800 rounded-xl">
          <p className="font-display text-3xl tracking-wide">NO TICKETS FOUND</p>
          <p className="text-sm mt-2">Try a different city or check back later.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {listings.map((l) => {
            const eventId = l.event_id ?? l.events?.id;
            const discount = l.original_price > l.price
              ? Math.round((1 - l.price / l.original_price) * 100) : 0;
            const date = l.events?.date
              ? new Date(l.events.date).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })
              : "";
            return (
              <Link
                key={l.id}
                href={eventId ? `/events/${eventId}` : "/marketplace"}
                className="block group"
              >
                <div className="relative rounded-xl border border-zinc-800 bg-zinc-900 p-4 hover:border-zinc-600 transition-all duration-200 flex flex-col gap-3">
                  {discount > 0 && (
                    <span className="absolute top-3 right-3 bg-amber-500 text-zinc-950 text-xs font-mono px-2 py-0.5 rounded-full">
                      -{discount}%
                    </span>
                  )}
                  <div>
                    <h3 className="font-display tracking-wide text-lg text-zinc-100 leading-tight pr-12">
                      {l.events?.title ?? l.events?.name ?? "Untitled Event"}
                    </h3>
                    <p className="text-zinc-500 text-xs mt-1 flex items-center gap-1">
                      <Calendar className="w-3 h-3" />{date}
                    </p>
                  </div>
                  <p className="text-zinc-500 text-xs flex items-center gap-1">
                    <MapPin className="w-3 h-3" />
                    {l.events?.venue} · {l.cities?.name}
                  </p>
                  <div className="flex items-end justify-between mt-auto pt-2 border-t border-zinc-800">
                    <div>
                      <p className="text-zinc-500 text-xs line-through font-mono">₹{l.original_price?.toLocaleString()}</p>
                      <p className="text-amber-400 text-lg font-mono font-medium">₹{l.price?.toLocaleString()}</p>
                      <p className="text-zinc-600 text-xs">Qty: {l.quantity}</p>
                    </div>
                    <span className="px-3 py-1.5 rounded-lg bg-zinc-800 text-zinc-300 text-xs group-hover:bg-zinc-700 transition-colors">
                      View →
                    </span>
                  </div>
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
