"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, Clock } from "lucide-react";
import { cn } from "@/lib/utils";

function remaining(deadline: string) {
  const ms = new Date(deadline).getTime() - Date.now();
  const expired = ms <= 0;
  const abs = Math.abs(ms);

  const h = Math.floor(abs / 3600000);
  const m = Math.floor((abs % 3600000) / 60000);
  const s = Math.floor((abs % 60000) / 1000);

  return {
    expired,
    text: `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`,
    urgent: !expired && abs < 3600000,
  };
}

/**
 * Ticks once a second against a server-supplied deadline.
 *
 * Deliberately does no arithmetic beyond the display — the SLA is enforced by
 * a backend job, so this is informational and can never be the thing that
 * decides whether a deadline was met.
 */
export function CountdownTimer({
  deadline,
  label = "Time remaining",
  className,
}: {
  deadline: string | null | undefined;
  label?: string;
  className?: string;
}) {
  const [state, setState] = useState<ReturnType<typeof remaining> | null>(null);

  useEffect(() => {
    if (!deadline) return;
    // First tick happens in the effect, not in useState, so server and client
    // render the same markup and React does not report a hydration mismatch.
    setState(remaining(deadline));
    const id = setInterval(() => setState(remaining(deadline)), 1000);
    return () => clearInterval(id);
  }, [deadline]);

  if (!deadline || !state) return null;

  return (
    <div
      className={cn(
        "flex items-center gap-2 rounded-md border px-3 py-2",
        state.expired
          ? "border-destructive/40 bg-destructive/10 text-destructive"
          : state.urgent
            ? "border-primary/40 bg-primary/10 text-primary"
            : "border-border bg-secondary/40 text-muted-foreground",
        className
      )}
    >
      {state.expired ? <AlertTriangle className="size-4" /> : <Clock className="size-4" />}
      <span className="text-xs">{state.expired ? "Overdue by" : label}</span>
      <span className="tnum ml-auto font-mono text-sm font-medium">{state.text}</span>
    </div>
  );
}
