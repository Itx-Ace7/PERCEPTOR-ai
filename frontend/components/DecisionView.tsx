"use client";

import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { releaseChain } from "@/lib/release";
import type { Bundle } from "@/lib/types";

export function DecisionView({
  bundle,
  activeId,
  onSimulate,
  onVerify,
  verifying,
}: {
  bundle: Bundle;
  activeId?: string;
  onSimulate: () => void;
  onVerify: () => void;
  verifying: boolean;
}) {
  const recorded = bundle.risk;
  const repaired = bundle.verification?.after;
  const risk = recorded && repaired?.risk
    ? {
        ...recorded,
        ...repaired.risk,
        score: repaired.score ?? repaired.risk.score,
        decision: repaired.decision || repaired.risk.decision,
        decision_label: repaired.decision_label || repaired.risk.decision_label,
      }
    : recorded;
  if (!risk) {
    return <div className="empty">The release decision is written after correlation finishes.</div>;
  }
  const tone = risk.decision === "NOT_READY" ? "bad" : risk.decision === "READY" ? "good" : "warn";
  const stroke = tone === "bad" ? "#fb7185" : tone === "good" ? "#4ade80" : "#fbbf24";
  const chart = Object.entries(risk.dimensions)
    .filter(([, info]) => info.weight > 0 || info.findings > 0)
    .map(([name, info]) => ({ name, score: info.score }));
  const chain = releaseChain(bundle);
  const verification = bundle.verification;
  const radius = 86;
  const circumference = 2 * Math.PI * radius;
  const dash = (Math.max(0, Math.min(100, risk.score)) / 100) * circumference;
  const counts = Object.entries(risk.counts || {}).filter(([, count]) => count > 0);

  return (
    <div className="decision">
      <div className="decision-hero">
        <svg className="ring" viewBox="0 0 210 210" aria-label={`Risk score ${risk.score}`}>
          <circle cx="105" cy="105" r={radius} fill="none" stroke="rgba(244,247,251,0.08)" strokeWidth="10" />
          <circle
            cx="105"
            cy="105"
            r={radius}
            fill="none"
            stroke={stroke}
            strokeWidth="10"
            strokeLinecap="round"
            strokeDasharray={`${dash} ${circumference}`}
            transform="rotate(-90 105 105)"
          />
          <text x="105" y="98" textAnchor="middle" fill="#f6f8fc" fontSize="46" fontFamily="var(--font-display), sans-serif">{risk.score}</text>
          <text x="105" y="122" textAnchor="middle" fill="#a8b1c4" fontSize="11" letterSpacing="1.5">{risk.overall}</text>
        </svg>
        <div>
          <p className="kicker">Release readiness</p>
          <h1>{risk.decision_label}</h1>
          <p className="lede">{bundle.product.short}</p>
          {counts.length > 0 && (
            <div className="sev-row">
              {counts.map(([name, count]) => (
                <span key={name} className={`chip mono sev ${name}`}>{count} {name}</span>
              ))}
            </div>
          )}
          <div className="actions" style={{ marginTop: 18 }}>
            <button className="btn btn-primary" onClick={onSimulate} disabled={chain.length === 0}>Simulate release</button>
            <button className="btn" onClick={onVerify} disabled={verifying || bundle.run.status === "RUNNING"}>
              {verifying ? "Verifying the repair…" : "Generate fixes and verify"}
            </button>
          </div>
        </div>
      </div>
      <ul className="why">
        {risk.why.map((reason) => <li key={reason}>{reason}</li>)}
      </ul>
      <div className="grid-2">
        <section className="panel">
          <h3>Risk dimensions</h3>
          <div style={{ width: "100%", height: 180 }}>
            <ResponsiveContainer>
              <BarChart data={chart}>
                <XAxis dataKey="name" stroke="#a8b1c4" fontSize={11} tickLine={false} axisLine={false} />
                <YAxis stroke="#a8b1c4" fontSize={11} domain={[0, 100]} tickLine={false} axisLine={false} width={28} />
                <Tooltip cursor={{ fill: "rgba(255,255,255,0.04)" }} contentStyle={{ background: "#12161e", border: "1px solid rgba(244,247,251,0.12)", borderRadius: 12, color: "#f6f8fc" }} />
                <Bar dataKey="score" fill="#5eead4" radius={[7, 7, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          {risk.waterfall.map((step) => (
            <div className="bar-row" key={step.name}>
              <span>{step.name}</span>
              <div className="track"><i style={{ width: `${Math.max(0, Math.min(100, step.score))}%` }} /></div>
              <span className="mono">+{step.delta}</span>
            </div>
          ))}
        </section>
        <div style={{ display: "grid", gap: 16, alignContent: "start" }}>
          {risk.blockers.length > 0 && (
            <section className="panel">
              <h3>Release blockers</h3>
              {risk.blockers.map((blocker) => (
                <div className="blocker" key={blocker.id}>
                  <span className={`sev mono ${blocker.severity}`}>{blocker.severity}</span>
                  <div>
                    <strong>{blocker.title}</strong>
                    <div className="muted mono">{blocker.file}:{blocker.line}</div>
                  </div>
                </div>
              ))}
            </section>
          )}
          <section className="panel">
            <h3>Before you release</h3>
            <ul className="action-list">
              {risk.actions.map((action) => (
                <li key={action}><span className="check" />{action}</li>
              ))}
            </ul>
            {chain.length > 0 && (
              <div className="chain" style={{ marginTop: 16 }}>
                {chain.map((node, index) => (
                  <div key={node.id} className={`step ${node.id === activeId ? "on" : ""}`}>
                    <span className="mono muted">0{index + 1}</span>
                    <strong> {node.label}</strong>
                    <div className="muted">{node.file}</div>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>
      </div>
      {verification && (
        <section className="panel" style={{ marginTop: 16 }}>
          <h3>Verification</h3>
          <div className="compare">
            <div>
              <span className="kicker">Before</span>
              <strong>{verification.before.score}</strong>
              <div className="muted">{verification.before.findings} findings · {verification.before.decision.replaceAll("_", " ")}</div>
            </div>
            <span className="mono muted">to</span>
            <div>
              <span className="kicker">After</span>
              <strong>{verification.after.score}</strong>
              <div className="muted">{verification.after.findings} findings · {verification.after.decision_label || verification.release_status}</div>
            </div>
          </div>
          <p className="quiet">Build {verification.build.status} · Tests {verification.tests.status} ({verification.tests.passed} passed, {verification.tests.failed} failed)</p>
        </section>
      )}
    </div>
  );
}
