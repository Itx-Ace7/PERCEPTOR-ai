from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.config import Settings


def git(cwd: Path, *args: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "--no-pager", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env={
            **dict(**__import__("os").environ),
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_PAGER": "cat",
            "GIT_CEILING_DIRECTORIES": str(cwd.resolve().parent),
        },
    )


_WINDOWS_BAD_CHARS = set('<>:"|?*\\')
_WINDOWS_RESERVED = {"con", "prn", "aux", "nul", *(f"com{n}" for n in range(1, 10)), *(f"lpt{n}" for n in range(1, 10))}


def portable_path(rel: str, root_len: int = 0, max_len: int = 0) -> bool:
    """False when the host filesystem cannot hold this path (only Windows is restrictive).

    root_len is the length of the directory the file lands in; max_len the longest full path allowed.
    """
    if os.name != "nt":
        return True
    if max_len and root_len + 1 + len(rel) >= max_len:
        return False
    for part in rel.split("/"):
        if not part:
            continue
        if set(part) & _WINDOWS_BAD_CHARS or part != part.rstrip(" .") or part.split(".")[0].lower() in _WINDOWS_RESERVED:
            return False
    return True


def checkout_portable(repo: Path, settings: Settings) -> list[dict]:
    """Check out HEAD without aborting on paths the host cannot create. Returns those paths."""
    listing = git(repo, "ls-tree", "-r", "-z", "--name-only", "HEAD", timeout=settings.sandbox_timeout)
    if listing.returncode != 0:
        raise RuntimeError(listing.stderr.strip() or "git ls-tree failed")
    wanted, skipped = [], []
    root_len = len(str(repo.resolve()))
    for rel in filter(None, listing.stdout.split("\0")):
        if portable_path(rel, root_len, settings.max_path_length):
            wanted.append(rel)
        else:
            skipped.append({"path": rel, "reason": "path not valid on this OS", "size": 0})
    if wanted:
        spec = repo / ".git" / "perceptor-pathspec"
        spec.write_bytes(b"\0".join(item.encode("utf-8") for item in wanted))
        done = git(
            repo, "--literal-pathspecs", "checkout", "HEAD", f"--pathspec-from-file={spec}", "--pathspec-file-nul",
            timeout=settings.sandbox_timeout,
        )
        spec.unlink(missing_ok=True)
        if done.returncode != 0:
            raise RuntimeError(done.stderr.strip() or "git checkout failed")
    return skipped


def is_notebook(path: str, settings: Settings) -> bool:
    return Path(path).suffix.lower() in settings.notebook_extensions


def notebook_source(raw: str) -> str | None:
    """Flatten the code cells of a Jupyter notebook so it can be parsed and reviewed.

    Outputs (often megabytes of embedded images) are dropped. Shell and magic lines are
    commented out so the remaining text is valid Python.
    """
    try:
        document = json.loads(raw)
    except ValueError:
        return None
    cells = document.get("cells") if isinstance(document, dict) else None
    if not isinstance(cells, list):
        return None
    parts = []
    for index, cell in enumerate(cells, start=1):
        if not isinstance(cell, dict) or cell.get("cell_type") != "code":
            continue
        source = cell.get("source", "")
        text = "".join(source) if isinstance(source, list) else str(source)
        lines = [f"# {line}" if line.lstrip().startswith(("%", "!")) else line for line in text.splitlines()]
        parts.append(f"# %% cell {index}\n" + "\n".join(lines))
    return "\n\n".join(parts)


def scan_tree(root: Path, settings: Settings) -> tuple[dict[str, str], list[dict]]:
    """Read every analysable file and record why each of the others was left out."""
    texts: dict[str, str] = {}
    skipped: list[dict] = []
    if not root.exists():
        return texts, skipped
    candidates: list[tuple[int, str, Path, int]] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in settings.skip_dirs for part in relative.parts):
            continue
        rel = relative.as_posix()
        size = path.stat().st_size
        notebook = is_notebook(rel, settings)
        if size > (settings.max_notebook_bytes if notebook else settings.max_file_bytes):
            skipped.append({"path": rel, "reason": "too large", "size": size})
            continue
        # Source code first, then other reviewable text, then everything else; stable by path.
        language = settings.extensions.get(Path(rel).suffix.lower(), "text")
        rank = 0 if language in settings.review_code_languages else 1 if language in settings.review_languages else 2
        candidates.append((rank, rel, path, size))
    candidates.sort(key=lambda item: (item[0], item[1]))
    # Reading is I/O bound, so read in parallel chunks; stop reading once the file limit is met.
    chunk = max(1, settings.read_chunk)
    with ThreadPoolExecutor(max_workers=settings.read_workers) as pool:
        for start in range(0, len(candidates), chunk):
            window = candidates[start : start + chunk]
            if len(texts) >= settings.max_files:
                for _rank, rel, _path, size in window:
                    skipped.append({"path": rel, "reason": "file limit reached", "size": size})
                continue
            payloads = list(pool.map(lambda item: item[2].read_bytes(), window))
            for (_rank, rel, _path, size), raw in zip(window, payloads):
                _accept(rel, size, raw, texts, skipped, settings)
    return texts, sorted(skipped, key=lambda item: item["path"])


def is_minified(rel: str, raw: bytes, settings: Settings) -> bool:
    """Bundled or minified code: very long lines, or a name that says so. Never real source a person edits."""
    name = Path(rel).name.lower()
    if any(marker in name for marker in settings.minified_name_markers):
        return True
    if len(raw) < settings.minified_min_bytes:
        return False
    return len(raw) / max(1, raw.count(b"\n") + 1) > settings.minified_avg_line_chars


def _accept(rel: str, size: int, raw: bytes, texts: dict[str, str], skipped: list[dict], settings: Settings) -> None:
    """Classify one file that has been read: keep its text, or record why it is left out."""
    notebook = is_notebook(rel, settings)
    if len(texts) >= settings.max_files:
        skipped.append({"path": rel, "reason": "file limit reached", "size": size})
        return
    if b"\0" in raw:
        skipped.append({"path": rel, "reason": "binary", "size": size})
        return
    if not notebook and is_minified(rel, raw, settings):
        skipped.append({"path": rel, "reason": "minified or generated", "size": size})
        return
    text = raw.decode("utf-8", errors="replace")
    if notebook:
        flattened = notebook_source(text)
        if flattened is None:
            skipped.append({"path": rel, "reason": "unreadable notebook", "size": size})
            return
        if len(flattened.encode("utf-8")) > settings.max_file_bytes:
            skipped.append({"path": rel, "reason": "too large", "size": size})
            return
        text = flattened
    texts[rel] = text


def read_tree(root: Path, settings: Settings) -> dict[str, str]:
    return scan_tree(root, settings)[0]


def write_changed(root: Path, current: dict[str, str], updated: dict[str, str], settings: Settings) -> None:
    """Write repaired files back. Notebooks are skipped: their flattened text is not the file format."""
    for path, text in updated.items():
        if current.get(path) == text or is_notebook(path, settings):
            continue
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


def has_parent(repo: Path) -> bool:
    if not (repo / ".git").exists():
        return False
    return git(repo, "rev-parse", "--verify", "HEAD~1").returncode == 0


def _revision_file(repo: Path, rev: str, rel: str, settings: Settings) -> str | None:
    shown = git(repo, "show", f"{rev}:{rel}")
    if shown.returncode != 0 or "\0" in shown.stdout:
        return None
    text = shown.stdout
    if is_notebook(rel, settings):
        text = notebook_source(text)
        if text is None:
            return None
    if len(text.encode("utf-8")) > settings.max_file_bytes:
        return None
    return text


def parent_texts(repo: Path, rev: str, head: dict[str, str], settings: Settings) -> dict[str, str]:
    """Reconstruct the parent snapshot from the head snapshot plus the real commit diff.

    Only files the commit touched are read from git. Everything else is identical on both
    sides by definition, so the two snapshots always cover the same files.
    """
    changes = git(repo, "diff", "--name-status", "-z", "--no-renames", rev, "HEAD", timeout=settings.sandbox_timeout)
    if changes.returncode != 0:
        return dict(head)
    base = dict(head)
    fields = [item for item in changes.stdout.split("\0") if item]
    for status, rel in zip(fields[0::2], fields[1::2]):
        if not portable_path(rel, len(str(repo.resolve())), settings.max_path_length):
            continue
        if status.startswith("A"):
            base.pop(rel, None)
            continue
        text = _revision_file(repo, rev, rel, settings)
        if text is None:
            base.pop(rel, None)
        else:
            base[rel] = text
    return base


def head_sha(repo: Path) -> str:
    result = git(repo, "rev-parse", "--short", "HEAD")
    if result.returncode != 0:
        return "working-tree"
    return result.stdout.strip() or "working-tree"


def content_hash(base: dict[str, str], head: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for label, texts in (("base", base), ("head", head)):
        digest.update(label.encode())
        for path in sorted(texts):
            digest.update(path.encode())
            digest.update(b"\0")
            digest.update(texts[path].encode())
            digest.update(b"\0")
    return digest.hexdigest()


def copy_worktree(src: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns(".git", "node_modules", ".venv", "__pycache__"))


def safe_extract(archive, dest: Path) -> None:
    import zipfile

    if not isinstance(archive, zipfile.ZipFile):
        raise TypeError("expected a zip file")
    root = dest.resolve()
    for member in archive.infolist():
        target = (dest / member.filename).resolve()
        if not target.is_relative_to(root):
            raise ValueError(f"Zip entry escapes the workspace: {member.filename}")
    archive.extractall(dest)
