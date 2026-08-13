import Link from "next/link";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

/**
 * Every empty list gets one of these. A blank panel reads as a bug; a stated
 * reason plus a way out reads as a designed state. Multi-city browsing
 * (Decision 4) makes these genuinely reachable, so they are load-bearing
 * rather than polish.
 */
export function EmptyState({
  icon: Icon,
  title,
  description,
  actionLabel,
  actionHref,
  className,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
  actionLabel?: string;
  actionHref?: string;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center rounded-lg border border-dashed border-border px-6 py-16 text-center",
        className
      )}
    >
      <div className="mb-4 flex size-11 items-center justify-center rounded-full border border-border bg-secondary/40">
        <Icon className="size-5 text-muted-foreground" />
      </div>
      <p className="font-display text-2xl tracking-display">{title}</p>
      <p className="mt-1.5 max-w-sm text-sm text-muted-foreground">{description}</p>
      {actionLabel && actionHref && (
        <Button asChild variant="outline" size="sm" className="mt-5">
          <Link href={actionHref}>{actionLabel}</Link>
        </Button>
      )}
    </div>
  );
}
