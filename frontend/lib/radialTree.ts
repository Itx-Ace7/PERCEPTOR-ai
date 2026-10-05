import type { GraphEdge, GraphNode } from "./types";

export type TreeNode = { id: string; depth: number; parent: string | null; children: string[]; leaves: number };
export type RadialTree = { nodes: Map<string, TreeNode>; order: string[]; maxDepth: number };

const CENTER = "__release__";
export const CENTER_ID = CENTER;
export const GROUP_PREFIX = "group:";

/**
 * Build a breadth-first tree over call edges, following their direction from the changed code
 * outward. A virtual centre stands for the release itself; its children are the roots.
 * Every node appears once, under the shallowest parent that reaches it.
 */
export function buildTree(
  nodes: GraphNode[],
  edges: GraphEdge[],
  roots: string[],
  maxDepth: number,
  /** Optional grouping level: maps a root to the node (e.g. its file) it should hang under. */
  groupOf: (id: string) => string | null = () => null,
): RadialTree {
  const known = new Set(nodes.map((node) => node.id));
  const out = new Map<string, string[]>();
  for (const edge of edges) {
    if (edge.kind !== "calls" || !known.has(edge.source) || !known.has(edge.target)) continue;
    out.set(edge.source, [...(out.get(edge.source) || []), edge.target]);
    // Callers are impacted too, so walk the edge both ways but remember which way it points.
    out.set(edge.target, [...(out.get(edge.target) || []), edge.source]);
  }
  const tree = new Map<string, TreeNode>();
  tree.set(CENTER, { id: CENTER, depth: 0, parent: null, children: [], leaves: 0 });
  const queue: string[] = [];
  const attach = (id: string, parent: string, depth: number) => {
    tree.set(id, { id, depth, parent, children: [], leaves: 0 });
    tree.get(parent)!.children.push(id);
    queue.push(id);
  };
  for (const root of roots) {
    if (!known.has(root) || tree.has(root)) continue;
    const group = groupOf(root);
    // A group is either a real file node or a synthetic folder bucket ("group:...").
    if (group && (known.has(group) || group.startsWith(GROUP_PREFIX))) {
      if (!tree.has(group)) attach(group, CENTER, 1);
      attach(root, group, 2);
    } else {
      attach(root, CENTER, 1);
    }
  }
  for (let head = 0; head < queue.length; head++) {
    const current = tree.get(queue[head])!;
    // File groups only organise their symbols; calls are followed from the symbols themselves.
    if (current.depth >= maxDepth || current.id.startsWith("file:") || current.id.startsWith(GROUP_PREFIX)) continue;
    for (const next of out.get(current.id) || []) {
      if (tree.has(next)) continue;
      tree.set(next, { id: next, depth: current.depth + 1, parent: current.id, children: [], leaves: 0 });
      current.children.push(next);
      queue.push(next);
    }
  }
  const order = [CENTER, ...queue];
  for (const id of [...order].reverse()) {
    const node = tree.get(id)!;
    node.leaves = node.children.length ? node.children.reduce((sum, child) => sum + tree.get(child)!.leaves, 0) : 1;
  }
  return { nodes: tree, order, maxDepth: Math.max(...[...tree.values()].map((node) => node.depth)) };
}
