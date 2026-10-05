from __future__ import annotations

import hashlib
import json
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from shutil import copytree, ignore_patterns, rmtree

from app import events
from app.analysis.llm import restore_ai, stage_ai
from app.analysis.snapshots import (
    content_hash,
    copy_worktree,
    git,
    has_parent,
    checkout_portable,
    head_sha,
    parent_texts,
    read_tree,
    safe_extract,
    scan_tree,
    write_changed,
)
from app.analysis.stages import (
    restore_correlate,
    restore_diff,
    restore_impact,
    restore_parse,
    restore_risk,
    restore_static,
    restore_tests,
    stage_correlate,
    stage_diff,
    stage_impact,
    stage_parse,
    stage_risk,
    stage_static,
    stage_tests,
)
from app.analysis.types import AnalysisState
from app.analysis.verify import execute_verification
from app.config import Settings
from app.db import Database
from app.pipeline.retention import prune


def ordered_nodes(pipeline: dict) -> list[dict]:
    nodes = list(pipeline.get("nodes", []))
    index = {node["id"]: position for position, node in enumerate(nodes)}
    pending = {node["id"]: set(node.get("depends_on", [])) for node in nodes}
    ordered = []
    while pending:
        ready = sorted([node_id for node_id, deps in pending.items() if not deps], key=lambda item: index[item])
        if not ready:
            raise RuntimeError("Pipeline has a cycle")
        for node_id in ready:
            ordered.append(next(node for node in nodes if node["id"] == node_id))
            del pending[node_id]
            for deps in pending.values():
                deps.discard(node_id)
    return ordered


class RunContext:
    def __init__(self, settings: Settings, db: Database, run: dict, repo: dict) -> None:
        self.settings = settings
        self.db = db
        self.run = run
        self.repo = repo
        self.state: AnalysisState | None = None
        self.nodes: dict = {}
        self.output_hash: dict[str, str] = {}
        self.content = ""
        self.verification: dict | None = None

    def emit(self, event_type: str, node_id: str | None, payload: dict) -> None:
        self.db.add_event(self.run["id"], event_type, node_id, payload)


def _load_state(workspace: Path, settings: Settings) -> AnalysisState:
    head, skipped = scan_tree(workspace, settings)
    if has_parent(workspace):
        base = parent_texts(workspace, "HEAD~1", head, settings)
    else:
        base = dict(head)
    return AnalysisState(workspace=str(workspace), base=base, head=head, commit_sha=head_sha(workspace), skipped=skipped)


def _ingest(ctx: RunContext) -> dict:
    settings = ctx.settings
    repo = ctx.repo
    dest = settings.workspaces / repo["id"]
    source_type = repo["source_type"]
    unportable: list[dict] = []
    ref = repo.get("source_ref") or ""
    if source_type == "github":
        if dest.exists():
            rmtree(dest)
        cloned = git(
            settings.workspaces, "clone", "--no-checkout", "--depth", str(settings.clone_depth), ref, repo["id"],
            timeout=settings.sandbox_timeout,
        )
        if cloned.returncode != 0:
            raise RuntimeError(cloned.stderr.strip() or "git clone failed")
        unportable = checkout_portable(dest, settings)
        name = ref.rstrip("/").split("/")[-1].removesuffix(".git")
    elif source_type == "path":
        source = Path(ref)
        if not source.is_dir():
            raise FileNotFoundError(ref)
        if dest.exists():
            rmtree(dest)
        copytree(source, dest, ignore=ignore_patterns("node_modules", ".venv", "__pycache__"))
        name = source.name
    elif source_type == "zip":
        import zipfile

        if dest.exists():
            rmtree(dest)
        dest.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(ref) as archive:
            safe_extract(archive, dest)
        name = Path(ref).stem
    else:
        raise ValueError(f"Unknown source type: {source_type}")
    ctx.state = _load_state(dest, settings)
    ctx.state.skipped = sorted([*ctx.state.skipped, *unportable], key=lambda item: item["path"])
    ctx.db.update_repository(
        repo["id"],
        name=name,
        workspace=str(dest),
        commit_sha=ctx.state.commit_sha,
        file_count=len(ctx.state.head),
    )
    ctx.repo = ctx.db.repository(repo["id"]) or repo
    ctx.db.save_artifact(ctx.run["id"], "skipped", ctx.state.skipped)
    preview = [name, ctx.state.commit_sha or "working-tree", f"{len(ctx.state.head)} files"]
    if ctx.state.skipped:
        preview.append(f"{len(ctx.state.skipped)} skipped")
    return {"preview": preview}


def _fix(ctx: RunContext) -> dict:
    from app.analysis.autofix import apply_fixes

    assert ctx.state is not None
    findings = ctx.db.artifact(ctx.run["id"], "findings") or ctx.state.findings
    workspace = Path(ctx.state.workspace)
    fixed = workspace.parent / f"{workspace.name}-fixed"
    copy_worktree(workspace, fixed)
    current = read_tree(fixed, ctx.settings)
    updated, notes = apply_fixes(current, ctx.state.base, findings, ctx.settings.rules)
    write_changed(fixed, current, updated, ctx.settings)
    ctx.verification = {"fixes": notes, "workspace": str(fixed)}
    applied = [note for note in notes if not str(note.get("note", "")).startswith(("no ", "skipped"))]
    return {"preview": [f"{len(applied)} repairs applied"], "fixes": notes, "fixed_workspace": str(fixed)}


def _verify(ctx: RunContext) -> dict:
    assert ctx.state is not None
    findings = ctx.db.artifact(ctx.run["id"], "findings") or ctx.state.findings
    before = ctx.db.artifact(ctx.run["id"], "risk") or ctx.state.risk
    workspace = Path(ctx.repo["workspace"])
    # Fix node already rewrote the sibling tree. Re-apply so verify is safe on its own.
    report = execute_verification(workspace, ctx.state.base, findings, before, ctx.settings)
    ctx.verification = report
    after_risk = (report.get("after") or {}).get("risk")
    if after_risk:
        ctx.state.risk = after_risk
    if report.get("remaining") is not None:
        ctx.state.findings = report["remaining"]
    if report.get("graph"):
        ctx.state.graph = report["graph"]
    ctx.db.save_artifact(ctx.run["id"], "verification", report)
    after = report["after"]["findings"]
    before_count = report["before"]["findings"]
    return {
        "preview": [
            f"{before_count} → {after} findings",
            report["tests"]["status"],
            report["release_status"],
        ],
        "verification": report,
    }


RUNNERS = {
    "parse": (stage_parse, restore_parse),
    "diff": (stage_diff, restore_diff),
    "static": (stage_static, restore_static),
    "impact": (stage_impact, restore_impact),
    "tests": (stage_tests, restore_tests),
    "ai_review": (stage_ai, restore_ai),
    "correlate": (stage_correlate, restore_correlate),
    "risk": (stage_risk, restore_risk),
}


def _publish(ctx: RunContext, payload: dict) -> None:
    run_id = ctx.run["id"]
    ctx.db.save_artifact(run_id, "nodes", ctx.nodes)
    for kind in ("findings", "graph", "impact", "risk", "diff"):
        if kind in payload:
            ctx.db.save_artifact(run_id, kind, payload[kind])
    if ctx.state is not None and ctx.state.findings and "findings" not in payload:
        ctx.db.save_artifact(run_id, "findings", ctx.state.findings)
    if ctx.state is not None and ctx.state.graph:
        ctx.db.save_artifact(run_id, "graph", ctx.state.graph)
    if ctx.state is not None and ctx.state.impact:
        ctx.db.save_artifact(run_id, "impact", ctx.state.impact)
    if ctx.state is not None and ctx.state.risk:
        ctx.db.save_artifact(run_id, "risk", ctx.state.risk)


def _execute_node(ctx: RunContext, node: dict, use_cache: bool) -> None:
    import time

    node_id = node["id"]
    ctx.nodes[node_id] = {"status": "running", "preview": [], "cached": False, "duration_ms": 0}
    ctx.db.save_artifact(ctx.run["id"], "nodes", ctx.nodes)
    ctx.emit(events.NODE_STARTED, node_id, {"title": node.get("title", node_id)})
    started = time.perf_counter()
    depends = list(node.get("depends_on", []))
    cache_key = ""
    if use_cache and node_id in RUNNERS and ctx.state is not None:
        raw = json.dumps(
            {
                "node": node_id,
                "content": ctx.content,
                "config": ctx.settings.config_hash(),
                "parents": {dep: ctx.output_hash.get(dep) for dep in depends},
            },
            sort_keys=True,
        )
        cache_key = hashlib.sha256(raw.encode()).hexdigest()
        cached = ctx.db.cache_get(cache_key)
        if cached is not None:
            RUNNERS[node_id][1](ctx.state, cached)
            preview = cached.get("preview", [])
            ctx.output_hash[node_id] = hashlib.sha256(json.dumps(cached, sort_keys=True, default=str).encode()).hexdigest()
            ctx.nodes[node_id] = {"status": "completed", "preview": preview, "cached": True, "duration_ms": 0}
            _publish(ctx, cached)
            ctx.emit(events.NODE_COMPLETED, node_id, {"preview": preview, "cached": True, "duration_ms": 0})
            return
    if node_id == "ingest":
        payload = _ingest(ctx)
        ctx.content = content_hash(ctx.state.base, ctx.state.head) if ctx.state else ""
    elif node_id == "fix":
        payload = _fix(ctx)
    elif node_id == "verify":
        payload = _verify(ctx)
    else:
        stage, _restore = RUNNERS[node_id]
        if node_id == "ai_review":

            def _progress(done: int, total: int) -> None:
                ctx.nodes[node_id]["preview"] = [f"{done}/{total} review passes"]
                ctx.db.save_artifact(ctx.run["id"], "nodes", ctx.nodes)
                ctx.emit(events.NODE_PROGRESS, node_id, {"done": done, "total": total})

            payload = stage(ctx.state, ctx.settings, _progress)
        else:
            payload = stage(ctx.state, ctx.settings)
    duration_ms = int((time.perf_counter() - started) * 1000)
    preview = payload.get("preview", [])
    ctx.nodes[node_id] = {"status": "completed", "preview": preview, "cached": False, "duration_ms": duration_ms}
    encoded = json.dumps(payload, sort_keys=True, default=str)
    ctx.output_hash[node_id] = hashlib.sha256(encoded.encode()).hexdigest()
    # A degraded result (provider timeout or error) must not be replayed for identical code.
    if cache_key and not payload.get("degraded"):
        ctx.db.cache_put(cache_key, node_id, payload)
    if node_id == "parse" and ctx.state is not None:
        ctx.db.update_repository(
            ctx.repo["id"],
            languages=json.dumps(ctx.state.languages),
            file_count=len(ctx.state.head),
        )
    _publish(ctx, payload)
    ctx.emit(events.NODE_COMPLETED, node_id, {"preview": preview, "cached": False, "duration_ms": duration_ms})
    if node_id == "impact":
        ctx.emit(events.GRAPH_UPDATED, node_id, {"counts": (ctx.state.impact or {}).get("counts", {}) if ctx.state else {}})
    if node_id == "correlate" and ctx.state is not None:
        for finding in ctx.state.findings:
            ctx.emit(events.FINDING_CREATED, node_id, {"id": finding.get("id"), "severity": finding.get("severity"), "title": finding.get("title")})
        ctx.emit(events.GRAPH_UPDATED, node_id, {"nodes": len(ctx.state.graph.get("nodes", []))})
    if node_id in {"risk", "verify"} and ctx.state is not None and ctx.state.risk:
        ctx.emit(events.RISK_UPDATED, node_id, {"decision": ctx.state.risk.get("decision"), "score": ctx.state.risk.get("score")})
    if node_id == "verify" and ctx.verification:
        ctx.emit(
            events.RISK_UPDATED,
            node_id,
            {"decision": ctx.verification.get("release_status"), "score": ctx.verification.get("after", {}).get("score")},
        )


def execute(settings: Settings, db: Database, run_id: str, verify_only: bool = False) -> None:
    run = db.run(run_id)
    if run is None:
        return
    repo = db.repository(run["repository_id"])
    if repo is None:
        db.update_run(run_id, "FAILED", "Repository missing", finished=True)
        return
    ctx = RunContext(settings, db, run, repo)
    db.update_run(run_id, "VERIFYING" if verify_only else "RUNNING")
    ctx.emit(events.RUN_STARTED, None, {"verify_only": verify_only})
    try:
        ctx.nodes = db.artifact(run_id, "nodes") or {}
        for node in ordered_nodes(settings.pipeline):
            ctx.nodes.setdefault(node["id"], {"status": "pending", "preview": [], "cached": False, "duration_ms": 0})
        if verify_only:
            ctx.state = _load_state(Path(repo["workspace"]), settings)
            ctx.content = content_hash(ctx.state.base, ctx.state.head)
            selected = [node for node in ordered_nodes(settings.pipeline) if node["id"] in {"fix", "verify"}]
        else:
            selected = [node for node in ordered_nodes(settings.pipeline) if not node.get("optional")]
        for node in selected:
            _execute_node(ctx, node, use_cache=not verify_only and node["id"] not in {"ingest", "fix", "verify"})
        db.save_artifact(run_id, "nodes", ctx.nodes)
        db.update_run(run_id, "COMPLETED", finished=True)
        ctx.emit(events.RUN_COMPLETED, None, {"status": "COMPLETED"})
    except Exception as exc:
        db.update_run(run_id, "FAILED", str(exc), finished=True)
        ctx.emit(events.RUN_FAILED, None, {"error": str(exc), "trace": traceback.format_exc()[-2000:]})


_pool: ThreadPoolExecutor | None = None
_pool_lock = threading.Lock()


def _workers(settings: Settings) -> ThreadPoolExecutor:
    """One shared, bounded pool: a burst of submissions queues instead of exhausting the machine."""
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(max_workers=settings.max_concurrent_runs, thread_name_prefix="run")
        return _pool


def launch(settings: Settings, db: Database, run_id: str, verify_only: bool = False) -> None:
    if not verify_only:
        try:
            prune(settings, db)
        except Exception:  # housekeeping must never block a new analysis
            pass
    _workers(settings).submit(execute, settings, db, run_id, verify_only)
