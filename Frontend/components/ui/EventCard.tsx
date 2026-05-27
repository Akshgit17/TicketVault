import Link from "next/link";
import { Calendar, MapPin } from "lucide-react";

interface EventCardProps {
  event: {
    id: string;
    name?: string;
    title?: string;
    venue: string;
    date: string;
    image_url?: string;
    cities: { name: string };
  };
}

export function EventCard({ event }: EventCardProps) {
  const eventLabel = event.title ?? event.name ?? "Untitled Event";
  const date = new Date(event.date).toLocaleDateString("en-IN", {
    weekday: "short", day: "numeric", month: "short",
  });

  return (
    <Link href={`/events/${event.id}`} className="group block">
      <div className="relative rounded-xl overflow-hidden aspect-[4/3] bg-zinc-800">
        {event.image_url ? (
          <img
            src={event.image_url}
            alt={eventLabel}
            className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500 opacity-70"
          />
        ) : (
          <div className="w-full h-full bg-gradient-to-br from-zinc-800 to-zinc-900" />
        )}
        <div className="absolute inset-0 bg-gradient-to-t from-zinc-950 via-zinc-950/40 to-transparent" />

        <div className="absolute bottom-0 left-0 right-0 p-4">
          <h3 className="font-display tracking-wide text-xl text-zinc-100 leading-tight">
            {eventLabel}
          </h3>
          <div className="flex items-center gap-3 mt-1.5 text-xs text-zinc-400">
            <span className="flex items-center gap-1">
              <Calendar className="w-3 h-3" />{date}
            </span>
            <span className="flex items-center gap-1">
              <MapPin className="w-3 h-3" />{event.venue}
            </span>
          </div>
        </div>
      </div>
    </Link>
  );
}
