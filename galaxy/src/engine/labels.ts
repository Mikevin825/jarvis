/**
 * The label layer.
 *
 * Ordinary HTML text for the sub-agents, positioned each frame to follow its
 * avatar's spot on screen. Kept as DOM rather than drawn into the canvas
 * because text belongs to the browser: it stays crisp at any pixel ratio, it is
 * selectable and hoverable, and a screen reader can read it.
 *
 * The layer itself is click-through; only the labels themselves take pointer
 * events, so clicking anywhere else still reaches the scene.
 */

import type { AgentSpec } from "./agents/spec";

export interface AgentLabel {
  root: HTMLDivElement;
  name: HTMLElement;
  specialty: HTMLElement;
  /** False until the first real position has been computed. */
  revealed: boolean;
}

export class LabelLayer {
  readonly root: HTMLDivElement;

  constructor(parent: HTMLElement = document.body) {
    this.root = document.createElement("div");
    this.root.className = "labels";
    this.root.setAttribute("aria-hidden", "true");
    parent.append(this.root);
  }

  create(spec: AgentSpec): AgentLabel {
    const root = document.createElement("div");
    root.className = "label";
    root.dataset.agent = spec.id;
    // Hidden until positioned, so nothing flashes in the corner on load.
    root.style.opacity = "0";

    const name = document.createElement("div");
    name.className = "label__name";
    name.textContent = spec.name;
    name.style.color = spec.color;

    const specialty = document.createElement("div");
    specialty.className = "label__specialty";
    specialty.textContent = spec.specialty;

    root.append(name, specialty);
    this.root.append(root);

    return { root, name, specialty, revealed: false };
  }

  /**
   * Place a label under a screen position.
   *
   * `depth` is 0 (far) .. 1 (near): it drives both opacity and stacking, so a
   * near agent's name sits over a far one's.
   */
  place(
    label: AgentLabel,
    x: number,
    y: number,
    opacity: number,
    depth: number,
  ): void {
    if (!label.revealed) {
      label.revealed = true;
      label.root.style.transform = `translate(-50%, 0) translate(${x}px, ${y}px)`;
      // One frame at zero opacity to settle, then let the caller fade it in.
      requestAnimationFrame(() => {
        label.root.style.opacity = String(opacity);
      });
      label.root.style.zIndex = String(1000 + Math.round(depth * 500));
      return;
    }

    label.root.style.transform = `translate(-50%, 0) translate(${x}px, ${y}px)`;
    label.root.style.opacity = String(opacity);
    label.root.style.zIndex = String(1000 + Math.round(depth * 500));
  }

  remove(label: AgentLabel): void {
    label.root.remove();
  }

  dispose(): void {
    this.root.remove();
  }
}
