/**
 * The demo page.
 *
 * Buttons for every state, plus the toggles. This exists so each layer can be
 * checked on screen before the next is built — and it is the surface the real
 * JARVIS wiring will drive later.
 */

import { GalaxyEngine } from "../engine";
import { syntheticLevels, smoothLevels, ZERO_LEVELS, type AudioLevels } from "../engine/audio";
import { STATES, type AiState } from "../engine/state";

const canvas = document.getElementById("scene") as HTMLCanvasElement;
const stateName = document.getElementById("state-name")!;
const fpsLabel = document.getElementById("fps")!;
const liveRegion = document.getElementById("live-region")!;
const stateButtons = document.getElementById("states")!;
const audioToggle = document.getElementById("audio-toggle")!;
const perfToggle = document.getElementById("perf-toggle")!;
const motionToggle = document.getElementById("motion-toggle")!;

const engine = new GalaxyEngine(canvas, {
  reducedMotion: window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  onPerformanceChange: (enabled) => {
    perfToggle.textContent = `performance: ${enabled ? "on" : "off"}`;
  },
});

// -- state buttons --------------------------------------------------------

for (const state of STATES) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = state;
  button.dataset.state = state;
  button.setAttribute("aria-pressed", String(state === "idle"));
  button.addEventListener("click", () => selectState(state));
  stateButtons.append(button);
}

function selectState(state: AiState): void {
  engine.setState(state);
  stateName.textContent = state;
  liveRegion.textContent = `State: ${state}`;
  for (const el of stateButtons.querySelectorAll("button")) {
    el.setAttribute("aria-pressed", String((el as HTMLElement).dataset.state === state));
  }
}

// -- toggles --------------------------------------------------------------

let syntheticAudio = true;
audioToggle.addEventListener("click", () => {
  syntheticAudio = !syntheticAudio;
  audioToggle.textContent = `synthetic audio: ${syntheticAudio ? "on" : "off"}`;
  audioToggle.setAttribute("aria-pressed", String(syntheticAudio));
});

let perfMode: "auto" | "on" | "off" = "auto";
perfToggle.addEventListener("click", () => {
  perfMode = perfMode === "auto" ? "on" : perfMode === "on" ? "off" : "auto";
  engine.setPerformance(perfMode);
  perfToggle.textContent = `performance: ${perfMode}`;
});

let reducedMotion = engine.reducedMotion;
motionToggle.addEventListener("click", () => {
  reducedMotion = !reducedMotion;
  engine.setReducedMotion(reducedMotion);
  motionToggle.textContent = `reduced motion: ${reducedMotion ? "on" : "off"}`;
  motionToggle.setAttribute("aria-pressed", String(reducedMotion));
});

// -- audio ----------------------------------------------------------------
// No analyser yet (that arrives in Layer 4). Until then the synthetic envelope
// keeps the orb alive so the shape can be judged.

let levels: AudioLevels = ZERO_LEVELS;
let elapsed = 0;

// -- frame loop -----------------------------------------------------------

engine.start();

let frames = 0;
let fpsAccum = 0;

function tick(): void {
  const delta = 1 / 60;

  if (syntheticAudio) {
    const state = engine.getState();
    const speaking = state === "speaking" || state === "thinking";
    const raw = syntheticLevels(elapsed, speaking);
    levels = smoothLevels(levels, raw);
  } else {
    levels = smoothLevels(levels, ZERO_LEVELS);
  }
  engine.setLevels(levels);

  elapsed += delta;

  // Rough frame counter for the HUD.
  frames++;
  fpsAccum += delta;
  if (fpsAccum >= 0.5) {
    fpsLabel.textContent = String(Math.round(frames / fpsAccum));
    frames = 0;
    fpsAccum = 0;
  }

  requestAnimationFrame(tick);
}
requestAnimationFrame(tick);

// -- window ---------------------------------------------------------------

window.addEventListener("resize", () => engine.resize());

// Teardown for hot-reload during development: release the GL context rather
// than leaking one on every edit.
if (import.meta.hot) {
  import.meta.hot.dispose(() => engine.dispose());
}
