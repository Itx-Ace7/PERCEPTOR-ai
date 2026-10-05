"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { createRun, fetchMeta, fetchRuns, uploadZip } from "@/lib/api";
import type { RunSummary } from "@/lib/types";
import { Credit } from "@/components/Credit";
import { Mark } from "@/components/Mark";

const NODES: [number, number, string][] = [
  [90, 78, "Ingest"],
  [250, 150, "Parse"],
  [410, 70, "Diff"],
  [410, 230, "Static"],
  [590, 150, "Impact"],
  [760, 78, "Review"],
  [760, 230, "Risk"],
];
const LINKS = [[0, 1], [1, 2], [1, 3], [2, 4], [3, 4], [4, 5], [4, 6], [5, 6]];

export default function HomePage() {
  const router = useRouter();
  const [tagline, setTagline] = useState("Predictive Engineering Review & Code Evaluation for Proactive Threat Observation & Risk");
  const [version, setVersion] = useState("");
  const [model, setModel] = useState("deterministic engine");
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [online, setOnline] = useState<boolean | null>(null);

  useEffect(() => {
    fetchMeta()
      .then((meta) => {
        setTagline(meta.product.tagline);
        setVersion(meta.product.version);
        setModel(meta.llm.enabled ? meta.llm.model : "deterministic engine");
        setOnline(true);
      })
      .catch(() => setOnline(false));
    fetchRuns().then((payload) => setRuns(payload.runs)).catch(() => undefined);
  }, []);

  async function go(work: () => Promise<{ run_id: string }>) {
    setBusy(true);
    setError("");
    try {
      const created = await work();
      router.push(`/runs/${created.run_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start the run.");
      setBusy(false);
    }
  }

  return (
    <main className="app-bg landing">
      <header className="mast">
        <div className="brand"><Mark /> PERCEPTOR.AI</div>
        <span className="live-pill mono"><i /> {model}</span>
      </header>
      <section className="hero-grid">
        <motion.div className="hero-copy" initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.55 }}>
          <p className="kicker">Release graph {version ? `· ${version}` : ""}</p>
          <h1>What breaks if you <span className="glow-word">release</span> this?</h1>
          <p className="lede">{tagline}</p>
          <div className="intake">
            <form
              className="url-row"
              onSubmit={(event) => {
                event.preventDefault();
                if (url.trim()) go(() => createRun({ source_type: "github", url: url.trim() }));
              }}
            >
              <input value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://github.com/org/repository" aria-label="GitHub repository URL" />
              <button className="btn btn-primary" disabled={busy || !url.trim()} type="submit">
                {busy ? "Opening the graph…" : "Analyze repository"}
              </button>
            </form>
            <div className="actions">
              <label className="btn">
                Upload a zip
                <input
                  type="file"
                  accept=".zip,application/zip"
                  hidden
                  disabled={busy}
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    event.target.value = "";
                    if (file) go(() => uploadZip(file));
                  }}
                />
              </label>
            </div>
          </div>
          {online === false && <p className="error-line" style={{ marginTop: 12 }}>The analysis API is not running on this machine. Start it on port 8787, then analyze a repository or a zip.</p>}
          {error && <p className="error-line" style={{ marginTop: 12 }}>{error}</p>}
          <div className="principles">
            <div className="principle"><b>Trace the change</b><span>Ingest, parse, and diff before any opinion is formed.</span></div>
            <div className="principle"><b>Score in the open</b><span>Risk is a weighted policy, with the reasons written beside it.</span></div>
            <div className="principle"><b>Prove the repair</b><span>Apply the fix, rebuild, retest, and rescore the same graph.</span></div>
          </div>
          {runs.length > 0 && (
            <div className="run-list">
              {runs.slice(0, 4).map((run) => (
                <a className="run-link" key={run.id} href={`/runs/${run.id}`}>
                  <span className={`dot ${dotTone(run.status)}`} />
                  <span>{run.repo_name}</span>
                  <span className="mono muted">{run.status.replaceAll("_", " ")}</span>
                  <span className="mono muted when">{when(run.started_at)}</span>
                </a>
              ))}
            </div>
          )}
          <p className="quiet mono">Paste a repository or upload a zip. Inside a run, Ctrl K jumps the graph.</p>
        </motion.div>
        <Constellation />
      </section>
      <footer className="mast">
        <Credit />
        <span className="kicker mono">Signal · graph · decision</span>
      </footer>
    </main>
  );
}

function dotTone(status: string) {
  if (status === "FAILED") return "bad";
  if (status === "COMPLETED") return "good";
  if (status === "RUNNING" || status === "VERIFYING") return "live";
  return "";
}

function when(iso: string) {
  const then = Date.parse(iso);
  if (!Number.isFinite(then)) return "";
  const seconds = Math.max(0, (Date.now() - then) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

function Constellation() {
  return (
    <motion.div className="constellation" aria-hidden="true" initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.7, delay: 0.08 }}>
      <div className="viewfinder" />
      <svg viewBox="0 0 860 520">
        {LINKS.map(([from, to], index) => (
          <line
            key={`${from}-${to}`}
            className="flow-line"
            x1={NODES[from][0]}
            y1={NODES[from][1]}
            x2={NODES[to][0]}
            y2={NODES[to][1]}
            stroke={index % 4 === 0 ? "rgba(255,45,166,0.55)" : "rgba(62,224,255,0.45)"}
            strokeWidth="1.2"
            style={{ animationDelay: `${index * -1.4}s` }}
          />
        ))}
        {NODES.map(([x, y, label]) => (
          <g key={label}>
            <rect x={Number(x) - 58} y={Number(y) - 20} width="116" height="40" rx="6" fill="#0c1018" stroke="#3ee0ff" strokeOpacity="0.7" />
            <path d={`M${Number(x) + 44} ${Number(y) - 20} h12 v12`} fill="none" stroke="#ff2da6" strokeWidth="1.2" />
            <text x={x} y={Number(y) + 5} textAnchor="middle" fill="#e7fbff" fontSize="13" fontFamily="var(--font-outfit), sans-serif">{label}</text>
          </g>
        ))}
      </svg>
      <div className="constellation-caption">
        <div><b>One graph, one decision</b><span>From the diff to the failure chain.</span></div>
        <span className="mono">ingest → risk</span>
      </div>
    </motion.div>
  );
}
