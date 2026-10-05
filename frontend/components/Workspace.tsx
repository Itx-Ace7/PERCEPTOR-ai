"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import { Activity, Command, Crosshair, FileSearch, Gauge, ScrollText } from "lucide-react";
import { API_BASE, fetchBundle, reportUrl, startVerify } from "@/lib/api";
import { releaseChain } from "@/lib/release";
import type { Bundle } from "@/lib/types";
import { Credit } from "./Credit";
import { Mark } from "./Mark";
import { PipelineCanvas } from "./PipelineCanvas";
import { BlastMap } from "./BlastMap";
import { FindingsPanel } from "./FindingsPanel";
import { DecisionView } from "./DecisionView";

const VIEWS = [
  { id: "canvas", label: "Pipeline", short: "Flow", icon: Activity },
  { id: "blast", label: "Blast radius", short: "Blast", icon: Crosshair },
  { id: "findings", label: "Findings", short: "Finds", icon: FileSearch },
  { id: "decision", label: "Decision", short: "Call", icon: Gauge },
  { id: "report", label: "Report", short: "File", icon: ScrollText },
] as const;

type ViewId = (typeof VIEWS)[number]["id"];

export function Workspace({ runId, initialView }: { runId: string; initialView?: string }) {
  const router = useRouter();
  const [bundle, setBundle] = useState<Bundle | null>(null);
  const [error, setError] = useState("");
  const [view, setView] = useState<ViewId>(VIEWS.some((item) => item.id === initialView) ? (initialView as ViewId) : "canvas");
  const [palette, setPalette] = useState(false);
  const [query, setQuery] = useState("");
  const [activeId, setActiveId] = useState<string>();
  const [report, setReport] = useState("");
  const [verifying, setVerifying] = useState(false);

  useEffect(() => {
    let stop = false;
    const load = async () => {
      try {
        const next = await fetchBundle(runId);
        if (!stop) {
          setBundle(next);
          setError("");
        }
        return next;
      } catch (err) {
        if (!stop) setError(err instanceof Error ? err.message : "The analysis service is not reachable.");
        return null;
      }
    };
    load();
    const source = new EventSource(`${API_BASE}/api/runs/${runId}/events`);
    source.onmessage = () => {
      load();
    };
    const timer = window.setInterval(load, 1000);
    return () => {
      stop = true;
      source.close();
      window.clearInterval(timer);
    };
  }, [runId]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPalette((open) => !open);
      }
      if (event.key === "Escape") setPalette(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (view !== "report") return;
    fetch(reportUrl(runId, "md"))
      .then((response) => response.text())
      .then(setReport)
      .catch(() => setReport("Report is not available yet."));
  }, [view, runId, bundle?.run.status, bundle?.findings.length]);

  const commands = useMemo(() => {
    const items: { id: string; label: string; run: () => void }[] = VIEWS.map((item) => ({
      id: item.id,
      label: item.label,
      run: () => setView(item.id),
    }));
    items.push({ id: "verify", label: "Generate fixes and verify", run: () => verify() });
    items.push({
      id: "simulate",
      label: "Simulate release",
      run: () => {
        setView("blast");
        simulate();
      },
    });
    return items.filter((item) => item.label.toLowerCase().includes(query.toLowerCase()));
  }, [query, bundle]);

  function simulate() {
    const chain = bundle ? releaseChain(bundle) : [];
    chain.forEach((node, index) => {
      window.setTimeout(() => setActiveId(node.id), index * 700);
    });
    window.setTimeout(() => setActiveId(undefined), chain.length * 700 + 900);
  }

  async function verify() {
    setVerifying(true);
    setView("decision");
    try {
      await startVerify(runId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Verification could not start.");
      setVerifying(false);
    }
  }

  useEffect(() => {
    if (bundle?.verification && bundle.run.status === "COMPLETED") setVerifying(false);
  }, [bundle?.verification, bundle?.run.status]);

  const risk = bundle?.risk;
  const running = bundle?.pipeline.nodes.find((node) => bundle.nodes[node.id]?.status === "running");
  const stamp = !bundle
    ? "Connecting"
    : bundle.run.status === "FAILED"
      ? "Failed"
      : risk?.decision_label || running?.title || bundle.run.status.replaceAll("_", " ");
  const tone = risk?.decision === "NOT_READY" || bundle?.run.status === "FAILED" ? "bad" : risk?.decision === "READY" ? "good" : risk ? "warn" : "live";
  const sha = bundle?.repository.commit_sha ? bundle.repository.commit_sha.slice(0, 7) : "pending";
  const done = bundle ? bundle.pipeline.nodes.filter((node) => ["completed", "skipped"].includes(bundle.nodes[node.id]?.status || "")).length : 0;

  function openCommand(command: { id: string; run: () => void }) {
    command.run();
    const next = command.id === "verify" ? "decision" : command.id === "simulate" ? "blast" : command.id;
    setPalette(false);
    setQuery("");
    router.replace(`/runs/${runId}?view=${next}`);
  }

  return (
    <div className="app-bg workspace">
      <aside className="rail">
        <Link href="/" className="mark-link" aria-label="Home"><Mark size={26} /></Link>
        {VIEWS.map((item) => {
          const Icon = item.icon;
          return (
            <button key={item.id} className={view === item.id ? "active" : ""} onClick={() => { setView(item.id); router.replace(`/runs/${runId}?view=${item.id}`); }} aria-label={item.label} aria-current={view === item.id ? "page" : undefined}>
              <Icon size={16} />
              <span>{item.short}</span>
            </button>
          );
        })}
        <div className="spacer" />
        <button onClick={() => setPalette(true)} aria-label="Command palette">
          <Command size={16} />
          <span>Jump</span>
        </button>
      </aside>
      <section className="main">
        <header className="topbar">
          <div className="identity">
            <strong>{bundle?.repository.name || "Perceptor.AI"}</strong>
            <div className="meta-line mono">
              <span>{sha}</span>
              <span>{bundle?.repository.file_count || 0} files</span>
              <span>{(bundle?.repository.languages || []).join(" · ") || "reading tree"}</span>
              <span>{bundle ? `${done}/${bundle.pipeline.nodes.length} stages` : "—"}</span>
              <span>{bundle?.llm.enabled ? bundle.llm.model : "model key not set"}</span>
            </div>
          </div>
          <div className="film" aria-label="Pipeline progress">
            {bundle?.pipeline.nodes.map((node) => {
              const status = bundle.nodes[node.id]?.status || "pending";
              const cached = bundle.nodes[node.id]?.cached;
              return (
                <button key={node.id} className={`pip ${status} ${cached ? "cached" : ""}`} title={node.title} onClick={() => setView("canvas")}>
                  <i />
                </button>
              );
            })}
          </div>
          <div className="top-end">
            <button className={`stamp ${tone}`} onClick={() => setView("decision")}>{stamp}</button>
            <Credit />
          </div>
        </header>
        <nav className="views" aria-label="Views">
          {VIEWS.map((item) => (
            <button key={item.id} className={view === item.id ? "on" : ""} onClick={() => setView(item.id)}>{item.label}</button>
          ))}
        </nav>
        {error && <p className="banner">{error}</p>}
        <div className="stage-area">
          {!bundle && (
            <div className="boot">
              <div className="boot-mark"><Mark size={42} /></div>
              <p>{error || "Opening the release graph"}</p>
              <span className="mono quiet">{runId}</span>
            </div>
          )}
          {bundle && (
            <AnimatePresence mode="wait">
              <motion.div key={view} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.22 }}>
                {view === "canvas" && <PipelineCanvas bundle={bundle} />}
                {view === "blast" && <BlastMap bundle={bundle} activeId={activeId} />}
                {view === "findings" && <FindingsPanel findings={bundle.findings} />}
                {view === "decision" && (
                  <DecisionView bundle={bundle} activeId={activeId} onSimulate={() => { setView("blast"); simulate(); }} onVerify={verify} verifying={verifying || bundle.run.status === "VERIFYING"} />
                )}
                {view === "report" && (
                  <div className="report">
                    <div className="actions">
                      <a className="btn" href={reportUrl(runId, "md")} target="_blank" rel="noreferrer">Markdown</a>
                      <a className="btn" href={reportUrl(runId, "sarif")} target="_blank" rel="noreferrer">SARIF</a>
                    </div>
                    <div className="doc">
                      <pre className="mono">{report || "Writing the report…"}</pre>
                    </div>
                  </div>
                )}
              </motion.div>
            </AnimatePresence>
          )}
        </div>
      </section>
      {palette && (
        <div className="palette-backdrop" onClick={() => setPalette(false)}>
          <div className="palette" onClick={(event) => event.stopPropagation()}>
            <input
              autoFocus
              placeholder="Jump to a view, or verify the release"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && commands[0]) openCommand(commands[0]);
              }}
            />
            {commands.map((command) => (
              <button key={command.id} onClick={() => openCommand(command)}>
                <span>{command.label}</span>
                <span className="kbd mono">↵</span>
              </button>
            ))}
            {commands.length === 0 && <p className="quiet">Nothing matches that.</p>}
          </div>
        </div>
      )}
    </div>
  );
}
