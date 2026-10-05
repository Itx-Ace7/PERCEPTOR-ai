# API

Base URL: `http://127.0.0.1:8787`

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Liveness and product version |
| GET | `/api/meta` | Product copy, pipeline, policy, model name |
| GET | `/api/runs` | Recent runs |
| POST | `/api/runs` | Start a run. Body: `{ "source_type": "github" \| "path", "url"?, "path"? }` |
| POST | `/api/runs/upload` | Multipart zip upload |
| GET | `/api/runs/{id}` | Full bundle: nodes, findings, graph, impact, risk, verification |
| GET | `/api/runs/{id}/events` | Server-sent events |
| POST | `/api/runs/{id}/verify` | Run the fix and verify stages |
| GET | `/api/runs/{id}/report.md` | Markdown report |
| GET | `/api/runs/{id}/report.sarif` | SARIF 2.1.0 |

Git URLs must be `https://` or `git@`. Zip entries that escape the workspace are rejected. Local-path runs are accepted only when the server is bound to loopback, or `server.allow_local_paths` is set.

## Authentication

Set `PERCEPTOR_API_TOKEN` on the server to require a token on every route except `/api/health`. Send it as the `x-api-key` header, or as `?api_key=` for `EventSource` and download links, which cannot set headers. With no token set the API is open, which suits local development. The token guards a shared deployment against casual access. It is not per-user authentication.

## Bundle fields worth knowing

`skipped` lists every file that was left out, each with `path`, `reason` (`binary`, `too large`, `file limit reached`, `path not valid on this OS`, `unreadable notebook`) and `size`. Jupyter notebooks are analysed as their code cells.

## Limits and retention

`config/settings.yaml` sets the file limits, the number of concurrent runs, the model time budget, and how many finished runs are kept (`retention.keep_runs`). Older runs are deleted with their workspaces. Runs interrupted by a restart are marked FAILED at startup.

## Finding shape

```json
{
  "id": "SEC-SQLI-001",
  "rule_id": "SEC-SQLI",
  "severity": "CRITICAL",
  "category": "SECURITY",
  "file": "backend/repo.py",
  "line": 2,
  "title": "SQL built with string interpolation",
  "evidence": "Interpolated SQL: SELECT * FROM rows WHERE owner_id = ?",
  "impact": "Untrusted input can change the query.",
  "recommendation": "Use a parameterized query.",
  "confidence": 0.96,
  "sources": ["static"],
  "checks": [{ "source": "static", "rule_id": "SEC-SQLI", "line": 2, "evidence": "..." }]
}
```

## Risk shape

`decision` is `NOT_READY`, `READY_WITH_WARNINGS`, or `READY`. `overall` is the score band. `why`, `actions`, `waterfall`, and `failure_chain` are the explanation.
