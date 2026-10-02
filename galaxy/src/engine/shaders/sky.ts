/**
 * The sky.
 *
 * A full-screen quad drawn first, with depth testing off, so everything else
 * lands on top of it. Three things live here:
 *
 *   nebula   three layers of fractal value noise, drifting at a glacial pace,
 *            each faded in with a soft threshold so they read as wisps rather
 *            than fog
 *   stars    two layers — a fine field of pinpoints and a sparser set of larger
 *            soft stars — each twinkling at its own rate
 *   bloom    soft radial falloffs in the orb's current colour, sitting behind
 *            the centre, brightening with the voice
 *
 * The star grid is made square in screen space by passing the aspect ratio in.
 * Without that, stars stretch into little dashes on tall or wide windows.
 */

import { NOISE_GLSL } from "./noise";

export const SKY_VERTEX = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = vec4(position.xy, 0.0, 1.0);
}
`;

export const SKY_FRAGMENT = /* glsl */ `
precision highp float;

uniform float uTime;
uniform vec2  uResolution;
uniform float uAspect;
uniform vec3  uPrimary;
uniform float uBrightness;
uniform float uBloom;

varying vec2 vUv;

${NOISE_GLSL}

// -- value noise on a 2D grid, for the nebula --------------------------------
float hash21(vec2 p) {
  p = fract(p * vec2(123.34, 456.21));
  p += dot(p, p + 45.32);
  return fract(p.x * p.y);
}

float valueNoise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  // Smoothstep interpolation, so the field has no visible grid.
  vec2 u = f * f * (3.0 - 2.0 * f);
  float a = hash21(i);
  float b = hash21(i + vec2(1.0, 0.0));
  float c = hash21(i + vec2(0.0, 1.0));
  float d = hash21(i + vec2(1.0, 1.0));
  return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}

// Five octaves, each rotated so the layers do not share a grid direction.
float fractal(vec2 p, float rot) {
  float total = 0.0;
  float amplitude = 0.5;
  mat2 spin = mat2(cos(rot), -sin(rot), sin(rot), cos(rot));
  for (int i = 0; i < 5; i++) {
    total += valueNoise(p) * amplitude;
    p = spin * p * 2.03;
    amplitude *= 0.5;
  }
  return total;
}

// One nebula layer, faded in softly so it reads as a wisp rather than fog.
vec3 nebulaLayer(vec2 uv, vec3 tint, float scale, float speed, float threshold, float phase) {
  vec2 p = uv * scale;
  p += vec2(uTime * speed, uTime * speed * 0.6);
  float n = fractal(p, 0.6 + phase);

  // Soft threshold: everything below the cut falls away smoothly.
  float wisp = smoothstep(threshold, threshold + 0.35, n);
  return tint * wisp;
}

// -- stars -------------------------------------------------------------------
// A hashed grid, made square by dividing x by the aspect ratio.
vec3 starLayer(vec2 uv, float density, float size, float twinkleSpeed, float seed) {
  vec2 p = vec2(uv.x * uAspect, uv.y) * density;
  vec2 cell = floor(p);
  vec2 local = fract(p) - 0.5;

  float h = hash21(cell + seed);
  // Only some cells carry a star.
  if (h < 0.82) return vec3(0.0);

  // Jitter the star within its cell so the grid is not obvious.
  vec2 offset = (vec2(hash21(cell + seed + 1.0), hash21(cell + seed + 2.0)) - 0.5) * 0.7;
  float d = length(local - offset);

  // A TIGHT falloff is essential. A gentle one spreads the glow to the cell
  // boundary, and because adjacent cells then all show a soft edge, the grid
  // itself becomes visible as a lattice of squares. A star is a point.
  float radius = size * 0.075;
  float brightness = smoothstep(radius, 0.0, d);
  brightness *= brightness;

  // Each star twinkles at its own rate and phase.
  float phase = hash21(cell + seed + 3.0) * 6.283;
  float twinkle = 0.72 + 0.28 * sin(uTime * twinkleSpeed * (0.5 + h) + phase);

  return vec3(brightness * twinkle);
}

void main() {
  // Centre-origin coordinates, y from -1..1.
  vec2 uv = (vUv - 0.5) * 2.0;
  float radius = length(uv);

  // -- base: near-black navy, darker toward the edges ------------------------
  vec3 colour = mix(vec3(0.008, 0.014, 0.030), vec3(0.020, 0.030, 0.055), 1.0 - radius);

  // -- nebula ----------------------------------------------------------------
  vec2 nuv = vec2(uv.x * uAspect, uv.y);
  colour += nebulaLayer(nuv, vec3(0.05, 0.16, 0.15), 2.1, 0.004, 0.52, 0.0) * uBrightness;
  colour += nebulaLayer(nuv, vec3(0.11, 0.06, 0.17), 1.7, 0.003, 0.55, 1.7) * uBrightness;
  colour += nebulaLayer(nuv, vec3(0.04, 0.08, 0.18), 2.6, 0.005, 0.50, 3.1) * uBrightness;

  // -- bloom behind the orb --------------------------------------------------
  // A few soft radial falloffs in the orb's colour, with a tiny pale core.
  float core = exp(-radius * 7.0);
  float wide = exp(-radius * 2.1);
  colour += uPrimary * (core * 0.22 + wide * 0.07) * uBloom;

  float pinpoint = exp(-radius * 26.0);
  colour += vec3(0.55, 0.85, 0.95) * pinpoint * 0.10 * uBloom;

  // -- stars -----------------------------------------------------------------
  colour += starLayer(uv, 90.0, 0.9, 1.1, 11.0) * 0.75 * uBrightness;
  colour += starLayer(uv, 26.0, 1.6, 0.6, 47.0) * 0.55 * uBrightness;

  // -- vignette --------------------------------------------------------------
  colour *= 1.0 - smoothstep(0.75, 1.65, radius) * 0.75;

  gl_FragColor = vec4(colour, 1.0);
}
`;
