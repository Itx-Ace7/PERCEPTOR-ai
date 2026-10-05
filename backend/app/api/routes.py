from __future__ import annotations

import asyncio
import json
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from app.analysis.reports import markdown_report, sarif_text
from app.pipeline.runner import launch
from app import runtime
from app.security import require_token

public = APIRouter()
router = APIRouter(dependencies=[Depends(require_token)])


class RunRequest(BaseModel):
    source_type: str
    url: str | None = None
    path: str | None = None


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _bundle(run_id: str) -> dict:
    assert runtime.db is not None and runtime.settings is not None
    run = runtime.db.run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    repo = runtime.db.repository(run["repository_id"])
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    try:
        languages = json.loads(repo.get("languages") or "[]")
    except json.JSONDecodeError:
        languages = []
    return {
        "product": runtime.settings.product,
        "pipeline": runtime.settings.pipeline,
        "policy": {
            "weights": runtime.settings.policy.get("weights", {}),
            "thresholds": runtime.settings.policy.get("thresholds", {}),
            "decision_labels": runtime.settings.policy.get("decision_labels", {}),
        },
        "llm": {"enabled": bool(runtime.settings.api_key), "model": runtime.settings.llm_model},
        "run": {
            "id": run["id"],
            "status": run["status"],
            "started_at": run["started_at"],
            "finished_at": run["finished_at"],
            "error": run["error"],
        },
        "repository": {
            "id": repo["id"],
            "name": repo["name"],
            "source_type": repo["source_type"],
            "commit_sha": repo["commit_sha"],
            "languages": languages,
            "file_count": repo["file_count"],
        },
        "nodes": runtime.db.artifact(run_id, "nodes") or {},
        "skipped": runtime.db.artifact(run_id, "skipped") or [],
        "findings": runtime.db.artifact(run_id, "findings") or [],
        "graph": runtime.db.artifact(run_id, "graph") or {"nodes": [], "edges": []},
        "impact": runtime.db.artifact(run_id, "impact") or {},
        "risk": runtime.db.artifact(run_id, "risk"),
        "verification": runtime.db.artifact(run_id, "verification"),
    }


def _normalize_git_url(url: str) -> str:
    cleaned = url.strip().split("?", 1)[0].split("#", 1)[0].rstrip("/")
    if cleaned.startswith("git@"):
        if not re.match(r"^git@[\w.\-]+:[\w./\-]+$", cleaned):
            raise HTTPException(status_code=400, detail="Unsupported git URL")
        return cleaned
    github = re.match(r"^https://github\.com/([^/]+)/([^/]+)(?:/.*)?$", cleaned, re.IGNORECASE)
    if github:
        owner, repo = github.group(1), github.group(2)
        return f"https://github.com/{owner}/{repo.removesuffix('.git')}.git"
    if not re.match(r"^https://[\w.\-]+/[\w./\-]+$", cleaned):
        raise HTTPException(status_code=400, detail="Only https git URLs are accepted")
    return cleaned


@public.get("/api/health")
def health() -> dict:
    assert runtime.settings is not None
    return {
        "status": "ok",
        "product": runtime.settings.product["name"],
        "version": runtime.settings.product["version"],
        "auth_required": bool(runtime.settings.api_token),
    }


@router.get("/api/meta")
def meta() -> dict:
    assert runtime.settings is not None
    return {
        "product": runtime.settings.product,
        "pipeline": runtime.settings.pipeline,
        "llm": {"enabled": bool(runtime.settings.api_key), "model": runtime.settings.llm_model},
        "policy": runtime.settings.policy,
    }


@router.get("/api/runs")
def list_runs() -> dict:
    assert runtime.db is not None
    return {"runs": runtime.db.list_runs()}


@router.post("/api/runs")
def create_run(body: RunRequest) -> dict:
    assert runtime.db is not None and runtime.settings is not None
    source_type = body.source_type.strip().lower()
    if source_type not in {"github", "path"}:
        raise HTTPException(status_code=400, detail="source_type must be github or path")
    ref = ""
    if source_type == "github":
        if not body.url:
            raise HTTPException(status_code=400, detail="url is required")
        ref = _normalize_git_url(body.url)
    elif source_type == "path":
        if not runtime.settings.allow_local_paths:
            raise HTTPException(status_code=403, detail="Local path analysis is disabled on this server")
        if not body.path:
            raise HTTPException(status_code=400, detail="path is required")
        if not Path(body.path).is_dir():
            raise HTTPException(status_code=400, detail="path is not a directory")
        ref = str(Path(body.path).resolve())
    repo_id = _new_id()
    run_id = _new_id()
    runtime.db.insert_repository(
        {"id": repo_id, "name": "repository", "source_type": source_type, "source_ref": ref, "workspace": "", "commit_sha": "", "languages": "[]", "file_count": 0}
    )
    runtime.db.insert_run(run_id, repo_id)
    launch(runtime.settings, runtime.db, run_id, verify_only=False)
    return {"run_id": run_id, "repository_id": repo_id, "status": "QUEUED"}


@router.post("/api/runs/upload")
async def upload_run(file: UploadFile = File(...)) -> dict:
    assert runtime.db is not None and runtime.settings is not None
    payload = await file.read()
    if len(payload) > runtime.settings.upload_max_bytes:
        raise HTTPException(status_code=413, detail="Upload exceeds the configured limit")
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Upload a .zip archive")
    repo_id = _new_id()
    run_id = _new_id()
    target = runtime.settings.workspaces / "uploads" / f"{repo_id}.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    runtime.db.insert_repository(
        {
            "id": repo_id,
            "name": Path(file.filename or "upload.zip").stem,
            "source_type": "zip",
            "source_ref": str(target),
            "workspace": "",
            "commit_sha": "",
            "languages": "[]",
            "file_count": 0,
        }
    )
    runtime.db.insert_run(run_id, repo_id)
    launch(runtime.settings, runtime.db, run_id, verify_only=False)
    return {"run_id": run_id, "repository_id": repo_id, "status": "QUEUED"}


@router.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict:
    return _bundle(run_id)


@router.get("/api/runs/{run_id}/events")
async def stream_events(run_id: str) -> StreamingResponse:
    assert runtime.db is not None
    if runtime.db.run(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")

    async def generate():
        last = 0
        idle = 0
        while True:
            batch = runtime.db.events_after(run_id, last)
            if batch:
                idle = 0
                for event in batch:
                    last = event["seq"]
                    yield f"data: {json.dumps(event)}\n\n"
            else:
                idle += 1
            run = runtime.db.run(run_id)
            if run and run["status"] in {"COMPLETED", "FAILED"} and not runtime.db.events_after(run_id, last):
                break
            if idle > 240:
                break
            await asyncio.sleep(0.25)

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.post("/api/runs/{run_id}/verify")
def verify_run(run_id: str) -> dict:
    assert runtime.db is not None and runtime.settings is not None
    run = runtime.db.run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if run["status"] not in {"COMPLETED", "FAILED"}:
        raise HTTPException(status_code=409, detail="Wait until analysis finishes")
    if run["status"] == "FAILED":
        raise HTTPException(status_code=409, detail="The analysis run failed")
    launch(runtime.settings, runtime.db, run_id, verify_only=True)
    return {"run_id": run_id, "status": "VERIFYING"}


@router.get("/api/runs/{run_id}/report.md", response_class=PlainTextResponse)
def report_markdown(run_id: str) -> str:
    return markdown_report(_bundle(run_id))


@router.get("/api/runs/{run_id}/report.sarif", response_class=PlainTextResponse)
def report_sarif(run_id: str) -> str:
    return sarif_text(_bundle(run_id))
