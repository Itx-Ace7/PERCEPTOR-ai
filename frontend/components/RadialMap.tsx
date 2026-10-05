"use client";

import { useEffect, useRef, useState } from "react";
import type { Core, NodeSingular } from "cytoscape";
import { treeElements } from "@/lib/radialElements";
import { RADIAL_STYLE } from "@/lib/radialStyle";
import { IDLE, type SimState } from "@/lib/simulation";
import { applySimulation } from "@/lib/simulationEffects";
import type { Bundle } from "@/lib/types";

type Tip = { x: number; y: number; title: string; meta: string };

// How many top-degree circles keep a name visible when the whole tree is zoomed out.
const HUB_LABELS = 14;

/** Round, directed blast-radius tree: the release at the centre, call depth as rings. */
export function RadialMap({ bundle, activeId, sim = IDLE, onReady }: { bundle: Bundle; activeId?: string; sim?: SimState; onReady?: () => void }) {
  const host = useRef<HTMLDivElement>(null);
  const readyRef = useRef(onReady);
  readyRef.current = onReady;
  const cyRef = useRef<Core | null>(null);
  const [tip, setTip] = useState<Tip | null>(null);
  const [error, setError] = useState("");
  const [summary, setSummary] = useState({ shown: 0, roots: 0 });
  const key = bundle.graph.nodes.map((node) => `${node.id}:${node.severity || ""}:${node.changed ? 1 : 0}`).join("|") + bundle.graph.edges.length;

  useEffect(() => {
    let destroyed = false;
    if (!host.current) return;
    const font = getComputedStyle(document.body).fontFamily;
    (async () => {
      const cytoscape = (await import("cytoscape")).default;
      if (destroyed || !host.current) return;
      cyRef.current?.destroy();
      const built = treeElements(bundle);
      setSummary({ shown: built.shown, roots: built.roots });
      let cy: Core;
      try {
        cy = cytoscape({
          container: host.current,
          elements: built.elements,
          style: [{ selector: "node", style: { "font-family": font } }, ...(RADIAL_STYLE as never[])] as never,
          layout: { name: "preset", fit: true, padding: 56 },
          // Low enough that fit() can always show a very large tree whole.
          minZoom: 0.02,
          maxZoom: 3.2,
          wheelSensitivity: 0.16,
        });
      } catch (err) {
        if (!destroyed) setError(err instanceof Error ? err.message : "The blast map could not be drawn.");
        return;
      }
      if (destroyed) {
        cy.destroy();
        return;
      }
      setError("");
      const focus = (event: { target: NodeSingular; renderedPosition: { x: number; y: number } }) => {
        const node = event.target;
        cy.elements().removeClass("hover hot").addClass("dim");
        node.removeClass("dim").addClass("hover");
        node.neighborhood().removeClass("dim");
        node.connectedEdges().addClass("hot").removeClass("dim");
        const bounds = host.current?.getBoundingClientRect();
        setTip({
          x: Math.min(event.renderedPosition.x + 18, (bounds?.width || 640) - 250),
          y: Math.max(12, event.renderedPosition.y - 22),
          title: String(node.data("label") || node.id()),
          meta: [node.data("kind"), node.data("file"), node.data("line") ? `line ${node.data("line")}` : ""].filter(Boolean).join(" · "),
        });
      };
      const release = () => {
        cy.elements().removeClass("dim hover hot");
        setTip(null);
      };
      cy.on("mouseover", "node", focus);
      cy.on("tap", "node", focus);
      cy.on("mouseout", "node", release);
      cy.on("tap", (event) => {
        if (event.target === cy) release();
      });
      cy.on("pan zoom", () => setTip(null));
      // In a big tree the overview shrinks every label. Keep the ones that orient you readable
      // (release, files, failure chain) and let the rest appear as you zoom in.
      let frame = 0;
      const scaleLabels = () => {
        cancelAnimationFrame(frame);
        frame = requestAnimationFrame(() => {
          // Aim for ~13px on screen at any zoom. The cap is high enough for a phone-sized overview.
          const size = Math.max(11, Math.min(90, 13 / Math.max(cy.zoom(), 0.05)));
          // The best-connected circles are the ones worth naming in an overview.
          const hubIds = new Set(
            cy.nodes(".orb").not(".filenode").sort((a, b) => b.data("degree") - a.data("degree")).slice(0, HUB_LABELS).map((n) => n.id()),
          );
          cy.batch(() => {
            cy.nodes(".centre, .filenode, .onchain").style({ "font-size": size, "min-zoomed-font-size": 0, "text-max-width": `${Math.round(size * 8)}px` });
            cy.nodes(".orb").not(".filenode, .onchain").forEach((node) => {
              const degree = node.data("degree") as number;
              if (degree >= 4) return; // already labelled with its degree number
              const named = hubIds.has(node.id()) && degree >= 2;
              node.style({ "min-zoomed-font-size": named ? 0 : 8, ...(named ? { "font-size": size * 0.8 } : {}) });
            });
          });
        });
      };
      cy.on("zoom", scaleLabels);
      scaleLabels();
      cyRef.current = cy;
      readyRef.current?.();
      if (process.env.NODE_ENV !== "production") (window as unknown as { __cy?: Core }).__cy = cy;
    })();
    return () => {
      destroyed = true;
      cyRef.current?.destroy();
      cyRef.current = null;
    };
  }, [key]);

  const effect = useRef<{ stop?: () => void }>({});
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const wasPlaying = effect.current.stop !== undefined;
    applySimulation(cy, sim, effect.current);
    // When a run ends or is stopped, bring the whole tree back into view.
    if (sim.status === "idle" && wasPlaying) cy.animate({ fit: { eles: cy.elements(), padding: 56 } }, { duration: 600, easing: "ease-in-out-cubic" });
  }, [sim, key]);
  useEffect(() => () => effect.current.stop?.(), []);

  return (
    <div className="radial-stage">
      <div ref={host} className="cy" />
      {error && <p className="graph-error">{error}</p>}
      {tip && (
        <div className="graph-tip" style={{ left: tip.x, top: tip.y }}>
          <strong>{tip.title}</strong>
          <span>{tip.meta}</span>
        </div>
      )}
      <div className="graph-controls">
        <button type="button" onClick={() => cyRef.current?.animate({ fit: { eles: cyRef.current.elements(), padding: 56 }, duration: 380 })}>Fit</button>
      </div>
      <div className="graph-legend mono">
        <span><i className="orb centre" /> release</span>
        <span><i className="orb file" /> file / folder</span>
        <span><i className="orb risk" /> finding</span>
        <span><i className="orb size" /> bigger = more calls</span>
        <span><i className="orb source" /> calls others</span>
        <span><i className="orb sink" /> is called</span>
        <span><i className="arrow" /> call</span>
        <span><i className="arrow chain" /> failure chain</span>
      </div>
      <p className="radial-note mono">{summary.shown} nodes · {summary.roots} entry points · rings = call depth</p>
    </div>
  );
}
