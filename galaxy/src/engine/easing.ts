/**
 * Frame-rate independent easing.
 *
 * The naive form — `value += (target - value) * 0.1` every frame — moves twice
 * as far per second on a 120 Hz monitor as on a 60 Hz one. The orb would breathe
 * differently on different machines, which is exactly the kind of bug that is
 * invisible until someone else looks at it.
 *
 * The fix is to treat the smoothing constant as "the fraction of the remaining
 * distance to cover in one second", then raise it to the power of how much of a
 * second actually elapsed. Ten steps of 16 ms and five steps of 32 ms then land
 * in the same place.
 */

/** A frame's worth of time, in seconds. */
export interface FrameTime {
  /** Seconds since the previous frame. */
  delta: number;
  /** Multiplier for reduced-motion. Slows the animation clock, never time itself. */
  clockScale: number;
}

/**
 * Move `current` a fraction of the way toward `target`, adjusted for elapsed time.
 *
 * @param current  Where the value is now.
 * @param target   Where it should end up.
 * @param rate     Fraction of the remaining distance covered per second.
 *                 Larger is snappier. 0 never moves, 1 arrives within a frame.
 * @param delta    Seconds elapsed since the last frame.
 */
export function approach(
  current: number,
  target: number,
  rate: number,
  delta: number,
): number {
  if (rate <= 0) return current;
  if (rate >= 1) return target;
  // Guard against a huge delta after a tab was backgrounded: without this the
  // first frame back would jump the whole way and look like a glitch.
  const step = Math.min(delta, 0.1);
  return current + (target - current) * (1 - Math.pow(1 - rate, step * 60));
}

/**
 * Ease a whole record of numbers toward a target record.
 *
 * Every visual parameter moves this way, so nothing in the scene ever snaps.
 */
export function approachAll<K extends string>(
  current: Record<K, number>,
  target: Record<K, number>,
  rates: Record<K, number> | number,
  delta: number,
): Record<K, number> {
  const out = { ...current };
  for (const key of Object.keys(target) as K[]) {
    const rate = typeof rates === "number" ? rates : rates[key];
    out[key] = approach(current[key], target[key], rate, delta);
  }
  return out;
}

/** Linear interpolation, for values that are not smoothed over time. */
export function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

/** Clamp to a range. */
export function clamp(value: number, min: number, max: number): number {
  return value < min ? min : value > max ? max : value;
}

/**
 * An animation clock that respects reduced-motion.
 *
 * Reduced motion slows a *separate* clock rather than multiplying elapsed time.
 * Multiplying time makes every sine wave jump the moment the setting changes,
 * because the phase is a function of the scaled total. Advancing a separate
 * accumulator keeps every phase continuous.
 */
export class AnimationClock {
  /** Seconds of animation time, advancing more slowly under reduced motion. */
  elapsed = 0;

  advance(delta: number, reducedMotion: boolean): number {
    this.elapsed += delta * (reducedMotion ? 0.25 : 1);
    return this.elapsed;
  }

  reset(): void {
    this.elapsed = 0;
  }
}
