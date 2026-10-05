# Evaluation

Numbers come from `scripts/benchmark.py`, which writes `outputs/benchmark-results/benchmark.json`. They are not a general accuracy claim.

## Regression fixture

`tests/fixtures.py` holds a small base tree and a head tree that trips ten rules. The fixture lives in the test suite only. It is not shipped data and the analyzer never reads the expected list.

| | |
|---|---|
| Planted | 10 |
| Detected | 10 |
| Missed | 0 |
| Unlabeled extra findings | 0 |
| Recall on this set | 1.0 |
| Decision | NOT READY |
| Score | 43 |

`tests/test_engine.py` asserts the same thing, plus that the repair strategies clear every blocking finding and that duplicate signals merge into one finding.

## Latency

The synthetic trees are generated Python modules with a call chain. They are a timing fixture, not a vulnerability corpus, so zero findings there is expected. The last recorded run in `outputs/benchmark-results/benchmark.json`:

| Fixture | Files | Seconds |
|---|---|---|
| Small | 51 | 0.16 |
| Medium | 151 | 0.29 |
| Large | 501 | 0.96 |

Re-run the benchmark on your machine for current figures.

## Incremental analysis

Each analysis node is cached by content hash. Re-analyzing an unchanged repository serves downstream nodes from the cache. Ingest and parse always recompute, because a fresh clone gets a new workspace.

## How to reproduce

```powershell
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python scripts\benchmark.py
```

Real-repository accuracy is not measured here. Run the app on repositories you know and compare the findings with what you expect.
