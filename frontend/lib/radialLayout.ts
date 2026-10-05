import { CENTER_ID, type RadialTree } from "./radialTree";

export type Placed = { x: number; y: number; angle: number; radius: number };

/**
 * Place a tree on concentric rings. Each subtree owns an angular wedge sized by how much room
 * its leaves need, so siblings never overlap and a busy branch gets the space it requires.
 * Rings grow only as far as the crowded ring demands, so circles never touch.
 */
export function layoutRadial(tree: RadialTree, nodeSize = 46, ringGap = 120): Map<string, Placed> {
  const placed = new Map<string, Placed>();
  const perRing = new Map<number, number>();
  for (const node of tree.nodes.values()) perRing.set(node.depth, (perRing.get(node.depth) || 0) + 1);

  // Smallest radius at which `count` circles fit around a ring with breathing room.
  const slot = nodeSize + 22;
  const needed = (count: number) => (count * slot) / (2 * Math.PI);
  const radii: number[] = [0];
  for (let depth = 1; depth <= tree.maxDepth; depth++) {
    radii[depth] = Math.max(radii[depth - 1] + ringGap, needed(perRing.get(depth) || 1));
  }

  // A wedge is wide enough for the circles beneath it: a leaf needs one slot of arc on its ring,
  // and a parent needs at least as much as its children combined.
  const weight = new Map<string, number>();
  const measure = () => {
    for (const id of [...tree.order].reverse()) {
      const node = tree.nodes.get(id)!;
      const own = id === CENTER_ID ? 0 : slot / Math.max(1, radii[node.depth]);
      const below = node.children.reduce((sum, child) => sum + (weight.get(child) || 0), 0);
      weight.set(id, Math.max(own, below));
    }
    return weight.get(CENTER_ID) || 0;
  };
  // If the wedges need more than a full turn, shrinking them to fit would squeeze circles
  // together. Grow every ring instead until the demand fits inside 2π.
  for (let pass = 0; pass < 12; pass++) {
    const demand = measure();
    if (demand <= 2 * Math.PI) break;
    const grow = (demand / (2 * Math.PI)) * 1.01;
    for (let depth = 1; depth < radii.length; depth++) radii[depth] *= grow;
  }
  measure();

  const place = (id: string, start: number, end: number) => {
    const node = tree.nodes.get(id)!;
    const angle = (start + end) / 2;
    const radius = radii[node.depth];
    placed.set(id, { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius, angle, radius });
    const total = weight.get(id) || 1e-9;
    let cursor = start;
    for (const child of node.children) {
      const share = ((end - start) * (weight.get(child) || 0)) / total;
      place(child, cursor, cursor + share);
      cursor += share;
    }
  };

  placed.set(CENTER_ID, { x: 0, y: 0, angle: 0, radius: 0 });
  // Start at the top and sweep clockwise. The full circle is split by each branch's weight.
  const centre = tree.nodes.get(CENTER_ID)!;
  const whole = weight.get(CENTER_ID) || 1e-9;
  let cursor = -Math.PI / 2;
  for (const child of centre.children) {
    const share = (2 * Math.PI * (weight.get(child) || 0)) / whole;
    place(child, cursor, cursor + share);
    cursor += share;
  }
  return placed;
}
