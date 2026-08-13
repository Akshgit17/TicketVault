"use client";

import { useEffect, useState } from "react";
import { MapPin } from "lucide-react";
import { api } from "@/lib/api";
import { useCityStore, type City } from "@/store/city";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";

const ALL = "__all__";

export function CitySelector({ className }: { className?: string }) {
  const { selected, setCity } = useCityStore();
  const [cities, setCities] = useState<City[]>([]);

  useEffect(() => {
    api
      .get("/cities")
      .then(({ data }) => setCities(data ?? []))
      // Falls back to "All cities", which still returns a full catalogue.
      .catch(() => setCities([]));
  }, []);

  return (
    <Select
      value={selected?.id ?? ALL}
      onValueChange={(id) =>
        setCity(id === ALL ? null : cities.find((c) => c.id === id) ?? null)
      }
    >
      <SelectTrigger
        className={
          className ??
          "h-9 w-[190px] border-transparent bg-secondary/50 text-sm hover:bg-secondary"
        }
      >
        <span className="flex items-center gap-2 truncate">
          <MapPin className="size-3.5 shrink-0 text-primary" />
          <SelectValue placeholder="All cities" />
        </span>
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ALL}>All cities</SelectItem>
        {cities.map((c) => (
          <SelectItem key={c.id} value={c.id}>
            {c.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
