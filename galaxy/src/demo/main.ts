/**
 * The demo page.
 *
 * Buttons for every state, plus the toggles. This exists so each layer can be
 * checked on screen before the next is built — and it is the surface the real
 * JARVIS wiring will drive later.
 *
 * Layer 4: real audio capture with synthetic fallback. The orb rides the
 * waveform of real audio when a mic or playback source is available, and
 * falls back to synthetic levels when it isn't.
 */

import { GalaxyEngine } from "../engine";
import { AudioCapture } from "../engine/audio-capture";
import { syntheticLevels, smoothLevels, ZERO_LEVELS } from "../engine/audio";
import { STATES, type AiState } from "../engine/state";

const canvas = document.getElementById("scene") as HTMLCanvasElement;
const stateName = document.getElementById("state-name")!;
const fpsLabel = document.getElementById("fps")!;
const liveRegion = document.getElementById("live-region")!;
const stateButtons = document.getElementById("states")!;
const audioToggle = document.getElementById("audio-toggle")!;
const perfToggle = document.getElementById("perf-toggle")!;
const motionToggle = document.getElementById("motion-toggle")!;
const micToggle = document.getElementById("mic-toggle")!;
const themeToggle = document.getElementById("theme-toggle")!;

const engine = new GalaxyEngine(canvas, {
  reducedMotion: window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  onPerformanceChange: (enabled) => {
    perfToggle.textContent = `performance: ${enabled ? "on" : "off"}`;
  },
});

const capture = new AudioCapture();

// -- state buttons --------------------------------------------------------

for (const state of STATES) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = state;
  button.dataset.state = state;
  button.setAttribute("aria-pressed", String(state === "idle"));
  button.setAttribute("role", "radio");
  button.tabIndex = state === "idle" ? 0 : -1;
  button.addEventListener("click", () => selectState(state));
  button.addEventListener("keydown", (e) => {
    const buttons = Array.from(stateButtons.querySelectorAll("button"));
    const idx = buttons.indexOf(button);
    if (e.key === "ArrowRight" || e.key === "ArrowDown") {
      e.preventDefault();
      const next = buttons[(idx + 1) % buttons.length];
      next.focus();
      selectState(next.dataset.state as AiState);
    } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
      e.preventDefault();
      const prev = buttons[(idx - 1 + buttons.length) % buttons.length];
      prev.focus();
      selectState(prev.dataset.state as AiState);
    }
  });
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

let useRealAudio = true;
audioToggle.addEventListener("click", () => {
  useRealAudio = !useRealAudio;
  audioToggle.textContent = `audio source: ${useRealAudio ? "real" : "synthetic"}`;
  audioToggle.setAttribute("aria-pressed", String(useRealAudio));
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

// Theme: default to OS preference, remember the choice.
const storedTheme = localStorage.getItem("galaxy-theme");
const osPrefersLight = window.matchMedia("(prefers-color-scheme: light)").matches;
let theme = storedTheme || (osPrefersLight ? "light" : "dark");
document.documentElement.dataset.theme = theme;
themeToggle.textContent = theme === "dark" ? "🌙" : "☀️";
themeToggle.setAttribute("aria-pressed", String(theme === "light"));
themeToggle.setAttribute("aria-label", `Theme: ${theme}`);
themeToggle.addEventListener("click", () => {
  theme = theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = theme;
  localStorage.setItem("galaxy-theme", theme);
  themeToggle.textContent = theme === "dark" ? "🌙" : "☀️";
  themeToggle.setAttribute("aria-pressed", String(theme === "light"));
  themeToggle.setAttribute("aria-label", `Theme: ${theme}`);
  engine.setLightMode(theme === "light" ? 1 : 0);
});

let micEnabled = true;
micToggle.addEventListener("click", () => {
  micEnabled = !micEnabled;
  micToggle.textContent = `mic: ${micEnabled ? "on" : "off"}`;
  micToggle.setAttribute("aria-pressed", String(micEnabled));
  if (useRealAudio) {
    if (micEnabled) {
      void capture.start();
    } else {
      capture.stop();
    }
  }
});

// -- JARVIS connection ----------------------------------------------------
// Poll JARVIS state files and update the galaxy. The bridge writes
// state/galaxy-state.json and state/galaxy-audio.json; we read them here.

let jarvisConnected = false;
let elapsed = 0;

async function pollJarvisState(): Promise<void> {
  try {
    const [stateRes, audioRes] = await Promise.all([
      fetch("/state/galaxy-state.json"),
      fetch("/state/galaxy-audio.json"),
    ]);
    if (!stateRes.ok || !audioRes.ok) return;

    const stateData = await stateRes.json();
    const audioData = await audioRes.json();

    engine.setState(stateData.state);
    engine.setLevels({
      voice: audioData.voice ?? 0,
      bass: audioData.bass ?? 0,
      treble: audioData.treble ?? 0,
    });

    if (!jarvisConnected) {
      jarvisConnected = true;
      liveRegion.textContent = "Connected to JARVIS";
    }
  } catch {
    // JARVIS not running or state files not available — stay in demo mode.
  }
}

// Poll every 500ms. The bridge writes at most every 500ms, so this is
// the tightest loop that doesn't waste cycles.
setInterval(pollJarvisState, 500);

// -- frame loop -----------------------------------------------------------

engine.start();

let frames = 0;
let fpsAccum = 0;

function tick(): void {
  const delta = 1 / 60;
  elapsed += delta;

  const state = engine.getState();
  const speaking = state === "speaking" || state === "thinking";

  if (useRealAudio) {
    const levels = capture.read(delta, speaking && micEnabled);
    engine.setLevels(levels);
  } else {
    // Pure synthetic — no capture at all.
    const raw = syntheticLevels(elapsed, speaking);
    engine.setLevels(smoothLevels(ZERO_LEVELS, raw));
  }

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

// Start audio capture on first user interaction (browsers require this).
const startAudio = (): void => {
  if (useRealAudio && micEnabled) {
    void capture.start();
  }
  window.removeEventListener("click", startAudio);
  window.removeEventListener("keydown", startAudio);
};
window.addEventListener("click", startAudio);
window.addEventListener("keydown", startAudio);

// Teardown for hot-reload during development: release the GL context rather
// than leaking one on every edit.
if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    engine.dispose();
    capture.stop();
  });
}
