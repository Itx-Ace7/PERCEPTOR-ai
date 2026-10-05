"use client";

import { AnimatePresence, motion } from "framer-motion";
import type { SimState } from "@/lib/simulation";
import { STEP_MS } from "@/lib/simulation";
import type { ChainNode } from "@/lib/types";

/** What is happening right now, in words: the step, how far along, and what it means for the release. */
export function SimulationHud({ sim, chain }: { sim: SimState; chain: ChainNode[] }) {
  const live = sim.status !== "idle";
  const finished = sim.status === "done";
  return (
    <AnimatePresence>
      {live && sim.current && (
        <motion.aside
          className={`sim-hud ${finished ? "done" : ""}`}
          initial={{ opacity: 0, y: 18, scale: 0.97 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 12 }}
          transition={{ duration: 0.28 }}
          aria-live="polite"
        >
          <div className="sim-head mono">
            <span>{finished ? "Chain complete" : `Step ${sim.step + 1} of ${sim.total}`}</span>
            <span className="sim-kind">{sim.current.kind}</span>
          </div>
          <AnimatePresence mode="wait">
            <motion.div key={sim.current.id} initial={{ opacity: 0, x: 14 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -14 }} transition={{ duration: 0.22 }}>
              <h3>{sim.current.label}</h3>
              <p className="muted">{sim.current.reason}</p>
              {sim.current.file && <p className="sim-file mono">{sim.current.file}</p>}
            </motion.div>
          </AnimatePresence>
          <div className="sim-track" aria-hidden="true">
            {/* Re-keyed per step so the bar fills once over exactly the time the step is shown. */}
            <motion.i
              key={`${sim.step}-${finished}`}
              initial={{ width: finished ? "100%" : "0%" }}
              animate={{ width: "100%" }}
              transition={{ duration: finished ? 0 : STEP_MS / 1000, ease: "linear" }}
            />
          </div>
          <ol className="sim-steps">
            {chain.map((node, index) => (
              <li key={node.id} className={index < sim.step || finished ? "past" : index === sim.step ? "now" : ""}>
                <span className="sim-dot" />
                <span className="sim-name">{node.label}</span>
              </li>
            ))}
          </ol>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}
