/**
 * Tests for the constellation's pure maths.
 *
 * No WebGL, no DOM — the orbit, depth, label and flare functions are plain
 * numbers, so they can be checked in Node. That is the whole reason they live
 * in a separate module from the renderer.
 */

import { describe, expect, it } from "vitest";
import {
  DEFAULT_AGENTS,
  applyTilt,
  breathe,
  depthFactor,
  easeInOut,
  flareCurve,
  hexToRgb01,
  labelOpacity,
  orbitAngle,
  orbitPosition,
  phaseFromId,
} from "../src/engine/agents/spec";

describe("the default constellation", () => {
  it("has the three JARVIS sub-agents", () => {
    expect(DEFAULT_AGENTS.map((a) => a.id)).toEqual(["scout", "board", "mindmap"]);
  });

  it("gives every agent a distinct starting phase", () => {
    const phases = DEFAULT_AGENTS.map((a) => a.orbit.phase);
    expect(new Set(phases).size).toBe(phases.length);
  });

  it("gives every agent a distinct orbit radius", () => {
    const radii = DEFAULT_AGENTS.map((a) => a.orbit.radius);
    expect(new Set(radii).size).toBe(radii.length);
  });

  it("gives every agent a distinct speed, so they never move in lockstep", () => {
    const speeds = DEFAULT_AGENTS.map((a) => a.orbit.speed);
    expect(new Set(speeds).size).toBe(speeds.length);
  });

  it("alternates tilt direction, so the orbits sit in different planes", () => {
    const signs = DEFAULT_AGENTS.map((a) => Math.sign(a.orbit.tiltX));
    expect(signs).toContain(1);
    expect(signs).toContain(-1);
  });

  it("keeps every orbit clear of the orb's glow shell (radius > 1.3)", () => {
    for (const agent of DEFAULT_AGENTS) {
      expect(agent.orbit.radius).toBeGreaterThan(1.3);
    }
  });

  it("gives every agent a valid hex colour and a panel to dock beside", () => {
    for (const agent of DEFAULT_AGENTS) {
      expect(() => hexToRgb01(agent.color)).not.toThrow();
      expect(agent.panelId).toBeTruthy();
    }
  });
});

describe("orbitAngle", () => {
  it("returns the phase at t=0", () => {
    const orbit = { radius: 1, speed: 0.5, phase: 1.2, tiltX: 0, tiltZ: 0 };
    expect(orbitAngle(orbit, 0)).toBeCloseTo(1.2, 6);
  });

  it("advances at the orbit's speed", () => {
    const orbit = { radius: 1, speed: 0.5, phase: 0, tiltX: 0, tiltZ: 0 };
    expect(orbitAngle(orbit, 2)).toBeCloseTo(1.0, 6);
  });
});

describe("applyTilt", () => {
  it("is the identity at zero tilt", () => {
    const p = applyTilt({ x: 1, y: 2, z: 3 }, 0, 0);
    expect(p.x).toBeCloseTo(1, 6);
    expect(p.y).toBeCloseTo(2, 6);
    expect(p.z).toBeCloseTo(3, 6);
  });

  it("rotates around X without changing the length", () => {
    const p = applyTilt({ x: 0, y: 1, z: 0 }, Math.PI / 2, 0);
    expect(Math.hypot(p.x, p.y, p.z)).toBeCloseTo(1, 6);
    expect(p.z).toBeCloseTo(1, 6);
  });
});

describe("orbitPosition", () => {
  it("stays on the sphere of the orbit radius", () => {
    const orbit = { radius: 1.7, speed: 0.3, phase: 0.4, tiltX: 0.35, tiltZ: -0.2 };
    for (let t = 0; t < 10; t += 0.37) {
      const p = orbitPosition(orbit, t);
      expect(Math.hypot(p.x, p.y, p.z)).toBeCloseTo(1.7, 5);
    }
  });
});

describe("depthFactor", () => {
  it("is 1 at the near side and 0 at the far side", () => {
    expect(depthFactor({ x: 0, y: 0, z: 2 }, 2)).toBeCloseTo(1, 6);
    expect(depthFactor({ x: 0, y: 0, z: -2 }, 2)).toBeCloseTo(0, 6);
  });

  it("is 0.5 at the sides", () => {
    expect(depthFactor({ x: 2, y: 0, z: 0 }, 2)).toBeCloseTo(0.5, 6);
  });

  it("clamps out-of-range input rather than returning nonsense", () => {
    expect(depthFactor({ x: 0, y: 0, z: 99 }, 2)).toBe(1);
    expect(depthFactor({ x: 0, y: 0, z: -99 }, 2)).toBe(0);
  });

  it("survives a zero radius without dividing by zero", () => {
    expect(depthFactor({ x: 0, y: 0, z: 0 }, 0)).toBe(0.5);
  });
});

describe("labelOpacity", () => {
  it("hides the label when the agent is behind the orb", () => {
    expect(labelOpacity(0)).toBe(0);
    expect(labelOpacity(0.1)).toBe(0);
  });

  it("shows it fully once the agent has swung to the front", () => {
    expect(labelOpacity(1)).toBe(1);
    expect(labelOpacity(0.6)).toBe(1);
  });

  it("rises monotonically in between", () => {
    let last = -1;
    for (let d = 0; d <= 1; d += 0.05) {
      const v = labelOpacity(d);
      expect(v).toBeGreaterThanOrEqual(last);
      last = v;
    }
  });
});

describe("flareCurve", () => {
  it("is zero at both ends and peaks in the middle", () => {
    expect(flareCurve(0)).toBe(0);
    expect(flareCurve(1)).toBe(0);
    expect(flareCurve(0.5)).toBeCloseTo(1, 6);
  });

  it("is zero outside the unit interval", () => {
    expect(flareCurve(-0.5)).toBe(0);
    expect(flareCurve(1.5)).toBe(0);
  });
});

describe("easeInOut", () => {
  it("pins both ends", () => {
    expect(easeInOut(0)).toBe(0);
    expect(easeInOut(1)).toBe(1);
  });

  it("clamps out-of-range input", () => {
    expect(easeInOut(-3)).toBe(0);
    expect(easeInOut(7)).toBe(1);
  });

  it("is symmetric about the midpoint", () => {
    expect(easeInOut(0.5)).toBeCloseTo(0.5, 6);
    expect(easeInOut(0.25) + easeInOut(0.75)).toBeCloseTo(1, 6);
  });
});

describe("breathe", () => {
  it("stays within 0..1", () => {
    for (let t = 0; t < 20; t += 0.13) {
      const v = breathe(t, 0.7);
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThanOrEqual(1);
    }
  });

  it("puts two agents out of phase, so the constellation never throbs in unison", () => {
    const a = breathe(1.0, 0);
    const b = breathe(1.0, Math.PI);
    expect(Math.abs(a - b)).toBeGreaterThan(0.5);
  });
});

describe("phaseFromId", () => {
  it("is stable for the same id", () => {
    expect(phaseFromId("scout")).toBe(phaseFromId("scout"));
  });

  it("differs between ids", () => {
    expect(phaseFromId("scout")).not.toBe(phaseFromId("board"));
  });

  it("stays within one turn", () => {
    for (const id of ["scout", "board", "mindmap", "a", "some-long-agent-name"]) {
      const p = phaseFromId(id);
      expect(p).toBeGreaterThanOrEqual(0);
      expect(p).toBeLessThan(Math.PI * 2 + 1e-9);
    }
  });
});

describe("hexToRgb01", () => {
  it("parses a hex colour into 0..1 components", () => {
    const c = hexToRgb01("#ffc247");
    expect(c.x).toBeCloseTo(1, 4);
    expect(c.y).toBeCloseTo(0.7608, 3);
    expect(c.z).toBeCloseTo(0.2784, 3);
  });

  it("throws on a malformed colour rather than silently returning black", () => {
    expect(() => hexToRgb01("not-a-colour")).toThrow();
    expect(() => hexToRgb01("#fff")).toThrow();
  });
});
