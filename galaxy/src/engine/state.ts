/**
 * The state table.
 *
 * Every visual parameter for every state is defined here and nowhere else. Each
 * frame, each parameter eases part of the way toward the current state's target,
 * so nothing snaps. Adding a state means adding a row — no renderer changes.
 *
 * The six states map onto what JARVIS is actually doing:
 *
 *   idle       nothing happening
 *   arming     the mic was requested, no audio yet — "waiting for permission"
 *              is a different thing from "listening", and showing it honestly
 *              is the point
 *   listening  recording the user, bright gold: the only warm thing in a cool
 *              universe, so it is unmistakable
 *   thinking   processing, teal shifting toward purple, rings appear
 *   speaking   replying, driven by playback audio
 *   error      something went wrong, red and still
 */

export type AiState =
  | "idle"
  | "arming"
  | "listening"
  | "thinking"
  | "speaking"
  | "error";

export const STATES: AiState[] = [
  "idle",
  "arming",
  "listening",
  "thinking",
  "speaking",
  "error",
];

/** A colour as linear-ish RGB, 0..1. Kept plain so the maths stays testable. */
export interface Rgb {
  r: number;
  g: number;
  b: number;
}

/** Convert #rrggbb to an Rgb. Throws on anything malformed. */
export function hexToRgb(hex: string): Rgb {
  const match = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!match) throw new Error(`not a hex colour: ${hex}`);
  const value = parseInt(match[1], 16);
  return {
    r: ((value >> 16) & 0xff) / 255,
    g: ((value >> 8) & 0xff) / 255,
    b: (value & 0xff) / 255,
  };
}

/**
 * Every parameter the renderer reads. All numbers, all eased.
 *
 * Colours are kept as three separate numbers rather than an Rgb object so the
 * whole record can flow through `approachAll` unchanged.
 */
export interface VisualTargets {
  // colour
  primaryR: number;
  primaryG: number;
  primaryB: number;
  secondaryR: number;
  secondaryG: number;
  secondaryB: number;

  // orb
  displacementAmplitude: number;
  noiseSpeed: number;
  fresnelSharpness: number;
  orbOpacity: number;
  glowStrength: number;
  rotationSpeed: number;

  // rings
  ringOpacity: number;

  // the galaxy answering the AI
  networkOpacity: number;
  networkScale: number;
  networkRotationSpeed: number;
  nodeSize: number;
  skyBrightness: number;
  cameraPush: number;
}

/** Build a full target record from a compact description. */
function targets(spec: {
  primary: string;
  secondary: string;
  displacementAmplitude: number;
  noiseSpeed: number;
  fresnelSharpness: number;
  orbOpacity: number;
  glowStrength: number;
  rotationSpeed: number;
  ringOpacity: number;
  networkOpacity: number;
  networkScale: number;
  networkRotationSpeed: number;
  nodeSize: number;
  skyBrightness: number;
  cameraPush: number;
}): VisualTargets {
  const p = hexToRgb(spec.primary);
  const s = hexToRgb(spec.secondary);
  return {
    primaryR: p.r,
    primaryG: p.g,
    primaryB: p.b,
    secondaryR: s.r,
    secondaryG: s.g,
    secondaryB: s.b,
    displacementAmplitude: spec.displacementAmplitude,
    noiseSpeed: spec.noiseSpeed,
    fresnelSharpness: spec.fresnelSharpness,
    orbOpacity: spec.orbOpacity,
    glowStrength: spec.glowStrength,
    rotationSpeed: spec.rotationSpeed,
    ringOpacity: spec.ringOpacity,
    networkOpacity: spec.networkOpacity,
    networkScale: spec.networkScale,
    networkRotationSpeed: spec.networkRotationSpeed,
    nodeSize: spec.nodeSize,
    skyBrightness: spec.skyBrightness,
    cameraPush: spec.cameraPush,
  };
}

/**
 * The table. Gold is the accent (chosen over the default teal so the listening
 * state matches JARVIS's own palette).
 */
export const STATE_TABLE: Record<AiState, VisualTargets> = {
  // At rest: dim, slow, barely there. If it looks busy here, it is wrong.
  idle: targets({
    primary: "#2a6b6b",
    secondary: "#3d8f8f",
    displacementAmplitude: 0.16,
    noiseSpeed: 0.12,
    fresnelSharpness: 2.4,
    orbOpacity: 0.5,
    glowStrength: 0.28,
    rotationSpeed: 0.05,
    ringOpacity: 0.0,
    networkOpacity: 0.28,
    networkScale: 1.0,
    networkRotationSpeed: 0.015,
    nodeSize: 1.0,
    skyBrightness: 0.55,
    cameraPush: 0.0,
  }),

  // Mic requested, no audio yet. A dim ember: clearly waiting, not listening.
  arming: targets({
    primary: "#7a4a1e",
    secondary: "#a86a2a",
    displacementAmplitude: 0.22,
    noiseSpeed: 0.3,
    fresnelSharpness: 2.6,
    orbOpacity: 0.6,
    glowStrength: 0.45,
    rotationSpeed: 0.12,
    ringOpacity: 0.0,
    networkOpacity: 0.28,
    networkScale: 1.0,
    networkRotationSpeed: 0.015,
    nodeSize: 1.0,
    skyBrightness: 0.6,
    cameraPush: 0.0,
  }),

  // Recording. Bright gold — the one warm thing in a cool universe.
  listening: targets({
    primary: "#ffc247",
    secondary: "#ffe08a",
    displacementAmplitude: 0.85,
    noiseSpeed: 0.75,
    fresnelSharpness: 1.9,
    orbOpacity: 0.95,
    glowStrength: 1.15,
    rotationSpeed: 0.3,
    ringOpacity: 0.0,
    networkOpacity: 0.28,
    networkScale: 1.0,
    networkRotationSpeed: 0.015,
    nodeSize: 1.0,
    skyBrightness: 0.7,
    cameraPush: 0.0,
  }),

  // Processing. Colour flows, rings appear, the galaxy leans in.
  thinking: targets({
    primary: "#38c8c8",
    secondary: "#9a6ce0",
    displacementAmplitude: 0.42,
    noiseSpeed: 0.6,
    fresnelSharpness: 2.1,
    orbOpacity: 0.8,
    glowStrength: 0.85,
    rotationSpeed: 0.55,
    ringOpacity: 0.55,
    networkOpacity: 0.5,
    networkScale: 1.04,
    networkRotationSpeed: 0.06,
    nodeSize: 1.25,
    skyBrightness: 0.85,
    cameraPush: 0.35,
  }),

  // Replying. Driven by playback audio; the galaxy answers the AI's own voice.
  speaking: targets({
    primary: "#4fe0d8",
    secondary: "#a8f0ea",
    displacementAmplitude: 0.8,
    noiseSpeed: 0.55,
    fresnelSharpness: 2.0,
    orbOpacity: 0.9,
    glowStrength: 1.1,
    rotationSpeed: 0.28,
    ringOpacity: 0.1,
    networkOpacity: 0.65,
    networkScale: 1.05,
    networkRotationSpeed: 0.05,
    nodeSize: 1.3,
    skyBrightness: 0.95,
    cameraPush: 0.3,
  }),

  // Something broke. Red, still, sharp. No motion to distract from the message.
  error: targets({
    primary: "#e04a4a",
    secondary: "#ff7a7a",
    displacementAmplitude: 0.12,
    noiseSpeed: 0.08,
    fresnelSharpness: 3.4,
    orbOpacity: 0.85,
    glowStrength: 0.6,
    rotationSpeed: 0.02,
    ringOpacity: 0.0,
    networkOpacity: 0.12,
    networkScale: 1.0,
    networkRotationSpeed: 0.005,
    nodeSize: 1.0,
    skyBrightness: 0.5,
    cameraPush: 0.0,
  }),
};

/**
 * How quickly each parameter chases its target, per second.
 *
 * Colour moves fast enough to feel responsive; geometry moves slowly so the orb
 * swells rather than pops. The prompt's check is that a state change lands
 * within about a second.
 */
export const DEFAULT_RATES: Record<keyof VisualTargets, number> = {
  primaryR: 0.14, primaryG: 0.14, primaryB: 0.14,
  secondaryR: 0.14, secondaryG: 0.14, secondaryB: 0.14,
  displacementAmplitude: 0.1,
  noiseSpeed: 0.1,
  fresnelSharpness: 0.12,
  orbOpacity: 0.15,
  glowStrength: 0.12,
  rotationSpeed: 0.06,
  ringOpacity: 0.1,
  networkOpacity: 0.1,
  networkScale: 0.08,
  networkRotationSpeed: 0.06,
  nodeSize: 0.1,
  skyBrightness: 0.08,
  cameraPush: 0.06,
};

/** Normalise an arbitrary string to a known state, defaulting to idle. */
export function asState(value: string): AiState {
  return (STATES as string[]).includes(value) ? (value as AiState) : "idle";
}
