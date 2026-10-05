import type { Bundle, RunSummary } from "./types";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8787";

// Optional shared secret. NEXT_PUBLIC_* values are visible in the browser, so this guards a
// shared deployment against casual access; it is not a substitute for per-user authentication.
const API_TOKEN = process.env.NEXT_PUBLIC_API_TOKEN || "";

/** Append the token to URLs that the browser fetches without custom headers (EventSource, links). */
export function withToken(url: string): string {
  if (!API_TOKEN) return url;
  return `${url}${url.includes("?") ? "&" : "?"}api_key=${encodeURIComponent(API_TOKEN)}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(API_TOKEN ? { "x-api-key": API_TOKEN } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch {
      detail = await response.text();
    }
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export function fetchMeta() {
  return request<{ product: Bundle["product"]; llm: Bundle["llm"] }>("/api/meta");
}

export function fetchRuns() {
  return request<{ runs: RunSummary[] }>("/api/runs");
}

export function createRun(body: { source_type: string; url?: string; path?: string }) {
  return request<{ run_id: string }>("/api/runs", { method: "POST", body: JSON.stringify(body) });
}

export function uploadZip(file: File) {
  const data = new FormData();
  data.append("file", file);
  return request<{ run_id: string }>("/api/runs/upload", { method: "POST", body: data });
}

export function fetchBundle(runId: string) {
  return request<Bundle>(`/api/runs/${runId}`);
}

export function startVerify(runId: string) {
  return request<{ status: string }>(`/api/runs/${runId}/verify`, { method: "POST" });
}

export function reportUrl(runId: string, kind: "md" | "sarif") {
  return withToken(`${API_BASE}/api/runs/${runId}/report.${kind}`);
}
