import type { ElementDefinition } from "cytoscape";
import { layoutRadial } from "./radialLayout";
import { buildTree, CENTER_ID, GROUP_PREFIX } from "./radialTree";
import { releaseChain } from "./release";
import type { Bundle, GraphNode } from "./types";

export const TREE_DEPTH = 3;
// Enough entry points to show the real shape of a repository, not a token sample.
const MAX_ROOTS = 160;
const MAX_CROSS_LINKS = 220;
const MIN_SIZE = 30;
const MAX_SIZE = 84;

/** Circle diameter grows with how connected a node is, on a square-root scale so hubs stand out without swamping the rest. */
export function sizeForDegree(degree: number, peak: number): number {
  if (degree <= 0 || peak <= 0) return MIN_SIZE;
  return Math.round(MIN_SIZE + (MAX_SIZE - MIN_SIZE) * Math.sqrt(Math.min(degree, peak) / peak));
}
const SEVERITY_RANK: Record<string, number> = { CRITICAL: 4, HIGH: 3, MEDIUM: 2, LOW: 1 };

/** Where the release starts: changed code first, then the failure chain, then the riskiest symbols. */
export function pickRoots(bundle: Bundle): string[] {
  const symbols = bundle.graph.nodes.filter((node) => node.kind !== "file");
  const byRisk = (a: GraphNode, b: GraphNode) => (SEVERITY_RANK[b.severity || ""] || 0) - (SEVERITY_RANK[a.severity || ""] || 0);
  const degree = new Map<string, number>();
  for (const edge of bundle.graph.edges) {
    if (edge.kind !== "calls") continue;
    degree.set(edge.source, (degree.get(edge.source) || 0) + 1);
    degree.set(edge.target, (degree.get(edge.target) || 0) + 1);
  }
  const byRiskThenDegree = (a: GraphNode, b: GraphNode) => byRisk(a, b) || (degree.get(b.id) || 0) - (degree.get(a.id) || 0);
  const chain = releaseChain(bundle).map((step) => step.id);
  const known = new Set(symbols.map((node) => node.id));
  const picked = new Set<string>();
  const add = (nodes: GraphNode[]) => {
    for (const node of nodes) if (picked.size < MAX_ROOTS) picked.add(node.id);
  };
  // Fill in priority order and never stop early: the changed code, then anything with a finding,
  // then the best-connected nodes. A release with two changed symbols still shows its real surroundings.
  add(chain.filter((id) => known.has(id)).map((id) => symbols.find((node) => node.id === id)!));
  add(symbols.filter((node) => node.changed && !node.is_test && node.severity).sort(byRiskThenDegree));
  add(symbols.filter((node) => node.changed && !node.is_test).sort(byRiskThenDegree));
  add(symbols.filter((node) => node.severity).sort(byRiskThenDegree));
  add([...symbols].sort(byRiskThenDegree));
  return [...picked];
}

function folderName(path: string): string {
  const parts = path.replace(/\\/g, "/").split("/").filter(Boolean);
  if (parts.length <= 1) return parts[0] || "root";
  // Two levels is enough to separate "blockchain_integration/pi_network" from "api/routes".
  return parts.slice(0, Math.min(2, parts.length - 1)).join("/");
}

function shorten(label: string) {
  const leaf = (label.split(/[/\\]/).pop() || label).trim();
  return leaf.length > 16 ? `${leaf.slice(0, 14)}…` : leaf;
}

export function treeElements(bundle: Bundle): { elements: ElementDefinition[]; shown: number; roots: number } {
  const roots = pickRoots(bundle);
  const owner = new Map<string, string>();
  for (const edge of bundle.graph.edges) if (edge.kind === "contains") owner.set(edge.target, edge.source);
  const byId = new Map(bundle.graph.nodes.map((node) => [node.id, node]));
  // Degree counts calls in each direction. Callers (in) and callees (out) are told apart so the
  // map can show which way a node leans.
  const inDeg = new Map<string, number>();
  const outDeg = new Map<string, number>();
  for (const edge of bundle.graph.edges) {
    if (edge.kind !== "calls") continue;
    outDeg.set(edge.source, (outDeg.get(edge.source) || 0) + 1);
    inDeg.set(edge.target, (inDeg.get(edge.target) || 0) + 1);
  }
  const degreeOf = (id: string) => (inDeg.get(id) || 0) + (outDeg.get(id) || 0);
  const peak = Math.max(1, ...bundle.graph.nodes.map((node) => degreeOf(node.id)));
  // Symbols without a file panel (API endpoints) are grouped by folder so the ring reads as clusters.
  const groupOf = (id: string): string | null => {
    const file = owner.get(id);
    if (file) return file;
    const node = byId.get(id);
    return node ? `${GROUP_PREFIX}${folderName(node.file || node.label)}` : null;
  };
  const tree = buildTree(bundle.graph.nodes, bundle.graph.edges, roots, TREE_DEPTH + 1, groupOf);
  const sizeOf = (id: string) => {
    if (id === CENTER_ID) return 96;
    if (id.startsWith(GROUP_PREFIX) || id.startsWith("file:")) return 64;
    return sizeForDegree(degreeOf(id), peak);
  };
  const placed = layoutRadial(tree, 46, 120, sizeOf);
  const chain = new Set(releaseChain(bundle).map((step) => step.id));
  const direction = new Map<string, string>();
  for (const edge of bundle.graph.edges) if (edge.kind === "calls") direction.set(`${edge.source}>${edge.target}`, edge.id);

  const elements: ElementDefinition[] = [];
  for (const id of tree.order) {
    const at = placed.get(id)!;
    if (id === CENTER_ID) {
      elements.push({ data: { id, label: "RELEASE", short: "RELEASE", depth: 0 }, classes: "centre", position: { x: at.x, y: at.y } });
      continue;
    }
    const depth = tree.nodes.get(id)!.depth;
    if (id.startsWith(GROUP_PREFIX)) {
      const folder = id.slice(GROUP_PREFIX.length);
      const members = tree.nodes.get(id)!.children.length;
      elements.push({
        data: { id, label: folder, short: shorten(folder), kind: "folder", depth, size: sizeOf(id), members, degree: members },
        classes: "orb filenode folder",
        position: { x: at.x, y: at.y },
      });
      continue;
    }
    const node = byId.get(id);
    if (!node) continue;
    const classes = [
      "orb",
      node.kind === "file" ? "filenode" : "",
      node.kind === "endpoint" ? "endpoint" : "",
      node.is_test ? "test" : "",
      chain.has(id) ? "onchain" : "",
      // Leaning: mostly called (a sink), mostly calling (a source), or balanced.
      (inDeg.get(id) || 0) > (outDeg.get(id) || 0) ? "sink" : (outDeg.get(id) || 0) > (inDeg.get(id) || 0) ? "source" : "",
    ];
    elements.push({
      data: {
        ...node,
        short: shorten(node.label),
        depth,
        size: sizeOf(id),
        degree: degreeOf(id),
        callers: inDeg.get(id) || 0,
        callees: outDeg.get(id) || 0,
      },
      classes: classes.filter(Boolean).join(" "),
      position: { x: at.x, y: at.y },
    });
  }
  for (const id of tree.order) {
    const entry = tree.nodes.get(id)!;
    if (!entry.parent) continue;
    // Arrows keep the real call direction: down a ring when the parent calls the child, up when it is called.
    const down = direction.has(`${entry.parent}>${id}`);
    const calls = down || direction.has(`${id}>${entry.parent}`);
    const source = down || !calls ? entry.parent : id;
    const target = source === id ? entry.parent : id;
    const structural = entry.parent === CENTER_ID || entry.parent.startsWith("file:") || entry.parent.startsWith(GROUP_PREFIX);
    elements.push({
      data: { id: `t:${source}>${target}`, source, target, kind: structural ? "origin" : "calls" },
      classes: [structural ? "origin" : "", chain.has(id) && chain.has(entry.parent) ? "chain" : "", !down && calls ? "caller" : ""].filter(Boolean).join(" "),
    });
  }
  // Cross-links: real calls between two circles that are both on the map but are not parent and
  // child. These are what make the picture a graph and not just a tree. Capped so they stay legible.
  const treeEdge = new Set<string>();
  for (const id of tree.order) {
    const parent = tree.nodes.get(id)!.parent;
    if (parent) treeEdge.add(`${parent}|${id}`).add(`${id}|${parent}`);
  }
  let cross = 0;
  for (const edge of bundle.graph.edges) {
    if (edge.kind !== "calls" || cross >= MAX_CROSS_LINKS) continue;
    if (!tree.nodes.has(edge.source) || !tree.nodes.has(edge.target)) continue;
    if (treeEdge.has(`${edge.source}|${edge.target}`)) continue;
    cross++;
    elements.push({ data: { id: `x:${edge.source}>${edge.target}`, source: edge.source, target: edge.target, kind: "cross" }, classes: "cross" });
  }
  // The failure chain is a path in its own right. Its steps can sit under different files in
  // the tree, so draw it explicitly: that way the pink route always shows, whatever the tree shape.
  const steps = releaseChain(bundle).map((step) => step.id).filter((id) => tree.nodes.has(id));
  for (let i = 0; i + 1 < steps.length; i++) {
    elements.push({
      data: { id: `chain:${steps[i]}>${steps[i + 1]}`, source: steps[i], target: steps[i + 1], kind: "chain" },
      classes: "chain route",
    });
  }
  return { elements, shown: tree.nodes.size - 1, roots: roots.length };
}
