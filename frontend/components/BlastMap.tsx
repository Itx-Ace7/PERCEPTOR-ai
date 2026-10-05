"use client";

import { useEffect, useRef, useState } from "react";
import type { Core } from "cytoscape";
import { RadialMap } from "@/components/RadialMap";
import { presentGraph, spanElements } from "@/lib/blastLayout";
import { releaseChain } from "@/lib/release";
import type { Bundle } from "@/lib/types";

const STYLE = [
  {
    selector: "node",
    style: {
      label: "data(short)",
      "font-size": 11,
      "font-weight": 560,
      color: "#d7e4ee",
      "text-valign": "center",
      "text-halign": "center",
      "text-wrap": "ellipsis",
      "text-max-width": "108px",
      "text-outline-width": 0,
      "background-opacity": 1,
      "underlay-opacity": 0,
      shape: "round-rectangle",
      "min-zoomed-font-size": 7,
    },
  },
  {
    selector: "node.file-group",
    style: {
      "text-valign": "top",
      "text-halign": "center",
      "text-margin-y": 8,
      "font-size": 12,
      color: "#d5defc",
      "text-max-width": "160px",
      shape: "round-rectangle",
      "background-color": "#0c1018",
      "background-opacity": 0.94,
      "border-width": 1,
      "border-color": "rgba(129,140,248,0.55)",
      padding: "28px",
    },
  },
  {
    selector: "node.lone",
    style: {
      width: "label",
      height: 32,
      padding: "12px",
      "text-max-width": "140px",
      "background-color": "#10141f",
      "border-width": 1,
      "border-color": "#818cf8",
      color: "#e7ecff",
    },
  },
  {
    selector: "node.symbol",
    style: {
      width: 128,
      height: 30,
      "font-size": 12,
      "text-max-width": "116px",
      "background-color": "#101820",
      "border-width": 1,
      "border-color": "#314556",
      color: "#d5e7ee",
    },
  },
  { selector: "node.symbol.endpoint", style: { "border-color": "#fbbf24", color: "#ffe7c2" } },
  { selector: "node.symbol.test", style: { "border-color": "#a5b4fc", color: "#efeaff" } },
  { selector: "node.symbol[severity = 'CRITICAL']", style: { "border-color": "#fb7185", "background-color": "#241018", color: "#ffd0e0" } },
  { selector: "node.symbol[severity = 'HIGH']", style: { "border-color": "#fbbf24", "background-color": "#241c10", color: "#ffe7c2" } },
  { selector: "node.symbol[severity = 'MEDIUM']", style: { "border-color": "#a5b4fc", color: "#efeaff" } },
  { selector: "node.symbol[severity = 'LOW']", style: { "border-color": "#6d7a8c" } },
  { selector: "node.file-group[severity = 'CRITICAL'], node.lone[severity = 'CRITICAL']", style: { "border-color": "#fb7185" } },
  { selector: "node.file-group[severity = 'HIGH'], node.lone[severity = 'HIGH']", style: { "border-color": "#fbbf24" } },
  {
    selector: "node.sim",
    style: {
      "background-color": "#d9fff4",
      "border-color": "#5eead4",
      "border-width": 2,
      color: "#071018",
      "z-index": 9,
    },
  },
  { selector: "node.hover", style: { "border-width": 2, "border-color": "#5eead4", "z-index": 8 } },
  { selector: "node.dim", style: { opacity: 0.22 } },
  { selector: "edge.dim", style: { opacity: 0.04 } },
  {
    selector: "edge",
    style: {
      width: 1,
      // Taxi routing keeps parallel calls orderly instead of a tangle of curves.
      "curve-style": "bezier",
      "control-point-step-size": 36,
      "target-arrow-shape": "triangle",
      "arrow-scale": 0.7,
      // Faint by default: with hundreds of calls the picture is the nodes, not the wires.
      opacity: 0.18,
      "line-color": "rgba(94,234,212,1)",
      "target-arrow-color": "#5eead4",
    },
  },
  { selector: "edge.chain", style: { opacity: 0.95, width: 2, "line-color": "#f472b6", "target-arrow-color": "#f472b6", "z-index": 7 } },
  { selector: "edge[kind = 'contains']", style: { display: "none" } },
  {
    selector: "edge[kind = 'imports']",
    style: {
      display: "none",
      width: 1,
      "line-style": "dashed",
      "line-dash-pattern": [4, 5],
      "line-color": "rgba(244,114,182,0.45)",
      "target-arrow-color": "rgba(244,114,182,0.75)",
    },
  },
  { selector: "edge.quiet", style: { display: "none" } },
  { selector: "edge.hot", style: { display: "element", width: 2.2, "line-color": "#5eead4", "target-arrow-color": "#5eead4", opacity: 1, "z-index": 9 } },
  { selector: "edge.chain.hot", style: { "line-color": "#f472b6", "target-arrow-color": "#f472b6" } },
];

const DENSE_CALLS = 60;

export function BlastMap({
  bundle,
  activeId,
}: {
  bundle: Bundle;
  activeId?: string;
}) {
  const host = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const [tip, setTip] = useState<{ x: number; y: number; title: string; meta: string } | null>(null);
  const [showImports, setShowImports] = useState(false);
  const [graphError, setGraphError] = useState("");
  // The round directed tree is the default view; the boxed per-file map stays one click away.
  const [mode, setMode] = useState<"tree" | "boxed">("tree");
  const framed = presentGraph(bundle);
  const importsRef = useRef(showImports);
  importsRef.current = showImports;
  // A few calls read fine as lines. Hundreds become a hairball, so start with the chain only.
  const callCount = framed.edges.filter((edge) => edge.kind === "calls").length;
  const [showCalls, setShowCalls] = useState(callCount <= DENSE_CALLS);
  const callsRef = useRef(showCalls);
  callsRef.current = showCalls;
  const chain = releaseChain(bundle);
  const counts = bundle.impact.counts || {};
  const graphKey = bundle.graph.nodes.map((node) => `${node.id}:${node.severity || ""}:${node.changed ? 1 : 0}`).join("|") + bundle.graph.edges.length;

  useEffect(() => {
    let destroyed = false;
    if (mode !== "boxed" || !host.current) return;
    const font = getComputedStyle(document.body).fontFamily;
    (async () => {
      const cytoscape = (await import("cytoscape")).default;
      if (destroyed || !host.current) return;
      cyRef.current?.destroy();
      let cy;
      try {
        cy = cytoscape({
          container: host.current,
          elements: spanElements(bundle, host.current.clientWidth / Math.max(1, host.current.clientHeight)),
          style: [{ selector: "node", style: { "font-family": font } }, ...(STYLE as never[])] as never,
          layout: { name: "preset", fit: true, padding: 36 },
          minZoom: 0.05,
          maxZoom: 2.6,
          wheelSensitivity: 0.14,
        });
      } catch (err) {
        if (!destroyed) setGraphError(err instanceof Error ? err.message : "The blast map could not be drawn.");
        return;
      }
      if (destroyed) {
        cy.destroy();
        return;
      }
      setGraphError("");
      cy.edges("[kind = 'imports']").style("display", importsRef.current ? "element" : "none");
      // Light up the failure chain: its edges are the story, the rest is context.
      const onChain = new Set(chain.map((step) => step.id));
      cy.edges().forEach((edge) => {
        if (onChain.has(edge.source().id()) && onChain.has(edge.target().id())) edge.addClass("chain");
      });
      cy.edges("[kind = 'calls']").not(".chain").toggleClass("quiet", !callsRef.current);
      cy.fit(undefined, 36);
      const focusNode = (event: { target: import("cytoscape").NodeSingular; renderedPosition: { x: number; y: number } }) => {
        const node = event.target;
        cy.elements().removeClass("hover hot").addClass("dim");
        node.removeClass("dim").addClass("hover");
        node.neighborhood().removeClass("dim");
        node.connectedEdges().addClass("hot").removeClass("dim");
        const kind = String(node.data("kind") || "symbol");
        const file = String(node.data("file") || "");
        const line = node.data("line");
        const bounds = host.current?.getBoundingClientRect();
        const x = Math.min(event.renderedPosition.x + 16, (bounds?.width || 640) - 240);
        const y = Math.max(12, event.renderedPosition.y - 18);
        setTip({
          x,
          y,
          title: String(node.data("label") || node.id()),
          meta: [kind, file, line ? `line ${line}` : ""].filter(Boolean).join(" · "),
        });
      };
      cy.on("mouseover", "node", focusNode);
      // Touch has no hover, so a tap on a node gives the same focus a mouse gets.
      cy.on("tap", "node", focusNode);
      const clearFocus = () => {
        cy.elements().removeClass("dim hover hot");
        setTip(null);
      };
      cy.on("mouseout", "node", clearFocus);
      // Touch screens never send "mouse out", so tapping empty space must also release the focus.
      cy.on("tap", (event) => {
        if (event.target === cy) clearFocus();
      });
      // Keep file names readable when the whole map is zoomed out: the label grows as the
      // map shrinks, so the overview shows which files matter and detail appears on zoom.
      let frame = 0;
      const scaleFileLabels = () => {
        cancelAnimationFrame(frame);
        frame = requestAnimationFrame(() => {
          const size = Math.max(12, Math.min(34, 13 / Math.max(cy.zoom(), 0.05)));
          cy.batch(() => cy.nodes(".file-group, .lone").style("font-size", size));
        });
      };
      cy.on("zoom", scaleFileLabels);
      scaleFileLabels();
      cy.on("pan zoom", () => setTip(null));
      cyRef.current = cy;
      // Development-only handle so the layout can be measured in a real browser.
      if (process.env.NODE_ENV !== "production") (window as unknown as { __cy?: Core }).__cy = cy;
    })();
    return () => {
      destroyed = true;
      cyRef.current?.destroy();
      cyRef.current = null;
    };
  }, [graphKey, mode]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.edges("[kind = 'imports']").style("display", showImports ? "element" : "none");
  }, [showImports, graphKey, mode]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.edges("[kind = 'calls']").not(".chain").toggleClass("quiet", !showCalls);
  }, [showCalls, graphKey, mode]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.nodes().removeClass("sim");
    if (activeId) {
      const node = cy.$id(activeId);
      if (!node.nonempty()) return;
      node.addClass("sim");
      try {
        cy.animate({ center: { eles: node }, duration: 420 });
      } catch {
        cy.center(node);
      }
    }
  }, [activeId, graphKey, mode]);

  return (
    <div className="blast-wrap">
      <div className="blast-stage">
        <div className="mode-switch" role="tablist" aria-label="Map style">
          <button type="button" role="tab" aria-selected={mode === "tree"} className={mode === "tree" ? "on" : ""} onClick={() => setMode("tree")}>Tree</button>
          <button type="button" role="tab" aria-selected={mode === "boxed"} className={mode === "boxed" ? "on" : ""} onClick={() => setMode("boxed")}>Boxed</button>
        </div>
        {mode === "tree" && <RadialMap bundle={bundle} activeId={activeId} />}
        {mode === "boxed" && (
          <>
            <div ref={host} className="cy" />
            {graphError && <p className="graph-error">{graphError}</p>}
            {tip && (
              <div className="graph-tip" style={{ left: tip.x, top: tip.y }}>
                <strong>{tip.title}</strong>
                <span>{tip.meta}</span>
              </div>
            )}
            <div className="graph-controls">
              <button type="button" className={showCalls ? "on" : ""} onClick={() => setShowCalls((value) => !value)}>
                {showCalls ? "Calls on" : `Show calls (${callCount})`}
              </button>
              <button type="button" className={showImports ? "on" : ""} onClick={() => setShowImports((value) => !value)}>
                {showImports ? "Imports on" : "Show imports"}
              </button>
              <button type="button" onClick={() => cyRef.current?.fit(undefined, 36)}>Fit</button>
            </div>
            <div className="graph-legend mono">
              <span><i className="file" /> file</span>
              <span><i className="fn" /> symbol</span>
              <span><i className="risk" /> finding</span>
              <span><i className="call" /> call</span>
            </div>
          </>
        )}
      </div>
      <aside className="side">
        <p className="kicker">Blast radius</p>
        <h2>What this change touches</h2>
        <p className="muted">
          {mode === "tree"
            ? "The release sits at the centre. Each ring is one step further along the calls, and arrows point the way a call goes. Pink marks the failure chain. Hover or tap a circle to see only its connections."
            : "Each panel is a file. The symbols inside it are the functions that review touched. Cyan lines are calls. Imports stay off until you ask for them, so the map can spread out."}
        </p>
        <div className="stat-grid">
          {[
            ["changed_files", "Files"],
            ["changed_symbols", "Symbols"],
            ["affected_symbols", "Affected"],
            ["affected_apis", "APIs"],
            ["affected_tests", "Tests"],
            ["regression_paths", "Chains"],
          ].map(([key, label]) => (
            <div className="stat" key={key}>
              <b>{counts[key] ?? 0}</b>
              <span>{label}</span>
            </div>
          ))}
        </div>
        <p className="kicker">Failure chain</p>
        <div className="chain">
          {chain.map((node) => (
            <div key={node.id} className={`step ${node.id === activeId ? "on" : ""}`}>
              <strong>{node.label}</strong>
              <div className="muted">{node.reason}</div>
            </div>
          ))}
          {chain.length === 0 && <p className="muted">The chain appears once impact analysis finishes.</p>}
        </div>
        {(framed.omitted > 0 || bundle.graph.truncated) && (
          <p className="quiet">
            Showing {framed.nodes.length} nodes around the findings
            {bundle.graph.total_nodes ? `. The full graph has ${bundle.graph.total_nodes} nodes` : ""}.
          </p>
        )}
      </aside>
    </div>
  );
}
