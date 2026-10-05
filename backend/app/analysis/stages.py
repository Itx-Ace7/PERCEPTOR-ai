from __future__ import annotations

import difflib
import math
import re
from collections import defaultdict
from pathlib import Path

import networkx as nx

from app.analysis.hooks import run_rules
from app.analysis.parse import language_of, parse_source
from app.analysis.types import AnalysisState, ParsedFile, redact
from app.config import Settings


def _preview_counts(findings: list[dict]) -> list[str]:
    buckets: dict[str, int] = defaultdict(int)
    for finding in findings:
        buckets[finding["severity"]] += 1
    if not buckets:
        return ["No findings"]
    order = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
    return [f"{buckets[name]} {name.lower()}" for name in order if buckets[name]]


def stage_parse(state: AnalysisState, settings: Settings) -> dict:
    state.head_files = []
    state.base_files = []
    languages = set()
    for path, source in sorted(state.head.items()):
        languages.add(language_of(path, settings))
        parsed = parse_source(path, source, settings)
        if parsed is not None:
            state.head_files.append(parsed)
    for path, source in sorted(state.base.items()):
        parsed = parse_source(path, source, settings)
        if parsed is not None:
            state.base_files.append(parsed)
    state.languages = sorted(languages)
    symbols = sum(len(item.symbols) for item in state.head_files)
    parsers = sorted({item.parser for item in state.head_files}) or ["none"]
    return {
        "preview": [
            f"{len(state.head)} files",
            f"{symbols} symbols",
            f"parsers: {', '.join(parsers)}",
        ],
        "head_files": [item.to_dict() for item in state.head_files],
        "base_files": [item.to_dict() for item in state.base_files],
        "languages": state.languages,
    }


def restore_parse(state: AnalysisState, payload: dict) -> None:
    state.head_files = [ParsedFile.from_dict(item) for item in payload.get("head_files", [])]
    state.base_files = [ParsedFile.from_dict(item) for item in payload.get("base_files", [])]
    state.languages = list(payload.get("languages", []))


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _changed_lines(before: str, after: str) -> list[int]:
    matcher = difflib.SequenceMatcher(a=before.splitlines(), b=after.splitlines())
    lines: set[int] = set()
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if j1 == j2:
            lines.add(max(j1, 1))
        else:
            lines.update(range(j1 + 1, j2 + 1))
    return sorted(lines)


def _overlaps(start: int, end: int, lines: list[int]) -> bool:
    if not lines:
        return False
    wanted = set(lines)
    return any(line in wanted for line in range(start, end + 1))


def stage_diff(state: AnalysisState, settings: Settings) -> dict:
    paths = set(state.base) | set(state.head)
    changed_files = []
    for path in sorted(paths):
        before = state.base.get(path)
        after = state.head.get(path)
        if before is not None:
            before = _normalize_newlines(before)
        if after is not None:
            after = _normalize_newlines(after)
        if before == after:
            continue
        if before is None:
            status = "added"
            lines = list(range(1, after.count("\n") + 1))
        elif after is None:
            status = "deleted"
            lines = []
        else:
            status = "modified"
            lines = _changed_lines(before, after)
        changed_files.append({"path": path, "status": status, "lines": lines})
    line_map = {item["path"]: item["lines"] for item in changed_files}
    status_map = {item["path"]: item["status"] for item in changed_files}
    changed_symbols = []
    for parsed in state.head_files:
        status = status_map.get(parsed.path)
        if status is None:
            continue
        for symbol in parsed.symbols:
            if status == "added" or _overlaps(symbol.start, symbol.end, line_map.get(parsed.path, [])):
                changed_symbols.append(
                    {
                        "id": symbol.sid,
                        "name": symbol.name,
                        "qualname": symbol.qualname,
                        "file": symbol.file,
                        "kind": symbol.kind,
                        "start": symbol.start,
                        "end": symbol.end,
                        "is_test": symbol.is_test,
                    }
                )
    code_changes = [
        item["path"]
        for item in changed_files
        if language_of(item["path"], settings) in settings.review_code_languages
    ]
    scope = "diff" if code_changes else "snapshot"
    review_files = _review_paths(state, settings, code_changes if scope == "diff" else [])
    state.diff = {
        "changed_files": changed_files,
        "changed_symbols": changed_symbols,
        "added": [item["path"] for item in changed_files if item["status"] == "added"],
        "modified": [item["path"] for item in changed_files if item["status"] == "modified"],
        "deleted": [item["path"] for item in changed_files if item["status"] == "deleted"],
        "scope": scope,
        "review_files": review_files,
    }
    if scope == "snapshot":
        preview = [f"Full snapshot · {len(review_files)} files", "No parent delta"]
    else:
        preview = [f"{len(changed_files)} files changed", f"{len(changed_symbols)} symbols touched"]
    return {"preview": preview, "diff": state.diff}


def _review_paths(state: AnalysisState, settings: Settings, changed_paths: list[str]) -> list[str]:
    skip = settings.review_skip_names
    if changed_paths:
        selected = [path for path in changed_paths if Path(path).name not in skip]
        return selected[: settings.llm_max_files]
    ranked: list[tuple[int, int, str]] = []
    for path, source in state.head.items():
        if Path(path).name in skip:
            continue
        language = language_of(path, settings)
        if language not in settings.review_languages:
            continue
        priority = 0 if language in settings.review_code_languages else 1
        ranked.append((priority, len(source), path))
    ranked.sort()
    return [path for _, _, path in ranked[: settings.llm_max_files]]


def restore_diff(state: AnalysisState, payload: dict) -> None:
    state.diff = payload.get("diff", {})


def stage_static(state: AnalysisState, settings: Settings) -> dict:
    state.static_findings = run_rules(settings.rules, state, settings, "static")
    return {"preview": _preview_counts(state.static_findings), "static_findings": state.static_findings}


def restore_static(state: AnalysisState, payload: dict) -> None:
    state.static_findings = list(payload.get("static_findings", []))


def stage_tests(state: AnalysisState, settings: Settings) -> dict:
    state.test_findings = run_rules(settings.rules, state, settings, "tests")
    removed = len(state.test_findings)
    return {
        "preview": [f"{removed} coverage gap{'s' if removed != 1 else ''}" if removed else "No removed regression tests"],
        "test_findings": state.test_findings,
    }


def restore_tests(state: AnalysisState, payload: dict) -> None:
    state.test_findings = list(payload.get("test_findings", []))


def _index_files(files: list[ParsedFile]) -> dict[str, ParsedFile]:
    return {item.path: item for item in files}


def _resolve_call(name: str, file: str, by_name: dict[str, list]) -> str | None:
    candidates = by_name.get(name, [])
    if not candidates:
        return None
    same = [item for item in candidates if item.file == file]
    if len(same) == 1:
        return same[0].sid
    if len(candidates) == 1:
        return candidates[0].sid
    return None


def build_graph(state: AnalysisState, settings: Settings) -> dict:
    graph = nx.DiGraph()
    by_name: dict[str, list] = defaultdict(list)
    stems: dict[str, str] = {}
    changed_files = {item["path"] for item in state.diff.get("changed_files", [])}
    changed_ids = {item["id"] for item in state.diff.get("changed_symbols", [])}
    snapshot = state.diff.get("scope") == "snapshot"
    review_files = set(state.diff.get("review_files") or [])
    for parsed in state.head_files:
        stems[Path(parsed.path).stem] = parsed.path
        file_id = f"file:{parsed.path}"
        graph.add_node(
            file_id,
            label=Path(parsed.path).name,
            kind="file",
            file=parsed.path,
            language=parsed.language,
            changed=parsed.path in changed_files or (snapshot and parsed.path in review_files),
            severity=None,
        )
        for symbol in parsed.symbols:
            by_name[symbol.name].append(symbol)
            graph.add_node(
                symbol.sid,
                label=symbol.qualname,
                kind=symbol.kind,
                file=symbol.file,
                line=symbol.start,
                changed=symbol.sid in changed_ids or (snapshot and symbol.file in review_files),
                is_test=symbol.is_test,
                severity=None,
            )
            graph.add_edge(file_id, symbol.sid, kind="contains")
    for parsed in state.head_files:
        file_id = f"file:{parsed.path}"
        for imported in parsed.imports:
            stem = Path(imported.replace("\\", "/")).stem
            target = stems.get(stem)
            if target and target != parsed.path:
                graph.add_edge(file_id, f"file:{target}", kind="imports")
        for symbol in parsed.symbols:
            for callee in symbol.calls:
                target = _resolve_call(callee, symbol.file, by_name)
                if target and target != symbol.sid:
                    graph.add_edge(symbol.sid, target, kind="calls")
    return _graph_json(graph, settings)


def _graph_json(graph: nx.DiGraph, settings: Settings) -> dict:
    nodes = []
    for node_id, attrs in graph.nodes(data=True):
        nodes.append({"id": node_id, **attrs})
    edges = []
    for index, (source, target, attrs) in enumerate(graph.edges(data=True)):
        edges.append({"id": f"e{index}", "source": source, "target": target, **attrs})
    focus = _focus_graph(nodes, edges, settings.max_graph_nodes)
    return {"nodes": focus["nodes"], "edges": focus["edges"], "total_nodes": len(nodes), "truncated": focus["truncated"]}


def _focus_graph(nodes: list[dict], edges: list[dict], limit: int) -> dict:
    if len(nodes) <= limit:
        return {"nodes": nodes, "edges": edges, "truncated": False}
    by_id = {node["id"]: node for node in nodes}
    ranked = sorted(
        nodes,
        key=lambda node: (
            {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(node.get("severity") or "", 0),
            1 if node.get("kind") == "endpoint" else 0,
            0 if node.get("kind") == "file" else 1,
            1 if node.get("changed") else 0,
            0 if node.get("is_test") else 1,
        ),
        reverse=True,
    )
    keep: set[str] = set()
    for node in ranked:
        if len(keep) >= limit:
            break
        if node.get("changed") or node.get("severity") or node.get("kind") == "endpoint":
            keep.add(node["id"])
    if not keep:
        keep = {node["id"] for node in ranked[:limit]}
    for edge in edges:
        if len(keep) >= limit:
            break
        if edge.get("kind") == "contains" and edge.get("target") in keep:
            keep.add(edge.get("source"))
    adjacency = defaultdict(set)
    for edge in edges:
        if edge.get("kind") == "contains":
            continue
        adjacency[edge["source"]].add(edge["target"])
        adjacency[edge["target"]].add(edge["source"])
    frontier = list(keep)
    while frontier and len(keep) < limit:
        current = frontier.pop(0)
        for neighbor in adjacency[current]:
            if neighbor not in keep:
                keep.add(neighbor)
                frontier.append(neighbor)
            if len(keep) >= limit:
                break
    kept_nodes = [by_id[node_id] for node_id in keep if node_id in by_id]
    kept_edges = [edge for edge in edges if edge["source"] in keep and edge["target"] in keep]
    return {"nodes": kept_nodes, "edges": kept_edges, "truncated": True}


def _chains(graph: nx.DiGraph, start: str, depth: int) -> list[str]:
    best = [start]

    def walk(node: str, path: list[str], remaining: int) -> None:
        nonlocal best
        if len(path) > len(best):
            best = path[:]
        if remaining == 0:
            return
        callers = [
            pred
            for pred in graph.predecessors(node)
            if graph.edges[pred, node].get("kind") == "calls" and pred not in path
        ]
        for pred in callers:
            path.append(pred)
            walk(pred, path, remaining - 1)
            path.pop()

    if start not in graph:
        return [start]
    walk(start, [start], depth)
    return best


def stage_impact(state: AnalysisState, settings: Settings) -> dict:
    state.graph = build_graph(state, settings)
    raw = nx.DiGraph()
    for edge in state.graph["edges"]:
        raw.add_edge(edge["source"], edge["target"], kind=edge.get("kind"))
    for node in state.graph["nodes"]:
        raw.add_node(node["id"], **node)
    changed = state.diff.get("changed_symbols", [])
    seeds = [item["id"] for item in changed if not item.get("is_test")]
    if not seeds and state.diff.get("scope") == "snapshot":
        review = set(state.diff.get("review_files") or [])
        hot = {item.get("file") for item in state.static_findings}
        picked: list[str] = []
        for parsed in state.head_files:
            if parsed.path not in review:
                continue
            if hot and parsed.path not in hot:
                continue
            for symbol in parsed.symbols:
                if not symbol.is_test:
                    picked.append(symbol.sid)
            if len(picked) >= 12:
                break
        seeds = picked[:12]
    affected: set[str] = set()

    def walk(seed: str, reverse: bool) -> None:
        frontier = [(seed, 0)]
        seen = {seed}
        while frontier:
            node, depth = frontier.pop(0)
            affected.add(node)
            if depth >= settings.impact_depth or node not in raw:
                continue
            neighbors = raw.predecessors(node) if reverse else raw.successors(node)
            for neighbor in neighbors:
                edge = raw.edges[neighbor, node] if reverse else raw.edges[node, neighbor]
                if edge.get("kind") not in {"calls", "imports"}:
                    continue
                if neighbor in seen:
                    continue
                seen.add(neighbor)
                frontier.append((neighbor, depth + 1))

    for seed in seeds:
        walk(seed, reverse=False)
        walk(seed, reverse=True)
    node_by_id = {node["id"]: node for node in state.graph["nodes"]}
    affected_symbols = [node_by_id[node_id] for node_id in affected if node_id in node_by_id and node_by_id[node_id].get("kind") != "file"]
    affected_apis = [node for node in affected_symbols if node.get("kind") == "endpoint"]
    affected_tests = [node for node in affected_symbols if node.get("is_test")]
    chains = []
    for seed in seeds:
        if seed not in raw:
            continue
        chain_ids = _chains(raw, seed, settings.impact_depth)
        if len(chain_ids) < 2:
            continue
        nodes = []
        for index, node_id in enumerate(chain_ids):
            meta = node_by_id.get(node_id, {"label": node_id, "file": "", "kind": "function"})
            if index == 0:
                reason = "Changed in this release"
            elif meta.get("kind") == "endpoint":
                reason = "Client-facing endpoint"
            else:
                reason = "Depends on the changed behavior"
            nodes.append(
                {
                    "id": node_id,
                    "label": meta.get("label", node_id),
                    "file": meta.get("file", ""),
                    "kind": meta.get("kind", "function"),
                    "reason": reason,
                }
            )
        chains.append({"id": f"chain-{len(chains) + 1}", "nodes": nodes, "length": len(nodes)})
    chains.sort(key=lambda item: item["length"], reverse=True)
    state.impact = {
        "changed_files": state.diff.get("changed_files", []),
        "changed_symbols": changed,
        "affected_symbols": affected_symbols,
        "affected_apis": affected_apis,
        "affected_tests": affected_tests,
        "failure_chains": chains[:4],
        "regression_paths": chains[:4],
        "counts": {
            "changed_files": len(state.diff.get("changed_files", [])),
            "changed_symbols": len(changed),
            "affected_symbols": len(affected_symbols),
            "affected_apis": len(affected_apis),
            "affected_tests": len(affected_tests),
            "regression_paths": min(len(chains), 4),
        },
    }
    counts = state.impact["counts"]
    return {
        "preview": [
            f"{counts['affected_symbols']} affected symbols",
            f"{counts['affected_apis']} APIs",
            f"{counts['regression_paths']} failure chains",
        ],
        "impact": state.impact,
        "graph": state.graph,
    }


def restore_impact(state: AnalysisState, payload: dict) -> None:
    state.impact = payload.get("impact", {})
    state.graph = payload.get("graph", {"nodes": [], "edges": []})


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", text.lower()) if len(token) > 2}


def _same_issue(left: dict, right: dict) -> bool:
    if left.get("file") != right.get("file"):
        return False
    if left.get("rule_id") and left.get("rule_id") == right.get("rule_id"):
        return True
    if left.get("category") != right.get("category"):
        return False
    if abs(int(left.get("line") or 0) - int(right.get("line") or 0)) > 5:
        return False
    a = _tokens(left.get("title", ""))
    b = _tokens(right.get("title", ""))
    if not a or not b:
        return False
    return len(a & b) / len(a | b) >= 0.4


def _excerpt(source: str, line: int, hits: set[int], radius: int = 7) -> dict:
    rows = source.splitlines()
    if not rows:
        return {"start": 1, "lines": []}
    start = max(1, line - radius)
    end = min(len(rows), line + radius)
    return {
        "start": start,
        "lines": [
            {"n": number, "text": redact(rows[number - 1]), "hit": number in hits}
            for number in range(start, end + 1)
        ],
    }


def stage_correlate(state: AnalysisState, settings: Settings) -> dict:
    incoming = [*state.static_findings, *state.test_findings, *state.ai_findings]
    groups: list[list[dict]] = []
    for finding in incoming:
        placed = False
        for group in groups:
            if _same_issue(group[0], finding):
                group.append(finding)
                placed = True
                break
        if not placed:
            groups.append([finding])
    rank = settings.policy.get("rank", {})
    merged = []
    for index, group in enumerate(groups, start=1):
        primary = max(group, key=lambda item: rank.get(item.get("severity"), 0))
        checks = [
            {
                "source": item.get("source", "static"),
                "rule_id": item.get("rule_id"),
                "line": item.get("line"),
                "evidence": item.get("evidence", ""),
                "title": item.get("title", ""),
            }
            for item in group
        ]
        hit_lines = {int(item.get("line") or 1) for item in group}
        related = []
        for symbol in state.impact.get("affected_symbols", []):
            if symbol.get("file") == primary.get("file"):
                related.append({"id": symbol.get("id"), "label": symbol.get("label"), "kind": symbol.get("kind")})
        item = dict(primary)
        item["id"] = f"{primary.get('rule_id', 'FINDING')}-{index:03d}"
        item["sources"] = sorted({check["source"] for check in checks})
        item["checks"] = checks
        item["confidence"] = round(max(float(entry.get("confidence") or 0) for entry in group), 2)
        item["evidence"] = "\n".join(dict.fromkeys(entry.get("evidence", "") for entry in group if entry.get("evidence")))[:1200]
        item["excerpt"] = _excerpt(state.head.get(primary.get("file"), ""), int(primary.get("line") or 1), hit_lines)
        item["related_symbols"] = related[:8]
        item["status"] = "OPEN"
        merged.append(item)
    merged.sort(key=lambda item: (-rank.get(item.get("severity"), 0), item.get("file", ""), item.get("line", 0)))
    state.findings = merged
    _paint(state, settings)
    return {
        "preview": [f"{len(merged)} findings", f"{len(incoming)} signals merged"],
        "findings": merged,
        "graph": state.graph,
    }


def restore_correlate(state: AnalysisState, payload: dict) -> None:
    state.findings = list(payload.get("findings", []))
    if payload.get("graph"):
        state.graph = payload["graph"]


def _paint(state: AnalysisState, settings: Settings) -> None:
    rank = settings.policy.get("rank", {})
    by_file: dict[str, list[dict]] = defaultdict(list)
    by_symbol: dict[str, list[dict]] = defaultdict(list)
    for finding in state.findings:
        by_file[finding.get("file", "")].append(finding)
        if finding.get("symbol"):
            by_symbol[f"sym:{finding['file']}::{finding['symbol']}"].append(finding)
    for node in state.graph.get("nodes", []):
        if node.get("kind") == "file":
            owned = by_file.get(node.get("file"), [])
        else:
            owned = by_symbol.get(node.get("id"), []) or by_file.get(node.get("file"), [])
        if not owned:
            node["severity"] = None
            node["finding_count"] = 0
            continue
        best = max(owned, key=lambda item: rank.get(item.get("severity"), 0))
        node["severity"] = best.get("severity")
        node["finding_count"] = len(owned)


def _band(score: int, policy: dict) -> str:
    thresholds = policy.get("thresholds", {})
    if score <= int(thresholds.get("low_max", 25)):
        return "LOW"
    if score <= int(thresholds.get("medium_max", 50)):
        return "MEDIUM"
    if score <= int(thresholds.get("high_max", 75)):
        return "HIGH"
    return "CRITICAL"


def dimension_score(raw_points: float, scale: float) -> int:
    """Map unbounded raw points onto 0..100 without a hard cap.

    Strictly increasing in raw_points: adding a finding can raise a score but never lower it,
    and 1000 points still scores higher than 500 (a min(100, raw) cap would call them equal).
    """
    if raw_points <= 0 or scale <= 0:
        return 0
    return min(100, int(round(100 * (1 - math.exp(-raw_points / scale)))))


def _weighted_points(findings: list[dict], points: dict, growth: float) -> float:
    """Sum severity points, scaled by how many signals each merged finding stands for.

    Correlation folds every hit of one rule in one file into a single finding, so the number of
    checks it carries is the real occurrence count. The n-th repeat adds less than a new issue.
    """
    total = 0.0
    for finding in findings:
        occurrences = max(1, len(finding.get("checks") or []))
        total += int(points.get(finding.get("severity"), 0)) * (1 + growth * math.log2(occurrences))
    return total


def stage_risk(state: AnalysisState, settings: Settings) -> dict:
    policy = settings.policy
    points = policy.get("severity_points", {})
    mapping = policy.get("category_dimension", {})
    weights = policy.get("weights", {})
    extra = policy.get("extra_dimensions", {})
    scoring = policy.get("scoring", {})
    scale = float(scoring.get("scale", 100))
    growth = float(scoring.get("occurrence_growth", 0.35))
    by_dimension: dict[str, list[dict]] = defaultdict(list)
    for finding in state.findings:
        dimension = mapping.get(finding.get("category"))
        if dimension:
            by_dimension[dimension].append(finding)
    dimensions = {}
    names = list(dict.fromkeys([*weights.keys(), *extra.keys()]))
    for name in names:
        group = by_dimension.get(name, [])
        dimensions[name] = {
            "score": dimension_score(_weighted_points(group, points, growth), scale),
            "weight": float(weights.get(name, extra.get(name, 0))),
            "findings": len(group),
        }
    overall = 0.0
    for name, info in dimensions.items():
        overall += info["score"] * info["weight"]
    score = int(round(overall))
    blocker_severities = set(policy.get("blocker_severities", []))
    blocker_categories = set(policy.get("blocker_categories", []))
    always_blocking = set(policy.get("always_blocking_severities", []))
    blockers = [
        finding
        for finding in state.findings
        if finding.get("severity") in always_blocking
        or (finding.get("severity") in blocker_severities and finding.get("category") in blocker_categories)
    ]
    if blockers:
        decision = "NOT_READY"
    elif state.findings:
        decision = "READY_WITH_WARNINGS"
    else:
        decision = "READY"
    chain = (state.impact.get("failure_chains") or [None])[0]
    why = []
    for finding in blockers[:5]:
        why.append(f"{finding['title']} in {finding['file']}:{finding['line']}. {finding.get('impact', '')}".strip())
    if chain:
        why.append("Failure chain: " + " → ".join(node["label"] for node in chain["nodes"]) + ".")
    if not why and state.findings:
        first = state.findings[0]
        why.append(f"{first['title']} in {first['file']}:{first['line']}.")
    seen = set()
    actions = []
    for finding in [*blockers, *state.findings]:
        text = finding.get("recommendation", "")
        if text and text not in seen:
            seen.add(text)
            actions.append(text)
        if len(actions) >= 6:
            break
    running = 0.0
    waterfall = []
    for name, info in dimensions.items():
        if info["weight"] <= 0:
            continue
        delta = round(info["score"] * info["weight"], 1)
        running = round(running + delta, 1)
        waterfall.append({"name": name, "delta": delta, "running": running, "score": info["score"]})
    labels = policy.get("decision_labels", {})
    state.risk = {
        "overall": _band(score, policy),
        "score": score,
        "decision": decision,
        "decision_label": labels.get(decision, decision),
        "dimensions": dimensions,
        "waterfall": waterfall,
        "blockers": [
            {"id": item.get("id"), "title": item.get("title"), "file": item.get("file"), "line": item.get("line"), "severity": item.get("severity")}
            for item in blockers
        ],
        "why": why,
        "actions": actions,
        "failure_chain": chain,
        "counts": state.impact.get("counts", {}),
    }
    return {"preview": [state.risk["decision_label"], f"score {score}", state.risk["overall"]], "risk": state.risk}


def restore_risk(state: AnalysisState, payload: dict) -> None:
    state.risk = payload.get("risk")


def analyze_directories(base: Path, head: Path, settings: Settings, with_ai: bool = False) -> AnalysisState:
    from app.analysis.llm import stage_ai
    from app.analysis.snapshots import read_tree

    state = AnalysisState(workspace=str(head), base=read_tree(base, settings), head=read_tree(head, settings))
    stage_parse(state, settings)
    stage_diff(state, settings)
    stage_static(state, settings)
    stage_impact(state, settings)
    stage_tests(state, settings)
    if with_ai:
        stage_ai(state, settings)
    else:
        state.ai_findings = []
        state.ai_note = "skipped"
    stage_correlate(state, settings)
    stage_risk(state, settings)
    return state
