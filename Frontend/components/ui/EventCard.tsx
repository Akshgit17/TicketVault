import Link from "next/link";
import { MapPin } from "lucide-react";
import { cn, formatEventDate, inr, relativeTo } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";

export interface EventSummary {
  id: string;
  title?: string;
  name?: string;
  venue: string;
  date: string;
  image_url?: string | null;
  cities?: { name: string } | null;
  /** Present when the caller has joined listing data. */
  listing_count?: number;
  from_price?: number | null;
}

/**
 * The date block is a torn ticket stub rather than a line of text — it is the
 * single most scanned piece of information on a listings grid, and giving it
 * its own shape means the eye finds it without reading.
 */
export function EventCard({
  event,
  className,
  priority,
}: {
  event: EventSummary;
  className?: string;
  priority?: boolean;
}) {
  const label = event.title ?? event.name ?? "Untitled event";
  const d = formatEventDate(event.date);
  const soon = new Date(event.date).getTime() - Date.now() < 7 * 86400000;

  return (
    <Link
      href={`/events/${event.id}`}
      className={cn(
        "group relative block overflow-hidden rounded-lg border border-border bg-card",
        "transition-colors hover:border-zinc-700",
        className
      )}
    >
      <div className="relative aspect-[16/10] overflow-hidden bg-secondary">
        {event.image_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={event.image_url}
            alt=""
            loading={priority ? "eager" : "lazy"}
            className="size-full object-cover opacity-75 transition-[transform,opacity] duration-500 group-hover:scale-[1.04] group-hover:opacity-90"
          />
        ) : (
          <div className="size-full bg-gradient-to-br from-zinc-800 to-zinc-900" />
        )}
        <div className="absolute inset-0 bg-gradient-to-t from-card via-card/50 to-transparent" />

        {/* Date stub */}
        <div className="absolute left-4 top-4 rounded-md border border-border bg-background/90 px-2.5 py-1.5 text-center backdrop-blur-sm">
          <p className="font-mono text-[10px] leading-none tracking-[0.14em] text-primary">
            {d.month}
          </p>
          <p className="tnum font-display text-2xl leading-none">{d.day}</p>
        </div>

        {soon && (
          <Badge className="absolute right-4 top-4 bg-background/90 backdrop-blur-sm">
            {relativeTo(event.date)}
          </Badge>
        )}
      </div>

      <div className="p-4">
        <h3 className="font-display text-xl leading-tight tracking-display line-clamp-2">
          {label}
        </h3>
        <p className="mt-1.5 flex items-center gap-1.5 text-xs text-muted-foreground">
          <MapPin className="size-3 shrink-0" />
          <span className="truncate">
            {event.venue}
            {event.cities?.name ? ` · ${event.cities.name}` : ""}
          </span>
        </p>

        {typeof event.listing_count === "number" && (
          <>
            <div className="perforation my-3.5" />
            <div className="flex items-baseline justify-between">
              <span className="text-xs text-muted-foreground">
                {event.listing_count === 0
                  ? "No tickets yet"
                  : `${event.listing_count} ticket${event.listing_count === 1 ? "" : "s"}`}
              </span>
              {event.from_price != null && (
                <span className="tnum font-mono text-sm text-foreground">
                  from {inr(event.from_price)}
                </span>
              )}
            </div>
          </>
        )}
      </div>
    </Link>
  );
}
