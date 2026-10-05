import type { ElementDefinition } from "cytoscape";
import { releaseChain } from "./release";
import type { Bundle } from "./types";

export function shortName(label: string, kind?: string) {
  const leaf = (label.split(/[/\\]/).pop() || label).trim();
  const text = kind === "file" ? leaf : leaf.replace(/\.(py|js|ts|tsx|jsx|go|sql)$/i, "");
  return text.length > 22 ? `${text.slice(0, 20)}…` : text;
}

export function columnsFor(count: number) {
  if (count <= 1) return 1;
  if (count <= 4) return 2;
  if (count <= 9) return 3;
  if (count <= 20) return 4;
  if (count <= 40) return 6;
  return 8;
}

const VIEW_LIMIT = 140;

export function presentGraph(bundle: Bundle) {
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

/** Folder a node lives in, so files from one directory are placed side by side. */
function folderOf(node: { file?: string; label: string }): string {
  const path = (node.file || node.label).replace(/\\/g, "/");
  const cut = path.lastIndexOf("/");
  return cut > 0 ? path.slice(0, cut) : "";
}

/** Pick the column count whose finished map is closest to the viewport's shape. */
function columnsForShape(sizes: [number, number][], aspect: number): number {
  if (sizes.length <= 1) return 1;
  const gapX = 88;
  const gapY = 96;
  let best = 1;
  let bestScore = Infinity;
  for (let cols = 1; cols <= Math.min(12, sizes.length); cols++) {
    const rows = Math.ceil(sizes.length / cols);
    let width = 0;
    let height = 0;
    for (let row = 0; row < rows; row++) {
      const slice = sizes.slice(row * cols, row * cols + cols);
      width = Math.max(width, slice.reduce((sum, size) => sum + size[0] + gapX, 0));
      height += Math.max(...slice.map((size) => size[1])) + gapY;
    }
    const score = Math.abs(Math.log(width / height / aspect));
    if (score < bestScore) {
      bestScore = score;
      best = cols;
    }
  }
  return best;
}

export function spanElements(bundle: Bundle, aspect = 1.6): ElementDefinition[] {
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
  const chipW = 128;
  const chipH = 30;
  const gap = 14;
  const pad = 40;
  const cells = files
    .map((file) => {
      const kids = [...(children.get(file.id) || [])].sort((a, b) => Number(Boolean(b.severity)) - Number(Boolean(a.severity)) || a.label.localeCompare(b.label));
      const cols = Math.min(3, Math.max(1, kids.length || 1));
      const rows = Math.max(1, Math.ceil((kids.length || 1) / cols));
      const width = kids.length ? cols * chipW + (cols - 1) * gap + pad * 2 : 210;
      const height = kids.length ? rows * chipH + (rows - 1) * gap + pad * 2 + 8 : 44;
      return { file, kids, cols, width, height };
    })
    .sort((a, b) => folderOf(a.file).localeCompare(folderOf(b.file)) || b.kids.length - a.kids.length || a.file.label.localeCompare(b.file.label));

  const columns = columnsForShape(cells.map((cell) => [cell.width, cell.height]), aspect);
  const positions = new Map<string, { x: number; y: number }>();
  let cursorX = 80;
  let cursorY = 70;
  let rowHeight = 0;
  let column = 0;
  for (const cell of cells) {
    if (column === columns) {
      column = 0;
      cursorX = 80;
      cursorY += rowHeight + 96;
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
    cursorX += cell.width + 88;
    column += 1;
  }

  // Symbols with no file panel (e.g. API endpoints) go in a grid shaped like the viewport,
  // with files from one folder kept side by side.
  const orphans = nodes
    .filter((node) => !placed.has(node.id))
    .sort((a, b) => folderOf(a).localeCompare(folderOf(b)) || Number(Boolean(b.severity)) - Number(Boolean(a.severity)) || a.label.localeCompare(b.label));
  const cellW = chipW + 44;
  const cellH = chipH + 30;
  const orphanCols = Math.max(1, Math.min(orphans.length, Math.round(Math.sqrt((orphans.length * aspect * cellH) / cellW))));
  const orphanTop = cells.length ? cursorY + rowHeight + 110 : 70;
  orphans.forEach((node, index) => {
    positions.set(node.id, {
      x: 80 + (index % orphanCols) * cellW,
      y: orphanTop + Math.floor(index / orphanCols) * cellH,
    });
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
