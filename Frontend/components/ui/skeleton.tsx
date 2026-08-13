import { cn } from "@/lib/utils";

/**
 * Shimmer rather than a pulsing block — a pulse reads as "broken", a sweep
 * reads as "loading". Used wherever a real layout is about to replace it, so
 * the page does not jump.
 */
function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("relative overflow-hidden rounded-md bg-secondary/60", className)}
      {...props}
    >
      <div className="absolute inset-0 -translate-x-full animate-shimmer bg-gradient-to-r from-transparent via-white/[0.06] to-transparent" />
    </div>
  );
}

export { Skeleton };
