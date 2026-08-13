import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** ₹ with Indian digit grouping. Prices are rupees, not paise. */
export function inr(amount: number | string, opts?: { decimals?: boolean }) {
  const n = typeof amount === "string" ? parseFloat(amount) : amount;
  if (!isFinite(n)) return "—";
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    minimumFractionDigits: opts?.decimals ? 2 : 0,
    maximumFractionDigits: opts?.decimals ? 2 : 0,
  }).format(n);
}

export function formatEventDate(iso: string) {
  const d = new Date(iso);
  return {
    day: d.toLocaleDateString("en-IN", { day: "2-digit" }),
    month: d.toLocaleDateString("en-IN", { month: "short" }).toUpperCase(),
    weekday: d.toLocaleDateString("en-IN", { weekday: "short" }).toUpperCase(),
    full: d.toLocaleDateString("en-IN", {
      weekday: "short",
      day: "numeric",
      month: "long",
      year: "numeric",
    }),
    time: d.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" }),
  };
}

/** "in 4 days" / "in 3 hours" / "today" — for event proximity and SLA clocks. */
export function relativeTo(iso: string) {
  const diff = new Date(iso).getTime() - Date.now();
  const abs = Math.abs(diff);
  const mins = Math.round(abs / 60000);
  const hours = Math.round(abs / 3600000);
  const days = Math.round(abs / 86400000);

  let value: string;
  if (mins < 60) value = `${mins} min`;
  else if (hours < 24) value = `${hours} hour${hours === 1 ? "" : "s"}`;
  else value = `${days} day${days === 1 ? "" : "s"}`;

  return diff < 0 ? `${value} ago` : `in ${value}`;
}
