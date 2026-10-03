/**
 * The star network scene object.
 *
 * Draws the pre-computed layout: GL_POINTS for stars, GL_LINES for links,
 * GL_POINTS for dust. Has its own perspective camera (60° FOV, ~42 units back)
 * that drifts slowly, separate from the orb camera.
 *
 * The network is drawn between the sky and the orb, with depth testing on but
 * depth writing off, so it composites correctly with both.
 */

import * as THREE from "three";
import type { VisualTargets } from "../state";
import type { NetworkLayout } from "./generate";
import {
  DUST_FRAGMENT,
  DUST_VERTEX,
  LINK_FRAGMENT,
  LINK_VERTEX,
  NETWORK_FRAGMENT,
  NETWORK_VERTEX,
} from "../shaders/network";

export class StarNetwork {
  readonly group = new THREE.Group();

  private nodeGeometry: THREE.BufferGeometry;
  private nodeMaterial: THREE.ShaderMaterial;
  private linkGeometry: THREE.BufferGeometry;
  private linkMaterial: THREE.ShaderMaterial;
  private dustGeometry: THREE.BufferGeometry;
  private dustMaterial: THREE.ShaderMaterial;
  private camera: THREE.PerspectiveCamera;

  constructor(layout: NetworkLayout, pixelRatio = 1) {
    // -- nodes --------------------------------------------------------------
    this.nodeGeometry = new THREE.BufferGeometry();
    this.nodeGeometry.setAttribute(
      "position",
      new THREE.BufferAttribute(layout.positions, 3),
    );
    this.nodeGeometry.setAttribute(
      "aSize",
      new THREE.BufferAttribute(layout.sizes, 1),
    );
    this.nodeGeometry.setAttribute(
      "aPhase",
      new THREE.BufferAttribute(layout.phases, 1),
    );
    this.nodeGeometry.setAttribute(
      "aColourIndex",
      new THREE.BufferAttribute(layout.colourIndices, 1),
    );

    this.nodeMaterial = new THREE.ShaderMaterial({
      vertexShader: NETWORK_VERTEX,
      fragmentShader: NETWORK_FRAGMENT,
      uniforms: {
        uTime: { value: 0 },
        uNodeSize: { value: 1.5 },
        uPixelRatio: { value: pixelRatio },
        uPrimary: { value: new THREE.Color(0x2a6b6b) },
        uOpacity: { value: 0.5 },
        uLightMode: { value: 0 },
      },
      transparent: true,
      depthWrite: false,
      depthTest: true,
      blending: THREE.AdditiveBlending,
    });

    const nodes = new THREE.Points(this.nodeGeometry, this.nodeMaterial);
    nodes.renderOrder = -500;
    this.group.add(nodes);

    // -- links --------------------------------------------------------------
    // Each link gets its own pair of vertices so the colour indices are correct.
    // Using an index buffer would share vertices between links, making per-link
    // colours impossible.
    const linkPositions = new Float32Array(layout.linkCount * 6);
    const linkColoursA = new Float32Array(layout.linkCount * 2);
    const linkColoursB = new Float32Array(layout.linkCount * 2);
    for (let i = 0; i < layout.linkCount; i++) {
      const a = layout.links[i * 2];
      const b = layout.links[i * 2 + 1];
      linkPositions[i * 6 + 0] = layout.positions[a * 3 + 0];
      linkPositions[i * 6 + 1] = layout.positions[a * 3 + 1];
      linkPositions[i * 6 + 2] = layout.positions[a * 3 + 2];
      linkPositions[i * 6 + 3] = layout.positions[b * 3 + 0];
      linkPositions[i * 6 + 4] = layout.positions[b * 3 + 1];
      linkPositions[i * 6 + 5] = layout.positions[b * 3 + 2];
      linkColoursA[i * 2 + 0] = layout.colourIndices[a];
      linkColoursA[i * 2 + 1] = layout.colourIndices[a];
      linkColoursB[i * 2 + 0] = layout.colourIndices[b];
      linkColoursB[i * 2 + 1] = layout.colourIndices[b];
    }
    this.linkGeometry = new THREE.BufferGeometry();
    this.linkGeometry.setAttribute(
      "position",
      new THREE.BufferAttribute(linkPositions, 3),
    );
    this.linkGeometry.setAttribute(
      "aColourIndexA",
      new THREE.BufferAttribute(linkColoursA, 1),
    );
    this.linkGeometry.setAttribute(
      "aColourIndexB",
      new THREE.BufferAttribute(linkColoursB, 1),
    );

    this.linkMaterial = new THREE.ShaderMaterial({
      vertexShader: LINK_VERTEX,
      fragmentShader: LINK_FRAGMENT,
      uniforms: {
        uTime: { value: 0 },
        uPrimary: { value: new THREE.Color(0x2a6b6b) },
        uOpacity: { value: 0.28 },
        uLightMode: { value: 0 },
      },
      transparent: true,
      depthWrite: false,
      depthTest: true,
      blending: THREE.AdditiveBlending,
    });

    const links = new THREE.LineSegments(this.linkGeometry, this.linkMaterial);
    links.renderOrder = -501;
    this.group.add(links);

    // -- dust ---------------------------------------------------------------
    this.dustGeometry = new THREE.BufferGeometry();
    this.dustGeometry.setAttribute(
      "position",
      new THREE.BufferAttribute(layout.dustPositions, 3),
    );

    this.dustMaterial = new THREE.ShaderMaterial({
      vertexShader: DUST_VERTEX,
      fragmentShader: DUST_FRAGMENT,
      uniforms: {
        uTime: { value: 0 },
        uPixelRatio: { value: pixelRatio },
        uOpacity: { value: 0.28 },
        uLightMode: { value: 0 },
      },
      transparent: true,
      depthWrite: false,
      depthTest: true,
      blending: THREE.AdditiveBlending,
    });

    const dust = new THREE.Points(this.dustGeometry, this.dustMaterial);
    dust.renderOrder = -502;
    this.group.add(dust);

    // -- camera -------------------------------------------------------------
    // A wider field of view than the orb camera, positioned further back, so
    // the network reads as a vast structure the orb floats within.
    this.camera = new THREE.PerspectiveCamera(60, 1, 0.1, 200);
    this.camera.position.set(0, 0, 42);
  }

  /** Redraw for one frame. */
  update(elapsed: number, targets: VisualTargets): void {
    const u = this.nodeMaterial.uniforms;
    u.uTime.value = elapsed;
    u.uNodeSize.value = targets.nodeSize;
    u.uOpacity.value = targets.networkOpacity;
    u.uLightMode.value = targets.lightMode ? 1 : 0;
    (u.uPrimary.value as THREE.Color).setRGB(
      targets.primaryR,
      targets.primaryG,
      targets.primaryB,
    );

    const l = this.linkMaterial.uniforms;
    l.uTime.value = elapsed;
    l.uOpacity.value = targets.networkOpacity;
    l.uLightMode.value = targets.lightMode ? 1 : 0;
    (l.uPrimary.value as THREE.Color).setRGB(
      targets.primaryR,
      targets.primaryG,
      targets.primaryB,
    );

    const d = this.dustMaterial.uniforms;
    d.uTime.value = elapsed;
    d.uOpacity.value = targets.networkOpacity;
    d.uLightMode.value = targets.lightMode ? 1 : 0;

    // Slow rotation of the whole network.
    this.group.rotation.y = elapsed * targets.networkRotationSpeed;
    this.group.rotation.x = Math.sin(elapsed * 0.05) * 0.08;

    // Scale the network slightly with the state.
    const scale = targets.networkScale;
    this.group.scale.setScalar(scale);

    // Camera drift: a slow orbital sway so the network has parallax.
    const drift = 2.0;
    this.camera.position.x = Math.sin(elapsed * 0.03) * drift;
    this.camera.position.y = Math.cos(elapsed * 0.02) * drift * 0.4;
    this.camera.lookAt(0, 0, 0);
  }

  getCamera(): THREE.PerspectiveCamera {
    return this.camera;
  }

  resize(width: number, height: number): void {
    this.camera.aspect = width / Math.max(1, height);
    this.camera.updateProjectionMatrix();
  }

  setPixelRatio(ratio: number): void {
    this.nodeMaterial.uniforms.uPixelRatio.value = ratio;
    this.dustMaterial.uniforms.uPixelRatio.value = ratio;
  }

  /** Release every GPU resource. */
  dispose(): void {
    this.nodeGeometry.dispose();
    this.nodeMaterial.dispose();
    this.linkGeometry.dispose();
    this.linkMaterial.dispose();
    this.dustGeometry.dispose();
    this.dustMaterial.dispose();
    this.group.clear();
  }
}
