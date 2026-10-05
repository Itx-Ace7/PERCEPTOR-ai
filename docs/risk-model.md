# Risk model

The score is a prototype policy. The weights are a design choice, not a validated scientific model. They live in `config/policy.yaml` and can be edited without code changes.

## Weights

| Dimension | Weight |
|---|---|
| Security | 0.30 |
| Regression | 0.25 |
| Deployment | 0.20 |
| Testing | 0.15 |
| Performance | 0.10 |

Quality is displayed when quality findings exist. Its default weight is 0, so it does not move the overall score.

## Points

Each finding adds points to the dimension mapped from its category:

| Severity | Points |
|---|---|
| Critical | 40 |
| High | 25 |
| Medium | 12 |
| Low | 5 |

Points are summed per dimension. A finding that merges several hits of one rule in one file counts `points × (1 + g × log2(n))` for `n` hits, so repeats add less than a new issue. Both `g` (`occurrence_growth`) and the scale `s` live in the `scoring` block of `config/policy.yaml`.

A dimension score is `100 × (1 − e^(−points / s))`. It is strictly increasing, so adding a finding never lowers a score, and 1000 points still scores higher than 500. A hard cap at 100 would hide that difference. The overall score is the weighted sum of the dimension scores, rounded. Bands:

| Score | Band |
|---|---|
| 0-25 | Low |
| 26-50 | Medium |
| 51-75 | High |
| 76-100 | Critical |

## Decision

The band is not the decision.

- **NOT READY** when any finding is Critical in any category, or High in security, regression, API, deployment, config, dependency, or testing (`always_blocking_severities`, `blocker_severities` and `blocker_categories` in the policy).
- **READY WITH WARNINGS** when findings remain but none of them are blocking.
- **READY** when there are no findings.

The decision screen lists the blocking findings, the failure chain, and the recommendations. That explanation is assembled from the finding records. It is not a second model call.
