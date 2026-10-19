/**
 * The JARVIS event bridge.
 *
 * Connects the galaxy to what JARVIS is actually doing. Two paths:
 *
 *   1. State polling — the bridge writes state/galaxy-state.json and
 *      state/galaxy-audio.json, and we read them. This carries the orb's
 *      conversational state and its audio levels.
 *
 *   2. An event log — JARVIS appends agent events (dispatch, working) to
 *      state/galaxy-events.json, and we tail it. This carries the
 *      constellation's activity.
 *
 * Exposed on `window.galaxy` so every function can be driven by hand from the
 * browser console, which is how the wiring gets tested.
 */

import type { GalaxyEngine } from "../engine";
import type { AgentSpec } from "../engine/agents/spec";

export interface GalaxyEvent {
  /** Monotonic id, so the reader can tell what it has already seen. */
  seq: number;
  /** ISO timestamp. */
  at: string;
  type: "state" | "dispatch" | "working" | "idle" | "add-agent";
  /** Present for agent events. */
  agent?: string;
  /** Present for state events. */
  state?: string;
  /** Present for working events. */
  working?: boolean;
  /** Present for add-agent events. */
  spec?: AgentSpec;
}

export interface BridgeOptions {
  /** How often to poll the state files, in ms. */
  stateIntervalMs?: number;
  /** How often to read the event log, in ms. */
  eventIntervalMs?: number;
  /** Called whenever a new state is read. */
  onState?: (state: string) => void;
  /** Called when the connection to JARVIS is first established. */
  onConnected?: () => void;
  /** Called on a read error, so the UI can show it. */
  onError?: (message: string) => void;
}

export class JarvisBridge {
  private engine: GalaxyEngine;
  private options: BridgeOptions;
  private stateTimer = 0;
  private eventTimer = 0;
  private lastSeq = -1;
  private connected = false;
  private stopped = false;

  constructor(engine: GalaxyEngine, options: BridgeOptions = {}) {
    this.engine = engine;
    this.options = options;
  }

  start(): void {
    this.stopped = false;
    const stateMs = this.options.stateIntervalMs ?? 500;
    const eventMs = this.options.eventIntervalMs ?? 400;

    void this.pollState();
    void this.pollEvents();
    this.stateTimer = window.setInterval(() => void this.pollState(), stateMs);
    this.eventTimer = window.setInterval(() => void this.pollEvents(), eventMs);
  }

  stop(): void {
    this.stopped = true;
    window.clearInterval(this.stateTimer);
    window.clearInterval(this.eventTimer);
  }

  get isConnected(): boolean {
    return this.connected;
  }

  // -- state --------------------------------------------------------------

  private async pollState(): Promise<void> {
    if (this.stopped) return;
    try {
      const res = await fetch("/state/galaxy-state.json", { cache: "no-store" });
      if (!res.ok) return;
      const data = await res.json();

      if (typeof data.state === "string") {
        this.engine.setState(data.state);
        this.options.onState?.(data.state);
      }

      try {
        const audioRes = await fetch("/state/galaxy-audio.json", { cache: "no-store" });
        if (audioRes.ok) {
          const audio = await audioRes.json();
          this.engine.setLevels({
            voice: Number(audio.voice) || 0,
            bass: Number(audio.bass) || 0,
            treble: Number(audio.treble) || 0,
          });
        }
      } catch {
        // Audio file missing — the demo's synthetic levels take over.
      }

      if (!this.connected) {
        this.connected = true;
        this.options.onConnected?.();
      }
    } catch {
      // JARVIS is not running. Stay quiet; the demo driver keeps the scene alive.
    }
  }

  // -- events -------------------------------------------------------------

  private async pollEvents(): Promise<void> {
    if (this.stopped) return;
    try {
      const res = await fetch("/state/galaxy-events.json", { cache: "no-store" });
      if (!res.ok) return;
      const data = await res.json();
      const events: GalaxyEvent[] = Array.isArray(data) ? data : data.events ?? [];

      for (const event of events) {
        if (typeof event.seq !== "number" || event.seq <= this.lastSeq) continue;
        this.lastSeq = event.seq;
        this.apply(event);
      }
    } catch {
      // No event log yet — nothing to do.
    }
  }

  /** Apply one event to the scene. */
  private apply(event: GalaxyEvent): void {
    switch (event.type) {
      case "state":
        if (event.state) this.engine.setState(event.state);
        break;
      case "dispatch":
        if (event.agent) this.engine.dispatchAgent(event.agent);
        break;
      case "working":
        if (event.agent) this.engine.setAgentWorking(event.agent, event.working ?? true);
        break;
      case "idle":
        // Everything back to rest.
        for (const id of this.engine.agentIds()) {
          this.engine.setAgentWorking(id, false);
        }
        break;
      case "add-agent":
        if (event.spec) this.engine.addAgent(event.spec);
        break;
      default:
        break;
    }
  }
}

/**
 * Expose the engine's controls globally so the whole system can be exercised
 * from the console:
 *
 *   galaxy.state("listening")
 *   galaxy.dispatch("scout")
 *   galaxy.working("board", true)
 *   galaxy.agents()          → ["scout", "board", "mindmap"]
 *   galaxy.addAgent({...})   → grows the constellation at runtime
 */
export function exposeConsoleApi(engine: GalaxyEngine): void {
  const api = {
    state: (name: string) => engine.setState(name),
    dispatch: (agent: string) => engine.dispatchAgent(agent),
    working: (agent: string, on = true) => engine.setAgentWorking(agent, on),
    agents: () => engine.agentIds(),
    addAgent: (spec: AgentSpec) => engine.addAgent(spec),
    performance: (mode: boolean | "auto" | "on" | "off") => engine.setPerformance(mode),
    reducedMotion: (on: boolean) => engine.setReducedMotion(on),
  };
  (window as unknown as { galaxy: typeof api }).galaxy = api;
}
