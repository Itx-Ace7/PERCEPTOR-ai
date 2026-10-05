import type { Bundle } from "./types";

/**
 * True when two bundles would render identically. The bundle is large, so this compares the
 * parts that change while a run is live (status, per-stage state, and the sizes of the lists)
 * and a content fingerprint of the rest, instead of walking every node and edge.
 */
export function sameBundle(a: Bundle, b: Bundle): boolean {
  if (a === b) return true;
  return fingerprint(a) === fingerprint(b);
}

const cache = new WeakMap<Bundle, string>();

function fingerprint(bundle: Bundle): string {
  const known = cache.get(bundle);
  if (known !== undefined) return known;
  const value = JSON.stringify([
    bundle.run,
    bundle.repository,
    bundle.nodes,
    bundle.skipped?.length ?? 0,
    bundle.findings.length,
    bundle.findings.map((finding) => `${finding.id}:${finding.severity}:${finding.status}`),
    bundle.graph.nodes.length,
    bundle.graph.edges.length,
    bundle.risk,
    bundle.verification,
    bundle.llm,
  ]);
  cache.set(bundle, value);
  return value;
}
