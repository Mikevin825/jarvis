/**
 * The orb's shaders.
 *
 * Two materials work together:
 *
 *   orb   — a wireframe icosahedron whose vertices are pushed along their normals
 *           by noise, so the mesh breathes. Drawn as lines, not faces.
 *   glow  — a larger, coarser shell drawn back-faces-only with additive blending.
 *           It reads as a halo. If it ever looks like a solid disc, the falloff
 *           has been inverted.
 */

import { NOISE_GLSL } from "./noise";

/** Vertex shader shared by the orb and its glow shell. */
export const ORB_VERTEX = /* glsl */ `
uniform float uTime;
uniform float uAmplitude;
uniform float uNoiseSpeed;
uniform float uVoice;
uniform float uBass;
uniform float uTreble;
uniform float uBassPush;

varying vec3 vNormal;
varying vec3 vViewDir;
varying float vOutward;
varying float vNoise;

${NOISE_GLSL}

void main() {
  vec3 pos = position;

  // Derive the normal from the position rather than reading a normal
  // attribute. WireframeGeometry carries only position, so relying on the
  // attribute would give every vertex a zero normal, collapsing the mesh and
  // flattening the fresnel. For a sphere centred on the origin, position IS
  // the normal, and this works for the solid shell too.
  vec3 n = normalize(pos);

  // Noise sampled at a slowly drifting position, so the surface flows rather
  // than flickering.
  vec3 sampleAt = pos * 1.35 + vec3(0.0, uTime * uNoiseSpeed, uTime * uNoiseSpeed * 0.6);
  float n1 = fbm3(sampleAt, uTreble);

  // The key to a calm orb: displacement is dominated by how much is going on.
  // A small base plus a slow breath keeps it alive at rest; audio does the rest.
  float breath = sin(uTime * 0.7) * 0.04;
  float push = sin(uTime * 2.2 + pos.y * 3.0) * uBassPush * uBass;

  float amount = 0.04
               + breath
               + uVoice * uAmplitude * 0.55
               + uBass * uAmplitude * 0.35
               + push;

  amount = clamp(amount, -0.45, 0.45);

  vec3 displaced = pos + n * n1 * amount;

  vNoise = n1;
  // The normal must be carried to the fragment stage in VIEW space. Deriving a
  // rim term from the view vector alone does not work here: the camera sits 4.2
  // units from a radius-1 sphere, so the view direction is nearly constant
  // across the surface and the rim would vanish.
  vNormal = normalize(normalMatrix * n);
  vec4 viewPos = modelViewMatrix * vec4(displaced, 1.0);
  vViewDir = normalize(-viewPos.xyz);
  vOutward = amount;

  gl_Position = projectionMatrix * viewPos;
}
`;

/**
 * The orb's fragment shader: a thin fresnel edge.
 *
 * Edges glow; the face pointing straight at the camera is nearly transparent.
 * Parts pushing outward tint toward the secondary colour, which gives the
 * surface a sense of direction as it moves.
 */
export const ORB_FRAGMENT = /* glsl */ `
uniform vec3 uPrimary;
uniform vec3 uSecondary;
uniform float uOpacity;
uniform float uFresnelSharpness;

varying vec3 vNormal;
varying vec3 vViewDir;
varying float vOutward;
varying float vNoise;

void main() {
  // Fresnel: bright where the surface turns away from the camera, transparent
  // head-on. This is what makes the mesh read as a glowing shell rather than a
  // solid ball.
  float facing = abs(dot(normalize(vNormal), normalize(vViewDir)));
  float rim = pow(1.0 - facing, uFresnelSharpness);

  vec3 colour = mix(uPrimary, uSecondary, smoothstep(0.0, 0.12, vOutward));
  colour += vNoise * 0.06;

  float alpha = rim * uOpacity;
  if (alpha < 0.01) discard;

  gl_FragColor = vec4(colour, alpha);
}
`;

/**
 * The glow shell: a halo, not a filled disc.
 *
 * Drawn with `side: BackSide` and additive blending, so only the silhouette
 * contributes. The falloff is sharp near the centre and long at the rim.
 */
export const GLOW_VERTEX = /* glsl */ `
uniform float uTime;
uniform float uAmplitude;
uniform float uNoiseSpeed;
uniform float uVoice;
uniform float uBass;
uniform float uTreble;
uniform float uScale;

varying vec3 vNormal;
varying vec3 vViewDir;

${NOISE_GLSL}

void main() {
  vec3 pos = position * uScale;
  // Same reasoning as the orb: derive from position, since the wireframe has
  // no normal attribute. (This shell is solid, so it has one — but using the
  // same rule in both places keeps them deforming identically.)
  vec3 n = normalize(position);

  vec3 sampleAt = pos * 1.1 + vec3(0.0, uTime * uNoiseSpeed * 0.8, 0.0);
  float n1 = fbm3(sampleAt, uTreble);

  float amount = 0.05 + sin(uTime * 0.6) * 0.03 + uVoice * uAmplitude * 0.35 + uBass * uAmplitude * 0.2;
  vec3 displaced = pos + n * n1 * clamp(amount, -0.4, 0.4);

  vNormal = normalize(normalMatrix * n);
  vec4 viewPos = modelViewMatrix * vec4(displaced, 1.0);
  vViewDir = normalize(-viewPos.xyz);

  gl_Position = projectionMatrix * viewPos;
}
`;

export const GLOW_FRAGMENT = /* glsl */ `
uniform vec3 uPrimary;
uniform float uStrength;

varying vec3 vNormal;
varying vec3 vViewDir;

void main() {
  float facing = abs(dot(normalize(vNormal), normalize(vViewDir)));

  // Halo, not blob: brightest at the rim, fading quickly inward. Raising the
  // facing term to a high power is what keeps the middle hollow.
  float rim = pow(facing, 3.2);
  float alpha = rim * uStrength * 0.5;
  if (alpha < 0.004) discard;

  gl_FragColor = vec4(uPrimary * (1.0 + uStrength * 0.5), alpha);
}
`;
