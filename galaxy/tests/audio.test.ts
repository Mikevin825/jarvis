import { describe, expect, it } from "vitest";
import {
  ATTACK,
  DECAY,
  MIC_FLOOR,
  ZERO_LEVELS,
  bandAverage,
  breathValue,
  displacement,
  readLevels,
  smoothLevel,
  smoothLevels,
  syntheticLevels,
} from "../src/engine/audio";

/** Build a spectrum of `n` bins, all at `db`. */
function spectrum(n: number, db: number): Float32Array {
  return new Float32Array(n).fill(db);
}

describe("bandAverage", () => {
  it("returns 0 for an empty spectrum", () => {
    expect(bandAverage(new Float32Array(0), 0, 1)).toBe(0);
  });

  it("maps silence to 0 and full scale to 1", () => {
    expect(bandAverage(spectrum(64, -100), 0, 1)).toBeCloseTo(0, 2);
    expect(bandAverage(spectrum(64, 0), 0, 1)).toBeCloseTo(1, 2);
  });

  it("clamps below silence rather than going negative", () => {
    expect(bandAverage(spectrum(64, -140), 0, 1)).toBe(0);
  });

  it("reads only the requested slice", () => {
    const bins = new Float32Array(100).fill(-100);
    // Put energy only in the middle.
    for (let i = 40; i < 60; i++) bins[i] = 0;

    const middle = bandAverage(bins, 0.4, 0.6);
    const start = bandAverage(bins, 0, 0.1);
    expect(middle).toBeGreaterThan(0.9);
    expect(start).toBeLessThan(0.1);
  });

  it("handles a slice that would round to nothing", () => {
    const value = bandAverage(spectrum(8, 0), 0.99, 1);
    expect(Number.isFinite(value)).toBe(true);
  });
});

describe("readLevels", () => {
  it("returns zero for silence", () => {
    const levels = readLevels(spectrum(128, -100));
    expect(levels.voice).toBeCloseTo(0, 2);
    expect(levels.bass).toBeCloseTo(0, 2);
  });

  it("reads bass from the bottom of the spectrum", () => {
    const bins = new Float32Array(128).fill(-100);
    for (let i = 0; i < 6; i++) bins[i] = 0; // energy only in the bass
    const levels = readLevels(bins);
    expect(levels.bass).toBeGreaterThan(0.9);
    expect(levels.voice).toBeLessThan(0.2);
  });

  it("reads treble from the top of the spectrum", () => {
    const bins = new Float32Array(128).fill(-100);
    for (let i = 100; i < 128; i++) bins[i] = 0;
    const levels = readLevels(bins);
    expect(levels.treble).toBeGreaterThan(0.5);
    expect(levels.bass).toBeLessThan(0.2);
  });

  it("applies gain and a floor for the microphone", () => {
    const quiet = spectrum(128, -80);
    const asMic = readLevels(quiet, { mic: true });
    const asPlayback = readLevels(quiet, { mic: false });
    expect(asMic.voice).toBeGreaterThan(asPlayback.voice);
    expect(asMic.voice).toBeGreaterThanOrEqual(MIC_FLOOR);
  });

  it("keeps the mic floor so the orb never looks dead", () => {
    const silence = readLevels(spectrum(128, -100), { mic: true });
    expect(silence.voice).toBeGreaterThan(0);
  });

  it("never exceeds 1", () => {
    const loud = readLevels(spectrum(128, 20), { mic: true });
    expect(loud.voice).toBeLessThanOrEqual(1);
    expect(loud.bass).toBeLessThanOrEqual(1);
  });

  it("works for any analyser size", () => {
    for (const size of [32, 512, 2048]) {
      const levels = readLevels(spectrum(size, -50));
      expect(Number.isFinite(levels.voice)).toBe(true);
      expect(levels.voice).toBeGreaterThanOrEqual(0);
    }
  });
});

describe("smoothing", () => {
  it("attacks faster than it decays", () => {
    expect(ATTACK).toBeGreaterThan(DECAY);
    const rising = smoothLevel(0, 1);
    const falling = smoothLevel(1, 0);
    expect(rising).toBeGreaterThan(1 - falling);
  });

  it("moves toward the new value without overshooting", () => {
    const up = smoothLevel(0.2, 0.9);
    expect(up).toBeGreaterThan(0.2);
    expect(up).toBeLessThan(0.9);

    const down = smoothLevel(0.9, 0.2);
    expect(down).toBeLessThan(0.9);
    expect(down).toBeGreaterThan(0.2);
  });

  it("smooths all three bands", () => {
    const next = smoothLevels(ZERO_LEVELS, { voice: 1, bass: 1, treble: 1 });
    expect(next.voice).toBeGreaterThan(0);
    expect(next.bass).toBeGreaterThan(0);
    expect(next.treble).toBeGreaterThan(0);
  });

  it("settles toward the target over repeated frames", () => {
    let level = 0;
    for (let i = 0; i < 200; i++) level = smoothLevel(level, 0.8);
    expect(level).toBeCloseTo(0.8, 2);
  });
});

describe("syntheticLevels", () => {
  it("is silent when not speaking", () => {
    expect(syntheticLevels(1.5, false)).toEqual(ZERO_LEVELS);
  });

  it("is deterministic — the same time gives the same result", () => {
    expect(syntheticLevels(3.25, true)).toEqual(syntheticLevels(3.25, true));
  });

  it("varies over time rather than sitting flat", () => {
    const samples = [];
    for (let t = 0; t < 4; t += 0.1) samples.push(syntheticLevels(t, true).voice);
    const min = Math.min(...samples);
    const max = Math.max(...samples);
    expect(max - min).toBeGreaterThan(0.2);
  });

  it("stays within range", () => {
    for (let t = 0; t < 20; t += 0.05) {
      const levels = syntheticLevels(t, true);
      expect(levels.voice).toBeGreaterThanOrEqual(0);
      expect(levels.voice).toBeLessThanOrEqual(1);
      expect(levels.bass).toBeGreaterThanOrEqual(0);
      expect(levels.bass).toBeLessThanOrEqual(1);
    }
  });
});

describe("displacement", () => {
  it("is small at rest", () => {
    // The orb should barely ripple when nothing is happening.
    const value = displacement(0, 0, ZERO_LEVELS, 0.16);
    expect(Math.abs(value)).toBeLessThan(0.1);
  });

  it("grows with audio", () => {
    const quiet = displacement(0, 0, { voice: 0, bass: 0, treble: 0 }, 0.85);
    const loud = displacement(0, 0, { voice: 1, bass: 1, treble: 0 }, 0.85);
    expect(loud).toBeGreaterThan(quiet);
  });

  it("is clamped so the orb never tears itself apart", () => {
    const extreme = displacement(10, 10, { voice: 1, bass: 1, treble: 1 }, 10);
    expect(extreme).toBeLessThanOrEqual(0.45);
    expect(extreme).toBeGreaterThanOrEqual(-0.45);
  });

  it("scales with amplitude", () => {
    const levels = { voice: 1, bass: 0, treble: 0 };
    const small = displacement(0, 0, levels, 0.2);
    const large = displacement(0, 0, levels, 0.9);
    expect(large).toBeGreaterThan(small);
  });
});

describe("breathValue", () => {
  it("oscillates gently", () => {
    const values = [];
    for (let t = 0; t < 10; t += 0.1) values.push(breathValue(t));
    expect(Math.max(...values)).toBeLessThanOrEqual(0.04);
    expect(Math.min(...values)).toBeGreaterThanOrEqual(-0.04);
  });

  it("actually moves", () => {
    expect(Math.abs(breathValue(0) - breathValue(2.2))).toBeGreaterThan(0.001);
  });
});
