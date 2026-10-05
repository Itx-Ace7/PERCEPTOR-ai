# Architecture

Perceptor.AI separates deterministic evidence from model reasoning. The model never sees the whole repository, and it is not the source of the release score.

```text
Web UI  -- REST + SSE -->  FastAPI
                              |
                         Pipeline runner
                              |
        ingest -> parse -> diff -> static -> impact -> ai review
                    |                 \-> test gaps ----\
                    |                                    correlate -> risk
                    optional: fix -> verify
```

## Stages

The stage list, dependencies, and canvas positions live in `config/pipeline.yaml`. The runner executes that file. Optional stages (`fix`, `verify`) run when the user asks to verify.

| Stage | What it produces |
|---|---|
| Ingest | A workspace. GitHub URLs are cloned, local paths are copied. Zip archives are extracted with a path check. |
| Parse | Symbols, imports, and calls. Python uses tree-sitter for the syntax tree and the stdlib AST for calls, complexity, and hooks. JavaScript symbols come from tree-sitter. |
| Diff | Added, modified, and deleted files, plus symbols whose line range overlaps a hunk. |
| Static | YAML regex rules and AST hooks in `rules/`. |
| Impact | Callers, callees, affected endpoints, and failure chains on a NetworkX graph. |
| Test gaps | Tests removed while the functions they named were changing. |
| AI review | OpenRouter, only over the diff, neighbors, and static findings. Skipped cleanly when no key is set. |
| Correlate | One finding per issue, with every supporting check attached. |
| Risk | Weighted, explainable decision from `config/policy.yaml`. |
| Fix / Verify | Deterministic repairs, then compile, pytest, and a rescore. |

## Event contract

The runner appends events that the UI consumes:

- `run.started`, `run.completed`, `run.failed`
- `node.started`, `node.completed`
- `graph.updated`
- `finding.created`
- `risk.updated`

`GET /api/runs/{id}` returns the full bundle, so a refresh does not depend on having seen every event.

## Cache

Each analysis node is cached by the hash of the file contents, the config and rule files, and the hashes of its parent outputs. A repeated run recomputes ingest and parse, because the new workspace has a new commit, and serves the downstream nodes from cache.

## What is read

`config/settings.yaml` sets `max_files` and `max_total_mb`. Source code is ranked ahead of other text, and both limits are applied before anything is read, so the cut only drops the least useful files. Each skipped file is stored with a reason. Python and JavaScript are parsed into symbols. SQL, YAML, JSON, and TOML can match text rules. The blast-radius view keeps the connected neighbourhood, capped by `max_graph_nodes`.

## Isolation

Untrusted trees are copied into `data/workspaces` and are not executed as services. Verification runs `compileall` and `pytest` in that copy with a timeout from `config/settings.yaml`. This is process isolation, not a container. Docker was not available in the build environment.

## Storage

SQLite holds repositories, runs, the event log, artifacts, and the node cache. Paths are in `config/settings.yaml`.
