from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from app.analysis.parse import language_of
from app.analysis.pyast import (
    call_names,
    first_value_guard,
    functions_by_name,
    joined_sql,
    lookup_risks,
    parse,
    queries_in_loops,
    return_ints,
    value_guard,
    walk_functions,
)
from app.analysis.types import AnalysisState, finding_dict
from app.config import Settings

HOOKS: dict = {}


def hook(name: str):
    def wrap(fn):
        HOOKS[name] = fn
        return fn

    return wrap


def _params(rule: dict) -> dict:
    return (rule.get("detect") or {}).get("params") or {}


def _changed(state: AnalysisState) -> set[tuple[str, str]]:
    return {(item["file"], item["qualname"]) for item in state.diff.get("changed_symbols", [])}


def _python_pairs(state: AnalysisState):
    paths = set(state.head) | set(state.base)
    for path in sorted(paths):
        if not path.endswith(".py"):
            continue
        yield path, state.base.get(path, ""), state.head.get(path, "")


@hook("sql_injection")
def sql_injection(rule: dict, state: AnalysisState, settings: Settings) -> list[dict]:
    keywords = [item.upper() for item in _params(rule).get("keywords", ["SELECT", "INSERT", "UPDATE", "DELETE"])]
    findings = []
    js_pattern = re.compile(r"`[^`]*\b(?:SELECT|INSERT|UPDATE|DELETE)\b[^`]*\$\{", re.IGNORECASE)
    for path, source in state.head.items():
        language = language_of(path, settings)
        if language == "python":
            tree = parse(source)
            if tree is None:
                continue
            owners = []
            for fn, qual in walk_functions(tree):
                owners.append((fn.lineno, getattr(fn, "end_lineno", fn.lineno) or fn.lineno, qual))
            for node in ast.walk(tree):
                if not isinstance(node, ast.JoinedStr):
                    continue
                built = joined_sql(node, keywords)
                if not built:
                    continue
                qual = next((name for start, end, name in owners if start <= node.lineno <= end), None)
                findings.append(
                    finding_dict(rule, path, node.lineno, f"Interpolated SQL: {built[0][:180]}", symbol=qual)
                )
        elif language == "javascript":
            for index, line in enumerate(source.splitlines(), start=1):
                if js_pattern.search(line):
                    findings.append(finding_dict(rule, path, index, line.strip()[:180]))
    return findings


@hook("unchecked_lookup")
def unchecked_lookup(rule: dict, state: AnalysisState, settings: Settings) -> list[dict]:
    markers = [item.lower() for item in _params(rule).get("lookup_markers", ["lookup", "fetch"])]
    findings = []
    for path, source in state.head.items():
        if language_of(path, settings) != "python":
            continue
        for risk in lookup_risks(source, markers):
            findings.append(
                finding_dict(
                    rule,
                    path,
                    risk["line"],
                    f"{risk['name']} is used without checking that the lookup returned a value.",
                    symbol=risk["qualname"],
                )
            )
    return findings


@hook("validation_removed")
def validation_removed(rule: dict, state: AnalysisState, settings: Settings) -> list[dict]:
    names = set(_params(rule).get("value_names", ["amount"]))
    findings = []
    for path, base, head in _python_pairs(state):
        if not base or not head:
            continue
        before = functions_by_name(base)
        after = functions_by_name(head)
        for qual, fn in after.items():
            old = before.get(qual)
            if old is None:
                continue
            if value_guard(old, names) and not value_guard(fn, names):
                findings.append(
                    finding_dict(
                        rule,
                        path,
                        fn.lineno,
                        f"{qual} no longer rejects empty or non-positive input.",
                        symbol=qual,
                    )
                )
    return findings


@hook("auth_removed")
def auth_removed(rule: dict, state: AnalysisState, settings: Settings) -> list[dict]:
    auth_calls = set(_params(rule).get("auth_calls", ["require_auth"]))
    findings = []
    for path, base, head in _python_pairs(state):
        if not base or not head:
            continue
        before = functions_by_name(base)
        after = functions_by_name(head)
        for qual, fn in after.items():
            old = before.get(qual)
            if old is None:
                continue
            removed = (call_names(old) & auth_calls) - call_names(fn)
            if removed:
                findings.append(
                    finding_dict(
                        rule,
                        path,
                        fn.lineno,
                        f"{qual} no longer calls {', '.join(sorted(removed))}.",
                        symbol=qual,
                    )
                )
    return findings


@hook("api_status_changed")
def api_status_changed(rule: dict, state: AnalysisState, settings: Settings) -> list[dict]:
    findings = []
    for path, base, head in _python_pairs(state):
        if not base or not head:
            continue
        if not any(pattern in path.lower() for pattern in settings.endpoint_file_patterns):
            continue
        before = functions_by_name(base)
        after = functions_by_name(head)
        for qual, fn in after.items():
            old = before.get(qual)
            if old is None:
                continue
            old_ints = return_ints(old)
            new_ints = return_ints(fn)
            if old_ints != new_ints and (old_ints or new_ints):
                findings.append(
                    finding_dict(
                        rule,
                        path,
                        fn.lineno,
                        f"{qual} response status changed from {old_ints or ['none']} to {new_ints or ['none']}.",
                        symbol=qual,
                    )
                )
    return findings


@hook("complexity")
def complexity(rule: dict, state: AnalysisState, settings: Settings) -> list[dict]:
    changed = _changed(state)
    findings = []
    for parsed in state.head_files:
        for symbol in parsed.symbols:
            if (symbol.file, symbol.qualname) not in changed or symbol.is_test:
                continue
            if symbol.complexity > settings.complexity_threshold:
                findings.append(
                    finding_dict(
                        rule,
                        symbol.file,
                        symbol.start,
                        f"Cyclomatic complexity is {symbol.complexity}. Threshold is {settings.complexity_threshold}.",
                        symbol=symbol.qualname,
                    )
                )
    return findings


@hook("long_function")
def long_function(rule: dict, state: AnalysisState, settings: Settings) -> list[dict]:
    changed = _changed(state)
    findings = []
    for parsed in state.head_files:
        for symbol in parsed.symbols:
            if (symbol.file, symbol.qualname) not in changed or symbol.is_test:
                continue
            length = symbol.end - symbol.start + 1
            if length > settings.function_length_threshold:
                findings.append(
                    finding_dict(
                        rule,
                        symbol.file,
                        symbol.start,
                        f"{symbol.qualname} is {length} lines. Threshold is {settings.function_length_threshold}.",
                        symbol=symbol.qualname,
                    )
                )
    return findings


@hook("query_in_loop")
def query_in_loop(rule: dict, state: AnalysisState, settings: Settings) -> list[dict]:
    names = set(_params(rule).get("call_names", ["execute", "query"]))
    findings = []
    for path, source in state.head.items():
        if language_of(path, settings) != "python":
            continue
        tree = parse(source)
        if tree is None:
            continue
        for fn, qual in walk_functions(tree):
            lines = queries_in_loops(fn, names)
            if lines:
                findings.append(
                    finding_dict(
                        rule,
                        path,
                        lines[0],
                        f"{qual} runs a query inside a loop ({len(lines)} call site{'s' if len(lines) != 1 else ''}).",
                        symbol=qual,
                    )
                )
    return findings


def _parse_requirements(text: str) -> dict[str, str | None]:
    found: dict[str, str | None] = {}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        match = re.match(r"([A-Za-z0-9_.-]+)\s*(?:[=<>!~]=?|==)\s*([A-Za-z0-9_.*+\-]+)", line)
        if match:
            found[match.group(1).lower()] = match.group(2)
            continue
        name = re.match(r"([A-Za-z0-9_.-]+)", line)
        if name:
            found[name.group(1).lower()] = None
    return found


def _version_key(value: str | None) -> tuple:
    if not value:
        return tuple()
    parts = []
    for piece in re.split(r"[.\-+]", value):
        if piece.isdigit():
            parts.append(int(piece))
        else:
            break
    return tuple(parts)


def _package_versions(text: str) -> dict[str, str]:
    try:
        document = json.loads(text)
    except json.JSONDecodeError:
        return {}
    found = {}
    for section in ("dependencies", "devDependencies"):
        for name, version in (document.get(section) or {}).items():
            found[name.lower()] = str(version).lstrip("^~=v")
    return found


@hook("dependency_downgrade")
def dependency_downgrade(rule: dict, state: AnalysisState, settings: Settings) -> list[dict]:
    findings = []
    for path in sorted(set(state.base) | set(state.head)):
        name = Path(path).name
        before = state.base.get(path, "")
        after = state.head.get(path, "")
        if before == after:
            continue
        pairs: list[tuple[str, str, str]] = []
        if name == "requirements.txt":
            old = _parse_requirements(before)
            new = _parse_requirements(after)
            for package, new_version in new.items():
                old_version = old.get(package)
                if old_version and new_version and _version_key(new_version) < _version_key(old_version):
                    pairs.append((package, old_version, new_version))
        elif name == "package.json":
            old = _package_versions(before)
            new = _package_versions(after)
            for package, new_version in new.items():
                old_version = old.get(package)
                if old_version and _version_key(new_version) < _version_key(old_version):
                    pairs.append((package, old_version, new_version))
        for package, old_version, new_version in pairs:
            findings.append(
                finding_dict(
                    rule,
                    path,
                    1,
                    f"{package} moved from {old_version} to {new_version}.",
                    symbol=package,
                )
            )
    return findings


@hook("test_removed")
def test_removed(rule: dict, state: AnalysisState, settings: Settings) -> list[dict]:
    changed_names = {item["name"] for item in state.diff.get("changed_symbols", []) if not item.get("is_test")}
    if not changed_names:
        return []
    findings = []
    paths = sorted(set(state.base) | set(state.head))
    for path in paths:
        if not path.endswith(".py"):
            continue
        if "/tests/" not in f"/{path}" and not Path(path).name.startswith("test_"):
            continue
        before = functions_by_name(state.base.get(path, ""))
        after = functions_by_name(state.head.get(path, ""))
        for qual, fn in before.items():
            if not fn.name.startswith("test_") or qual in after:
                continue
            segment = ast.get_source_segment(state.base.get(path, ""), fn) or ""
            covered = sorted(name for name in changed_names if name in segment)
            if not covered:
                continue
            findings.append(
                finding_dict(
                    rule,
                    path if path in state.head else path,
                    1,
                    f"Removed {fn.name}, which referenced {', '.join(covered)}.",
                    symbol=fn.name,
                    source="tests",
                )
            )
    return findings


def _suppressed(finding: dict, rule: dict, state: AnalysisState, path_filters: list, markers: list[str]) -> bool:
    """Shared noise filter, driven entirely by the rule file."""
    path = finding.get("file", "")
    if any(expression.search(path) for expression in path_filters):
        return True
    if markers:
        lines = state.head.get(path, "").splitlines()
        index = int(finding.get("line") or 1) - 1
        nearby = " ".join(lines[max(0, index - 1) : index + 1]).lower()
        return any(marker in nearby for marker in markers)
    return False


def run_rules(rules: list[dict], state: AnalysisState, settings: Settings, stage: str) -> list[dict]:
    findings: list[dict] = []
    for rule in rules:
        if rule.get("stage", "static") != stage:
            continue
        detect = rule.get("detect") or {}
        kind = detect.get("type")
        if kind == "regex":
            produced = _run_regex(rule, state, settings)
        elif kind == "hook":
            fn = HOOKS.get(detect.get("name"))
            if fn is None:
                continue
            produced = fn(rule, state, settings)
        else:
            continue
        path_filters = [re.compile(item) for item in rule.get("exclude_paths") or []]
        markers = [str(item).lower() for item in rule.get("suppress_markers") or settings.suppress_markers]
        findings.extend(item for item in produced if not _suppressed(item, rule, state, path_filters, markers))
    return findings


def _run_regex(rule: dict, state: AnalysisState, settings: Settings) -> list[dict]:
    detect = rule.get("detect") or {}
    patterns = list(detect.get("patterns") or [])
    if detect.get("pattern"):
        patterns.append(detect["pattern"])
    compiled = []
    for pattern in patterns:
        try:
            compiled.append(re.compile(pattern))
        except re.error:
            continue
    languages = set(detect.get("languages") or settings.regex_languages)
    path_filters = [re.compile(item) for item in detect.get("exclude_paths") or []]
    line_filters = [re.compile(item) for item in detect.get("exclude_lines") or []]
    findings = []
    for path, source in state.head.items():
        if language_of(path, settings) not in languages:
            continue
        if any(expression.search(path) for expression in path_filters):
            continue
        for index, line in enumerate(source.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith("//"):
                continue
            if any(expression.search(line) for expression in line_filters):
                continue
            if any(expression.search(line) for expression in compiled):
                findings.append(finding_dict(rule, path, index, stripped[:400]))
    return findings
