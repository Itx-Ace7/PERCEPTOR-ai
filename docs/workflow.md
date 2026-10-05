# Workflow

1. The user pastes an `https://` or `git@` URL, or uploads a zip.
2. Ingest materializes a workspace and snapshots the parent revision (`HEAD~1`) when one exists.
3. Parse builds the symbol graph.
4. Diff marks the files and symbols that moved.
5. Static rules and the test-gap hook emit findings with file, line, evidence, impact, and a recommendation.
6. Impact walks call edges out to the configured depth and builds failure chains from the changed symbol back through its callers to an endpoint.
7. If `OPENROUTER_API_KEY` is set, the review prompt in `config/prompts/review.txt` is filled with the diff, neighboring symbols, and static findings. Secrets that match the redaction patterns are removed before the request. Findings that name a file outside the tree are dropped.
8. Correlation merges repeated signals for the same rule and file, and merges a model finding with a static one when they share a file, category, and nearby lines.
9. The risk engine writes NOT READY, READY WITH WARNINGS, or READY, plus the reasons and the failure chain.
10. **Generate fixes and verify** copies the workspace, applies the repair strategies named in the rule files, compiles the Python, runs pytest, and rescores.

The UI follows the same order: pipeline canvas, blast radius, findings, decision, report. The blast radius is a round directed tree sized by connectivity. Simulate release walks the failure chain on that map.
