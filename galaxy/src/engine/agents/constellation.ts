/**
 * The sub-agent constellation.
 *
 * Each agent is a small glowing avatar orbiting the orb on its own tilted path,
 * with a dispatch beam, a working pulse, an expanding sonar ring, and the
 * ability to leave orbit and settle beside its panel while it works.
 *
 * Like the rest of the engine this file draws; it does not decide. Every
 * position and opacity arrives from the pure helpers in ./spec.
 */

import * as THREE from "three";
import { clamp } from "../easing";
import { LabelLayer, type AgentLabel } from "../labels";
import { generateAvatarTexture } from "./avatar";
import {
  DEFAULT_AGENTS,
  breathe,
  depthFactor,
  easeInOut,
  flareCurve,
  labelOpacity,
  orbitPosition,
  phaseFromId,
  type AgentSpec,
} from "./spec";

/** How long a dispatch beam takes to race out and back, in seconds. */
export const DISPATCH_SECONDS = 2.2;
/** How long the sonar ring expands, in seconds. */
export const RING_SECONDS = 1.1;
/** How long an agent takes to fly to its panel and back, in seconds. */
export const DOCK_IN_SECONDS = 0.9;
export const DOCK_OUT_SECONDS = 1.6;

/** Avatar scale while at rest, and the flare peak while dispatched. */
const AVATAR_SCALE = 0.16;
const FLARE_SCALE = 1.9;

interface AgentRuntime {
  spec: AgentSpec;
  group: THREE.Group;
  avatar: THREE.Mesh;
  avatarMaterial: THREE.MeshBasicMaterial;
  /** The soft additive light behind the avatar. */
  halo: THREE.Sprite;
  haloMaterial: THREE.SpriteMaterial;
  /** The steady pulsing ring shown while the agent is working. */
  workingRing: THREE.Mesh;
  workingMaterial: THREE.MeshBasicMaterial;
  /** The dispatch beam: a thick glowing line from the orb out to the agent. */
  beam: THREE.Mesh;
  beamMaterial: THREE.MeshBasicMaterial;
  /** The expanding sonar ring spawned at the flare peak. */
  ping: THREE.Mesh;
  pingMaterial: THREE.MeshBasicMaterial;
  label: AgentLabel;
  phase: number;
  working: boolean;
  /** Seconds since the last dispatch, or Infinity if never dispatched. */
  sinceDispatch: number;
  /** 0 = in orbit, 1 = fully docked beside its panel. */
  dock: number;
  /** Whether the agent is currently trying to dock. */
  docking: boolean;
  /** Current world position, so docking can blend from it. */
  position: THREE.Vector3;
}

export interface ConstellationFrame {
  elapsed: number;
  delta: number;
  /** The camera the constellation is drawn with, for screen projection. */
  camera: THREE.PerspectiveCamera;
  /** Canvas size in CSS pixels. */
  width: number;
  height: number;
  reducedMotion: boolean;
}

export class Constellation {
  readonly group = new THREE.Group();

  private agents: AgentRuntime[] = [];
  private labels: LabelLayer;
  private reducedMotion = false;
  private visible = true;

  /** Pulse waves that ripple out from the orb while it is thinking. */
  private waves: THREE.Mesh[] = [];
  private waveMaterials: THREE.MeshBasicMaterial[] = [];
  private sinceWave = 0;
  private waveStrength = 0;
  private thinking = false;

  private scratch = new THREE.Vector3();

  constructor(
    specs: AgentSpec[] = DEFAULT_AGENTS,
    labelLayer: LabelLayer = new LabelLayer(),
  ) {
    this.labels = labelLayer;
    this.group.renderOrder = 5;
    for (const spec of specs) this.addAgent(spec);
  }

  // -- construction -------------------------------------------------------

  /** Add an agent to the constellation at runtime. */
  addAgent(spec: AgentSpec): void {
    const group = new THREE.Group();
    const color = new THREE.Color(spec.color);

    // The avatar disc, textured with a generated (or loaded) image.
    const avatarMaterial = new THREE.MeshBasicMaterial({
      map: generateAvatarTexture(spec),
      transparent: true,
      depthWrite: false,
      opacity: 0,
    });
    const avatar = new THREE.Mesh(
      new THREE.PlaneGeometry(1, 1),
      avatarMaterial,
    );
    avatar.scale.setScalar(AVATAR_SCALE);
    group.add(avatar);

    // A soft additive halo behind it, so it reads as a little light source.
    const haloMaterial = new THREE.SpriteMaterial({
      map: generateAvatarTexture(spec),
      color,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      opacity: 0,
    });
    const halo = new THREE.Sprite(haloMaterial);
    halo.scale.setScalar(AVATAR_SCALE * 3.4);
    group.add(halo);

    // The steady ring shown while the agent is working.
    const workingMaterial = new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      opacity: 0,
      side: THREE.DoubleSide,
    });
    const workingRing = new THREE.Mesh(
      new THREE.RingGeometry(0.82, 1.0, 48),
      workingMaterial,
    );
    workingRing.scale.setScalar(AVATAR_SCALE * 1.9);
    group.add(workingRing);

    // The dispatch beam. A unit cylinder along +Y, oriented per dispatch.
    const beamMaterial = new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      opacity: 0,
    });
    const beam = new THREE.Mesh(
      new THREE.CylinderGeometry(0.028, 0.028, 1, 8, 1, true),
      beamMaterial,
    );
    beam.visible = false;
    this.group.add(beam);

    // The expanding sonar ring, spawned at the flare peak.
    const pingMaterial = new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      opacity: 0,
      side: THREE.DoubleSide,
    });
    const ping = new THREE.Mesh(new THREE.RingGeometry(0.9, 1.0, 64), pingMaterial);
    ping.visible = false;
    this.group.add(ping);

    const label = this.labels.create(spec);

    this.group.add(group);
    // Layer 2 only: the orb camera sees it, the distant network camera does not
    // (otherwise the agents would be re-drawn as tiny specks 42 units away).
    group.traverse((obj) => obj.layers.set(2));
    beam.layers.set(2);
    ping.layers.set(2);

    this.agents.push({
      spec,
      group,
      avatar,
      avatarMaterial,
      halo,
      haloMaterial,
      workingRing,
      workingMaterial,
      beam,
      beamMaterial,
      ping,
      pingMaterial,
      label,
      phase: phaseFromId(spec.id),
      working: false,
      sinceDispatch: Infinity,
      dock: 0,
      docking: false,
      position: new THREE.Vector3(),
    });
  }

  // -- events -------------------------------------------------------------

  /** Fire the dispatch animation for one agent. */
  dispatch(agentId: string): void {
    const agent = this.agents.find((a) => a.spec.id === agentId);
    if (!agent) return;
    agent.sinceDispatch = 0;
  }

  /** Mark an agent as actively working. */
  setWorking(agentId: string, working: boolean): void {
    const agent = this.agents.find((a) => a.spec.id === agentId);
    if (!agent || agent.working === working) return;
    agent.working = working;
    agent.docking = working;
  }

  /** Every agent id currently in the constellation. */
  ids(): string[] {
    return this.agents.map((a) => a.spec.id);
  }

  /** Hide the whole constellation (small screens). */
  setVisible(visible: boolean): void {
    this.visible = visible;
    this.group.visible = visible;
    this.labels.root.style.display = visible ? "" : "none";
  }

  // -- the frame ----------------------------------------------------------

  update(frame: ConstellationFrame): void {
    this.reducedMotion = frame.reducedMotion;
    if (!this.visible) return;

    for (const agent of this.agents) {
      this.updateAgent(agent, frame);
    }

    this.updateWaves(frame);
  }

  private updateAgent(agent: AgentRuntime, frame: ConstellationFrame): void {
    const { elapsed, delta, camera, width, height } = frame;
    const spec = agent.spec;

    // -- where it sits ------------------------------------------------------
    // Reduced motion holds the agent at its starting angle rather than
    // freezing mid-swing, which would look like a stall.
    const orbitTime = this.reducedMotion ? 0 : elapsed;
    const orbit = orbitPosition(spec.orbit, orbitTime);
    const orbitVec = this.scratch.set(orbit.x, orbit.y, orbit.z);

    // Docking: ease toward the panel's spot, then back out again.
    const target = agent.docking ? 1 : 0;
    const rate = delta / (target > agent.dock ? DOCK_IN_SECONDS : DOCK_OUT_SECONDS);
    agent.dock = clamp(agent.dock + Math.sign(target - agent.dock) * rate, 0, 1);
    if (Math.abs(target - agent.dock) < 0.001) agent.dock = target;

    const dockEase = easeInOut(agent.dock);
    if (dockEase > 0.001 && spec.panelId) {
      const dockTarget = this.panelWorldPosition(spec.panelId, camera, width, height);
      if (dockTarget) {
        orbitVec.lerp(dockTarget, dockEase);
      }
    }

    agent.position.copy(orbitVec);
    agent.group.position.copy(orbitVec);

    // -- depth, so labels fade and stack correctly --------------------------
    const depth = depthFactor(orbit, spec.orbit.radius);
    const depthOpacity = labelOpacity(depth);

    // -- breathing, plus the working pulse ---------------------------------
    const rest = breathe(elapsed, agent.phase);
    let glow = 0.55 + rest * 0.45;
    let scale = AVATAR_SCALE * (1 + rest * 0.05);

    if (agent.working) {
      // A steady pulse on top of everything else: a glance tells you who's busy.
      const pulse = 0.5 + 0.5 * Math.sin(elapsed * 3.4 + agent.phase);
      glow = Math.max(glow, 0.75 + pulse * 0.45);
      agent.workingMaterial.opacity = 0.35 + pulse * 0.4;
      agent.workingRing.scale.setScalar(AVATAR_SCALE * (1.9 + pulse * 0.28));
      agent.workingRing.quaternion.copy(camera.quaternion);
    } else {
      agent.workingMaterial.opacity = 0;
    }

    // Keep the avatar facing the camera — it is a billboard, not a disc in space.
    agent.avatar.quaternion.copy(camera.quaternion);
    agent.halo.quaternion.copy(camera.quaternion);

    // -- the dispatch flare -------------------------------------------------
    if (agent.sinceDispatch !== Infinity) {
      agent.sinceDispatch += delta;
      const t = agent.sinceDispatch / DISPATCH_SECONDS;
      if (t >= 1) {
        agent.sinceDispatch = Infinity;
        agent.beam.visible = false;
        agent.beamMaterial.opacity = 0;
        agent.ping.visible = false;
        agent.pingMaterial.opacity = 0;
      } else {
        const flare = flareCurve(t);
        glow = Math.max(glow, 0.4 + flare * 1.3);
        scale *= 1 + flare * (FLARE_SCALE - 1);

        // The beam races out and back, thickening as it peaks.
        const reach = Math.sin(t * Math.PI * 0.5);
        const outward = orbitVec.clone().multiplyScalar(Math.max(0.001, reach));
        this.orientBeam(agent.beam, new THREE.Vector3(0, 0, 0), outward);
        agent.beam.visible = true;
        agent.beamMaterial.opacity = flare * 0.85;
        agent.beam.scale.x = 1 + flare * 1.6;
        agent.beam.scale.z = 1 + flare * 1.6;

        // The sonar ping, spawned at the flare's peak.
        const pingT = (t - 0.5) / (RING_SECONDS / DISPATCH_SECONDS);
        if (pingT > 0 && pingT < 1) {
          agent.ping.visible = true;
          agent.ping.position.copy(agent.position);
          agent.ping.quaternion.copy(camera.quaternion);
          agent.ping.scale.setScalar(AVATAR_SCALE * (1.4 + pingT * 5.2));
          agent.pingMaterial.opacity = (1 - pingT) * 0.75;
        } else {
          agent.ping.visible = false;
          agent.pingMaterial.opacity = 0;
        }
      }
    }

    agent.avatarMaterial.opacity = clamp(glow, 0, 1) * depthOpacity;
    agent.haloMaterial.opacity = clamp(glow * 0.6, 0, 1) * depthOpacity;
    agent.avatar.scale.setScalar(scale);
    agent.halo.scale.setScalar(scale * 3.4);

    // -- the label ----------------------------------------------------------
    const screen = this.project(agent.position, camera, width, height);
    if (screen) {
      const labelY = screen.y + AVATAR_SCALE * height * 0.55 + 8;
      // Hide entirely while the agent is directly behind the orb (depth well
      // below the midpoint), and fade with depth everywhere else.
      const opacity = depthOpacity;
      this.labels.place(agent.label, screen.x, labelY, opacity, depth);
    }
  }

  /** Point a unit cylinder from `from` to `to`. */
  private orientBeam(beam: THREE.Mesh, from: THREE.Vector3, to: THREE.Vector3): void {
    const dir = new THREE.Vector3().subVectors(to, from);
    const length = dir.length();
    if (length < 0.0001) return;
    beam.position.copy(from).addScaledVector(dir, 0.5);
    beam.scale.y = length;
    beam.quaternion.setFromUnitVectors(
      new THREE.Vector3(0, 1, 0),
      dir.normalize(),
    );
  }

  /**
   * The world position that puts an agent beside its panel.
   *
   * Unprojects the panel's screen centre to a point in front of the camera, so
   * the agent genuinely lands next to the panel the user can see rather than at
   * a hard-coded coordinate.
   */
  private panelWorldPosition(
    panelId: string,
    camera: THREE.PerspectiveCamera,
    width: number,
    height: number,
  ): THREE.Vector3 | null {
    const panel = document.getElementById(panelId);
    if (!panel) return null;
    const rect = panel.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) return null;

    // The panel's centre, in normalised device coordinates.
    const cx = (rect.left + rect.width / 2) / width;
    const cy = (rect.top + rect.height / 2) / height;
    const ndcX = cx * 2 - 1;
    const ndcY = -(cy * 2 - 1);

    // Unproject at a depth in front of the orb, so the agent sits between the
    // camera and the orb rather than at the panel's true 3D location.
    const point = new THREE.Vector3(ndcX, ndcY, 0.5).unproject(camera);
    const dir = point.sub(camera.position).normalize();
    const distance = camera.position.length() * 0.62;
    return camera.position.clone().addScaledVector(dir, distance);
  }

  /** Project a world position to CSS pixel coordinates, or null if behind. */
  private project(
    position: THREE.Vector3,
    camera: THREE.PerspectiveCamera,
    width: number,
    height: number,
  ): { x: number; y: number } | null {
    const p = position.clone().project(camera);
    if (p.z > 1) return null;
    return {
      x: (p.x * 0.5 + 0.5) * width,
      y: (-p.y * 0.5 + 0.5) * height,
    };
  }

  // -- thinking waves -----------------------------------------------------

  /**
   * Tell the constellation whether the orb is thinking, so the ripple waves
   * fade in and out. Waves only run while this is true.
   */
  setThinking(thinking: boolean): void {
    if (thinking && this.waves.length === 0) this.buildWaves();
    this.thinking = thinking;
  }

  private buildWaves(): void {
    for (let i = 0; i < 3; i++) {
      const material = new THREE.MeshBasicMaterial({
        color: new THREE.Color("#7fe6e0"),
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
        opacity: 0,
        side: THREE.DoubleSide,
      });
      const mesh = new THREE.Mesh(new THREE.RingGeometry(0.94, 1.0, 64), material);
      mesh.rotation.x = Math.PI / 2;
      mesh.visible = false;
      this.waves.push(mesh);
      this.waveMaterials.push(material);
      this.group.add(mesh);
    }
  }

  private updateWaves(frame: ConstellationFrame): void {
    if (this.waves.length === 0) return;
    const { elapsed, delta } = frame;

    // Only advance the ripple while the orb is thinking; otherwise fade out.
    if (this.thinking) {
      this.sinceWave += delta;
      this.waveStrength = Math.min(1, this.waveStrength + delta * 1.5);
    } else {
      this.waveStrength = Math.max(0, this.waveStrength - delta * 1.5);
      if (this.waveStrength === 0) {
        for (const wave of this.waves) wave.visible = false;
        return;
      }
    }

    // One wave every 1.6 seconds, staggered so they ripple outward in sequence.
    const period = 1.6;
    for (let i = 0; i < this.waves.length; i++) {
      const age = (this.sinceWave + (i * period) / this.waves.length) % period;
      const t = age / period;
      const wave = this.waves[i];
      wave.visible = true;
      wave.position.set(0, 0, 0);
      wave.scale.setScalar(1.4 + t * 2.6);
      this.waveMaterials[i].opacity = (1 - t) * 0.16 * this.waveStrength;
      // A slow tumble so the waves do not look like flat discs.
      wave.rotation.z = elapsed * 0.12 + i;
    }
  }

  // -- teardown -----------------------------------------------------------

  dispose(): void {
    for (const agent of this.agents) {
      agent.avatar.geometry.dispose();
      agent.avatarMaterial.map?.dispose();
      agent.avatarMaterial.dispose();
      agent.haloMaterial.map?.dispose();
      agent.haloMaterial.dispose();
      agent.workingRing.geometry.dispose();
      agent.workingMaterial.dispose();
      agent.beam.geometry.dispose();
      agent.beamMaterial.dispose();
      agent.ping.geometry.dispose();
      agent.pingMaterial.dispose();
      this.labels.remove(agent.label);
    }
    for (const wave of this.waves) wave.geometry.dispose();
    for (const material of this.waveMaterials) material.dispose();
    this.agents = [];
    this.waves = [];
    this.waveMaterials = [];
    this.group.clear();
  }
}
