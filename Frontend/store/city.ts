import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * Cities come from GET /cities, never from a hardcoded list.
 *
 * This file previously held its own array of 15 city names, which drifted from
 * the `cities` table — it listed "Bangalore" while every seeded event pointed
 * at "Bengaluru", so selecting it returned an empty marketplace. Only the
 * user's *selection* is client state; the catalogue is server state.
 */

export interface City {
  id: string;
  name: string;
  slug: string;
}

interface CityStore {
  /** null means "all cities" — a valid, and the default, browsing mode. */
  selected: City | null;
  setCity: (city: City | null) => void;
}

export const useCityStore = create<CityStore>()(
  persist(
    (set) => ({
      selected: null,
      setCity: (city) => set({ selected: city }),
    }),
    {
      name: "ticketvault-city",
      version: 2,
      // v1 stored a bare city *name* string under `selectedCity`. There is no
      // id to recover from that, so drop it and fall back to "all cities"
      // rather than persisting a selection that cannot be resolved.
      migrate: () => ({ selected: null }),
    }
  )
);
