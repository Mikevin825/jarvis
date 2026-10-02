/**
 * The star network scene object.
 *
 * Draws the pre-computed layout: GL_POINTS for stars, GL_LINES for links.
 * Shares the orb camera — no separate camera. Draw order is controlled by
 * renderOrder: sky (-1000) → network (-500) → orb (0).
 *
 * The network is drawn between the sky and the orb, with depth testing on but
 * depth writing off, so it composites correctly with both.
 */

import * as THREE from "three";
import type { VisualTargets } from "../state";
import type { NetworkLayout } from "./generate";
import {
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

    this.nodeMaterial = new THREE.ShaderMaterial({
      vertexShader: NETWORK_VERTEX,
      fragmentShader: NETWORK_FRAGMENT,
      uniforms: {
        uTime: { value: 0 },
        uNodeSize: { value: 1.5 },
        uPixelRatio: { value: pixelRatio },
        uPrimary: { value: new THREE.Color(0x2a6b6b) },
        uOpacity: { value: 0.5 },
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
    this.linkGeometry = new THREE.BufferGeometry();
    this.linkGeometry.setAttribute(
      "position",
      new THREE.BufferAttribute(layout.positions, 3),
    );
    this.linkGeometry.setIndex(new THREE.BufferAttribute(layout.links, 1));

    this.linkMaterial = new THREE.ShaderMaterial({
      vertexShader: LINK_VERTEX,
      fragmentShader: LINK_FRAGMENT,
      uniforms: {
        uTime: { value: 0 },
        uPrimary: { value: new THREE.Color(0x2a6b6b) },
        uOpacity: { value: 0.28 },
      },
      transparent: true,
      depthWrite: false,
      depthTest: true,
      blending: THREE.AdditiveBlending,
    });

    const links = new THREE.LineSegments(this.linkGeometry, this.linkMaterial);
    links.renderOrder = -501;
    this.group.add(links);
  }

  /** Redraw for one frame. */
  update(elapsed: number, targets: VisualTargets): void {
    const u = this.nodeMaterial.uniforms;
    u.uTime.value = elapsed;
    u.uNodeSize.value = targets.nodeSize;
    u.uOpacity.value = targets.networkOpacity;
    (u.uPrimary.value as THREE.Color).setRGB(
      targets.primaryR,
      targets.primaryG,
      targets.primaryB,
    );

    const l = this.linkMaterial.uniforms;
    l.uTime.value = elapsed;
    l.uOpacity.value = targets.networkOpacity;
    (l.uPrimary.value as THREE.Color).setRGB(
      targets.primaryR,
      targets.primaryG,
      targets.primaryB,
    );

    // Slow rotation of the whole network.
    this.group.rotation.y = elapsed * targets.networkRotationSpeed;
    this.group.rotation.x = Math.sin(elapsed * 0.05) * 0.08;

    // Scale the network slightly with the state.
    const scale = targets.networkScale;
    this.group.scale.setScalar(scale);
  }

  setPixelRatio(ratio: number): void {
    this.nodeMaterial.uniforms.uPixelRatio.value = ratio;
  }

  /** Release every GPU resource. */
  dispose(): void {
    this.nodeGeometry.dispose();
    this.nodeMaterial.dispose();
    this.linkGeometry.dispose();
    this.linkMaterial.dispose();
    this.group.clear();
  }
}
