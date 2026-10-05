"""Measure indexing time and detection on the regression fixture.

Results are written to outputs/benchmark-results. Numbers in the report come from this file.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests"))

from app.analysis.stages import analyze_directories  # noqa: E402
from app.analysis.snapshots import read_tree  # noqa: E402
from app.config import get_settings  # noqa: E402
from fixtures import BASE, EXPECTED, HEAD, write_tree  # noqa: E402


def write_synthetic(dest: Path, count: int) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    (dest / "backend").mkdir(parents=True)
    for index in range(count):
        calls = ""
        if index:
            calls = f"    helper_{index - 1}()\n"
        (dest / "backend" / f"mod_{index}.py").write_text(
            "def helper_{i}(amount):\n"
            "    if amount is None:\n"
            "        return 0\n"
            "{calls}"
            "    return amount\n".format(i=index, calls=calls),
            encoding="utf-8",
        )
    (dest / "requirements.txt").write_text("flask==3.0.3\n", encoding="utf-8")


def time_analysis(base: Path, head: Path, settings) -> dict:
    started = time.perf_counter()
    state = analyze_directories(base, head, settings)
    elapsed = time.perf_counter() - started
    files = len(read_tree(head, settings))
    return {
        "files": files,
        "symbols": sum(len(item.symbols) for item in state.head_files),
        "findings": len(state.findings),
        "seconds": round(elapsed, 3),
        "files_per_second": round(files / elapsed, 2) if elapsed else None,
    }


def detection(settings) -> dict:
    """Recall on the in-repo regression fixture used by the tests."""
    with tempfile.TemporaryDirectory() as scratch:
        base = write_tree(Path(scratch) / "base", BASE)
        head = write_tree(Path(scratch) / "head", HEAD)
        started = time.perf_counter()
        state = analyze_directories(base, head, settings)
        seconds = round(time.perf_counter() - started, 3)
    hit = lambda rule, path: any(item["rule_id"] == rule and item["file"].endswith(path) for item in state.findings)
    matched = [pair for pair in EXPECTED if hit(*pair)]
    missed = [pair for pair in EXPECTED if not hit(*pair)]
    extra = [{"id": item["rule_id"], "file": item["file"]} for item in state.findings if (item["rule_id"], item["file"]) not in set(EXPECTED)]
    return {
        "planted": len(EXPECTED),
        "detected": len(matched),
        "missed": missed,
        "unlabeled": extra,
        "recall": round(len(matched) / len(EXPECTED), 3) if EXPECTED else None,
        "decision": state.risk["decision"],
        "score": state.risk["score"],
        "seconds": seconds,
    }


def main() -> None:
    settings = get_settings()
    out_dir = ROOT / "outputs" / "benchmark-results"
    out_dir.mkdir(parents=True, exist_ok=True)
    scratch = ROOT / "data" / "benchmark-repos"
    sizes = {}
    for label, count in (("small", 50), ("medium", 150), ("large", 500)):
        head = scratch / label
        base = scratch / f"{label}-base"
        write_synthetic(head, count)
        write_synthetic(base, count)
        # One changed file stands in for a pull request.
        changed = head / "backend" / "mod_0.py"
        changed.write_text(changed.read_text(encoding="utf-8") + "\ndef extra():\n    return 1\n", encoding="utf-8")
        sizes[label] = time_analysis(base, head, settings)
    report = {
        "detection": detection(settings),
        "repository_sizes": sizes,
        "note": "detection runs on tests/fixtures.py. repository_sizes are generated timing fixtures, not vulnerability corpora.",
    }
    target = out_dir / "benchmark.json"
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
