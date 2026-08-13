"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { SignInButton, SignedIn, SignedOut, UserButton } from "@clerk/nextjs";
import { Menu, ShieldCheck, Ticket } from "lucide-react";

import { CitySelector } from "@/components/ui/CitySelector";
import { Button } from "@/components/ui/button";
import { useMe } from "@/lib/hooks/use-me";
import { cn } from "@/lib/utils";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

const LINKS = [
  // Two different things, deliberately named as such. "Concerts" is the
  // catalogue of shows; "Tickets" is what is actually for sale right now. A
  // single "Browse" hid that distinction and made an empty marketplace look
  // like an empty site.
  { href: "/events",      label: "Concerts" },
  { href: "/marketplace", label: "Tickets" },
  { href: "/sell",        label: "Sell" },
];

/**
 * The only routes where choosing a city changes anything.
 *
 * It used to sit in the navbar on every page, including the homepage, where it
 * did nothing at all: the homepage is a server component that fetches events
 * at render time, and the selection lives in client state it cannot see. A
 * control that silently does nothing is worse than no control, because it
 * teaches people it is broken and they stop trusting the ones that do work.
 *
 * Event pages are excluded too. Once you are looking at a specific concert,
 * changing city has no meaning.
 */
const CITY_AWARE_ROUTES = ["/events", "/marketplace", "/sell"];

export function Navbar() {
  const pathname = usePathname();
  const { me } = useMe();

  const isActive = (href: string) =>
    pathname === href || pathname.startsWith(`${href}/`);

  // Exact match, not prefix. /events is a city-filtered catalogue, but
  // /events/[id] is one specific concert, where changing city would be the
  // same silent no-op this was removed from the homepage for.
  const showCitySelector = CITY_AWARE_ROUTES.includes(pathname);

  return (
    <header className="sticky top-0 z-50 border-b border-border bg-background/80 backdrop-blur-xl">
      <div className="container flex h-16 items-center gap-4">
        <Link href="/" className="flex shrink-0 items-center gap-2">
          <Ticket className="size-5 text-primary" strokeWidth={1.5} />
          <span className="font-display text-xl tracking-[0.18em]">TICKETVAULT</span>
        </Link>

        <nav className="ml-4 hidden items-center gap-1 md:flex">
          {LINKS.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className={cn(
                "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                isActive(l.href)
                  ? "text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              {l.label}
            </Link>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-2">
          {showCitySelector && (
            <div className="hidden sm:block">
              <CitySelector />
            </div>
          )}

          <SignedOut>
            <SignInButton mode="modal">
              <Button size="sm">Sign in</Button>
            </SignInButton>
          </SignedOut>

          <SignedIn>
            <Button asChild variant="ghost" size="sm" className="hidden md:inline-flex">
              <Link href="/dashboard">Dashboard</Link>
            </Button>

            {/* Convenience only — every /admin route re-checks the flag server-side. */}
            {me?.is_admin && (
              <Button asChild variant="ghost" size="sm" className="hidden md:inline-flex gap-1.5">
                <Link href="/admin">
                  <ShieldCheck className="size-4 text-primary" />
                  Admin
                </Link>
              </Button>
            )}

            <UserButton
              afterSignOutUrl="/"
              appearance={{ elements: { avatarBox: "size-8" } }}
            />
          </SignedIn>

          {/* Mobile menu */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" className="md:hidden" aria-label="Menu">
                <Menu />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {LINKS.map((l) => (
                <DropdownMenuItem key={l.href} asChild>
                  <Link href={l.href}>{l.label}</Link>
                </DropdownMenuItem>
              ))}
              <SignedIn>
                <DropdownMenuItem asChild>
                  <Link href="/dashboard">Dashboard</Link>
                </DropdownMenuItem>
                {me?.is_admin && (
                  <DropdownMenuItem asChild>
                    <Link href="/admin">Admin</Link>
                  </DropdownMenuItem>
                )}
              </SignedIn>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {showCitySelector && (
        <div className="container pb-3 sm:hidden">
          <CitySelector className="h-9 w-full border-transparent bg-secondary/50 text-sm" />
        </div>
      )}
    </header>
  );
}
