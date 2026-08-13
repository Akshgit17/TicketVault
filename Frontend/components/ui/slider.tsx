"use client";

import * as React from "react";
import * as SliderPrimitive from "@radix-ui/react-slider";
import { cn } from "@/lib/utils";

/**
 * Supports an optional shaded "recommended band" behind the track — used by
 * the pricing slider to show the model's P25–P75 range. `band` is expressed
 * as percentages of the track width.
 */
const Slider = React.forwardRef<
  React.ElementRef<typeof SliderPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof SliderPrimitive.Root> & {
    band?: { from: number; to: number };
  }
>(({ className, band, ...props }, ref) => (
  <SliderPrimitive.Root
    ref={ref}
    className={cn("relative flex w-full touch-none select-none items-center py-2", className)}
    {...props}
  >
    <SliderPrimitive.Track className="relative h-1.5 w-full grow overflow-hidden rounded-full bg-secondary">
      {band && (
        <span
          aria-hidden
          className="absolute inset-y-0 bg-success/35"
          style={{
            left: `${Math.max(0, Math.min(100, band.from))}%`,
            width: `${Math.max(0, Math.min(100, band.to - band.from))}%`,
          }}
        />
      )}
      <SliderPrimitive.Range className="absolute h-full bg-primary" />
    </SliderPrimitive.Track>
    <SliderPrimitive.Thumb
      className={cn(
        "block size-5 rounded-full border-2 border-primary bg-background shadow transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
        "disabled:pointer-events-none disabled:opacity-50"
      )}
    />
  </SliderPrimitive.Root>
));
Slider.displayName = SliderPrimitive.Root.displayName;

export { Slider };
