"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { api } from "@/lib/api";

/**
 * Business constants come from GET /config, not from the frontend.
 *
 * The deposit rate used to be hardcoded as `0.2` in sell/page.tsx while the
 * backend held its own LISTING_FEE_RATE — two sources of truth for a number
 * the user is charged. The defaults below exist only so the UI can render
 * before the request lands; they are replaced the moment it does.
 */
export interface AppConfig {
  listing_fee_rate: number;
  price_cap_multiplier: number;
  transfer_sla_hours: number;
  settlement_hold_hours: number;
  buyer_compensation_rate: number;
  /** Commission deducted from the seller on a completed sale. */
  seller_success_fee_rate: number;
  currency: string;
  /** True when seller payouts are recorded but no money actually moves. */
  simulated_payouts: boolean;
}

const DEFAULTS: AppConfig = {
  listing_fee_rate: 0.2,
  price_cap_multiplier: 1.2,
  transfer_sla_hours: 6,
  settlement_hold_hours: 6,
  buyer_compensation_rate: 0.1,
  seller_success_fee_rate: 0.02,
  currency: "INR",
  simulated_payouts: true,
};

const ConfigContext = createContext<{ config: AppConfig; loaded: boolean }>({
  config: DEFAULTS,
  loaded: false,
});

export function ConfigProvider({ children }: { children: React.ReactNode }) {
  const [config, setConfig] = useState<AppConfig>(DEFAULTS);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .get("/config")
      .then(({ data }) => {
        if (!cancelled) setConfig({ ...DEFAULTS, ...data });
      })
      .catch(() => {
        // Non-fatal: the page still renders on defaults. A pricing box that
        // silently degrades is better than one that takes the page down.
      })
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <ConfigContext.Provider value={{ config, loaded }}>
      {children}
    </ConfigContext.Provider>
  );
}

export function useConfig() {
  return useContext(ConfigContext);
}
