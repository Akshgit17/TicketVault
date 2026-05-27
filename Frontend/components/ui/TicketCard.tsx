import clsx from "clsx";
import { MapPin } from "lucide-react";

interface TicketCardProps {
  ticket: {
    id: string;
    price: number;
    original_price: number;
    events: { name: string; date: string; venue: string };
    cities: { name: string };
    status: string;
  };
  onBuy?: (id: string) => void;
}

export function TicketCard({ ticket, onBuy }: TicketCardProps) {
  const discount = Math.round((1 - ticket.price / ticket.original_price) * 100);
  const date = new Date(ticket.events.date).toLocaleDateString("en-IN", {
    day: "numeric", month: "short", year: "numeric",
  });

  return (
    <div className="group relative rounded-xl border border-zinc-800 bg-zinc-900 p-4 hover:border-zinc-600 transition-all duration-200 flex flex-col gap-3">
      {discount > 0 && (
        <span className="absolute top-3 right-3 bg-amber-500 text-zinc-950 text-xs font-mono font-medium px-2 py-0.5 rounded-full">
          -{discount}%
        </span>
      )}

      <div>
        <h3 className="font-display tracking-wide text-lg text-zinc-100 leading-tight pr-12">
          {ticket.events.name}
        </h3>
        <p className="text-zinc-500 text-xs mt-1">{date}</p>
      </div>

      <div className="flex items-center gap-1 text-zinc-500 text-xs">
        <MapPin className="w-3 h-3" />
        <span>{ticket.events.venue} · {ticket.cities.name}</span>
      </div>

      <div className="flex items-end justify-between mt-auto pt-2 border-t border-zinc-800">
        <div>
          <p className="text-zinc-500 text-xs line-through font-mono">
            ₹{ticket.original_price.toLocaleString()}
          </p>
          <p className="text-amber-400 text-lg font-mono font-medium">
            ₹{ticket.price.toLocaleString()}
          </p>
        </div>
        {onBuy && (
          <button
            onClick={() => onBuy(ticket.id)}
            className="px-4 py-1.5 rounded-lg bg-zinc-100 text-zinc-950 text-sm font-medium hover:bg-amber-400 transition-colors"
          >
            Buy
          </button>
        )}
      </div>
    </div>
  );
}
