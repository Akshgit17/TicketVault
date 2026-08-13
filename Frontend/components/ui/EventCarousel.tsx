"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import useEmblaCarousel from "embla-carousel-react";
import Autoplay from "embla-carousel-autoplay";
import { WheelGesturesPlugin } from "embla-carousel-wheel-gestures";
import { ArrowRight, MapPin } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn, formatEventDate, relativeTo } from "@/lib/utils";
import type { EventSummary } from "@/components/ui/EventCard";

const AUTOPLAY_MS = 3500;

/**
 * How far across a slide a gesture must travel before it commits to the next
 * one, as a fraction of slide width.
 *
 * Embla's own rule cannot express this. Internally it does:
 *
 *   goToNextThreshold = Limit(50, 225).constrain(percentOfView.measure(20))
 *   if (abs(force) < goToNextThreshold) return baseForce   // snaps to NEAREST
 *
 * `force` is derived from VELOCITY, not distance, and `goToNextThreshold` is a
 * hardcoded constant rather than an option. So a fast flick commits easily,
 * while a slow deliberate swipe generates almost no force no matter how far it
 * goes, falls through to the nearest-snap branch, and springs back unless it
 * passed the halfway mark. That asymmetry is what makes a trackpad swipe feel
 * unresponsive: trackpad gestures are usually slow and long rather than quick
 * and short.
 */
const COMMIT_FRACTION = 0.25;

/**
 * Featured events, as full-bleed editorial slides rather than a row of cards.
 *
 * Advances every 5 seconds and loops back to the first slide at the end.
 *
 * Manual control is gestural: a two finger trackpad swipe, a horizontal mouse
 * wheel, a touch swipe, or a click and drag. No arrow buttons, because a
 * full-bleed hero is large enough to grab anywhere and arrows sitting on top
 * of the artwork are just clutter.
 *
 * Autoplay RESUMES after a drag rather than stopping for good. The risk with
 * that is yanking a slide away from someone mid-read, so it pauses while the
 * pointer is over the carousel and picks up again when it leaves. On touch,
 * where there is no hover, the drag itself resets the timer, so a deliberate
 * swipe always buys a fresh five seconds.
 */
export function EventCarousel({ events }: { events: EventSummary[] }) {
  const [emblaRef, embla] = useEmblaCarousel(
    {
      loop: true,
      align: "start",
      // Snappier settle. 28 reads as a slow glide once the gesture has already
      // told you where it is going.
      duration: 20,
      // Explicit rather than relying on the default, because gestures are now
      // the only way to move the carousel by hand.
      watchDrag: true,
      dragFree: false,
      // Default is 10px. Lower means the slide starts tracking your finger
      // almost immediately instead of resisting the first few pixels.
      dragThreshold: 4,
    },
    [
      Autoplay({
        delay: AUTOPLAY_MS,
        stopOnInteraction: false,
        stopOnMouseEnter: true,
        stopOnFocusIn: true,
      }),
      // Two finger trackpad swipe, and horizontal mouse wheels.
      //
      // A trackpad swipe is a wheel event, not a drag, so embla's built in
      // pointer handling never sees it. This plugin reads the momentum stream
      // and translates it into carousel movement, which is what makes the
      // gesture feel continuous rather than stepping one slide per flick.
      //
      // The axis is deliberately NOT forced to 'x'. The plugin works out which
      // way the gesture is actually going, so a vertical two finger scroll
      // still scrolls the page instead of being swallowed by the hero. A
      // carousel that traps the scroll wheel is a well known way to make a
      // homepage impossible to get past.
      WheelGesturesPlugin(),
    ]
  );

  const [selected, setSelected] = useState(0);
  const [count, setCount] = useState(0);

  const onSelect = useCallback(() => {
    if (!embla) return;
    setSelected(embla.selectedScrollSnap());
  }, [embla]);

  useEffect(() => {
    if (!embla) return;
    setCount(embla.scrollSnapList().length);
    onSelect();

    embla.on("select", onSelect).on("reInit", onSelect);

    return () => {
      embla.off("select", onSelect).off("reInit", onSelect);
    };
  }, [embla, onSelect]);

  /**
   * Commit to the next slide once a gesture has travelled COMMIT_FRACTION,
   * regardless of how slowly it got there.
   *
   * Measured from raw pointer coordinates rather than embla's internals. That
   * is deliberate: the wheel-gestures plugin works by synthesising mousedown,
   * mousemove and mouseup on the same node, so one set of listeners covers a
   * trackpad swipe, a mouse drag and a touch swipe identically. It also avoids
   * depending on the sign of embla's internal translate, which is easy to get
   * backwards and awkward to reason about under `loop`.
   */
  useEffect(() => {
    if (!embla) return;
    const node = embla.rootNode();

    let startX: number | null = null;
    let startIndex = 0;

    const begin = (x: number) => {
      startX = x;
      startIndex = embla.selectedScrollSnap();
    };

    const finish = (x: number) => {
      if (startX === null) return;
      const dx = x - startX;
      startX = null;

      const width = node.clientWidth || 1;
      const fraction = dx / width;
      if (Math.abs(fraction) < COMMIT_FRACTION) return;

      // Let embla apply its own decision first, then only step in if it chose
      // to spring back. Without this guard a fast flick would advance twice,
      // once from embla and once from here.
      //
      // setTimeout rather than requestAnimationFrame so this still runs when
      // rAF is throttled, which browsers do in background tabs.
      setTimeout(() => {
        if (embla.selectedScrollSnap() !== startIndex) return;
        // Dragging leftwards reveals the slide to the right.
        if (fraction < 0) embla.scrollNext();
        else embla.scrollPrev();
      }, 0);
    };

    const onMouseDown = (e: MouseEvent) => begin(e.clientX);
    const onMouseUp = (e: MouseEvent) => finish(e.clientX);
    const onTouchStart = (e: TouchEvent) => {
      if (e.touches.length === 1) begin(e.touches[0].clientX);
    };
    const onTouchEnd = (e: TouchEvent) => {
      if (e.changedTouches.length) finish(e.changedTouches[0].clientX);
    };

    node.addEventListener("mousedown", onMouseDown);
    node.addEventListener("touchstart", onTouchStart, { passive: true });
    // Release is watched on the document because a gesture very often ends
    // with the pointer outside the carousel.
    document.addEventListener("mouseup", onMouseUp);
    document.addEventListener("touchend", onTouchEnd);

    return () => {
      node.removeEventListener("mousedown", onMouseDown);
      node.removeEventListener("touchstart", onTouchStart);
      document.removeEventListener("mouseup", onMouseUp);
      document.removeEventListener("touchend", onTouchEnd);
    };
  }, [embla]);

  if (!events.length) return null;

  return (
    <section
      className="relative"
      aria-roledescription="carousel"
      aria-label="Featured events"
    >
      {/* Cursor left as the default arrow on purpose. A grab hand reads as
          "this is a thing you must drag", when the carousel moves on its own
          and a trackpad swipe needs no pointer at all. The "Swipe to browse"
          hint below carries the affordance instead, without the whole hero
          announcing itself as a control. */}
      <div className="overflow-hidden" ref={emblaRef}>
        {/* select-none stops a drag turning into a text selection halfway
            through, which leaves the slide stuck and the words highlighted. */}
        <div className="flex select-none">
          {events.map((event, i) => {
            const label = event.title ?? event.name ?? "Untitled event";
            const d = formatEventDate(event.date);

            return (
              <div
                key={event.id}
                className="relative min-w-0 flex-[0_0_100%]"
                role="group"
                aria-roledescription="slide"
                aria-label={`${i + 1} of ${events.length}`}
              >
                <div className="relative h-[62vh] min-h-[440px] w-full overflow-hidden">
                  {event.image_url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={event.image_url}
                      alt=""
                      loading={i === 0 ? "eager" : "lazy"}
                      // Native image dragging hijacks the pointer and kills the
                      // swipe. Both the attribute and the CSS are needed:
                      // Firefox honours one, WebKit the other.
                      draggable={false}
                      className="pointer-events-none size-full select-none object-cover opacity-55 [-webkit-user-drag:none]"
                    />
                  ) : (
                    <div className="size-full bg-gradient-to-br from-zinc-800 to-zinc-950" />
                  )}

                  {/* Two gradients: one to seat the text, one to blend the section below. */}
                  <div className="pointer-events-none absolute inset-0 bg-gradient-to-r from-background via-background/70 to-transparent" />
                  <div className="pointer-events-none absolute inset-x-0 bottom-0 h-40 bg-gradient-to-t from-background to-transparent" />

                  <div className="absolute inset-0 flex items-center">
                    <div className="container">
                      <div className="max-w-xl">
                        <div className="mb-4 flex flex-wrap items-center gap-2">
                          <Badge>{relativeTo(event.date)}</Badge>
                          {event.cities?.name && (
                            <Badge variant="neutral">
                              <MapPin />
                              {event.cities.name}
                            </Badge>
                          )}
                        </div>

                        <h2 className="font-display text-5xl leading-[0.95] tracking-display sm:text-6xl md:text-7xl">
                          {label}
                        </h2>

                        <p className="mt-4 text-sm text-muted-foreground">
                          <span className="tnum">{d.full}</span>
                          <span className="mx-2 text-border">/</span>
                          {event.venue}
                        </p>

                        <div className="mt-7 flex flex-wrap gap-3">
                          <Button asChild size="lg">
                            <Link href={`/events/${event.id}`} draggable={false}>
                              View tickets
                              <ArrowRight />
                            </Link>
                          </Button>
                          <Button asChild size="lg" variant="outline">
                            <Link href="/sell" draggable={false}>
                              Sell for this event
                            </Link>
                          </Button>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Dots stay. They are orientation as much as navigation: without them
          there is no way to tell how many slides exist or where you are. */}
      <div className="container relative -mt-12 flex items-center gap-4 pb-4">
        <div className="flex items-center gap-2" role="tablist" aria-label="Featured events">
          {Array.from({ length: count }).map((_, i) => (
            <button
              key={i}
              role="tab"
              aria-selected={i === selected}
              aria-label={`Go to slide ${i + 1}`}
              onClick={() => embla?.scrollTo(i)}
              className={cn(
                "h-1 rounded-full transition-all",
                i === selected ? "w-8 bg-primary" : "w-4 bg-border hover:bg-zinc-600"
              )}
            />
          ))}
        </div>

        <p className="hidden text-[11px] text-muted-foreground sm:block">
          Swipe to browse
        </p>
      </div>
    </section>
  );
}
