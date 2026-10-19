/**
 * Avatar generation.
 *
 * Three-step fallback so a brand-new agent always looks finished:
 *   1. an explicit image, if the spec names one
 *   2. one found by naming convention (/agents/<id>.png|.svg)
 *   3. one generated on the fly — a soft halo, a disc fading from a dark core
 *      out to the agent's accent, a thin rim, and the agent's initial
 *
 * Generated avatars mean adding an agent needs zero art.
 */

import * as THREE from "three";
import type { AgentSpec } from "./spec";

/** Draw an avatar onto a fresh canvas. */
export function generateAvatarCanvas(spec: AgentSpec, size = 160): HTMLCanvasElement {
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (!ctx) return canvas;

  const c = size / 2;
  const discRadius = size * 0.32;
  const accent = spec.color;

  // 1. Soft halo, wider than the disc — this is what makes it read as a light
  //    source rather than a sticker.
  const halo = ctx.createRadialGradient(c, c, discRadius * 0.4, c, c, size * 0.5);
  halo.addColorStop(0, hexWithAlpha(accent, 0.55));
  halo.addColorStop(0.45, hexWithAlpha(accent, 0.16));
  halo.addColorStop(1, hexWithAlpha(accent, 0));
  ctx.fillStyle = halo;
  ctx.fillRect(0, 0, size, size);

  // 2. The disc: dark at the core, the accent at the rim.
  const disc = ctx.createRadialGradient(c, c, 0, c, c, discRadius);
  disc.addColorStop(0, "#0a0f16");
  disc.addColorStop(0.62, "#0d141d");
  disc.addColorStop(1, hexWithAlpha(accent, 0.85));
  ctx.beginPath();
  ctx.arc(c, c, discRadius, 0, Math.PI * 2);
  ctx.fillStyle = disc;
  ctx.fill();

  // 3. A thin rim, brighter than the disc, to define the edge.
  ctx.beginPath();
  ctx.arc(c, c, discRadius - size * 0.006, 0, Math.PI * 2);
  ctx.strokeStyle = hexWithAlpha(accent, 0.95);
  ctx.lineWidth = Math.max(1, size * 0.012);
  ctx.stroke();

  // 4. The initial.
  const initial = (spec.name.trim()[0] || "?").toUpperCase();
  ctx.font = `600 ${Math.round(size * 0.3)}px ui-monospace, "SF Mono", Menlo, monospace`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillStyle = "#e9f2f8";
  ctx.fillText(initial, c, c + size * 0.012);

  return canvas;
}

/** #rrggbb + alpha → rgba(). Falls back to the accent if the hex is odd. */
export function hexWithAlpha(hex: string, alpha: number): string {
  const match = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!match) return `rgba(255,255,255,${alpha})`;
  const value = parseInt(match[1], 16);
  const r = (value >> 16) & 0xff;
  const g = (value >> 8) & 0xff;
  const b = value & 0xff;
  return `rgba(${r},${g},${b},${alpha})`;
}

/** A texture from the generated canvas. */
export function generateAvatarTexture(spec: AgentSpec, size = 160): THREE.CanvasTexture {
  const texture = new THREE.CanvasTexture(generateAvatarCanvas(spec, size));
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.needsUpdate = true;
  return texture;
}

/** The conventional paths to try before falling back to a generated avatar. */
export function avatarCandidates(spec: AgentSpec): string[] {
  if (spec.avatar) return [spec.avatar];
  return [`agents/${spec.id}.png`, `agents/${spec.id}.svg`];
}

/**
 * Resolve an avatar texture, trying the explicit/conventional image first and
 * generating one if nothing loads. `onReady` always fires exactly once.
 */
export function loadAvatarTexture(
  spec: AgentSpec,
  onReady: (texture: THREE.Texture) => void,
): void {
  const candidates = avatarCandidates(spec);
  let index = 0;

  const fallBackToGenerated = (): void => {
    onReady(generateAvatarTexture(spec));
  };

  const tryNext = (): void => {
    if (index >= candidates.length) {
      fallBackToGenerated();
      return;
    }
    const url = candidates[index++];
    const image = new Image();
    image.onload = () => {
      const texture = new THREE.Texture(image);
      texture.colorSpace = THREE.SRGBColorSpace;
      texture.needsUpdate = true;
      onReady(texture);
    };
    image.onerror = tryNext;
    image.src = url;
  };

  tryNext();
}
