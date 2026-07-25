/* Smooth interpolation for the live position feed.

   Fixes arrive in discrete ticks — screen OCR reads about once a second,
   and a typed /loc is a single sample — so the hero has to be interpolated
   between them or it visibly hops. Two rules make the motion read as
   continuous rather than stepped:

     - tween LINEARLY. An ease-out curve decelerates to a full stop inside
       every tick, then sits still until the next one lands; that pause is
       exactly the stepping the easing looks like it should be smoothing.
     - tween over the MEASURED gap between fixes, not a fixed guess, so the
       marker is still moving when the next fix arrives instead of parking
       early and waiting for it.

   The cost is that the marker trails the truth by up to one tick — the
   standard trade for interpolated motion, and unnoticeable at run speed. */

export const MIN_GLIDE_MS = 250;
export const MAX_GLIDE_MS = 2000;

export function makeCadence(initialMs = 1000) {
  let last = 0;
  let ms = initialMs;
  return {
    /** Record a fix; returns how long to animate toward it. */
    tick(now: number): number {
      if (last) {
        const gap = now - last;
        // ignore repeat frames and AFK-sized pauses — neither describes the
        // feed's real cadence, and both would wreck the average
        if (gap > 60 && gap < 5000) ms = ms * 0.6 + gap * 0.4;
      }
      last = now;
      return Math.min(Math.max(ms, MIN_GLIDE_MS), MAX_GLIDE_MS);
    },
  };
}

export type Cadence = ReturnType<typeof makeCadence>;

/** Snap instead of animating when the user has asked for less motion. */
export function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}
