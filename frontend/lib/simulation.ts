import type { ChainNode } from "./types";

export type SimStatus = "idle" | "running" | "done";
export type SimState = { status: SimStatus; step: number; total: number; current?: ChainNode; reached: string[] };

export const IDLE: SimState = { status: "idle", step: -1, total: 0, reached: [] };

/** Time spent on each step of the chain, and the pause once the last step lands. */
export const STEP_MS = 1500;
export const SETTLE_MS = 2600;

/**
 * Plays the failure chain step by step. It owns its timers, reports each step through
 * `onChange`, and can be stopped at any point, so a second press restarts it cleanly.
 */
export function playSimulation(chain: ChainNode[], onChange: (state: SimState) => void): () => void {
  if (chain.length === 0) {
    onChange(IDLE);
    return () => undefined;
  }
  const timers: number[] = [];
  const reached: string[] = [];
  chain.forEach((node, index) => {
    timers.push(
      window.setTimeout(() => {
        reached.push(node.id);
        onChange({ status: "running", step: index, total: chain.length, current: node, reached: [...reached] });
      }, 400 + index * STEP_MS),
    );
  });
  const finish = 400 + chain.length * STEP_MS;
  timers.push(window.setTimeout(() => onChange({ status: "done", step: chain.length - 1, total: chain.length, current: chain.at(-1), reached: [...reached] }), finish));
  timers.push(window.setTimeout(() => onChange(IDLE), finish + SETTLE_MS));
  return () => timers.forEach((id) => window.clearTimeout(id));
}
