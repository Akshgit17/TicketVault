import { Ticket } from "lucide-react";
import Link from "next/link";

export function Footer() {
  return (
    <footer className="border-t border-zinc-800 mt-20 py-10 px-4">
      <div className="max-w-7xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4 text-zinc-500 text-sm">
        <div className="flex items-center gap-2">
          <Ticket className="w-4 h-4 text-amber-400" />
          <span className="font-display tracking-widest text-zinc-400">TICKETVAULT</span>
        </div>
        <div className="flex gap-6">
          <Link href="/marketplace" className="hover:text-zinc-300 transition-colors">Browse</Link>
          <Link href="/sell" className="hover:text-zinc-300 transition-colors">Sell</Link>
          <Link href="/dashboard" className="hover:text-zinc-300 transition-colors">Dashboard</Link>
        </div>
        <p>© {new Date().getFullYear()} TicketVault. All rights reserved.</p>
      </div>
    </footer>
  );
}
