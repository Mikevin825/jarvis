/**
 * The star network shaders.
 *
 * Three draw calls share this file:
 *
 *   nodes    — GL_POINTS, one per star. Each star is a soft disc with a bright
 *              core, sized by distance and the current nodeSize target. Colour
 *              comes from a per-node index into a palette.
 *   links    — GL_LINES, one segment per connection. Faint, additive, and
 *              faded by distance so the network reads as depth rather than
 *              a flat web. Coloured by the average of its endpoints.
 *   dust     — GL_POINTS, tiny faint blue-grey points on a larger shell.
 *
 * All are drawn with depth testing on but depth writing off, so they
 * composite correctly with each other and with the orb on top.
 */

export const NETWORK_VERTEX = /* glsl */ `
attribute float aSize;
attribute float aPhase;
attribute float aColourIndex;

uniform float uTime;
uniform float uNodeSize;
uniform float uPixelRatio;

varying float vPhase;
varying float vDepth;
varying float vColourIndex;

void main() {
  vPhase = aPhase;
  vColourIndex = aColourIndex;

  vec4 viewPos = modelViewMatrix * vec4(position, 1.0);
  vDepth = -viewPos.z;

  // Size attenuates with distance, as real points do.
  // The 500.0 divisor makes nodes large enough to read their colour at 42 units.
  gl_PointSize = aSize * uNodeSize * uPixelRatio * (500.0 / vDepth);
  gl_PointSize = clamp(gl_PointSize, 2.0, 80.0);

  gl_Position = projectionMatrix * viewPos;
}
`;

export const NETWORK_FRAGMENT = /* glsl */ `
uniform vec3 uPrimary;
uniform float uOpacity;
uniform float uLightMode;

varying float vPhase;
varying float vDepth;
varying float vColourIndex;

// The cool palette: teal, cyan, blue, purple, green-teal, indigo, blue-teal, violet.
// Index 8 is muted blue-grey for strays.
// Colours are saturated enough to distinguish clusters at low opacity.
vec3 palette(float index) {
  if (index < 0.5) return vec3(0.10, 0.55, 0.55);   // teal
  if (index < 1.5) return vec3(0.10, 0.90, 0.90);   // cyan
  if (index < 2.5) return vec3(0.15, 0.40, 1.00);   // blue
  if (index < 3.5) return vec3(0.70, 0.25, 1.00);   // purple
  if (index < 4.5) return vec3(0.10, 0.80, 0.40);   // green-teal
  if (index < 5.5) return vec3(0.35, 0.20, 0.90);   // indigo
  if (index < 6.5) return vec3(0.15, 0.60, 0.90);   // blue-teal
  if (index < 7.5) return vec3(0.75, 0.25, 0.95);   // violet
  return vec3(0.45, 0.55, 0.65);                     // muted blue-grey (strays)
}

void main() {
  // A soft disc: bright core, gentle falloff.
  vec2 centred = gl_PointCoord - 0.5;
  float dist = length(centred);
  if (dist > 0.5) discard;

  float core = smoothstep(0.5, 0.0, dist);
  float glow = core * core;

  // Each star pulses at its own rate.
  float pulse = 0.75 + 0.25 * sin(uTime * (0.4 + vPhase * 0.8) + vPhase * 6.28);

  // Fade with distance so the network has depth.
  // Calibrated for the network camera at 42 units: nodes at 13-25 units from
  // the origin are 17-29 units from the camera, so the fade should be ~1.0
  // there and only drop for the most distant dust.
  float depthFade = clamp(1.0 - (vDepth - 17.0) / 30.0, 0.3, 1.0);

  vec3 colour = palette(vColourIndex);

  // In light mode, nodes are lighter and smaller so they don't read as ink blots.
  colour = mix(colour, colour * 0.7 + 0.3, uLightMode);

  float alpha = glow * pulse * uOpacity * depthFade;
  gl_FragColor = vec4(colour * (0.6 + glow * 0.6), alpha);
}
`;

export const LINK_VERTEX = /* glsl */ `
attribute float aColourIndexA;
attribute float aColourIndexB;

uniform float uTime;

varying float vDepth;
varying float vColourIndexA;
varying float vColourIndexB;

void main() {
  vColourIndexA = aColourIndexA;
  vColourIndexB = aColourIndexB;

  vec4 viewPos = modelViewMatrix * vec4(position, 1.0);
  vDepth = -viewPos.z;
  gl_Position = projectionMatrix * viewPos;
}
`;

export const LINK_FRAGMENT = /* glsl */ `
uniform vec3 uPrimary;
uniform float uOpacity;
uniform float uLightMode;

varying float vDepth;
varying float vColourIndexA;
varying float vColourIndexB;

vec3 palette(float index) {
  if (index < 0.5) return vec3(0.10, 0.55, 0.55);
  if (index < 1.5) return vec3(0.10, 0.90, 0.90);
  if (index < 2.5) return vec3(0.15, 0.40, 1.00);
  if (index < 3.5) return vec3(0.70, 0.25, 1.00);
  if (index < 4.5) return vec3(0.10, 0.80, 0.40);
  if (index < 5.5) return vec3(0.35, 0.20, 0.90);
  if (index < 6.5) return vec3(0.15, 0.60, 0.90);
  if (index < 7.5) return vec3(0.75, 0.25, 0.95);
  return vec3(0.45, 0.55, 0.65);
}

void main() {
  // Faint, and fainter with distance.
  float depthFade = clamp(1.0 - (vDepth - 8.0) / 40.0, 0.05, 1.0);

  // Colour by the average of the endpoints.
  vec3 colourA = palette(vColourIndexA);
  vec3 colourB = palette(vColourIndexB);
  vec3 colour = (colourA + colourB) * 0.5;

  // In light mode, links are even fainter.
  colour = mix(colour, colour * 0.5, uLightMode);

  float alpha = uOpacity * depthFade * 0.12;
  gl_FragColor = vec4(colour, alpha);
}
`;

export const DUST_VERTEX = /* glsl */ `
uniform float uTime;
uniform float uPixelRatio;

varying float vDepth;

void main() {
  vec4 viewPos = modelViewMatrix * vec4(position, 1.0);
  vDepth = -viewPos.z;

  // Dust is tiny — just a few pixels.
  gl_PointSize = 2.0 * uPixelRatio * (120.0 / vDepth);
  gl_PointSize = clamp(gl_PointSize, 1.0, 4.0);

  gl_Position = projectionMatrix * viewPos;
}
`;

export const DUST_FRAGMENT = /* glsl */ `
uniform float uOpacity;
uniform float uLightMode;

varying float vDepth;

void main() {
  vec2 centred = gl_PointCoord - 0.5;
  float dist = length(centred);
  if (dist > 0.5) discard;

  float core = smoothstep(0.5, 0.0, dist);
  float depthFade = clamp(1.0 - (vDepth - 8.0) / 60.0, 0.05, 1.0);

  // Muted blue-grey dust.
  vec3 colour = vec3(0.45, 0.55, 0.65);
  colour = mix(colour, colour * 0.5, uLightMode);

  float alpha = core * uOpacity * depthFade * 0.3;
  gl_FragColor = vec4(colour, alpha);
}
`;
