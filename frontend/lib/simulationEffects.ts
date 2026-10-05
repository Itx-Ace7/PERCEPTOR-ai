import type { Core, NodeSingular } from "cytoscape";
import { IDLE, STEP_MS, type SimState } from "./simulation";

const FOCUS_ZOOM = 0.9;
const PULSES = 3;

type Handle = { stop: () => void };

/** Expanding ring around a node, drawn with Cytoscape's underlay so no extra elements are needed. */
function pulse(node: NodeSingular, ms: number): Handle {
  let cancelled = false;
  const started = performance.now();
  const tick = (now: number) => {
    if (cancelled || node.removed()) return;
    const t = ((now - started) % ms) / ms;
    const wave = (t * PULSES) % 1;
    node.style({ "underlay-opacity": 0.55 * (1 - wave), "underlay-padding": 8 + wave * 34 });
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
  return { stop: () => { cancelled = true; } };
}

/**
 * Plays a simulation on the map: the camera follows the chain, reached steps stay lit, the current
 * step pulses, and the route to it draws itself. Returns a function that restores the map exactly.
 */
export function applySimulation(cy: Core, sim: SimState, previous: { stop?: () => void }): void {
  previous.stop?.();
  previous.stop = undefined;
  const nodes = cy.nodes();
  const edges = cy.edges();
  const restore = () => {
    nodes.removeClass("sim reached dimmed");
    edges.removeClass("sim-route sim-faded");
    edges.style({ "line-dash-offset": 0 });
    nodes.removeStyle("underlay-opacity underlay-padding");
  };
  if (sim.status === "idle" || sim.reached.length === 0) {
    restore();
    return;
  }

  const reached = new Set(sim.reached);
  nodes.addClass("dimmed");
  nodes.filter((n) => reached.has(n.id())).removeClass("dimmed").addClass("reached");
  edges.addClass("sim-faded");
  // Route edges join consecutive reached steps; they are the path being traced.
  edges.filter((e) => reached.has(e.source().id()) && reached.has(e.target().id()) && e.hasClass("route")).removeClass("sim-faded").addClass("sim-route");

  const current = sim.current ? cy.$id(sim.current.id) : null;
  if (!current || !current.nonempty()) return;
  nodes.removeClass("sim");
  current.removeClass("dimmed").addClass("sim");
  const handle = sim.status === "running" ? pulse(current, STEP_MS) : { stop: () => undefined };

  // Draw the newest route edge from its source to this step by sliding its dash offset.
  const incoming = edges.filter((e) => e.hasClass("route") && e.target().id() === current.id());
  let drawing = true;
  const drawStart = performance.now();
  const draw = (now: number) => {
    if (!drawing || incoming.empty()) return;
    const progress = Math.min(1, (now - drawStart) / (STEP_MS * 0.6));
    incoming.style({ "line-style": "dashed", "line-dash-pattern": [1000, 1000], "line-dash-offset": 1000 * (1 - progress) });
    if (progress < 1) requestAnimationFrame(draw);
    else incoming.style({ "line-style": "solid" });
  };
  requestAnimationFrame(draw);

  cy.animate({ center: { eles: current }, zoom: Math.max(cy.zoom(), FOCUS_ZOOM) }, { duration: 650, easing: "ease-in-out-cubic" });
  previous.stop = () => {
    handle.stop();
    drawing = false;
  };
}

export { IDLE };
