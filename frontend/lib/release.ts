import type { Bundle, ChainNode } from "./types";

export function releaseChain(bundle: Bundle): ChainNode[] {
  const recorded = bundle.risk?.failure_chain?.nodes || [];
  if (recorded.length > 0) return recorded;
  const steps: ChainNode[] = [];
  const seen = new Set<string>();
  for (const finding of bundle.findings) {
    const id = finding.symbol ? `sym:${finding.file}::${finding.symbol}` : `file:${finding.file}`;
    if (seen.has(id)) continue;
    seen.add(id);
    steps.push({
      id,
      label: finding.symbol || finding.title,
      file: finding.file,
      kind: finding.symbol ? "function" : "file",
      reason: finding.title,
    });
    if (steps.length >= 6) break;
  }
  return steps;
}
