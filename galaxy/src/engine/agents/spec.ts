/**
 * Sub-agent specification and orbit maths.
 *
 * Pure: no three.js, no DOM, no GPU. The renderer reads these numbers; the
 * tests exercise them in plain Node. That separation is the same one the rest
 * of the engine follows — the maths is checkable without a screen.
 */

export interface Vec3 {
  x: number;
  y: number;
  z: number;
}

export interface OrbitParams {
  /** Distance from the orb centre, in world units. */
  radius: number;
  /** Radians per second around the orbit. */
  speed: number;
  /** Starting angle, radians. Spread these so agents never clump up. */
  phase: number;
  /** Tilt of the orbit plane around X, radians. */
  tiltX: number;
  /** Tilt of the orbit plane around Z, radians. */
  tiltZ: number;
}

export interface AgentSpec {
  id: string;
  name: string;
  /** One line, shown under the name. */
  specialty: string;
  /** Accent colour, #rrggbb. */
  color: string;
  /** Optional explicit avatar image path. */
  avatar?: string;
  orbit: OrbitParams;
  /** DOM id of the panel this agent settles beside while working. */
  panelId?: string;
}

/**
 * JARVIS's three sub-agents.
 *
 * Different radii, speeds, phases and alternating tilt directions, so their
 * paths sit in different planes and they never move in lockstep.
 *
 * Radii are tuned against the orb camera (45° FOV at 5.6 units): the visible
 * half-height at the orb's plane is ~2.3 units, so the outermost orbit leaves
 * room for a label beneath it without clipping.
 */
export const DEFAULT_AGENTS: AgentSpec[] = [
  {
    id: "scout",
    name: "Scout",
    specialty: "Hunts competitor and product news",
    color: "#4fe0d8",
    orbit: { radius: 1.62, speed: 0.22, phase: 0.0, tiltX: 0.35, tiltZ: 0.0 },
    panelId: "panel-scout",
  },
  {
    id: "board",
    name: "Board",
    specialty: "Convenes the advisors",
    color: "#a78bfa",
    orbit: { radius: 1.78, speed: 0.17, phase: 2.1, tiltX: -0.28, tiltZ: 0.18 },
    panelId: "panel-board",
  },
  {
    id: "mindmap",
    name: "Mind",
    specialty: "Maps memories and tools",
    color: "#f5a524",
    orbit: { radius: 1.94, speed: 0.13, phase: 4.2, tiltX: 0.12, tiltZ: -0.22 },
    panelId: "panel-mindmap",
  },
];

/** The angle an agent sits at, given elapsed seconds. */
export function orbitAngle(orbit: OrbitParams, elapsed: number): number {
  return orbit.phase + elapsed * orbit.speed;
}

/** Rotate a point around X, then around Z. Order is fixed so it is testable. */
export function applyTilt(p: Vec3, tiltX: number, tiltZ: number): Vec3 {
  const cosX = Math.cos(tiltX);
  const sinX = Math.sin(tiltX);
  const y1 = p.y * cosX - p.z * sinX;
  const z1 = p.y * sinX + p.z * cosX;

  const cosZ = Math.cos(tiltZ);
  const sinZ = Math.sin(tiltZ);
  const x2 = p.x * cosZ - y1 * sinZ;
  const y2 = p.x * sinZ + y1 * cosZ;

  return { x: x2, y: y2, z: z1 };
}

/** Where an agent sits at a moment in time. */
export function orbitPosition(orbit: OrbitParams, elapsed: number): Vec3 {
  const a = orbitAngle(orbit, elapsed);
  const flat: Vec3 = {
    x: Math.cos(a) * orbit.radius,
    y: 0,
    z: Math.sin(a) * orbit.radius,
  };
  return applyTilt(flat, orbit.tiltX, orbit.tiltZ);
}

/**
 * How near the camera an agent is: 0 = far side of the orbit, 1 = near side.
 * The camera looks down -Z, so a positive z is nearer.
 */
export function depthFactor(p: Vec3, radius: number): number {
  if (radius <= 0) return 0.5;
  const t = (p.z / radius + 1) / 2;
  return Math.max(0, Math.min(1, t));
}

/**
 * Label opacity for a given depth.
 *
 * Hidden while the agent is directly behind the orb, fully visible by the time
 * it swings past the side. This is what makes the labels read as sitting in
 * three dimensions rather than floating on the glass.
 */
export function labelOpacity(depth: number): number {
  const t = (depth - 0.18) / 0.32;
  return Math.max(0, Math.min(1, t));
}

/**
 * A 0 → 1 → 0 arc over the unit interval, peaking in the middle.
 * Used for the dispatch flare and the expanding ring.
 */
export function flareCurve(t: number): number {
  if (t <= 0 || t >= 1) return 0;
  return Math.sin(t * Math.PI);
}

/** Smooth 0..1 ramp, so a docked agent arrives without a corner in its path. */
export function easeInOut(t: number): number {
  const c = Math.max(0, Math.min(1, t));
  return c * c * (3 - 2 * c);
}

/**
 * An agent's resting glow pulse, slightly out of phase per agent so the
 * constellation never throbs in unison.
 */
export function breathe(elapsed: number, phase: number): number {
  return 0.5 + 0.5 * Math.sin(elapsed * 0.9 + phase);
}

/** Stable per-agent phase offset, derived from the id so it never changes. */
export function phaseFromId(id: string): number {
  let hash = 0;
  for (let i = 0; i < id.length; i++) {
    hash = (hash * 31 + id.charCodeAt(i)) | 0;
  }
  // `hash` is a signed 32-bit int, so mask off the sign before scaling —
  // otherwise half of all ids would get a negative phase.
  return ((hash >>> 0) % 1000) / 1000 * Math.PI * 2;
}

/** #rrggbb → {r,g,b} in 0..1. Throws on anything malformed. */
export function hexToRgb01(hex: string): Vec3 {
  const match = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!match) throw new Error(`not a hex colour: ${hex}`);
  const value = parseInt(match[1], 16);
  return {
    x: ((value >> 16) & 0xff) / 255,
    y: ((value >> 8) & 0xff) / 255,
    z: (value & 0xff) / 255,
  };
}
