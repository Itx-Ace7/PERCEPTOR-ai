from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from app.analysis.autofix import apply_fixes
from app.analysis.llm import stage_ai
from app.analysis.snapshots import copy_worktree, read_tree, write_changed
from app.analysis.stages import (
    stage_correlate,
    stage_diff,
    stage_impact,
    stage_parse,
    stage_risk,
    stage_static,
    stage_tests,
)
from app.analysis.types import AnalysisState
from app.config import Settings


def _counts(findings: list[dict]) -> dict[str, int]:
    buckets = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "INFO": 0}
    for finding in findings:
        buckets[finding.get("severity", "INFO")] = buckets.get(finding.get("severity", "INFO"), 0) + 1
    return buckets


def _run(command: list[str], cwd: Path, timeout: int) -> tuple[str, str, int]:
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return "TIMEOUT", "timed out", 124
    except OSError as exc:
        return "ERROR", str(exc), 1
    output = ((completed.stdout or "") + (completed.stderr or ""))[-4000:]
    return completed.stdout or "", output, completed.returncode


def _pytest_stats(output: str, code: int) -> dict:
    passed = int(re.search(r"(\d+) passed", output).group(1)) if re.search(r"(\d+) passed", output) else 0
    failed = int(re.search(r"(\d+) failed", output).group(1)) if re.search(r"(\d+) failed", output) else 0
    if code == 5:  # pytest: no tests collected
        return {"status": "SKIPPED", "passed": 0, "failed": 0, "output": output}
    if "No module named pytest" in output:
        return {"status": "SKIPPED", "passed": 0, "failed": 0, "output": output}
    return {"status": "PASS" if code == 0 else "FAIL", "passed": passed, "failed": failed, "output": output}


def rescore(base: dict[str, str], head_root: Path, settings: Settings, with_ai: bool) -> AnalysisState:
    state = AnalysisState(workspace=str(head_root), base=base, head=read_tree(head_root, settings))
    stage_parse(state, settings)
    stage_diff(state, settings)
    stage_static(state, settings)
    stage_impact(state, settings)
    stage_tests(state, settings)
    if with_ai:
        stage_ai(state, settings)
    else:
        state.ai_findings = []
        state.ai_note = "skipped during verification"
    stage_correlate(state, settings)
    stage_risk(state, settings)
    return state


def execute_verification(
    workspace: Path,
    base: dict[str, str],
    findings: list[dict],
    before_risk: dict | None,
    settings: Settings,
) -> dict:
    fixed = workspace.parent / f"{workspace.name}-fixed"
    copy_worktree(workspace, fixed)
    current = read_tree(fixed, settings)
    updated, notes = apply_fixes(current, base, findings, settings.rules)
    write_changed(fixed, current, updated, settings)
    after = rescore(base, fixed, settings, with_ai=bool(settings.api_key))
    compile_dir = "backend" if (fixed / "backend").is_dir() else "."
    _, build_output, build_code = _run([sys.executable, "-m", "compileall", "-q", compile_dir], fixed, settings.sandbox_timeout)
    _, test_output, test_code = _run([sys.executable, "-m", "pytest", "-q", "--tb=line"], fixed, settings.sandbox_timeout)
    before_findings = findings
    after_risk = after.risk or {}
    return {
        "workspace": str(fixed),
        "fixes": notes,
        "before": {
            "findings": len(before_findings),
            "by_severity": _counts(before_findings),
            "decision": (before_risk or {}).get("decision", "UNKNOWN"),
            "score": (before_risk or {}).get("score", 0),
        },
        "after": {
            "findings": len(after.findings),
            "by_severity": _counts(after.findings),
            "decision": after_risk.get("decision", "UNKNOWN"),
            "decision_label": after_risk.get("decision_label", ""),
            "score": after_risk.get("score", 0),
            "risk": after_risk,
        },
        "build": {"status": "PASS" if build_code == 0 else "FAIL", "output": build_output},
        "tests": _pytest_stats(test_output, test_code),
        "remaining": after.findings,
        "release_status": after_risk.get("decision", "UNKNOWN"),
        "graph": after.graph,
    }
