export type NodeStatus = "pending" | "running" | "completed" | "failed" | "skipped";

export type StageNodeState = {
  status: NodeStatus;
  preview: string[];
  cached: boolean;
  duration_ms: number;
  error?: string;
};

export type Finding = {
  id: string;
  rule_id: string;
  severity: string;
  category: string;
  file: string;
  line: number;
  title: string;
  evidence: string;
  impact: string;
  recommendation: string;
  confidence: number;
  source: string;
  symbol?: string | null;
  sources: string[];
  checks: { source: string; rule_id: string; line: number; evidence: string; title: string }[];
  excerpt?: { start: number; lines: { n: number; text: string; hit: boolean }[] };
  related_symbols?: { id: string; label: string; kind: string }[];
  status: string;
};

export type GraphNode = {
  id: string;
  label: string;
  kind: string;
  file?: string;
  line?: number;
  language?: string;
  changed?: boolean;
  is_test?: boolean;
  severity?: string | null;
  finding_count?: number;
};

export type GraphEdge = {
  id: string;
  source: string;
  target: string;
  kind: string;
};

export type ChainNode = {
  id: string;
  label: string;
  file: string;
  kind: string;
  reason: string;
};

export type Bundle = {
  product: { name: string; version: string; tagline: string; short: string };
  pipeline: {
    groups: Record<string, { label: string; accent: string }>;
    nodes: {
      id: string;
      title: string;
      blurb: string;
      group: string;
      optional?: boolean;
      depends_on: string[];
      position: { x: number; y: number };
    }[];
  };
  policy: {
    weights: Record<string, number>;
    thresholds: Record<string, number>;
    decision_labels: Record<string, string>;
  };
  llm: { enabled: boolean; model: string };
  run: { id: string; status: string; started_at: string; finished_at: string | null; error: string | null };
  repository: {
    id: string;
    name: string;
    source_type: string;
    commit_sha: string;
    languages: string[];
    file_count: number;
  };
  nodes: Record<string, StageNodeState>;
  skipped: { path: string; reason: string; size: number }[];
  findings: Finding[];
  graph: { nodes: GraphNode[]; edges: GraphEdge[]; total_nodes?: number; truncated?: boolean };
  impact: {
    counts?: Record<string, number>;
    failure_chains?: { id: string; nodes: ChainNode[]; length: number }[];
    changed_files?: { path: string; status: string }[];
  };
  risk: {
    overall: string;
    score: number;
    decision: string;
    decision_label: string;
    dimensions: Record<string, { score: number; weight: number; findings: number }>;
    waterfall: { name: string; delta: number; running: number; score: number }[];
    blockers: { id: string; title: string; file: string; line: number; severity: string }[];
    why: string[];
    actions: string[];
    failure_chain: { id: string; nodes: ChainNode[] } | null;
    counts: Record<string, number>;
  } | null;
  verification: {
    fixes: { file: string; strategy: string; note: string }[];
    before: { findings: number; by_severity: Record<string, number>; decision: string; score: number };
    after: {
      findings: number;
      by_severity: Record<string, number>;
      decision: string;
      decision_label: string;
      score: number;
      risk?: Bundle["risk"];
    };
    build: { status: string; output: string };
    tests: { status: string; passed: number; failed: number; output: string };
    release_status: string;
    remaining: Finding[];
    graph?: Bundle["graph"];
  } | null;
};

export type RunSummary = {
  id: string;
  status: string;
  started_at: string;
  repo_name: string;
  source_type: string;
  commit_sha: string;
};
