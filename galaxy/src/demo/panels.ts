/**
 * The agent panels.
 *
 * One small panel per sub-agent, sitting down the right edge. A panel appears
 * when its agent has something to report, and — because the engine unprojects
 * the panel's screen position — the agent docks right beside it while working.
 *
 * The panels are the docking targets. Without a matching element on screen the
 * agent simply pulses in orbit instead, which is the documented fallback.
 */

import type { AgentSpec } from "../engine/agents/spec";
import { hexWithAlpha } from "../engine/agents/avatar";

export interface AgentPanel {
  spec: AgentSpec;
  root: HTMLDivElement;
  dot: HTMLDivElement;
  body: HTMLDivElement;
  active: boolean;
}

export class PanelLayer {
  readonly root: HTMLDivElement;
  private panels = new Map<string, AgentPanel>();
  private pulseTimers = new Map<string, number>();

  constructor(parent: HTMLElement = document.body) {
    this.root = document.createElement("div");
    this.root.className = "agent-panels";
    parent.append(this.root);
  }

  create(spec: AgentSpec): AgentPanel {
    const root = document.createElement("div");
    root.className = "agent-panel";
    root.id = spec.panelId ?? `panel-${spec.id}`;
    root.dataset.agent = spec.id;
    root.dataset.active = "false";

    const head = document.createElement("div");
    head.className = "agent-panel__head";

    const dot = document.createElement("div");
    dot.className = "agent-panel__dot";
    dot.style.background = spec.color;
    dot.style.boxShadow = `0 0 8px ${hexWithAlpha(spec.color, 0.8)}`;

    const title = document.createElement("div");
    title.className = "agent-panel__title";
    title.textContent = spec.name;
    title.style.color = spec.color;

    const body = document.createElement("div");
    body.className = "agent-panel__body";
    body.textContent = spec.specialty;

    head.append(dot, title);
    root.append(head, body);
    this.root.append(root);

    const panel: AgentPanel = { spec, root, dot, body, active: false };
    this.panels.set(spec.id, panel);
    return panel;
  }

  /** Show or hide a panel, and start or stop its dot pulse. */
  setActive(agentId: string, active: boolean, message?: string): void {
    const panel = this.panels.get(agentId);
    if (!panel) return;

    if (message !== undefined) panel.body.textContent = message;
    if (panel.active === active) return;
    panel.active = active;
    panel.root.dataset.active = String(active);

    const existing = this.pulseTimers.get(agentId);
    if (existing !== undefined) {
      window.clearInterval(existing);
      this.pulseTimers.delete(agentId);
    }

    if (active) {
      // A gentle pulse on the dot, so a glance down the column shows who's busy.
      let t = 0;
      const timer = window.setInterval(() => {
        t += 0.12;
        const glow = 0.55 + 0.45 * Math.sin(t);
        panel.dot.style.opacity = String(0.5 + glow * 0.5);
      }, 60);
      this.pulseTimers.set(agentId, timer);
    } else {
      panel.dot.style.opacity = "1";
    }
  }

  /** The panel element for an agent, or null. Used by the docking maths. */
  element(agentId: string): HTMLElement | null {
    return this.panels.get(agentId)?.root ?? null;
  }

  dispose(): void {
    for (const timer of this.pulseTimers.values()) window.clearInterval(timer);
    this.pulseTimers.clear();
    this.panels.clear();
    this.root.remove();
  }
}
