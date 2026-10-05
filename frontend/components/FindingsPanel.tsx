"use client";

import { useMemo, useState } from "react";
import Editor from "@monaco-editor/react";
import type { Finding } from "@/lib/types";

const ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"];

export function FindingsPanel({ findings }: { findings: Finding[] }) {
  const sorted = useMemo(
    () => [...findings].sort((a, b) => ORDER.indexOf(a.severity) - ORDER.indexOf(b.severity) || a.file.localeCompare(b.file)),
    [findings],
  );
  const [filter, setFilter] = useState("ALL");
  const [selected, setSelected] = useState<string | null>(sorted[0]?.id ?? null);
  const visible = filter === "ALL" ? sorted : sorted.filter((item) => item.severity === filter);
  const finding = visible.find((item) => item.id === selected) || visible[0];
  const counts = useMemo(() => {
    const tally: Record<string, number> = {};
    for (const item of sorted) tally[item.severity] = (tally[item.severity] || 0) + 1;
    return tally;
  }, [sorted]);

  if (!sorted.length) {
    return <div className="empty">Findings appear here as the static engine and the model finish.</div>;
  }

  const excerpt = finding?.excerpt;
  const code = excerpt?.lines.map((line) => line.text).join("\n") || finding?.evidence || "";
  const leaves = finding?.checks?.length
    ? finding.checks
    : finding
      ? [{ source: finding.source, rule_id: finding.rule_id, line: finding.line, evidence: finding.evidence, title: finding.title }]
      : [];

  return (
    <div className="split">
      <div className="list">
        <div className="filters">
          <button className={filter === "ALL" ? "on" : ""} onClick={() => setFilter("ALL")}>All {sorted.length}</button>
          {ORDER.filter((level) => counts[level]).map((level) => (
            <button key={level} className={filter === level ? "on" : ""} onClick={() => setFilter(level)}>{level} {counts[level]}</button>
          ))}
        </div>
        {visible.map((item) => (
          <button key={item.id} className={`finding ${item.id === finding?.id ? "on" : ""}`} onClick={() => setSelected(item.id)}>
            <span className={`sev mono ${item.severity}`}>{item.severity} · {item.category}</span>
            <strong>{item.title}</strong>
            <small className="mono">{item.file}:{item.line}</small>
          </button>
        ))}
        {visible.length === 0 && <p className="quiet">No findings at this severity.</p>}
      </div>
      {finding && (
        <article className="detail">
          <span className={`sev mono ${finding.severity}`}>{finding.severity} · {finding.category} · {Math.round(finding.confidence * 100)}% confidence</span>
          <h2>{finding.title}</h2>
          <div className="chips">
            {(finding.sources || [finding.source]).map((source) => <span className="chip mono" key={source}>{source}</span>)}
            <span className="chip mono">{finding.rule_id}</span>
            {finding.symbol && <span className="chip mono">{finding.symbol}</span>}
          </div>
          <Evidence leaves={leaves} title={finding.title} related={finding.related_symbols || []} />
          <div className="code-block">
            <Editor
              height="280px"
              theme="perceptor"
              language={finding.file.endsWith(".py") ? "python" : finding.file.endsWith(".js") ? "javascript" : "plaintext"}
              value={code}
              beforeMount={(monaco) => {
                monaco.editor.defineTheme("perceptor", {
                  base: "vs-dark",
                  inherit: true,
                  rules: [],
                  colors: {
                    "editor.background": "#0c0f14",
                    "editorLineNumber.foreground": "#667084",
                    "editorLineNumber.activeForeground": "#f4f7fb",
                  },
                });
              }}
              options={{
                readOnly: true,
                minimap: { enabled: false },
                scrollBeyondLastLine: false,
                fontSize: 13,
                fontFamily: "var(--font-mono), ui-monospace, monospace",
                lineNumbers: (line) => String((excerpt?.start || finding.line) + line - 1),
                overviewRulerLanes: 0,
                renderLineHighlight: "none",
                padding: { top: 12, bottom: 12 },
              }}
            />
          </div>
          <div className="dossier">
            <article>
              <h3>Evidence</h3>
              <p>{finding.evidence}</p>
            </article>
            <article>
              <h3>Impact</h3>
              <p>{finding.impact}</p>
            </article>
            <article>
              <h3>Recommendation</h3>
              <p>{finding.recommendation}</p>
            </article>
          </div>
        </article>
      )}
    </div>
  );
}

function Evidence({
  leaves,
  title,
  related,
}: {
  leaves: Finding["checks"];
  title: string;
  related: { id: string; label: string; kind: string }[];
}) {
  const width = 760;
  const height = 160;
  const left = leaves.slice(0, 4);
  const right = related.slice(0, 3);
  return (
    <svg className="evidence-svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Evidence graph">
      {left.map((leaf, index) => {
        const y = 28 + index * 34;
        return (
          <g key={`${leaf.rule_id}-${leaf.line}-${index}`}>
            <line x1="168" y1={y} x2="292" y2={height / 2} stroke="rgba(122,243,214,0.45)" />
            <rect x="12" y={y - 14} width="156" height="28" rx="8" fill="#141820" stroke="rgba(244,247,251,0.14)" />
            <text x="22" y={y + 4} fill="#f4f7fb" fontSize="11">{leaf.source} · {leaf.rule_id}</text>
          </g>
        );
      })}
      <rect x="292" y={height / 2 - 24} width="188" height="48" rx="14" fill="#10241f" stroke="#7af3d6" />
      <text x="306" y={height / 2 + 4} fill="#f4f7fb" fontSize="12">{title.slice(0, 24)}</text>
      {right.map((item, index) => {
        const y = 36 + index * 40;
        return (
          <g key={item.id}>
            <line x1="480" y1={height / 2} x2="560" y2={y} stroke="rgba(201,188,255,0.55)" />
            <rect x="560" y={y - 13} width="184" height="28" rx="8" fill="#141820" stroke="rgba(244,247,251,0.14)" />
            <text x="572" y={y + 5} fill="#c9bcff" fontSize="11">{item.label}</text>
          </g>
        );
      })}
    </svg>
  );
}
