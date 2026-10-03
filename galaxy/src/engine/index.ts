/**
 * The engine: one renderer, one WebGL context, one frame loop.
 *
 * The spec is explicit that this must be a single context rather than two
 * stacked canvases — cheaper, and it avoids compositing glitches. Layers are
 * drawn in order: sky, then the star network, then the orb on top with a cleared
 * depth buffer.
 *
 * The engine owns no opinion about what state it is in. Callers push state in
 * with `setState`; the engine eases toward it.
 */

import * as THREE from "three";
import { AnimationClock, approachAll } from "./easing";
import type { AudioLevels } from "./audio";
import { Orb } from "./orb";
import { Sky } from "./sky";
import { StarNetwork } from "./network";
import { generateNetwork } from "./network/generate";
import {
  DEFAULT_RATES,
  STATE_TABLE,
  asState,
  type AiState,
  type VisualTargets,
} from "./state";

export interface EngineOptions {
  /** Accent colour override. The table already carries the palette. */
  reducedMotion?: boolean;
  /** Start with a coarser mesh and fewer nodes. */
  performance?: boolean;
  /** Called when performance mode decides to engage. */
  onPerformanceChange?: (enabled: boolean) => void;
}

/** Average frames per second below which performance mode engages. */
export const PERF_THRESHOLD_FPS = 45;
/** How long the frame rate must stay low before it engages, in seconds. */
export const PERF_SUSTAIN_SECONDS = 3;

export class GalaxyEngine {
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private orbCamera: THREE.PerspectiveCamera;
  private sky: Sky;
  private network: StarNetwork;
  private orb: Orb;
  private clock = new AnimationClock();

  private state: AiState = "idle";
  private targets: VisualTargets;
  private levels: AudioLevels = { voice: 0, bass: 0, treble: 0 };

  private running = false;
  private lastTime = 0;
  private frameHandle = 0;

  private performance = false;
  private lowFpsFor = 0;
  private onPerformanceChange?: (enabled: boolean) => void;

  reducedMotion = false;

  constructor(canvas: HTMLCanvasElement, options: EngineOptions = {}) {
    this.reducedMotion = options.reducedMotion ?? false;
    this.performance = options.performance ?? false;
    this.onPerformanceChange = options.onPerformanceChange;

    this.renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      alpha: false,
      powerPreference: "high-performance",
    });
    // Capped at 2: beyond that the cost climbs with no visible gain.
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, this.performance ? 1 : 2));
    this.renderer.setClearColor(0x05070d, 1);

    this.orbCamera = new THREE.PerspectiveCamera(45, 1, 0.1, 200);
    this.orbCamera.position.set(0, 0, 4.2);

    // Layer order matters and is enforced by renderOrder, not by insertion:
    // sky first (depth off), then the star network, then the orb on top.
    this.sky = new Sky();
    this.scene.add(this.sky.mesh);

    const layout = generateNetwork({
      seed: 1337,
      strayCount: this.performance ? 60 : 100,
      dustCount: this.performance ? 150 : 300,
    });
    this.network = new StarNetwork(layout, this.performance ? 1 : 2);
    this.scene.add(this.network.group);

    this.orb = new Orb(this.performance ? 12 : 24);
    this.scene.add(this.orb.group);

    // Each group has its own camera. The network camera is 60° FOV at 42 units
    // back; the orb camera is 45° FOV at 4.2 units. Layers control what each
    // camera sees: sky (0), network (1), orb (2).
    this.orbCamera.layers.enable(0);
    this.orbCamera.layers.enable(2);
    this.network.getCamera().layers.enable(0);
    this.network.getCamera().layers.enable(1);

    this.targets = { ...STATE_TABLE.idle };
    this.resize();
  }

  // -- public API ---------------------------------------------------------

  /** Set the state the scene eases toward. Unknown values fall back to idle. */
  setState(next: AiState | string): void {
    this.state = asState(String(next));
  }

  getState(): AiState {
    return this.state;
  }

  /** Push the current audio levels. Called every frame by the audio tap. */
  setLevels(levels: AudioLevels): void {
    this.levels = levels;
  }

  setReducedMotion(enabled: boolean): void {
    this.reducedMotion = enabled;
  }

  setLightMode(enabled: number): void {
    this.targets.lightMode = enabled;
  }

  /** Force performance mode on or off, or hand control back to the auto rule. */
  setPerformance(mode: boolean | "auto" | "on" | "off"): void {
    if (mode === "auto") {
      this.performance = false;
      this.lowFpsFor = 0;
      return;
    }
    this.applyPerformance(mode === true || mode === "on");
  }

  get isPerformance(): boolean {
    return this.performance;
  }

  resize(): void {
    const canvas = this.renderer.domElement;
    const width = canvas.clientWidth || window.innerWidth;
    const height = canvas.clientHeight || window.innerHeight;
    this.renderer.setSize(width, height, false);
    this.orbCamera.aspect = width / Math.max(1, height);
    this.orbCamera.updateProjectionMatrix();
    // The sky needs the pixel dimensions to keep its star grid square.
    this.sky.resize(width, height);
  }

  start(): void {
    if (this.running) return;
    this.running = true;
    this.lastTime = performance.now();
    this.frameHandle = requestAnimationFrame(this.frame);
  }

  stop(): void {
    this.running = false;
    if (this.frameHandle) cancelAnimationFrame(this.frameHandle);
    this.frameHandle = 0;
  }

  dispose(): void {
    this.stop();
    this.sky.dispose();
    this.network.dispose();
    this.orb.dispose();
    this.renderer.dispose();
  }

  // -- the loop -----------------------------------------------------------

  private frame = (now: number): void => {
    if (!this.running) return;

    const delta = Math.min((now - this.lastTime) / 1000, 0.1);
    this.lastTime = now;

    this.trackPerformance(delta);

    // Reduced motion slows a separate clock rather than scaling delta, so
    // toggling it never makes a phase jump.
    const elapsed = this.clock.advance(delta, this.reducedMotion);

    this.targets = approachAll(
      this.targets,
      STATE_TABLE[this.state],
      DEFAULT_RATES,
      delta,
    );

    this.render(elapsed);

    this.frameHandle = requestAnimationFrame(this.frame);
  };

  private render(elapsed: number): void {
    this.renderer.clear();

    // Update all three groups. Draw order is controlled by renderOrder:
    // sky (-1000) → network (-500) → orb (0).
    this.sky.update(elapsed, this.targets, this.levels.voice);
    this.network.update(elapsed, this.targets);
    this.orb.update({
      elapsed,
      targets: this.targets,
      levels: this.levels,
      detail: this.performance ? 12 : 24,
      showRings: this.state === "thinking" || this.targets.ringOpacity > 0.01,
    });

    // Render the network with its own camera (60° FOV, 42 units back).
    // Camera shake: almost imperceptible, only during speaking/thinking.
    const cam = this.network.getCamera();
    if (this.state === "speaking" || this.state === "thinking") {
      const shake = 0.02;
      cam.position.x += Math.sin(elapsed * 13.7) * shake;
      cam.position.y += Math.cos(elapsed * 11.3) * shake;
    }
    this.renderer.render(this.scene, cam);

    // Clear depth and render the orb on top with its own camera.
    this.renderer.clearDepth();
    this.renderer.render(this.scene, this.orbCamera);
  }

  // -- performance --------------------------------------------------------

  private trackPerformance(delta: number): void {
    if (this.performance || this.onPerformanceChange === undefined) return;

    const fps = delta > 0 ? 1 / delta : 0;
    if (fps < PERF_THRESHOLD_FPS) {
      this.lowFpsFor += delta;
      if (this.lowFpsFor >= PERF_SUSTAIN_SECONDS) {
        // Engage and stay engaged. Flapping back and forth is worse than
        // running slightly conservatively.
        this.applyPerformance(true);
      }
    } else {
      this.lowFpsFor = 0;
    }
  }

  private applyPerformance(enabled: boolean): void {
    if (this.performance === enabled) return;
    this.performance = enabled;
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, enabled ? 1 : 2));
    this.orb.setDetail(enabled ? 12 : 24);
    this.network.setPixelRatio(enabled ? 1 : 2);
    this.onPerformanceChange?.(enabled);
  }
}
