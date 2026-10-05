import { CENTER_ID, type RadialTree } from "./radialTree";

export type Placed = { x: number; y: number; angle: number; radius: number };

const BREATHING = 22;
// Rings with at least this many circles alternate between an inner and an outer lane.
const STAGGER_FROM = 24;

/**
 * Place a tree on concentric rings. Each subtree owns an angular wedge sized by how much room
 * its circles need, so siblings never overlap and a busy branch gets the space it requires.
 * Rings grow only as far as the crowded ring demands, so circles never touch.
 *
 * `sizeOf` returns a node's diameter, so high-degree hubs (drawn larger) are given more room.
 */
export function layoutRadial(
  tree: RadialTree,
  nodeSize = 46,
  ringGap = 120,
  sizeOf: (id: string) => number = () => nodeSize,
): Map<string, Placed> {
  const placed = new Map<string, Placed>();
  const slotOf = (id: string) => sizeOf(id) + BREATHING;

  // Arc length one ring must supply for every node on it.
  const demandPerRing = new Map<number, number>();
  const biggestPerRing = new Map<number, number>();
  for (const node of tree.nodes.values()) {
    demandPerRing.set(node.depth, (demandPerRing.get(node.depth) || 0) + slotOf(node.id));
    biggestPerRing.set(node.depth, Math.max(biggestPerRing.get(node.depth) || 0, sizeOf(node.id)));
  }
  // A crowded ring zigzags between two lanes. Neighbours then sit at different radii, so each
  // circle needs only about 60% of the arc and the whole ring can be much smaller.
  const countPerRing = new Map<number, number>();
  for (const node of tree.nodes.values()) countPerRing.set(node.depth, (countPerRing.get(node.depth) || 0) + 1);
  const staggered = (depth: number) => (countPerRing.get(depth) || 0) >= STAGGER_FROM;
  const laneOffset = (depth: number) => (staggered(depth) ? (biggestPerRing.get(depth) || 0) * 0.5 + 6 : 0);
  const arcShare = (depth: number) => (staggered(depth) ? 0.6 : 1);

  const radii: number[] = [0];
  for (let depth = 1; depth <= tree.maxDepth; depth++) {
    const fit = ((demandPerRing.get(depth) || 0) * arcShare(depth)) / (2 * Math.PI);
    // Rings are also spaced by the largest circle on either side, so big hubs never touch the next ring.
    const clear =
      (biggestPerRing.get(depth - 1) || 0) / 2 + (biggestPerRing.get(depth) || 0) / 2 + BREATHING * 2 + laneOffset(depth - 1) + laneOffset(depth);
    radii[depth] = Math.max(radii[depth - 1] + Math.max(ringGap, clear), fit);
  }

  // A wedge is wide enough for the circles beneath it: a leaf needs its own slot of arc on its ring,
  // and a parent needs at least as much as its children combined.
  const weight = new Map<string, number>();
  const measure = () => {
    for (const id of [...tree.order].reverse()) {
      const node = tree.nodes.get(id)!;
      const own = id === CENTER_ID ? 0 : slotOf(id) / Math.max(1, radii[node.depth]);
      const below = node.children.reduce((sum, child) => sum + (weight.get(child) || 0), 0);
      weight.set(id, Math.max(own, below));
    }
    return weight.get(CENTER_ID) || 0;
  };
  // If the wedges need more than a full turn, shrinking them to fit would squeeze circles
  // together. Grow every ring instead until the demand fits inside 2π.
  for (let pass = 0; pass < 14; pass++) {
    const demand = measure();
    if (demand <= 2 * Math.PI) break;
    const grow = (demand / (2 * Math.PI)) * 1.01;
    for (let depth = 1; depth < radii.length; depth++) radii[depth] *= grow;
  }
  measure();

  const lanes = new Map<number, number>();
  for (let depth = 0; depth <= tree.maxDepth; depth++) lanes.set(depth, 0);
  const place = (id: string, start: number, end: number) => {
    const node = tree.nodes.get(id)!;
    const angle = (start + end) / 2;
    // Alternate neighbours between the inner and outer lane of a crowded ring.
    const lane = staggered(node.depth) ? (lanes.get(node.depth)! % 2 === 0 ? -1 : 1) : 0;
    if (staggered(node.depth)) lanes.set(node.depth, lanes.get(node.depth)! + 1);
    const radius = radii[node.depth] + lane * laneOffset(node.depth) * 0.5;
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
