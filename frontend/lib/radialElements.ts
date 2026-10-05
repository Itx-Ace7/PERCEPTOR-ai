import type { ElementDefinition } from "cytoscape";
import { layoutRadial } from "./radialLayout";
import { buildTree, CENTER_ID } from "./radialTree";
import { releaseChain } from "./release";
import type { Bundle, GraphNode } from "./types";

export const TREE_DEPTH = 3;
const MAX_ROOTS = 12;
const SEVERITY_RANK: Record<string, number> = { CRITICAL: 4, HIGH: 3, MEDIUM: 2, LOW: 1 };

/** Where the release starts: changed code first, then the failure chain, then the riskiest symbols. */
export function pickRoots(bundle: Bundle): string[] {
  const symbols = bundle.graph.nodes.filter((node) => node.kind !== "file");
  const byRisk = (a: GraphNode, b: GraphNode) => (SEVERITY_RANK[b.severity || ""] || 0) - (SEVERITY_RANK[a.severity || ""] || 0);
  const changed = symbols.filter((node) => node.changed && !node.is_test).sort(byRisk);
  const chain = releaseChain(bundle).map((step) => step.id);
  const known = new Set(symbols.map((node) => node.id));
  const picked = new Set<string>(chain.slice(0, 1).filter((id) => known.has(id)));
  // The snapshot case marks every symbol as changed; keep only the ones that carry risk.
  const risky = changed.filter((node) => node.severity);
  for (const node of (risky.length ? risky : changed).slice(0, MAX_ROOTS)) picked.add(node.id);
  if (picked.size === 0) for (const node of [...symbols].sort(byRisk).slice(0, MAX_ROOTS)) picked.add(node.id);
  return [...picked].slice(0, MAX_ROOTS);
}

function shorten(label: string) {
  const leaf = (label.split(/[/\\]/).pop() || label).trim();
  return leaf.length > 16 ? `${leaf.slice(0, 14)}…` : leaf;
}

export function treeElements(bundle: Bundle): { elements: ElementDefinition[]; shown: number; roots: number } {
  const roots = pickRoots(bundle);
  const owner = new Map<string, string>();
  for (const edge of bundle.graph.edges) if (edge.kind === "contains") owner.set(edge.target, edge.source);
  const tree = buildTree(bundle.graph.nodes, bundle.graph.edges, roots, TREE_DEPTH + 1, (id) => owner.get(id) ?? null);
  const placed = layoutRadial(tree);
  const byId = new Map(bundle.graph.nodes.map((node) => [node.id, node]));
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
    const node = byId.get(id);
    if (!node) continue;
    const depth = tree.nodes.get(id)!.depth;
    const classes = [
      "orb",
      node.kind === "file" ? "filenode" : "",
      node.kind === "endpoint" ? "endpoint" : "",
      node.is_test ? "test" : "",
      chain.has(id) ? "onchain" : "",
    ];
    elements.push({
      data: { ...node, short: shorten(node.label), depth },
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
    const structural = entry.parent === CENTER_ID || entry.parent.startsWith("file:");
    elements.push({
      data: { id: `t:${source}>${target}`, source, target, kind: structural ? "origin" : "calls" },
      classes: [structural ? "origin" : "", chain.has(id) && chain.has(entry.parent) ? "chain" : "", !down && calls ? "caller" : ""].filter(Boolean).join(" "),
    });
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
