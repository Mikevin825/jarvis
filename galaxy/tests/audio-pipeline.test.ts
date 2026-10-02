import { describe, expect, it } from "vitest";
import { readLevels, smoothLevels, syntheticLevels, ZERO_LEVELS } from "../src/engine/audio";

/**
 * These tests cover the audio pipeline that AudioCapture relies on.
 * The capture class itself uses Web Audio API (not available in Node),
 * but the pure maths it calls is fully tested here.
 */

describe("audio pipeline (used by AudioCapture)", () => {
  it("readLevels returns zero for silence", () => {
    const bins = new Float32Array(2048).fill(-100);
    const levels = readLevels(bins);
    expect(levels.voice).toBeCloseTo(0, 2);
    expect(levels.bass).toBeCloseTo(0, 2);
    expect(levels.treble).toBeCloseTo(0, 2);
  });

  it("readLevels detects speech-band energy", () => {
    const bins = new Float32Array(2048).fill(-100);
    // Put energy in the voice band (10%-60% of spectrum)
    for (let i = 200; i < 1200; i++) bins[i] = -20;
    const levels = readLevels(bins);
    expect(levels.voice).toBeGreaterThan(0.5);
  });

  it("readLevels applies mic gain and floor", () => {
    const bins = new Float32Array(2048).fill(-100);
    const quiet = readLevels(bins, { mic: false });
    const mic = readLevels(bins, { mic: true });
    expect(mic.voice).toBeGreaterThan(quiet.voice);
    expect(mic.voice).toBeGreaterThan(0);
  });

  it("smoothLevels attacks faster than it decays", () => {
    const up = smoothLevels(ZERO_LEVELS, { voice: 1, bass: 1, treble: 1 });
    const down = smoothLevels(
      { voice: 1, bass: 1, treble: 1 },
      ZERO_LEVELS,
    );
    expect(up.voice).toBeGreaterThan(1 - down.voice);
  });

  it("syntheticLevels is silent when not speaking", () => {
    expect(syntheticLevels(1.5, false)).toEqual(ZERO_LEVELS);
  });

  it("syntheticLevels is deterministic", () => {
    expect(syntheticLevels(3.25, true)).toEqual(syntheticLevels(3.25, true));
  });

  it("syntheticLevels varies over time", () => {
    const samples = [];
    for (let t = 0; t < 4; t += 0.1) {
      samples.push(syntheticLevels(t, true).voice);
    }
    const min = Math.min(...samples);
    const max = Math.max(...samples);
    expect(max - min).toBeGreaterThan(0.2);
  });

  it("syntheticLevels stays within range", () => {
    for (let t = 0; t < 20; t += 0.05) {
      const levels = syntheticLevels(t, true);
      expect(levels.voice).toBeGreaterThanOrEqual(0);
      expect(levels.voice).toBeLessThanOrEqual(1);
      expect(levels.bass).toBeGreaterThanOrEqual(0);
      expect(levels.bass).toBeLessThanOrEqual(1);
      expect(levels.treble).toBeGreaterThanOrEqual(0);
      expect(levels.treble).toBeLessThanOrEqual(1);
    }
  });

  it("smoothLevels settles toward target over repeated frames", () => {
    let levels = ZERO_LEVELS;
    const target = { voice: 0.8, bass: 0.6, treble: 0.4 };
    for (let i = 0; i < 200; i++) {
      levels = smoothLevels(levels, target);
    }
    expect(levels.voice).toBeCloseTo(0.8, 1);
    expect(levels.bass).toBeCloseTo(0.6, 1);
    expect(levels.treble).toBeCloseTo(0.4, 1);
  });
});
