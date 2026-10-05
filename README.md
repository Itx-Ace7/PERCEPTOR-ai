# Perceptor.AI

Predictive Engineering Review & Code Evaluation for Proactive Threat Observation & Risk.

Perceptor.AI answers a release question: if this change ships, what can break, why, and what has to happen before it is ready. It builds a symbol and dependency graph, diffs the change against the parent revision, runs a deterministic rule engine, traces the blast radius, optionally asks a model to review that evidence, and turns the result into an explainable release decision.

The interface is a graph. A pipeline canvas shows each stage as a live node. A blast-radius map shows the components the change can reach. Each finding keeps the evidence that produced it.

- Live app: [perceptor-ai-release.vercel.app](https://perceptor-ai-release.vercel.app)
- GitHub: [github.com/Itx-Ace7/PERCEPTOR-ai](https://github.com/Itx-Ace7/PERCEPTOR-ai)
- Local app: [http://localhost:3000](http://localhost:3000) after the commands below

The Vercel app is the interface. With the API running on this machine, open the live app in the same browser. It calls `http://127.0.0.1:8787`.

## Run

```powershell
.\scripts\setup.ps1
.\scripts\run.ps1
```

Open [http://localhost:3000](http://localhost:3000), paste a GitHub repository, or upload a zip.

The API listens on `http://127.0.0.1:8787`. The deterministic pipeline does not need a model key. To enable the AI review node, copy `.env.example` to `.env` and set `OPENROUTER_API_KEY`.

## Layout

```text
backend/     FastAPI pipeline, parsers, rules, risk, fixes
frontend/    Next.js graph workspace
config/      policy, pipeline, prompts
rules/       YAML detectors
docs/        architecture, API, evaluation, report
tests/       engine tests and in-code fixtures
scripts/     setup, run, benchmark
```

## Docs

- [Project report](docs/REPORT.md)
- [Architecture](docs/architecture.md)
- [Workflow](docs/workflow.md)
- [Risk model](docs/risk-model.md)
- [API](docs/api.md)
- [Evaluation](docs/evaluation.md)
