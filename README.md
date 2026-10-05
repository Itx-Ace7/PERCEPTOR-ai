# Perceptor.AI

**Predictive Engineering Review & Code Evaluation for Proactive Threat Observation & Risk.**

Perceptor.AI answers one release question: if this change ships, what can break, why, and what has to happen before it is ready. It builds a symbol and dependency graph, diffs the change against the parent revision, runs a deterministic rule engine, traces the blast radius, optionally asks a model to review that evidence, and turns the result into an explainable release decision.

The model is optional. A full NOT READY decision is produced with no API key.

**Live app:** [perceptor-ai-release.vercel.app](https://perceptor-ai-release.vercel.app)

**Repository:** [github.com/Itx-Ace7/PERCEPTOR-ai](https://github.com/Itx-Ace7/PERCEPTOR-ai)

Developed by Team Cryptonix.

## What you see

- **Pipeline.** Each stage is a live node with status, duration, and its own output. Edges follow `depends_on` in `config/pipeline.yaml`.
- **Blast radius.** A round, directed tree. Node size is connectivity. Callers and callees are oriented, and the most connected symbols are listed beside the map.
- **Simulate release.** Plays the failure chain step by step on that map.
- **Findings.** Severity, file, evidence, impact, recommendation, and the checks that support the finding.
- **Decision.** NOT READY, READY WITH WARNINGS, or READY, with the score, the dimension bars, and the reasons.
- **Report.** Markdown and SARIF 2.1.0.

Inside a run, Ctrl+K jumps the graph.

## Run it

Requires Python 3.12 and Node.js.

```powershell
.\scripts\setup.ps1
.\scripts\run.ps1
```

Open [http://localhost:3000](http://localhost:3000). Paste an `https://` GitHub URL or upload a zip.

| Service | Address |
|---|---|
| Web UI | http://localhost:3000 |
| Analysis API | http://127.0.0.1:8787 |

The deterministic pipeline does not need a model key. To enable the AI review node, copy `.env.example` to `.env` and set `OPENROUTER_API_KEY`. The model name and time budget live in `config/settings.yaml`.

### Live interface

The [Vercel app](https://perceptor-ai-release.vercel.app) is this same interface. Analysis still runs on the API on your machine, because a run clones the repository, keeps a workspace, and streams progress for as long as the pipeline takes. Start the API with `scripts\run.ps1`, then open the live app in the same browser. It calls `http://127.0.0.1:8787`. The API already allows that origin.

## How a run works

```text
ingest → parse → diff → static → impact → tests
                                      \→ ai review
                    correlate → risk → optional fix → verify
```

1. Ingest clones the repository or unpacks the zip and snapshots the parent revision.
2. Parse extracts symbols, imports, and calls. Python and JavaScript are parsed. SQL and the other reviewable text formats are indexed and can match text rules.
3. Diff marks the files and symbols the change touches.
4. Static rules in `rules/` emit findings with file, line, evidence, impact, and a recommendation.
5. Impact walks the call graph and builds failure chains.
6. When a key is set, the model reviews only the diff, the neighbors, and the static findings.
7. Correlation merges repeated signals into one finding.
8. Risk writes the decision from `config/policy.yaml`.
9. Verify applies the named repairs, compiles, runs pytest, and rescores. The original tree is left intact.

## What gets read

Source is kept first. The scan stops at `max_files` (25000) or `max_total_mb` (200), whichever comes first, and records why each leftover file was left out. Per-file limits, minified-bundle skipping, and the graph cap (`max_graph_nodes`) are in `config/settings.yaml`.

| Extension | Treatment |
|---|---|
| `.py`, `.ipynb` | Parsed as Python. Notebooks are flattened to their code cells. |
| `.js`, `.jsx`, `.mjs`, `.ts`, `.tsx` | Parsed as JavaScript. |
| `.sql` | Indexed and matched by text rules. |
| `.yml`, `.yaml`, `.json`, `.toml`, `.md`, `.html`, `.css`, `.txt` | Indexed. YAML, JSON, TOML, and SQL can match text rules. |
| Other text | Read and stored. It is not parsed and does not produce rule findings. |

## Layout

```text
backend/     FastAPI pipeline, parsers, rules, risk, fixes
frontend/    Next.js workspace
config/      policy, pipeline, prompts, settings
rules/       YAML detectors (security and quality)
docs/        architecture, API, risk model, evaluation, report
tests/       engine tests and the planted-issue fixture
scripts/     setup, run, benchmark
```

## Configuration

| Variable | Where | Purpose |
|---|---|---|
| `OPENROUTER_API_KEY` | `.env` | Turns on the AI review node. Empty means the node is skipped. |
| `PERCEPTOR_MODEL` | `.env` | Overrides the model in `config/settings.yaml`. |
| `PERCEPTOR_API_TOKEN` | `.env` | Requires `x-api-key` (or `?api_key=`) on every route except `/api/health`. |
| `NEXT_PUBLIC_API_BASE` | `frontend/.env.local` | API the UI calls. Defaults to `http://127.0.0.1:8787`. |
| `NEXT_PUBLIC_API_TOKEN` | `frontend/.env.local` | Must match `PERCEPTOR_API_TOKEN` when that is set. It is visible in the browser. |

Local-path analysis is accepted only when the API is bound to loopback.

## Evaluation

On the planted fixture in `tests/fixtures.py`: 10 issues planted, 10 detected, 0 missed, decision NOT READY, score 43. Repairs clear every blocking finding. Figures and the timing fixture are in [docs/evaluation.md](docs/evaluation.md). Reproduce with:

```powershell
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python scripts\benchmark.py
```

## Limits

- Semantic parsing is Python and JavaScript. Other languages are read, not parsed.
- The drawn graph keeps the most connected neighbourhood, capped by `max_graph_nodes`.
- The AI review node sends at most the configured file budget, not the whole repository.
- Verification is a copied workspace plus a process timeout. It is not a container.
- These risk weights are a prototype policy, not a validated scientific model.

## Docs

- [Project report](docs/REPORT.md)
- [Architecture](docs/architecture.md)
- [Workflow](docs/workflow.md)
- [Risk model](docs/risk-model.md)
- [API](docs/api.md)
- [Evaluation](docs/evaluation.md)
