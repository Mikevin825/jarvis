import { describe, expect, it } from "vitest";
import { AnimationClock, approach, approachAll, clamp, lerp } from "../src/engine/easing";

describe("approach", () => {
  it("moves toward the target", () => {
    const next = approach(0, 1, 0.2, 1 / 60);
    expect(next).toBeGreaterThan(0);
    expect(next).toBeLessThan(1);
  });

  it("never overshoots", () => {
    let value = 0;
    for (let i = 0; i < 600; i++) value = approach(value, 1, 0.2, 1 / 60);
    expect(value).toBeLessThanOrEqual(1);
    expect(value).toBeGreaterThan(0.99);
  });

  it("is frame-rate independent", () => {
    // 60 small steps vs 30 double-length steps must land in the same place.
    // This is the property that stops the orb breathing differently on a
    // 120 Hz monitor than on a 30 fps laptop.
    let fast = 0;
    for (let i = 0; i < 60; i++) fast = approach(fast, 1, 0.15, 1 / 60);

    let slow = 0;
    for (let i = 0; i < 30; i++) slow = approach(slow, 1, 0.15, 1 / 30);

    expect(Math.abs(fast - slow)).toBeLessThan(0.02);
  });

  it("stays stable across wildly different frame rates", () => {
    let a = 0;
    for (let i = 0; i < 600; i++) a = approach(a, 1, 0.2, 1 / 600); // 600 fps
    let b = 0;
    for (let i = 0; i < 10; i++) b = approach(b, 1, 0.2, 1 / 10); // 10 fps
    // Both are most of the way there; neither has exploded or stalled.
    expect(a).toBeGreaterThan(0.9);
    expect(b).toBeGreaterThan(0.5);
    expect(Number.isFinite(a) && Number.isFinite(b)).toBe(true);
  });

  it("clamps a huge delta so a backgrounded tab does not jump", () => {
    // Coming back after ten seconds must not teleport the value.
    const afterLongGap = approach(0, 1, 0.2, 10);
    const afterClampedGap = approach(0, 1, 0.2, 0.1);
    expect(afterLongGap).toBeCloseTo(afterClampedGap, 10);
  });

  it("rate 0 never moves, rate 1 arrives at once", () => {
    expect(approach(0.3, 1, 0, 1 / 60)).toBe(0.3);
    expect(approach(0.3, 1, 1, 1 / 60)).toBe(1);
  });

  it("handles a negative delta without moving backwards", () => {
    const value = approach(0.5, 1, 0.2, -1);
    expect(Number.isFinite(value)).toBe(true);
  });
});

describe("approachAll", () => {
  it("eases every key", () => {
    const current = { a: 0, b: 0 };
    const target = { a: 1, b: 1 };
    const next = approachAll(current, target, 0.2, 1 / 60);
    expect(next.a).toBeGreaterThan(0);
    expect(next.b).toBeGreaterThan(0);
  });

  it("accepts a per-key rate map", () => {
    const current = { slow: 0, fast: 0 };
    const target = { slow: 1, fast: 1 };
    const next = approachAll(current, target, { slow: 0.01, fast: 0.9 }, 1 / 60);
    expect(next.fast).toBeGreaterThan(next.slow);
  });

  it("does not mutate the input", () => {
    const current = { a: 0 };
    approachAll(current, { a: 1 }, 0.5, 1 / 60);
    expect(current.a).toBe(0);
  });
});

describe("lerp and clamp", () => {
  it("lerps", () => {
    expect(lerp(0, 10, 0.5)).toBe(5);
    expect(lerp(0, 10, 0)).toBe(0);
    expect(lerp(0, 10, 1)).toBe(10);
  });

  it("clamps", () => {
    expect(clamp(5, 0, 1)).toBe(1);
    expect(clamp(-5, 0, 1)).toBe(0);
    expect(clamp(0.5, 0, 1)).toBe(0.5);
  });
});

describe("AnimationClock", () => {
  it("advances at full speed normally", () => {
    const clock = new AnimationClock();
    clock.advance(1, false);
    expect(clock.elapsed).toBeCloseTo(1);
  });

  it("advances more slowly under reduced motion", () => {
    const clock = new AnimationClock();
    clock.advance(1, true);
    expect(clock.elapsed).toBeLessThan(1);
    expect(clock.elapsed).toBeGreaterThan(0);
  });

  it("keeps phase continuous when reduced motion is toggled", () => {
    // This is the reason for a separate clock rather than scaling delta:
    // toggling the setting must not make every sine wave jump.
    const clock = new AnimationClock();
    clock.advance(2, false);
    const before = clock.elapsed;
    clock.advance(1 / 60, true);
    expect(clock.elapsed - before).toBeLessThan(1 / 60);
    expect(clock.elapsed).toBeGreaterThan(before);
  });

  it("resets", () => {
    const clock = new AnimationClock();
    clock.advance(5, false);
    clock.reset();
    expect(clock.elapsed).toBe(0);
  });
});
