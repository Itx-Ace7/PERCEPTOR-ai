import type { Bundle } from "./types";

export type DegreeRow = { id: string; label: string; file: string; callers: number; callees: number; degree: number; severity?: string | null };

/** The most connected symbols, with callers (in) and callees (out) counted separately. */
export function topByDegree(bundle: Bundle, limit = 8): DegreeRow[] {
  const callers = new Map<string, number>();
  const callees = new Map<string, number>();
  for (const edge of bundle.graph.edges) {
    if (edge.kind !== "calls") continue;
    callees.set(edge.source, (callees.get(edge.source) || 0) + 1);
    callers.set(edge.target, (callers.get(edge.target) || 0) + 1);
  }
  return bundle.graph.nodes
    .filter((node) => node.kind !== "file")
    .map((node) => {
      const inbound = callers.get(node.id) || 0;
      const outbound = callees.get(node.id) || 0;
      return { id: node.id, label: node.label, file: node.file || "", callers: inbound, callees: outbound, degree: inbound + outbound, severity: node.severity };
    })
    .filter((row) => row.degree > 0)
    .sort((a, b) => b.degree - a.degree || a.label.localeCompare(b.label))
    .slice(0, limit);
}
