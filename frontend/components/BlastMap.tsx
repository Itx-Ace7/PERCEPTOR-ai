"use client";

import { useEffect, useRef, useState } from "react";
import type { Core, ElementDefinition } from "cytoscape";
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
      "min-zoomed-font-size": 6,
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
      "border-color": "rgba(142,162,255,0.55)",
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
      "border-color": "#8ea2ff",
      color: "#e7ecff",
    },
  },
  {
    selector: "node.symbol",
    style: {
      width: 112,
      height: 26,
      "font-size": 10,
      "background-color": "#101820",
      "border-width": 1,
      "border-color": "#314556",
      color: "#d5e7ee",
    },
  },
  { selector: "node.symbol.endpoint", style: { "border-color": "#ffc56d", color: "#ffe7c2" } },
  { selector: "node.symbol.test", style: { "border-color": "#c4b6ff", color: "#efeaff" } },
  { selector: "node.symbol[severity = 'CRITICAL']", style: { "border-color": "#ff4d8d", "background-color": "#241018", color: "#ffd0e0" } },
  { selector: "node.symbol[severity = 'HIGH']", style: { "border-color": "#ffc56d", "background-color": "#241c10", color: "#ffe7c2" } },
  { selector: "node.symbol[severity = 'MEDIUM']", style: { "border-color": "#c4b6ff", color: "#efeaff" } },
  { selector: "node.symbol[severity = 'LOW']", style: { "border-color": "#6d7a8c" } },
  { selector: "node.file-group[severity = 'CRITICAL'], node.lone[severity = 'CRITICAL']", style: { "border-color": "#ff4d8d" } },
  { selector: "node.file-group[severity = 'HIGH'], node.lone[severity = 'HIGH']", style: { "border-color": "#ffc56d" } },
  {
    selector: "node.sim",
    style: {
      "background-color": "#d9fff4",
      "border-color": "#3ee0ff",
      "border-width": 2,
      color: "#071018",
      "z-index": 9,
    },
  },
  { selector: "node.hover", style: { "border-width": 2, "border-color": "#3ee0ff", "z-index": 8 } },
  { selector: ".dim", style: { opacity: 0.2 } },
  {
    selector: "edge",
    style: {
      width: 1.15,
      "curve-style": "bezier",
      "control-point-step-size": 48,
      "target-arrow-shape": "triangle",
      "arrow-scale": 0.75,
      "line-color": "rgba(62,224,255,0.55)",
      "target-arrow-color": "#3ee0ff",
    },
  },
  { selector: "edge[kind = 'contains']", style: { display: "none" } },
  {
    selector: "edge[kind = 'imports']",
    style: {
      display: "none",
      width: 1,
      "line-style": "dashed",
      "line-dash-pattern": [4, 5],
      "line-color": "rgba(255,45,166,0.45)",
      "target-arrow-color": "rgba(255,45,166,0.75)",
    },
  },
  { selector: "edge.hot", style: { width: 2.2, "line-color": "#3ee0ff", "target-arrow-color": "#3ee0ff", opacity: 1, "z-index": 9 } },
];

function shortName(label: string, kind?: string) {
  const leaf = (label.split(/[/\\]/).pop() || label).trim();
  const text = kind === "file" ? leaf : leaf.replace(/\.(py|js|ts|tsx|jsx|go|sql)$/i, "");
  return text.length > 22 ? `${text.slice(0, 20)}…` : text;
}

function columnsFor(count: number) {
  if (count <= 1) return 1;
  if (count <= 4) return 2;
  if (count <= 9) return 3;
  if (count <= 20) return 4;
  if (count <= 40) return 6;
  return 8;
}

const VIEW_LIMIT = 140;

function presentGraph(bundle: Bundle) {
  const nodes = bundle.graph.nodes;
  const edges = bundle.graph.edges;
  if (nodes.length <= VIEW_LIMIT) return { nodes, edges, omitted: 0 };
  const weight: Record<string, number> = { CRITICAL: 50, HIGH: 40, MEDIUM: 30, LOW: 10 };
  const chain = new Set(releaseChain(bundle).map((node) => node.id));
  const ranked = [...nodes].sort((a, b) => {
    const score = (node: (typeof nodes)[number]) =>
      (chain.has(node.id) ? 100 : 0) + (weight[node.severity || ""] || 0) + (node.kind === "endpoint" ? 8 : 0) + (node.kind === "file" ? 0 : 2);
    return score(b) - score(a);
  });
  const keep = new Set<string>();
  for (const node of ranked) {
    if (keep.size >= VIEW_LIMIT) break;
    if (chain.has(node.id) || node.severity || node.kind === "endpoint") keep.add(node.id);
  }
  for (const edge of edges) {
    if (edge.kind === "contains" && keep.has(edge.target) && keep.size < VIEW_LIMIT) keep.add(edge.source);
  }
  for (const edge of edges) {
    if (edge.kind !== "calls" || keep.size >= VIEW_LIMIT) continue;
    if (keep.has(edge.source)) keep.add(edge.target);
    if (keep.size < VIEW_LIMIT && keep.has(edge.target)) keep.add(edge.source);
  }
  if (keep.size < 24) {
    for (const node of ranked) {
      if (keep.size >= VIEW_LIMIT) break;
      keep.add(node.id);
    }
  }
  return {
    nodes: nodes.filter((node) => keep.has(node.id)),
    edges: edges.filter((edge) => keep.has(edge.source) && keep.has(edge.target)),
    omitted: nodes.length - keep.size,
  };
}

function spanElements(bundle: Bundle): ElementDefinition[] {
  const { nodes, edges } = presentGraph(bundle);
  const files = nodes.filter((node) => node.kind === "file");
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const children = new Map<string, typeof nodes>();
  for (const edge of edges) {
    if (edge.kind !== "contains") continue;
    const child = byId.get(edge.target);
    if (!child || child.kind === "file") continue;
    const list = children.get(edge.source) || [];
    list.push(child);
    children.set(edge.source, list);
  }
  const placed = new Set<string>();
  const chipW = 112;
  const chipH = 26;
  const gap = 10;
  const pad = 34;
  const cells = files
    .map((file) => {
      const kids = [...(children.get(file.id) || [])].sort((a, b) => Number(Boolean(b.severity)) - Number(Boolean(a.severity)) || a.label.localeCompare(b.label));
      const cols = Math.min(3, Math.max(1, kids.length || 1));
      const rows = Math.max(1, Math.ceil((kids.length || 1) / cols));
      const width = kids.length ? cols * chipW + (cols - 1) * gap + pad * 2 : 210;
      const height = kids.length ? rows * chipH + (rows - 1) * gap + pad * 2 + 8 : 44;
      return { file, kids, cols, width, height };
    })
    .sort((a, b) => b.kids.length - a.kids.length || a.file.label.localeCompare(b.file.label));

  const columns = columnsFor(cells.length);
  const positions = new Map<string, { x: number; y: number }>();
  let cursorX = 80;
  let cursorY = 70;
  let rowHeight = 0;
  let column = 0;
  for (const cell of cells) {
    if (column === columns) {
      column = 0;
      cursorX = 80;
      cursorY += rowHeight + 72;
      rowHeight = 0;
    }
    cell.kids.forEach((kid, index) => {
      const col = index % cell.cols;
      const row = Math.floor(index / cell.cols);
      positions.set(kid.id, {
        x: cursorX + pad + col * (chipW + gap) + chipW / 2,
        y: cursorY + pad + 6 + row * (chipH + gap) + chipH / 2,
      });
      placed.add(kid.id);
    });
    positions.set(cell.file.id, {
      x: cursorX + cell.width / 2,
      y: cursorY + (cell.kids.length ? 18 : cell.height / 2),
    });
    placed.add(cell.file.id);
    rowHeight = Math.max(rowHeight, cell.height);
    cursorX += cell.width + 64;
    column += 1;
  }

  const orphans = nodes.filter((node) => !placed.has(node.id));
  orphans.forEach((node, index) => {
    positions.set(node.id, { x: 80 + (index % 8) * 140, y: cursorY + rowHeight + 80 + Math.floor(index / 8) * 48 });
  });

  const nodeElements: ElementDefinition[] = [
    ...cells.map((cell) => ({
      data: { ...cell.file, short: shortName(cell.file.label, "file") },
      classes: cell.kids.length ? "file-group" : "lone",
      ...(cell.kids.length ? {} : { position: positions.get(cell.file.id) }),
    })),
    ...nodes
      .filter((node) => node.kind !== "file")
      .map((node) => {
        const parent = edges.find((edge) => edge.kind === "contains" && edge.target === node.id)?.source;
        const classes = ["symbol", node.kind === "endpoint" ? "endpoint" : "", node.is_test ? "test" : ""].filter(Boolean).join(" ");
        return {
          data: { ...node, short: shortName(node.label, node.kind), ...(parent && byId.has(parent) ? { parent } : {}) },
          classes,
          position: positions.get(node.id),
        };
      }),
  ];
  const visible = new Set(nodeElements.map((element) => String(element.data.id)));
  const edgeElements: ElementDefinition[] = edges
    .filter((edge) => edge.kind !== "contains" && visible.has(edge.source) && visible.has(edge.target))
    .map((edge) => ({ data: edge }));
  return [...nodeElements, ...edgeElements];
}

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
  const framed = presentGraph(bundle);
  const importsRef = useRef(showImports);
  importsRef.current = showImports;
  const chain = releaseChain(bundle);
  const counts = bundle.impact.counts || {};
  const graphKey = bundle.graph.nodes.map((node) => `${node.id}:${node.severity || ""}:${node.changed ? 1 : 0}`).join("|") + bundle.graph.edges.length;

  useEffect(() => {
    let destroyed = false;
    if (!host.current) return;
    const font = getComputedStyle(document.body).fontFamily;
    (async () => {
      const cytoscape = (await import("cytoscape")).default;
      if (destroyed || !host.current) return;
      cyRef.current?.destroy();
      let cy;
      try {
        cy = cytoscape({
          container: host.current,
          elements: spanElements(bundle),
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
      cy.fit(undefined, 36);
      cy.on("mouseover", "node", (event) => {
        const node = event.target;
        cy.elements().addClass("dim");
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
      });
      cy.on("mouseout", "node", () => {
        cy.elements().removeClass("dim hover hot");
        setTip(null);
      });
      cy.on("pan zoom", () => setTip(null));
      cyRef.current = cy;
    })();
    return () => {
      destroyed = true;
      cyRef.current?.destroy();
      cyRef.current = null;
    };
  }, [graphKey]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.edges("[kind = 'imports']").style("display", showImports ? "element" : "none");
  }, [showImports, graphKey]);

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
  }, [activeId, graphKey]);

  return (
    <div className="blast-wrap">
      <div className="blast-stage">
        <div ref={host} className="cy" />
        {graphError && <p className="graph-error">{graphError}</p>}
        {tip && (
          <div className="graph-tip" style={{ left: tip.x, top: tip.y }}>
            <strong>{tip.title}</strong>
            <span>{tip.meta}</span>
          </div>
        )}
        <div className="graph-controls">
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
      </div>
      <aside className="side">
        <p className="kicker">Blast radius</p>
        <h2>What this change touches</h2>
        <p className="muted">Each panel is a file. The symbols inside it are the functions that review touched. Cyan lines are calls. Imports stay off until you ask for them, so the map can spread out.</p>
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
