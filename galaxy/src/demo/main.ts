/**
 * The demo page.
 *
 * Buttons for every state, the toggles, and — since Tier 4/5 — the sub-agent
 * constellation: three agents orbiting the orb, each with a label that tracks
 * it on screen, a panel it docks beside while working, and dispatch beams.
 *
 * Tier 6 wiring: state and events come from JARVIS via the bridge when it is
 * running, and fall back to the demo driver when it is not. Everything is
 * exposed on `window.galaxy` for testing from the console.
 */

import { GalaxyEngine } from "../engine";
import { AudioCapture } from "../engine/audio-capture";
import { syntheticLevels, smoothLevels, ZERO_LEVELS } from "../engine/audio";
import { STATES, type AiState } from "../engine/state";
import { DEFAULT_AGENTS } from "../engine/agents/spec";
import { JarvisBridge, exposeConsoleApi } from "./bridge";
import { PanelLayer } from "./panels";

const canvas = document.getElementById("scene") as HTMLCanvasElement;
const stateName = document.getElementById("state-name")!;
const fpsLabel = document.getElementById("fps")!;
const linkLabel = document.getElementById("link")!;
const liveRegion = document.getElementById("live-region")!;
const stateButtons = document.getElementById("states")!;
const audioToggle = document.getElementById("audio-toggle")!;
const perfToggle = document.getElementById("perf-toggle")!;
const motionToggle = document.getElementById("motion-toggle")!;
const micToggle = document.getElementById("mic-toggle")!;
const themeToggle = document.getElementById("theme-toggle")!;

const panels = new PanelLayer();
for (const spec of DEFAULT_AGENTS) panels.create(spec);

const engine = new GalaxyEngine(canvas, {
  reducedMotion: window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  agents: DEFAULT_AGENTS,
  onPerformanceChange: (enabled) => {
    perfToggle.textContent = `performance: ${enabled ? "on" : "off"}`;
  },
  onConstellationVisibilityChange: (visible) => {
    if (!visible) {
      liveRegion.textContent = "Sub-agents hidden on this screen size";
    }
  },
});

exposeConsoleApi(engine);

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

// -- agent buttons --------------------------------------------------------
// One row per sub-agent: dispatch fires the beam, working toggles the dock.
// These exist so the constellation can be exercised without JARVIS running.

const agentBar = document.createElement("div");
agentBar.className = "controls__agents";

for (const spec of DEFAULT_AGENTS) {
  const wrap = document.createElement("div");
  wrap.className = "agent-control";
  wrap.style.setProperty("--agent-color", spec.color);

  const name = document.createElement("span");
  name.className = "agent-control__name";
  name.textContent = spec.name;
  name.style.color = spec.color;

  const dispatchBtn = document.createElement("button");
  dispatchBtn.type = "button";
  dispatchBtn.className = "toggle";
  dispatchBtn.textContent = "dispatch";
  dispatchBtn.addEventListener("click", () => {
    engine.dispatchAgent(spec.id);
    liveRegion.textContent = `${spec.name} dispatched`;
  });

  const workBtn = document.createElement("button");
  workBtn.type = "button";
  workBtn.className = "toggle";
  workBtn.textContent = "work";
  workBtn.setAttribute("aria-pressed", "false");
  let working = false;
  workBtn.addEventListener("click", () => {
    working = !working;
    engine.setAgentWorking(spec.id, working);
    panels.setActive(spec.id, working, working ? "Working…" : spec.specialty);
    workBtn.setAttribute("aria-pressed", String(working));
    workBtn.textContent = working ? "stop" : "work";
  });

  wrap.append(name, dispatchBtn, workBtn);
  agentBar.append(wrap);
}
document.querySelector(".controls")?.append(agentBar);

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
// The bridge polls JARVIS's state files and its agent event log. When JARVIS
// is running, it drives the scene; when it is not, the demo driver does.

const bridge = new JarvisBridge(engine, {
  onState: (state) => {
    stateName.textContent = state;
    liveRegion.textContent = `State: ${state}`;
    for (const el of stateButtons.querySelectorAll("button")) {
      el.setAttribute("aria-pressed", String((el as HTMLElement).dataset.state === state));
    }
  },
  onConnected: () => {
    linkLabel.textContent = "live";
    liveRegion.textContent = "Connected to JARVIS";
  },
  onError: (message) => {
    linkLabel.textContent = "error";
    liveRegion.textContent = message;
  },
});
bridge.start();

// Mirror panel visibility from the bridge's view of agent activity. The bridge
// sets working state on the engine; we reflect it in the panels so the docking
// target is on screen exactly when the agent wants to dock.
const originalSetWorking = engine.setAgentWorking.bind(engine);
engine.setAgentWorking = (agentId: string, working: boolean): void => {
  originalSetWorking(agentId, working);
  const spec = DEFAULT_AGENTS.find((a) => a.id === agentId);
  panels.setActive(agentId, working, working ? "Working…" : spec?.specialty);
};

// -- camera navigation ---------------------------------------------------
// Drag to rotate, scroll to zoom, R to reset, +/- to zoom, ? for help.

let camTheta = 0;
let camPhi = Math.PI / 2;
let camRadius = 4.2;
const CAM_MIN_RADIUS = 2.5;
const CAM_MAX_RADIUS = 12;
const CAM_MIN_PHI = 0.15;
const CAM_MAX_PHI = Math.PI - 0.15;

function applyCamera(): void {
  engine.setCameraOrbit(camTheta, camPhi, camRadius);
}

function resetCamera(): void {
  camTheta = 0;
  camPhi = Math.PI / 2;
  camRadius = 4.2;
  engine.resetCamera();
}

// Drag to rotate
let isDragging = false;
let dragStartX = 0;
let dragStartY = 0;

canvas.addEventListener("mousedown", (e) => {
  if (e.button === 0) {
    isDragging = true;
    dragStartX = e.clientX;
    dragStartY = e.clientY;
  }
});

window.addEventListener("mousemove", (e) => {
  if (!isDragging) return;
  const dx = e.clientX - dragStartX;
  const dy = e.clientY - dragStartY;
  camTheta -= dx * 0.005;
  camPhi = Math.max(CAM_MIN_PHI, Math.min(CAM_MAX_PHI, camPhi - dy * 0.005));
  dragStartX = e.clientX;
  dragStartY = e.clientY;
  applyCamera();
});

window.addEventListener("mouseup", () => {
  isDragging = false;
});

// Scroll to zoom
canvas.addEventListener("wheel", (e) => {
  e.preventDefault();
  camRadius = Math.max(CAM_MIN_RADIUS, Math.min(CAM_MAX_RADIUS, camRadius + e.deltaY * 0.003));
  applyCamera();
}, { passive: false });

// Touch support
let touchStartX = 0;
let touchStartY = 0;
let touchDist = 0;

canvas.addEventListener("touchstart", (e) => {
  if (e.touches.length === 1) {
    touchStartX = e.touches[0].clientX;
    touchStartY = e.touches[0].clientY;
  } else if (e.touches.length === 2) {
    const dx = e.touches[0].clientX - e.touches[1].clientX;
    const dy = e.touches[0].clientY - e.touches[1].clientY;
    touchDist = Math.sqrt(dx * dx + dy * dy);
  }
}, { passive: true });

canvas.addEventListener("touchmove", (e) => {
  e.preventDefault();
  if (e.touches.length === 1) {
    const dx = e.touches[0].clientX - touchStartX;
    const dy = e.touches[0].clientY - touchStartY;
    camTheta -= dx * 0.005;
    camPhi = Math.max(CAM_MIN_PHI, Math.min(CAM_MAX_PHI, camPhi - dy * 0.005));
    touchStartX = e.touches[0].clientX;
    touchStartY = e.touches[0].clientY;
    applyCamera();
  } else if (e.touches.length === 2) {
    const dx = e.touches[0].clientX - e.touches[1].clientX;
    const dy = e.touches[0].clientY - e.touches[1].clientY;
    const dist = Math.sqrt(dx * dx + dy * dy);
    camRadius = Math.max(CAM_MIN_RADIUS, Math.min(CAM_MAX_RADIUS, camRadius - (dist - touchDist) * 0.01));
    touchDist = dist;
    applyCamera();
  }
}, { passive: false });

// Navigation buttons
document.getElementById("nav-reset")!.addEventListener("click", resetCamera);
document.getElementById("nav-zoom-in")!.addEventListener("click", () => {
  camRadius = Math.max(CAM_MIN_RADIUS, camRadius - 0.5);
  applyCamera();
});
document.getElementById("nav-zoom-out")!.addEventListener("click", () => {
  camRadius = Math.min(CAM_MAX_RADIUS, camRadius + 0.5);
  applyCamera();
});

// Help panel
const navHelpPanel = document.getElementById("nav-help-panel")!;
document.getElementById("nav-help")!.addEventListener("click", () => {
  navHelpPanel.style.display = navHelpPanel.style.display === "none" ? "block" : "none";
});
navHelpPanel.addEventListener("click", () => {
  navHelpPanel.style.display = "none";
});

// Keyboard shortcuts
window.addEventListener("keydown", (e) => {
  if (e.target instanceof HTMLInputElement) return;
  switch (e.key) {
    case "r":
    case "R":
      resetCamera();
      break;
    case "+":
    case "=":
      camRadius = Math.max(CAM_MIN_RADIUS, camRadius - 0.5);
      applyCamera();
      break;
    case "-":
    case "_":
      camRadius = Math.min(CAM_MAX_RADIUS, camRadius + 0.5);
      applyCamera();
      break;
    case "?":
      navHelpPanel.style.display = navHelpPanel.style.display === "none" ? "block" : "none";
      break;
  }
});

// -- frame loop -----------------------------------------------------------

engine.start();

let elapsed = 0;
let frames = 0;
let fpsAccum = 0;
let lastFrameTime = performance.now();

function tick(): void {
  const now = performance.now();
  const delta = Math.min((now - lastFrameTime) / 1000, 0.1);
  lastFrameTime = now;
  elapsed += delta;

  const state = engine.getState();
  const speaking = state === "speaking" || state === "thinking";

  // The bridge owns the levels when it is connected; otherwise the demo does.
  if (!bridge.isConnected) {
    if (useRealAudio) {
      const levels = capture.read(delta, speaking && micEnabled);
      engine.setLevels(levels);
    } else {
      const raw = syntheticLevels(elapsed, speaking);
      engine.setLevels(smoothLevels(ZERO_LEVELS, raw));
    }
  }

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

// -- visibility -----------------------------------------------------------
// Pause when the tab is hidden. The clock keeps its phase, so returning does
// not make the scene jump.

document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    engine.stop();
  } else {
    lastFrameTime = performance.now();
    engine.start();
  }
});

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
    bridge.stop();
    engine.dispose();
    capture.stop();
    panels.dispose();
  });
}
