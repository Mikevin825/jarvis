/**
 * The star network shaders.
 *
 * Two draw calls share this file:
 *
 *   nodes    — GL_POINTS, one per star. Each star is a soft disc with a bright
 *              core, sized by distance and the current nodeSize target.
 *   links    — GL_LINES, one segment per connection. Faint, additive, and
 *              faded by distance so the network reads as depth rather than
 *              a flat web.
 *
 * Both are drawn with depth testing on but depth writing off, so they
 * composite correctly with each other and with the orb on top.
 */

export const NETWORK_VERTEX = /* glsl */ `
attribute float aSize;
attribute float aPhase;

uniform float uTime;
uniform float uNodeSize;
uniform float uPixelRatio;

varying float vPhase;
varying float vDepth;

void main() {
  vPhase = aPhase;

  vec4 viewPos = modelViewMatrix * vec4(position, 1.0);
  vDepth = -viewPos.z;

  // Size attenuates with distance, as real points do.
  gl_PointSize = aSize * uNodeSize * uPixelRatio * (120.0 / vDepth);
  gl_PointSize = clamp(gl_PointSize, 1.0, 64.0);

  gl_Position = projectionMatrix * viewPos;
}
`;

export const NETWORK_FRAGMENT = /* glsl */ `
uniform vec3 uPrimary;
uniform float uOpacity;

varying float vPhase;
varying float vDepth;

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
  float depthFade = clamp(1.0 - (vDepth - 8.0) / 30.0, 0.15, 1.0);

  float alpha = glow * pulse * uOpacity * depthFade;
  gl_FragColor = vec4(uPrimary * (0.6 + glow * 0.6), alpha);
}
`;

export const LINK_VERTEX = /* glsl */ `
uniform float uTime;

varying float vDepth;

void main() {
  vec4 viewPos = modelViewMatrix * vec4(position, 1.0);
  vDepth = -viewPos.z;
  gl_Position = projectionMatrix * viewPos;
}
`;

export const LINK_FRAGMENT = /* glsl */ `
uniform vec3 uPrimary;
uniform float uOpacity;

varying float vDepth;

void main() {
  // Faint, and fainter with distance.
  float depthFade = clamp(1.0 - (vDepth - 8.0) / 30.0, 0.1, 1.0);
  float alpha = uOpacity * depthFade * 0.6;
  gl_FragColor = vec4(uPrimary, alpha);
}
`;
