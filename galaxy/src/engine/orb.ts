/**
 * The orb, its glow shell and its orbital rings.
 *
 * This file draws. It does not decide anything: every number it uses arrives
 * already eased, already clamped, already computed by the pure modules. That
 * separation is what lets the maths be tested without a GPU.
 */

import * as THREE from "three";
import type { VisualTargets } from "./state";
import { GLOW_FRAGMENT, GLOW_VERTEX, ORB_FRAGMENT, ORB_VERTEX } from "./shaders/orb";

export interface OrbFrame {
  elapsed: number;
  targets: VisualTargets;
  levels: { voice: number; bass: number; treble: number };
  /** Detail level for the icosahedron; lowered by performance mode. */
  detail: number;
  /** Whether the rings should be drawn at all this frame. */
  showRings: boolean;
}

export class Orb {
  readonly group = new THREE.Group();

  private orbMesh: THREE.LineSegments;
  private orbMaterial: THREE.ShaderMaterial;
  private glowMesh: THREE.Mesh;
  private glowMaterial: THREE.ShaderMaterial;
  private rings: THREE.LineLoop[] = [];
  private ringMaterial: THREE.LineBasicMaterial;
  private currentDetail: number;

  constructor(detail = 24) {
    this.currentDetail = detail;

    // -- the wireframe mesh -------------------------------------------------
    const geometry = new THREE.IcosahedronGeometry(1, detail);

    this.orbMaterial = new THREE.ShaderMaterial({
      vertexShader: ORB_VERTEX,
      fragmentShader: ORB_FRAGMENT,
      uniforms: {
        uTime: { value: 0 },
        uAmplitude: { value: 0.16 },
        uNoiseSpeed: { value: 0.12 },
        uVoice: { value: 0 },
        uBass: { value: 0 },
        uTreble: { value: 0 },
        uBassPush: { value: 0.04 },
        uPrimary: { value: new THREE.Color(0x2a6b6b) },
        uSecondary: { value: new THREE.Color(0x3d8f8f) },
        uOpacity: { value: 0.5 },
        uFresnelSharpness: { value: 2.4 },
      },
      transparent: true,
      depthWrite: false,
      // Drawn as lines so the mesh reads as a wireframe rather than a surface.
      wireframe: true,
    });

    this.orbMesh = new THREE.LineSegments(
      new THREE.WireframeGeometry(geometry),
      this.orbMaterial,
    );
    geometry.dispose();
    this.group.add(this.orbMesh);

    // -- the glow shell -----------------------------------------------------
    const glowGeometry = new THREE.IcosahedronGeometry(1, Math.max(2, Math.floor(detail / 3)));
    this.glowMaterial = new THREE.ShaderMaterial({
      vertexShader: GLOW_VERTEX,
      fragmentShader: GLOW_FRAGMENT,
      uniforms: {
        uTime: { value: 0 },
        uAmplitude: { value: 0.16 },
        uNoiseSpeed: { value: 0.12 },
        uVoice: { value: 0 },
        uBass: { value: 0 },
        uTreble: { value: 0 },
        uScale: { value: 1.3 },
        uPrimary: { value: new THREE.Color(0x2a6b6b) },
        uStrength: { value: 0.28 },
      },
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      // Back faces only: the halo comes from the silhouette.
      side: THREE.BackSide,
    });
    this.glowMesh = new THREE.Mesh(glowGeometry, this.glowMaterial);
    this.group.add(this.glowMesh);

    // -- the rings ----------------------------------------------------------
    // Three thin orbits, each tilted differently and turning at its own rate.
    // They are invisible until the thinking state fades them in.
    this.ringMaterial = new THREE.LineBasicMaterial({
      color: new THREE.Color(0x7fe6e0),
      transparent: true,
      opacity: 0,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });

    const radii = [1.55, 1.65, 1.75];
    const tilts = [
      { x: 0.4, y: 0.2, z: 0.1 },
      { x: -0.3, y: 0.9, z: -0.2 },
      { x: 0.1, y: -0.5, z: 0.7 },
    ];
    for (let i = 0; i < radii.length; i++) {
      const points: THREE.Vector3[] = [];
      const segments = 128;
      for (let s = 0; s <= segments; s++) {
        const a = (s / segments) * Math.PI * 2;
        points.push(new THREE.Vector3(Math.cos(a) * radii[i], 0, Math.sin(a) * radii[i]));
      }
      const ring = new THREE.LineLoop(
        new THREE.BufferGeometry().setFromPoints(points),
        this.ringMaterial,
      );
      ring.rotation.set(tilts[i].x, tilts[i].y, tilts[i].z);
      this.rings.push(ring);
      this.group.add(ring);
    }
  }

  /** Redraw for one frame. */
  update(frame: OrbFrame): void {
    const { elapsed, targets: t, levels } = frame;

    const primary = new THREE.Color(t.primaryR, t.primaryG, t.primaryB);
    const secondary = new THREE.Color(t.secondaryR, t.secondaryG, t.secondaryB);

    // Orb
    const u = this.orbMaterial.uniforms;
    u.uTime.value = elapsed;
    u.uAmplitude.value = t.displacementAmplitude;
    u.uNoiseSpeed.value = t.noiseSpeed;
    u.uVoice.value = levels.voice;
    u.uBass.value = levels.bass;
    u.uTreble.value = levels.treble;
    u.uPrimary.value.copy(primary);
    u.uSecondary.value.copy(secondary);
    u.uOpacity.value = t.orbOpacity;
    u.uFresnelSharpness.value = t.fresnelSharpness;

    // Glow
    const g = this.glowMaterial.uniforms;
    g.uTime.value = elapsed;
    g.uAmplitude.value = t.displacementAmplitude;
    g.uNoiseSpeed.value = t.noiseSpeed;
    g.uVoice.value = levels.voice;
    g.uBass.value = levels.bass;
    g.uTreble.value = levels.treble;
    g.uPrimary.value.copy(primary);
    g.uStrength.value = t.glowStrength;

    // Slow rotation, and a scale that swells with the voice.
    this.group.rotation.y += t.rotationSpeed * 0.01;
    this.group.rotation.x = Math.sin(elapsed * 0.13) * 0.12;

    const swell = 1 + levels.voice * 0.06 + levels.bass * 0.04;
    this.orbMesh.scale.setScalar(swell);
    this.glowMesh.scale.setScalar(swell);

    // Rings fade in only while thinking.
    this.ringMaterial.opacity = frame.showRings ? t.ringOpacity : 0;
    for (let i = 0; i < this.rings.length; i++) {
      this.rings[i].rotation.y += (0.12 + i * 0.07) * (0.4 + t.rotationSpeed);
      this.rings[i].rotation.z += 0.03 * (0.4 + t.rotationSpeed);
      this.rings[i].scale.setScalar(swell);
    }
  }

  /**
   * Swap the icosahedron for a coarser one.
   *
   * Used by performance mode. Rebuilds rather than mutates, because three.js
   * geometries are immutable in the ways that matter here.
   */
  setDetail(detail: number): void {
    if (detail === this.currentDetail) return;
    this.currentDetail = detail;

    const geometry = new THREE.IcosahedronGeometry(1, detail);
    const next = new THREE.WireframeGeometry(geometry);
    geometry.dispose();

    this.orbMesh.geometry.dispose();
    this.orbMesh.geometry = next;

    const glowGeometry = new THREE.IcosahedronGeometry(1, Math.max(2, Math.floor(detail / 3)));
    this.glowMesh.geometry.dispose();
    this.glowMesh.geometry = glowGeometry;
  }

  /** Release every GPU resource. Browsers cap live WebGL contexts. */
  dispose(): void {
    this.orbMesh.geometry.dispose();
    this.orbMaterial.dispose();
    this.glowMesh.geometry.dispose();
    this.glowMaterial.dispose();
    for (const ring of this.rings) {
      ring.geometry.dispose();
    }
    this.ringMaterial.dispose();
    this.group.clear();
  }
}
