import Link from "next/link";
import { Ticket } from "lucide-react";
import { Separator } from "@/components/ui/separator";

const COLUMNS = [
  {
    title: "Marketplace",
    links: [
      { href: "/events",      label: "All concerts" },
      { href: "/marketplace", label: "Tickets on sale" },
      { href: "/sell",        label: "Sell a ticket" },
      { href: "/dashboard",   label: "Your dashboard" },
    ],
  },
  {
    title: "How it works",
    links: [
      { href: "/#how-it-works", label: "Buyer protection" },
      { href: "/#how-it-works", label: "Seller deposit" },
      { href: "/#how-it-works", label: "Ticket transfer" },
    ],
  },
];

export function Footer() {
  return (
    <footer className="mt-24 border-t border-border">
      <div className="container py-14">
        <div className="grid gap-10 md:grid-cols-[1.5fr_1fr_1fr]">
          <div>
            <div className="flex items-center gap-2">
              <Ticket className="size-4 text-primary" />
              <span className="font-display text-lg tracking-[0.18em]">TICKETVAULT</span>
            </div>
            <p className="mt-3 max-w-xs text-sm leading-relaxed text-muted-foreground">
              Concert tickets, transferred properly. Your money is held in escrow
              until the ticket is in your account, and every seller puts down a
              refundable deposit before they can list.
            </p>
          </div>

          {COLUMNS.map((col) => (
            <div key={col.title}>
              <p className="eyebrow mb-4">{col.title}</p>
              <ul className="space-y-2.5">
                {col.links.map((l) => (
                  <li key={l.label}>
                    <Link
                      href={l.href}
                      className="text-sm text-muted-foreground transition-colors hover:text-foreground"
                    >
                      {l.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <Separator perforated className="my-8" />

        <div className="flex flex-col gap-3 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
          <p>© {new Date().getFullYear()} TicketVault</p>
          <p className="font-mono">
            A student project. Payments run in test mode, so no real money moves.
          </p>
        </div>
      </div>
    </footer>
  );
}
