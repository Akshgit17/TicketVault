"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Info, Sparkles, TrendingDown, TrendingUp } from "lucide-react";

import { api } from "@/lib/api";
import { cn, inr } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Slider } from "@/components/ui/slider";
import { Skeleton } from "@/components/ui/skeleton";

export interface Suggestion {
  p25_paise: number;
  p50_paise: number;
  p75_paise: number;
  cap_paise: number;
  sell_probability: number | null;
  source: "model" | "median" | "rules" | "face_value";
  model_version: string | null;
}

const paise = (rupees: number) => Math.round(rupees * 100);
const rupees = (p: number) => Math.round(p / 100);

/**
 * The pricing slider.
 *
 * Two layers, and the difference is visible in the interaction itself:
 *
 *   the CAP is a rule    — the slider physically stops there
 *   the BAND is a model  — shaded, advisory, and steppable straight through
 *
 * The seller is never overruled by software inside the legal range, which is
 * what makes them accept the guidance rather than resent it. The model
 * persuades; the rule prevents.
 *
 * Ordering matters too: the band renders and the field is pre-filled at P50
 * *before* the seller types a number. Anchor first and most people accept the
 * anchor; show an empty box and they anchor on hope.
 */
export function PriceGuidance({
  faceValue,
  eventId,
  price,
  onPriceChange,
}: {
  faceValue: number;
  eventId?: string;
  price: number | null;
  onPriceChange: (price: number, suggestion: Suggestion | null) => void;
}) {
  const [suggestion, setSuggestion] = useState<Suggestion | null>(null);
  const [loading, setLoading] = useState(false);
  const [liveProbability, setLiveProbability] = useState<number | null>(null);
  const prefilled = useRef(false);

  // Fetch the band once per (face value, event). The probability updates
  // separately as the slider moves.
  useEffect(() => {
    if (!faceValue || faceValue <= 0) {
      setSuggestion(null);
      prefilled.current = false;
      return;
    }

    let cancelled = false;
    setLoading(true);

    api
      .get("/pricing/suggest", { params: { face_value: faceValue, event_id: eventId } })
      .then(({ data }) => {
        if (cancelled) return;
        setSuggestion(data);
        setLiveProbability(data.sell_probability);
        // Pre-fill at the median, once, and never fight the seller afterwards.
        if (!prefilled.current) {
          prefilled.current = true;
          onPriceChange(rupees(data.p50_paise), data);
        }
      })
      .catch(() => {
        // Guidance is advisory. Losing it must not block listing a ticket.
        if (!cancelled) setSuggestion(null);
      })
      .finally(() => !cancelled && setLoading(false));

    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [faceValue, eventId]);

  // Debounced: the slider fires continuously while dragging.
  const refreshProbability = useCallback(
    (next: number) => {
      if (!faceValue) return;
      api
        .get("/pricing/suggest", {
          params: { face_value: faceValue, event_id: eventId, proposed_price: next },
        })
        .then(({ data }) => setLiveProbability(data.sell_probability))
        .catch(() => {});
    },
    [faceValue, eventId]
  );

  useEffect(() => {
    if (!price || !suggestion) return;
    const t = setTimeout(() => refreshProbability(price), 220);
    return () => clearTimeout(t);
  }, [price, suggestion, refreshProbability]);

  if (loading && !suggestion) {
    return <Skeleton className="h-44 w-full" />;
  }
  if (!suggestion) return null;

  const cap = rupees(suggestion.cap_paise);
  const p25 = rupees(suggestion.p25_paise);
  const p50 = rupees(suggestion.p50_paise);
  const p75 = rupees(suggestion.p75_paise);
  const current = price ?? p50;

  const min = Math.max(1, Math.round(faceValue * 0.3));
  const span = Math.max(1, cap - min);
  const pct = (v: number) => ((Math.min(Math.max(v, min), cap) - min) / span) * 100;

  const atCap = current >= cap;
  const above = current > p75;
  const below = current < p25;
  const inBand = !above && !below;

  return (
    <div className="rounded-lg border border-border bg-card p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Sparkles className="size-4 text-primary" />
          <p className="font-display text-xl tracking-display">SUGGESTED PRICE</p>
        </div>
        {suggestion.source !== "model" && (
          // Honest about which rung of the fallback ladder answered, rather
          // than passing off a rule of thumb as a prediction.
          <Badge variant="neutral" title={`source: ${suggestion.source}`}>
            estimate
          </Badge>
        )}
      </div>

      <div className="mt-5 flex items-end justify-between">
        <div>
          <p className="tnum font-mono text-3xl text-primary">{inr(current)}</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Most sell between{" "}
            <span className="tnum text-foreground">{inr(p25)}</span> and{" "}
            <span className="tnum text-foreground">{inr(p75)}</span>
          </p>
        </div>

        {liveProbability != null && (
          <div className="text-right">
            <p
              className={cn(
                "tnum font-mono text-2xl",
                liveProbability >= 0.66
                  ? "text-success"
                  : liveProbability >= 0.4
                    ? "text-primary"
                    : "text-destructive"
              )}
            >
              {Math.round(liveProbability * 100)}%
            </p>
            <p className="text-xs text-muted-foreground">likely to sell</p>
          </div>
        )}
      </div>

      <div className="mt-5">
        <Slider
          value={[Math.min(Math.max(current, min), cap)]}
          min={min}
          max={cap}
          step={50}
          band={{ from: pct(p25), to: pct(p75) }}
          onValueChange={([v]) => onPriceChange(v, suggestion)}
          aria-label="Asking price"
        />
        <div className="mt-2 flex justify-between font-mono text-[10px] text-muted-foreground">
          <span className="tnum">{inr(min)}</span>
          <span className="tnum">cap {inr(cap)}</span>
        </div>
      </div>

      {/* Graded escalation. The model persuades; only the cap prevents. */}
      <div className="mt-4 flex items-start gap-2 text-sm">
        {atCap ? (
          <>
            <Info className="mt-0.5 size-4 shrink-0 text-destructive" />
            <p className="text-muted-foreground">
              <span className="text-destructive">That&apos;s the ceiling.</span> We cap
              resale at {inr(cap)} for this ticket so buyers know they&apos;re never
              being gouged.
            </p>
          </>
        ) : above ? (
          <>
            <TrendingDown className="mt-0.5 size-4 shrink-0 text-primary" />
            <p className="text-muted-foreground">
              Above what most tickets for this show sell for. You can list at this
              price. It&apos;ll just take longer, and might not sell at all.
            </p>
          </>
        ) : below ? (
          <>
            <TrendingUp className="mt-0.5 size-4 shrink-0 text-success" />
            <p className="text-muted-foreground">
              You could ask more. Tickets like this typically go for around{" "}
              <span className="tnum text-foreground">{inr(p50)}</span>.
            </p>
          </>
        ) : (
          inBand && (
            <>
              <Info className="mt-0.5 size-4 shrink-0 text-success" />
              <p className="text-muted-foreground">
                Priced in line with the market for this show.
              </p>
            </>
          )
        )}
      </div>
    </div>
  );
}
