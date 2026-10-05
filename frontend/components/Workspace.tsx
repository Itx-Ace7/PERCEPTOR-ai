"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import { Activity, Command, Crosshair, FileSearch, Gauge, ScrollText } from "lucide-react";
import { API_BASE, fetchBundle, reportUrl, startVerify, withToken } from "@/lib/api";
import { releaseChain } from "@/lib/release";
import { sameBundle } from "@/lib/sameBundle";
import { IDLE, playSimulation, type SimState } from "@/lib/simulation";
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
  const [sim, setSim] = useState<SimState>(IDLE);
  const stopSim = useRef<(() => void) | null>(null);
  const pendingStart = useRef(false);
  const [report, setReport] = useState("");
  const [verifying, setVerifying] = useState(false);
  // Bumped when a finished run starts again (Verify), so the live connection is opened afresh.
  const [restartKey, setRestartKey] = useState(0);

  useEffect(() => {
    let stop = false;
    let inFlight = false;
    let again = false;
    let finished = false;
    let source: EventSource | null = null;
    let timer = 0;

    const end = () => {
      // A finished run never changes unless Verify starts it again, which restarts this effect.
      source?.close();
      source = null;
      window.clearInterval(timer);
    };

    const load = async () => {
      // One request at a time. A burst of events while one is running becomes a single follow-up.
      if (inFlight) {
        again = true;
        return;
      }
      inFlight = true;
      try {
        const next = await fetchBundle(runId);
        if (stop) return;
        // Skip the state update when nothing changed, so an unchanged poll cannot re-render the tree.
        setBundle((current) => (current && sameBundle(current, next) ? current : next));
        setError("");
        finished = next.run.status === "COMPLETED" || next.run.status === "FAILED";
        if (finished) end();
      } catch (err) {
        if (!stop) setError(err instanceof Error ? err.message : "The analysis service is not reachable.");
      } finally {
        inFlight = false;
        if (again && !stop && !finished) {
          again = false;
          load();
        }
      }
    };

    load();
    source = new EventSource(withToken(`${API_BASE}/api/runs/${runId}/events`));
    source.onmessage = () => {
      load();
    };
    // The browser reconnects a closed stream on its own. When the server ends it, stop instead.
    source.onerror = () => {
      if (finished) end();
    };
    timer = window.setInterval(load, 1500);
    return () => {
      stop = true;
      source?.close();
      window.clearInterval(timer);
    };
  }, [runId, restartKey]);

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
      run: () => simulate(),
    });
    return items.filter((item) => item.label.toLowerCase().includes(query.toLowerCase()));
  }, [query, bundle]);

  function stopSimulation() {
    stopSim.current?.();
    stopSim.current = null;
    setSim(IDLE);
    setActiveId(undefined);
  }

  function start() {
    // A second press restarts from the first step instead of stacking a second run on the first.
    stopSim.current?.();
    const chain = bundle ? releaseChain(bundle) : [];
    stopSim.current = playSimulation(chain, (next) => {
      setSim(next);
      setActiveId(next.status === "idle" ? undefined : next.current?.id);
    });
  }

  function simulate() {
    // From another view the map is not on screen yet. Switch to it and wait for it to report
    // ready, so the first step is never played to an empty stage.
    if (view !== "blast") {
      setSim({ ...IDLE, status: "running", step: -1, total: bundle ? releaseChain(bundle).length : 0 });
      pendingStart.current = true;
      setView("blast");
      router.replace(`/runs/${runId}?view=blast`);
      return;
    }
    start();
  }

  function mapReady() {
    if (!pendingStart.current) return;
    pendingStart.current = false;
    start();
  }

  useEffect(() => () => stopSim.current?.(), []);

  async function verify() {
    setVerifying(true);
    setView("decision");
    try {
      await startVerify(runId);
      setRestartKey((key) => key + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Verification could not start.");
      setVerifying(false);
    }
  }

  // Depend on booleans, not the verification object, so a fresh-but-equal bundle cannot re-run this.
  const verifiedAndDone = Boolean(bundle?.verification) && bundle?.run.status === "COMPLETED";
  useEffect(() => {
    if (verifiedAndDone) setVerifying(false);
  }, [verifiedAndDone]);

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
              {bundle && bundle.skipped.length > 0 && (
                <span
                  className="skipped"
                  title={bundle.skipped.map((item) => `${item.path} (${item.reason}, ${Math.ceil(item.size / 1024)} KB)`).join("\n")}
                >
                  {bundle.skipped.length} skipped
                </span>
              )}
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
                {view === "blast" && <BlastMap bundle={bundle} activeId={activeId} sim={sim} onSimulate={simulate} onStop={stopSimulation} onReady={mapReady} />}
                {view === "findings" && <FindingsPanel findings={bundle.findings} />}
                {view === "decision" && (
                  <DecisionView bundle={bundle} activeId={activeId} onSimulate={simulate} onVerify={verify} verifying={verifying || bundle.run.status === "VERIFYING"} />
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
