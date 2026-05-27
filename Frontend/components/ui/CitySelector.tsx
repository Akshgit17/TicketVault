"use client";
import { useState, useRef, useEffect } from "react";
import { MapPin, ChevronDown } from "lucide-react";
import { useCityStore, CITIES, type City } from "@/store/city";
import clsx from "clsx";

export function CitySelector() {
  const { selectedCity, setCity } = useCityStore();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-zinc-700 bg-zinc-900 text-sm text-zinc-300 hover:border-zinc-500 transition-colors"
      >
        <MapPin className="w-3.5 h-3.5 text-amber-400" />
        <span>{selectedCity ?? "Select city"}</span>
        <ChevronDown className={clsx("w-3.5 h-3.5 transition-transform", open && "rotate-180")} />
      </button>

      {open && (
        <div className="absolute top-full mt-1 left-0 z-50 w-52 rounded-lg border border-zinc-700 bg-zinc-900 shadow-xl overflow-hidden animate-fade-up">
          <div className="grid grid-cols-2 gap-px p-1 max-h-72 overflow-y-auto">
            {CITIES.map((city) => (
              <button
                key={city}
                onClick={() => { setCity(city as City); setOpen(false); }}
                className={clsx(
                  "text-left px-3 py-2 text-sm rounded-md transition-colors",
                  selectedCity === city
                    ? "bg-amber-500 text-zinc-950 font-medium"
                    : "text-zinc-300 hover:bg-zinc-800"
                )}
              >
                {city}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
