// Cytoscape styles for the round, directed blast-radius tree. Colours match the design tokens in globals.css.
const INK = "#f6f8fc";
const CYAN = "#5eead4";
const PINK = "#f472b6";
const VIOLET = "#818cf8";
const SEVERITY: Record<string, string> = { CRITICAL: "#fb7185", HIGH: "#fbbf24", MEDIUM: "#a5b4fc", LOW: "#8a94a9" };

const severityRules = Object.entries(SEVERITY).map(([level, colour]) => ({
  selector: `node.orb[severity = '${level}']`,
  style: { "border-color": colour, "background-color": colour, "background-opacity": level === "LOW" ? 0.16 : 0.28, "underlay-color": colour },
}));

export const RADIAL_STYLE = [
  {
    selector: "node.orb",
    style: {
      shape: "ellipse",
      // Diameter is the node's degree, mapped on a square-root scale by the element builder.
      width: "data(size)",
      height: "data(size)",
      "background-color": "#0d111a",
      "background-opacity": 0.95,
      "border-width": 2,
      "border-color": VIOLET,
      label: "data(short)",
      color: INK,
      "font-size": 11,
      "font-weight": 600,
      "text-valign": "bottom",
      "text-halign": "center",
      "text-margin-y": 7,
      "text-wrap": "ellipsis",
      "text-max-width": "92px",
      "text-outline-width": 3,
      "text-outline-color": "#04050a",
      "min-zoomed-font-size": 8,
      "underlay-opacity": 0.18,
      "underlay-padding": 7,
      "underlay-shape": "ellipse",
    },
  },
  ...severityRules,
  { selector: "node.filenode", style: { "border-width": 3, "border-color": VIOLET, "background-color": "#12182a", "font-size": 12, "underlay-color": VIOLET } },
  { selector: "node.folder", style: { "border-style": "double", "border-width": 5, "background-color": "#101733" } },
  // Hubs show their degree as a number inside the circle: the answer to "how connected is this?".
  // Their name is in the hover card, and the top hubs are also listed by name in the side panel.
  {
    selector: "node.orb[degree >= 4]",
    style: { label: "data(degree)", "text-valign": "center", "text-margin-y": 0, "font-size": 15, "font-weight": 800, color: "#f6f8fc", "min-zoomed-font-size": 0, "text-outline-width": 0 },
  },
  // Direction of leaning: callees-heavy nodes glow cyan (they fan out), caller-heavy glow pink (they are depended on).
  { selector: "node.source", style: { "underlay-color": CYAN, "underlay-opacity": 0.28 } },
  { selector: "node.sink", style: { "underlay-color": PINK, "underlay-opacity": 0.28 } },
  { selector: "node.endpoint", style: { "border-color": "#fbbf24", "border-style": "double", "border-width": 4 } },
  { selector: "node.test", style: { "border-style": "dashed" } },
  { selector: "node.onchain", style: { "border-color": PINK, "border-width": 3, "underlay-color": PINK, "underlay-opacity": 0.35 } },
  {
    selector: "node.centre",
    style: {
      width: 92,
      height: 92,
      "background-color": "#0d111a",
      "border-width": 4,
      "border-color": CYAN,
      label: "data(short)",
      color: CYAN,
      "font-size": 12,
      "font-weight": 800,
      "text-valign": "center",
      "text-halign": "center",
      "letter-spacing": 2,
      "underlay-color": CYAN,
      "underlay-opacity": 0.3,
      "underlay-padding": 14,
      "underlay-shape": "ellipse",
    },
  },
  {
    selector: "edge",
    style: {
      width: 1.6,
      "curve-style": "bezier",
      "line-color": "rgba(129,140,248,0.55)",
      "target-arrow-color": "rgba(129,140,248,0.9)",
      "target-arrow-shape": "triangle",
      "arrow-scale": 1,
      opacity: 0.85,
    },
  },
  { selector: "edge.origin", style: { "line-style": "dotted", "line-color": "rgba(94,234,212,0.35)", "target-arrow-color": "rgba(94,234,212,0.6)", width: 1.4 } },
  { selector: "edge.caller", style: { "line-style": "dashed", "line-dash-pattern": [6, 5] } },
  // Cross-links join circles that are not parent and child. Faint curves keep them in the background.
  { selector: "edge.cross", style: { "curve-style": "unbundled-bezier", "control-point-distances": [26], "control-point-weights": [0.5], width: 1.1, "line-color": "rgba(165,180,252,0.5)", "target-arrow-color": "rgba(165,180,252,0.8)", "arrow-scale": 0.8, opacity: 0.45 } },
  { selector: "edge.chain", style: { width: 3, "line-color": PINK, "target-arrow-color": PINK, opacity: 1, "z-index": 8 } },
  // The route between chain steps may cross rings, so it curves gently and sits above the tree.
  { selector: "edge.route", style: { "curve-style": "unbundled-bezier", "control-point-distances": [-38], "control-point-weights": [0.5], width: 3.4, "z-index": 11 } },
  { selector: "node.dim", style: { opacity: 0.18 } },
  { selector: "edge.dim", style: { opacity: 0.05 } },
  { selector: "node.hover", style: { "border-color": CYAN, "border-width": 4, "z-index": 10 } },
  { selector: "edge.hot", style: { "line-color": CYAN, "target-arrow-color": CYAN, width: 3, opacity: 1, "z-index": 9 } },
  { selector: "node.sim", style: { "background-color": "#d9fff4", "border-color": CYAN, "border-width": 5, color: "#04120f", "z-index": 12 } },
];
