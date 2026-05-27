"use client";
import Link from "next/link";
import { SignInButton, SignedIn, SignedOut, UserButton } from "@clerk/nextjs";
import { CitySelector } from "@/components/ui/CitySelector";
import { Ticket } from "lucide-react";

export function Navbar() {
  return (
    <header className="sticky top-0 z-50 border-b border-zinc-800 bg-zinc-950/80 backdrop-blur-md">
      <div className="mx-auto max-w-7xl px-4 h-14 flex items-center justify-between gap-4">

        {/* Logo */}
        <Link href="/" className="flex items-center gap-2 shrink-0">
          <Ticket className="w-5 h-5 text-amber-400" strokeWidth={1.5} />
          <span className="font-display text-xl tracking-widest text-zinc-100">
            TICKETVAULT
          </span>
        </Link>

        {/* Center — city selector */}
        <div className="hidden sm:flex flex-1 justify-center">
          <CitySelector />
        </div>

        {/* Right — nav links + auth */}
        <nav className="flex items-center gap-5 text-sm font-medium text-zinc-400">
          <Link href="/marketplace" className="hover:text-zinc-100 transition-colors hidden md:block">
            Browse
          </Link>
          <Link href="/sell" className="hover:text-zinc-100 transition-colors hidden md:block">
            Sell
          </Link>

          <SignedOut>
            <SignInButton mode="modal">
              <button className="px-3 py-1.5 rounded-md bg-amber-500 text-zinc-950 text-sm font-medium hover:bg-amber-400 transition-colors">
                Sign in
              </button>
            </SignInButton>
          </SignedOut>

          <SignedIn>
            <Link href="/dashboard" className="hover:text-zinc-100 transition-colors hidden md:block">
              Dashboard
            </Link>
            <UserButton afterSignOutUrl="/" />
          </SignedIn>
        </nav>
      </div>

      {/* Mobile city selector */}
      <div className="sm:hidden px-4 pb-2">
        <CitySelector />
      </div>
    </header>
  );
}
