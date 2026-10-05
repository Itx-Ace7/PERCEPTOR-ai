from __future__ import annotations

import logging
import os
import stat
import sys
from pathlib import Path
from shutil import rmtree

from app.config import Settings
from app.db import Database

log = logging.getLogger(__name__)

FIXED_SUFFIX = "-fixed"
UPLOADS_DIR = "uploads"


def _clear_readonly(func, path, _error) -> None:
    """Git marks object files read-only; on Windows they cannot be deleted until that is cleared."""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError as exc:
        log.warning("could not remove %s: %s", path, exc)


def _remove(path: Path, root: Path) -> bool:
    """Delete a directory only when it really lives inside the workspaces root."""
    try:
        resolved, boundary = path.resolve(), root.resolve()
        if not resolved.is_relative_to(boundary) or resolved == boundary or not resolved.exists():
            return False
        if sys.version_info >= (3, 12):
            rmtree(resolved, onexc=_clear_readonly)
        else:
            rmtree(resolved, onerror=_clear_readonly)
        return not resolved.exists()
    except OSError as exc:
        log.warning("could not remove %s: %s", path, exc)
        return False


def sweep_orphans(settings: Settings, db: Database) -> int:
    """Remove workspace folders that no repository row owns (left by crashes or earlier failures)."""
    if not settings.workspaces.exists():
        return 0
    owned = db.repository_ids()
    removed = 0
    for entry in settings.workspaces.iterdir():
        if not entry.is_dir() or entry.name == UPLOADS_DIR:
            continue
        if entry.name.removesuffix(FIXED_SUFFIX) in owned:
            continue
        removed += int(_remove(entry, settings.workspaces))
    return removed


def prune(settings: Settings, db: Database) -> int:
    """Keep the newest runs; drop older ones with their workspaces, fixed copies and uploads."""
    removed = 0
    for row in db.expired_runs(settings.retain_runs):
        workspace = Path(row["workspace"]) if row.get("workspace") else settings.workspaces / row["repository_id"]
        _remove(workspace, settings.workspaces)
        _remove(workspace.parent / f"{workspace.name}{FIXED_SUFFIX}", settings.workspaces)
        upload = settings.workspaces / UPLOADS_DIR / f"{row['repository_id']}.zip"
        upload.unlink(missing_ok=True)
        db.delete_run(row["run_id"], row["repository_id"])
        removed += 1
    db.trim_cache(settings.retain_cache_entries)
    swept = sweep_orphans(settings, db)
    if removed or swept:
        log.info("retention removed %d old run(s) and %d orphan folder(s)", removed, swept)
    return removed
