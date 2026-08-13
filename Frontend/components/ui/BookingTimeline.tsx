"use client";

import { Check, Circle, X } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Makes the fulfilment state machine visible.
 *
 * There is a real state machine behind a booking, and until now the UI showed
 * none of it — a buyer saw a status string and had no idea what came next or
 * who was holding things up. Cheap to build, and it is the clearest signal
 * that this is a system rather than a set of forms.
 */

const STEPS = [
  { key: "paid",               label: "Paid",      caption: "Held in escrow" },
  { key: "awaiting_transfer",  label: "Transfer",  caption: "Seller sends ticket" },
  { key: "transfer_initiated", label: "Sent",      caption: "Awaiting your check" },
  { key: "transfer_confirmed", label: "Confirmed", caption: "Ticket received" },
  { key: "released",           label: "Released",  caption: "Seller paid" },
] as const;

const ORDER: Record<string, number> = {
  not_started: 0,
  awaiting_transfer: 1,
  transfer_initiated: 2,
  transfer_confirmed: 3,
  released: 4,
};

export function BookingTimeline({
  status,
  className,
}: {
  status: string;
  className?: string;
}) {
  const failed = status === "failed";
  const current = ORDER[status] ?? 0;

  return (
    <ol className={cn("flex w-full items-start", className)}>
      {STEPS.map((step, i) => {
        const done = !failed && i < current;
        const active = !failed && i === current;
        const last = i === STEPS.length - 1;

        return (
          <li key={step.key} className="flex min-w-0 flex-1 items-start">
            <div className="flex min-w-0 flex-1 flex-col items-center text-center">
              <div
                className={cn(
                  "flex size-7 shrink-0 items-center justify-center rounded-full border transition-colors",
                  done && "border-success bg-success text-success-foreground",
                  active && "border-primary bg-primary/15 text-primary",
                  failed && i === 1 && "border-destructive bg-destructive text-destructive-foreground",
                  !done && !active && !(failed && i === 1) && "border-border text-muted-foreground"
                )}
              >
                {done ? (
                  <Check className="size-3.5" strokeWidth={3} />
                ) : failed && i === 1 ? (
                  <X className="size-3.5" strokeWidth={3} />
                ) : (
                  <Circle className={cn("size-2", active && "fill-primary")} />
                )}
              </div>

              <p
                className={cn(
                  "mt-2 truncate text-xs font-medium",
                  active ? "text-foreground" : "text-muted-foreground"
                )}
              >
                {step.label}
              </p>
              <p className="mt-0.5 hidden text-[11px] leading-tight text-muted-foreground sm:block">
                {step.caption}
              </p>
            </div>

            {!last && (
              <div
                aria-hidden
                className={cn(
                  "mt-3.5 h-px min-w-4 flex-1",
                  i < current && !failed ? "bg-success" : "bg-border"
                )}
              />
            )}
          </li>
        );
      })}
    </ol>
  );
}
