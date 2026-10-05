# Perceptor.AI

**Predictive Engineering Review & Code Evaluation for Proactive Threat Observation & Risk**

Problem statement: PSA03 — AI Code Review & Release-Risk Assistant  
Repository: https://github.com/Itx-Ace7/PERCEPTOR-ai  
Live app: https://perceptor-ai-release.vercel.app

## 1. Problem

A release fails for reasons a file-level comment cannot see. An authentication check disappears from one handler, eight callers keep compiling, and the tests that would have caught it were deleted in the same change. A reviewer who only sees the diff, and a model that only sees one file, both miss the chain.

Perceptor.AI is built to answer a different question: if this change is released, what can break, why, which components are on the path, and whether a proposed fix actually holds.

## 2. Approach

The system reviews the change in the context of the repository.

1. It ingests a git repository or a zip, and snapshots the parent revision.
2. It parses Python and JavaScript into symbols, imports, and calls.
3. It diffs the change and marks the symbols the hunks touch.
4. It runs a deterministic rule engine before any model call.
5. It walks the call graph to build a blast radius and a failure chain.
6. It asks a model, when a key is configured, to review only that evidence.
7. It merges duplicate signals into one explainable finding.
8. It scores release risk from a written policy, not from an unexplained model number.
9. It can repair the tree and verify the repair with a compile and the test suite.

The part a judge can see is the graph. The pipeline is a node canvas. The blast radius is the repository. Each finding keeps the checks that support it.

## 3. What is different

A typical AI reviewer sends code to a model and prints comments. Perceptor.AI does the opposite order:

```text
repository -> structure -> diff -> static evidence -> impact
          -> model, over that evidence only -> correlated finding
          -> policy decision -> repair -> verification
```

The model can be absent. A full NOT READY decision is produced with no API key.

## 4. System

The backend is FastAPI. The workspace is Next.js. Stages, weights, thresholds, prompts, and detectors are files under `config/` and `rules/`, not constants buried in the UI.

Python files are parsed with tree-sitter and then with the standard-library AST, which supplies calls, complexity, and the semantic hooks. JavaScript symbols come from tree-sitter. The graph is NetworkX. Long work is a background run with a server-sent event stream and a bundle endpoint the UI can refetch.

Rules cover interpolated SQL, secrets, command execution, unsafe configuration, cross-site scripting sinks, removed authentication, removed validation, unguarded lookups, changed response status, queries in loops, dependency downgrades, and deleted regression tests. Repairs are strategies named by those rules: parameterized SQL, secrets moved to the environment, restored checks, restored tests, restored pins.

Verification copies the workspace, applies those repairs, runs `compileall` and `pytest`, and rescores. The original tree is left intact.

## 5. Release decision

Weights: security 30%, regression 25%, deployment 20%, testing 15%, performance 10%. Critical findings add 40 points to their dimension, high 25, medium 12, low 5, info 2. A dimension score is `100 × (1 − e^(−points / scale))`, so one more finding never lowers a score and a huge pile of findings still stays inside 0–100. The overall score is the weighted sum.

The decision is separate from the band. Critical or high findings in the blocking categories mean NOT READY. Remaining non-blocking findings mean READY WITH WARNINGS. No findings means READY. The screen shows the reasons, the chain, and the recommended actions. Details are in [risk-model.md](risk-model.md). These thresholds are a prototype policy.

## 6. Interface

- **Pipeline.** Each stage is a draggable node with a status, a duration, and its own output. Edges follow `depends_on` in the pipeline file. Cached nodes are marked.
- **Blast radius.** A round, directed tree. Node size follows connectivity, callers and callees stay oriented, and the most connected symbols are listed beside the map. Simulate release walks the failure chain on that map.
- **Findings.** Severity, file, evidence, impact, recommendation, and a drawing of the checks that support the finding. The excerpt is a read-only editor.
- **Decision.** The status, the score ring, dimension bars, the contribution of each weight, and the before/after verification.
- **Report.** Markdown and SARIF 2.1.0.

## 7. Evaluation

Measured on this build and recorded in `outputs/benchmark-results/benchmark.json`.

The regression fixture in `tests/fixtures.py` plants 10 issues. The analyzer detected 10, missed 0, and produced no extra unlabeled findings. The decision was NOT READY and the score was 43.

On the same fixture the repair strategies clear every blocking finding. The query inside a loop is not repaired automatically; it is medium and not a blocker, so the status becomes READY WITH WARNINGS.

Synthetic trees of 51, 151, and 501 files are timed by `scripts/benchmark.py`; re-run it for figures on your machine. A repeated run serves the downstream stages from the node cache.

These figures describe this fixture and this machine. They are not a general detection-rate claim.

## 8. Limitations

- Semantic analysis is implemented for Python and JavaScript. SQL, YAML, JSON, TOML, Markdown, HTML, CSS, and plain text are indexed. YAML, JSON, TOML, and SQL can match text rules. Other languages are read and stored, and they do not produce rule findings.
- A scan keeps source first and stops at the file count or the total size in `config/settings.yaml`. Each file left out is recorded with a reason.
- The sandbox is a copied workspace plus a process timeout. It is not a container. Docker was not available here.
- The rule engine is tree-sitter, the Python AST, and YAML patterns. Semgrep is not required and is not bundled.
- Without an OpenRouter key the AI review node records that it is waiting. It does not invent findings.
- The query-in-loop repair is intentionally not automatic, so a repaired tree can still end at READY WITH WARNINGS.
- The blast-radius view keeps the neighbourhood of the change, capped by `max_graph_nodes`, so a large repository stays readable.

## 9. How to run

```powershell
.\scripts\setup.ps1
.\scripts\run.ps1
```

Then open http://localhost:3000, paste a GitHub repository URL, or upload a zip. Set `OPENROUTER_API_KEY` in `.env` when the model node should take part.
