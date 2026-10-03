/**
 * The sky plane.
 *
 * A single full-screen quad. Depth testing is off and it is drawn first, so
 * everything else in the scene lands on top of it without any depth fighting.
 *
 * The mesh is deliberately not a real 3D object — it is a screen-space rectangle
 * positioned directly in front of the camera by the vertex shader, which ignores
 * the camera matrices entirely. That is cheaper than a large sphere and gives an
 * exact full-screen fit at any aspect ratio.
 */

import * as THREE from "three";
import type { VisualTargets } from "./state";
import { SKY_FRAGMENT, SKY_VERTEX } from "./shaders/sky";

export class Sky {
  readonly mesh: THREE.Mesh;
  private material: THREE.ShaderMaterial;
  private width = 1;
  private height = 1;

  constructor() {
    this.material = new THREE.ShaderMaterial({
      vertexShader: SKY_VERTEX,
      fragmentShader: SKY_FRAGMENT,
      uniforms: {
        uTime: { value: 0 },
        uResolution: { value: new THREE.Vector2(1, 1) },
        uAspect: { value: 1 },
        uPrimary: { value: new THREE.Color(0x2a6b6b) },
        uBrightness: { value: 0.55 },
        uBloom: { value: 0.5 },
        uLightMode: { value: 0 },
      },
      depthTest: false,
      depthWrite: false,
      // The quad is always in front; nothing should cull it.
      side: THREE.DoubleSide,
    });

    // A plain 2x2 plane. The vertex shader discards its position and writes clip
    // space directly, so the geometry only needs to cover the screen.
    const geometry = new THREE.PlaneGeometry(2, 2);
    this.mesh = new THREE.Mesh(geometry, this.material);
    // Drawn before everything, and never occluded.
    this.mesh.renderOrder = -1000;
    this.mesh.frustumCulled = false;
  }

  resize(width: number, height: number): void {
    this.width = Math.max(1, width);
    this.height = Math.max(1, height);
    (this.material.uniforms.uResolution.value as THREE.Vector2).set(
      this.width,
      this.height,
    );
    this.material.uniforms.uAspect.value = this.width / this.height;
  }

  update(elapsed: number, targets: VisualTargets, voiceLevel: number): void {
    const u = this.material.uniforms;
    u.uTime.value = elapsed;
    u.uBrightness.value = targets.skyBrightness;
    u.uLightMode.value = targets.lightMode ? 1 : 0;
    // The bloom breathes with the voice, so the sky answers the AI too.
    u.uBloom.value = 0.45 + targets.skyBrightness * 0.4 + voiceLevel * 0.5;
    (u.uPrimary.value as THREE.Color).setRGB(
      targets.primaryR,
      targets.primaryG,
      targets.primaryB,
    );
  }

  dispose(): void {
    this.mesh.geometry.dispose();
    this.material.dispose();
  }
}
