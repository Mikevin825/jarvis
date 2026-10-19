/**
 * The moon — a small celestial body that orbits the core while JARVIS thinks,
 * and docks beside it when JARVIS speaks.
 *
 * The moon is a visual metaphor for the "answer" being formed: it circles
 * while thinking, then settles into place when the answer arrives.
 */

import * as THREE from "three";
import { clamp } from "./easing";

/** Smooth 0..1 ramp so the moon arrives without a corner in its path. */
function easeInOut(t: number): number {
  const c = clamp(t, 0, 1);
  return c * c * (3 - 2 * c);
}

/** How long the moon takes to dock or undock, in seconds. */
const DOCK_SECONDS = 0.8;

/** Orbit radius and speed while thinking. */
const ORBIT_RADIUS = 2.8;
const ORBIT_SPEED = 0.35;

/** Docked position relative to the orb center. */
const DOCK_POSITION = new THREE.Vector3(2.2, 1.2, 0);

export interface MoonFrame {
  elapsed: number;
  delta: number;
  /** Whether the moon should be orbiting (thinking) or docked (speaking). */
  thinking: boolean;
  reducedMotion: boolean;
}

export class Moon {
  readonly group = new THREE.Group();

  private moon: THREE.Mesh;
  private moonMaterial: THREE.MeshBasicMaterial;
  private glow: THREE.Sprite;
  private glowMaterial: THREE.SpriteMaterial;
  private ring: THREE.Mesh;
  private ringMaterial: THREE.MeshBasicMaterial;

  /** 0 = orbiting, 1 = docked. */
  private dock = 0;
  private orbitAngle = 0;

  constructor() {
    // The moon itself — a small pale sphere, self-lit so it never goes dark
    this.moonMaterial = new THREE.MeshBasicMaterial({
      color: 0xd8d8e0,
    });
    this.moon = new THREE.Mesh(
      new THREE.SphereGeometry(0.18, 24, 24),
      this.moonMaterial,
    );
    this.group.add(this.moon);

    // A soft glow around the moon
    this.glowMaterial = new THREE.SpriteMaterial({
      color: 0xccccdd,
      transparent: true,
      opacity: 0.25,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    this.glow = new THREE.Sprite(this.glowMaterial);
    this.glow.scale.setScalar(0.8);
    this.group.add(this.glow);

    // A subtle ring that appears when docked
    this.ringMaterial = new THREE.MeshBasicMaterial({
      color: 0x8888aa,
      transparent: true,
      opacity: 0,
      side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    this.ring = new THREE.Mesh(
      new THREE.RingGeometry(0.28, 0.32, 48),
      this.ringMaterial,
    );
    this.ring.rotation.x = Math.PI / 2;
    this.group.add(this.ring);

    this.group.renderOrder = 3;
    this.group.traverse((obj) => obj.layers.set(2));
  }

  update(frame: MoonFrame): void {
    const { elapsed, delta, thinking, reducedMotion } = frame;

    // Advance orbit angle
    if (!reducedMotion) {
      this.orbitAngle += delta * ORBIT_SPEED;
    }

    // Ease dock toward target
    const target = thinking ? 0 : 1;
    const rate = delta / DOCK_SECONDS;
    this.dock = clamp(this.dock + Math.sign(target - this.dock) * rate, 0, 1);
    if (Math.abs(target - this.dock) < 0.001) this.dock = target;

    const dockEase = easeInOut(this.dock);

    // Orbit position
    const orbitX = Math.cos(this.orbitAngle) * ORBIT_RADIUS;
    const orbitZ = Math.sin(this.orbitAngle) * ORBIT_RADIUS;
    const orbitY = Math.sin(this.orbitAngle * 0.5) * 0.4;

    // Blend between orbit and dock
    const x = orbitX * (1 - dockEase) + DOCK_POSITION.x * dockEase;
    const y = orbitY * (1 - dockEase) + DOCK_POSITION.y * dockEase;
    const z = orbitZ * (1 - dockEase) + DOCK_POSITION.z * dockEase;

    this.group.position.set(x, y, z);

    // The moon rotates slowly
    this.moon.rotation.y = elapsed * 0.2;

    // Glow pulses gently while thinking, steadies when docked
    const pulse = thinking
      ? 0.2 + 0.1 * Math.sin(elapsed * 2.5)
      : 0.35;
    this.glowMaterial.opacity = pulse;

    // Ring fades in when docked
    this.ringMaterial.opacity = dockEase * 0.4;
    this.ring.scale.setScalar(1 + dockEase * 0.3);

    // Moon brightens slightly when docked
    const brightness = 0.85 + dockEase * 0.15;
    this.moonMaterial.color.setScalar(brightness);
  }

  dispose(): void {
    this.moon.geometry.dispose();
    this.moonMaterial.dispose();
    this.glowMaterial.dispose();
    this.ring.geometry.dispose();
    this.ringMaterial.dispose();
    this.group.clear();
  }
}
