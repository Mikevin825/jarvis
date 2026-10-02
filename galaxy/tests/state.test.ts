import { describe, expect, it } from "vitest";
import {
  DEFAULT_RATES,
  STATES,
  STATE_TABLE,
  asState,
  hexToRgb,
  type VisualTargets,
} from "../src/engine/state";

describe("hexToRgb", () => {
  it("parses a hex colour", () => {
    expect(hexToRgb("#ffffff")).toEqual({ r: 1, g: 1, b: 1 });
    expect(hexToRgb("#000000")).toEqual({ r: 0, g: 0, b: 0 });
  });

  it("works without the hash and in either case", () => {
    expect(hexToRgb("FFC247")).toEqual(hexToRgb("#ffc247"));
  });

  it("rejects malformed input", () => {
    expect(() => hexToRgb("not a colour")).toThrow();
    expect(() => hexToRgb("#fff")).toThrow();
  });
});

describe("the state table", () => {
  it("defines every state", () => {
    for (const state of STATES) {
      expect(STATE_TABLE[state]).toBeDefined();
    }
  });

  it("gives every state the same set of parameters", () => {
    // A missing parameter would mean a value that silently never eases.
    const reference = Object.keys(STATE_TABLE.idle).sort();
    for (const state of STATES) {
      expect(Object.keys(STATE_TABLE[state]).sort()).toEqual(reference);
    }
  });

  it("has a rate for every parameter", () => {
    for (const key of Object.keys(STATE_TABLE.idle) as (keyof VisualTargets)[]) {
      expect(DEFAULT_RATES[key]).toBeGreaterThan(0);
    }
  });

  it("keeps every value finite", () => {
    for (const state of STATES) {
      for (const [key, value] of Object.entries(STATE_TABLE[state])) {
        expect(Number.isFinite(value), `${state}.${key}`).toBe(true);
      }
    }
  });
});

describe("the character of each state", () => {
  it("idle is the quietest", () => {
    const idle = STATE_TABLE.idle;
    for (const state of STATES) {
      if (state === "idle") continue;
      expect(idle.glowStrength).toBeLessThanOrEqual(STATE_TABLE[state].glowStrength);
    }
    expect(idle.displacementAmplitude).toBeLessThan(0.25);
    expect(idle.ringOpacity).toBe(0);
  });

  it("listening is warm gold and the brightest", () => {
    const l = STATE_TABLE.listening;
    // Gold: red dominant, then green, then blue.
    expect(l.primaryR).toBeGreaterThan(l.primaryG);
    expect(l.primaryG).toBeGreaterThan(l.primaryB);
    expect(l.glowStrength).toBeGreaterThan(1);
  });

  it("listening is the only warm state", () => {
    // The recording light is meant to be the one warm thing in a cool universe,
    // so no other state should have red as its dominant channel.
    for (const state of STATES) {
      if (state === "listening" || state === "arming") continue;
      const t = STATE_TABLE[state];
      if (state === "error") continue; // red is the point of error
      expect(t.primaryB, `${state} should be cool`).toBeGreaterThanOrEqual(t.primaryR);
    }
  });

  it("error is red, still, and sharp", () => {
    const e = STATE_TABLE.error;
    expect(e.primaryR).toBeGreaterThan(e.primaryG);
    expect(e.primaryR).toBeGreaterThan(e.primaryB);
    expect(e.rotationSpeed).toBeLessThan(0.05);
    expect(e.fresnelSharpness).toBeGreaterThan(3);
  });

  it("thinking shows the rings and lights the galaxy", () => {
    expect(STATE_TABLE.thinking.ringOpacity).toBeGreaterThan(0.4);
    expect(STATE_TABLE.thinking.networkOpacity).toBeGreaterThan(0.4);
    expect(STATE_TABLE.thinking.networkScale).toBeGreaterThan(1);
  });

  it("speaking drives the galaxy hardest", () => {
    expect(STATE_TABLE.speaking.networkOpacity).toBeGreaterThanOrEqual(
      STATE_TABLE.thinking.networkOpacity,
    );
  });

  it("the galaxy stays dim while only listening", () => {
    // Listening affects the orb; the galaxy answers the AI, not the user.
    expect(STATE_TABLE.listening.networkOpacity).toBe(STATE_TABLE.idle.networkOpacity);
    expect(STATE_TABLE.listening.cameraPush).toBe(0);
  });

  it("arming is dimmer than listening so the two are distinguishable", () => {
    expect(STATE_TABLE.arming.glowStrength).toBeLessThan(STATE_TABLE.listening.glowStrength);
    expect(STATE_TABLE.arming.primaryR).toBeLessThan(STATE_TABLE.listening.primaryR);
  });
});

describe("asState", () => {
  it("passes through known states", () => {
    expect(asState("thinking")).toBe("thinking");
  });

  it("falls back to idle for anything else", () => {
    expect(asState("nonsense")).toBe("idle");
    expect(asState("")).toBe("idle");
  });
});
