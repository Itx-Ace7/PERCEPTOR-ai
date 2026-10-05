from __future__ import annotations

import json


def markdown_report(bundle: dict) -> str:
    run = bundle.get("run", {})
    repo = bundle.get("repository", {})
    risk = bundle.get("risk") or {}
    impact = (bundle.get("impact") or {}).get("counts", {})
    lines = [
        f"# {bundle.get('product', {}).get('name', 'Perceptor.AI')} release report",
        "",
        f"- Repository: {repo.get('name', 'unknown')}",
        f"- Commit: {repo.get('commit_sha', '')}",
        f"- Run: {run.get('id', '')}",
        f"- Status: {risk.get('decision_label', run.get('status', ''))}",
        f"- Score: {risk.get('score', 'n/a')} ({risk.get('overall', 'n/a')})",
        "",
        "## Why",
        "",
    ]
    for reason in risk.get("why") or ["No explanation was produced."]:
        lines.append(f"- {reason}")
    lines.extend(["", "## Change impact", ""])
    for key, label in (
        ("changed_files", "Changed files"),
        ("changed_symbols", "Changed symbols"),
        ("affected_symbols", "Affected symbols"),
        ("affected_apis", "Affected APIs"),
        ("affected_tests", "Affected tests"),
        ("regression_paths", "Failure chains"),
    ):
        lines.append(f"- {label}: {impact.get(key, 0)}")
    skipped = bundle.get("skipped") or []
    if skipped:
        lines.extend(["", "## Files not analysed", ""])
        for item in skipped:
            lines.append(f"- `{item.get('path')}`: {item.get('reason')} ({max(1, int(item.get('size', 0)) // 1024)} KB)")
    lines.extend(["", "## Findings", ""])
    findings = bundle.get("findings") or []
    if not findings:
        lines.append("No findings.")
    for finding in findings:
        lines.append(
            f"- **{finding.get('severity')}** `{finding.get('id')}` {finding.get('title')} "
            f"({finding.get('file')}:{finding.get('line')})"
        )
        if finding.get("evidence"):
            lines.append(f"  - Evidence: {finding['evidence'].splitlines()[0]}")
        if finding.get("recommendation"):
            lines.append(f"  - Recommendation: {finding['recommendation']}")
    verification = bundle.get("verification")
    if verification:
        lines.extend(
            [
                "",
                "## Verification",
                "",
                f"- Before: {verification.get('before', {}).get('decision')} / {verification.get('before', {}).get('findings')} findings",
                f"- After: {verification.get('release_status')} / {verification.get('after', {}).get('findings')} findings",
                f"- Build: {verification.get('build', {}).get('status')}",
                f"- Tests: {verification.get('tests', {}).get('status')} "
                f"({verification.get('tests', {}).get('passed', 0)} passed, {verification.get('tests', {}).get('failed', 0)} failed)",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def sarif_report(bundle: dict) -> dict:
    rules = []
    seen = set()
    results = []
    for finding in bundle.get("findings") or []:
        rule_id = finding.get("rule_id") or finding.get("id")
        if rule_id not in seen:
            seen.add(rule_id)
            rules.append(
                {
                    "id": rule_id,
                    "shortDescription": {"text": finding.get("title", rule_id)},
                    "help": {"text": finding.get("recommendation", "")},
                }
            )
        level = {"CRITICAL": "error", "HIGH": "error", "MEDIUM": "warning", "LOW": "note"}.get(finding.get("severity"), "warning")
        results.append(
            {
                "ruleId": rule_id,
                "level": level,
                "message": {"text": finding.get("evidence") or finding.get("title", "")},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": finding.get("file", "")},
                            "region": {"startLine": int(finding.get("line") or 1)},
                        }
                    }
                ],
            }
        )
    return {
        "version": "2.1.0",
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": bundle.get("product", {}).get("name", "Perceptor.AI"),
                        "version": bundle.get("product", {}).get("version", "1.0.0"),
                        "rules": rules,
                    }
                },
                "results": results,
            }
        ],
    }


def sarif_text(bundle: dict) -> str:
    return json.dumps(sarif_report(bundle), indent=2)
