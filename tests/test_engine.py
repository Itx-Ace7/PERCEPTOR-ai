import json
from pathlib import Path

import pytest

from app.analysis.autofix import apply_fixes, fstring_sql
from app.analysis.llm import _findings_from_document, _parse_model_json, build_batches
from app.analysis.snapshots import read_tree, scan_tree
from app.analysis.stages import _focus_graph, analyze_directories, stage_diff, stage_parse, stage_risk
from app.analysis.types import AnalysisState
from app.config import get_settings

from fixtures import BASE, EXPECTED, HEAD, write_tree


@pytest.fixture()
def trees(tmp_path: Path):
    return write_tree(tmp_path / "base", BASE), write_tree(tmp_path / "head", HEAD)


def test_planted_regressions_are_detected(trees):
    base, head = trees
    state = analyze_directories(base, head, get_settings())
    missing = [
        (rule, path)
        for rule, path in EXPECTED
        if not any(item["rule_id"] == rule and item["file"].endswith(path) for item in state.findings)
    ]
    assert missing == []
    assert state.risk["decision"] == "NOT_READY"
    assert state.impact["counts"]["changed_files"] >= 5
    assert state.impact["failure_chains"]


def test_repairs_clear_blocking_findings(trees, tmp_path: Path):
    settings = get_settings()
    base, head = trees
    before = analyze_directories(base, head, settings)
    updated, _notes = apply_fixes(read_tree(head, settings), read_tree(base, settings), before.findings, settings.rules)
    fixed = write_tree(tmp_path / "fixed", updated)
    after = analyze_directories(base, fixed, settings)
    blocking = [
        item["rule_id"]
        for item in after.findings
        if item["severity"] in set(settings.policy.get("always_blocking_severities", []))
        or (
            item["severity"] in set(settings.policy["blocker_severities"])
            and item["category"] in set(settings.policy["blocker_categories"])
        )
    ]
    assert blocking == []
    assert after.risk["decision"] in {"READY", "READY_WITH_WARNINGS"}


def test_newline_only_difference_is_a_snapshot():
    settings = get_settings()
    source = "def charge(amount):\n    return amount\n"
    state = AnalysisState(workspace=".", base={"billing.py": source}, head={"billing.py": source.replace("\n", "\r\n")})
    stage_parse(state, settings)
    stage_diff(state, settings)
    assert state.diff["changed_files"] == []
    assert state.diff["scope"] == "snapshot"
    assert "billing.py" in state.diff["review_files"]


def test_snapshot_review_includes_the_whole_tree(trees):
    settings = get_settings()
    _base, head = trees
    state = analyze_directories(head, head, settings)
    assert state.diff["scope"] == "snapshot"
    assert state.diff["changed_files"] == []
    reviewed = set(state.diff["review_files"])
    assert "backend/repo.py" in reviewed
    assert "backend/routes.py" in reviewed
    batches = build_batches(state, settings)
    assert batches
    joined = "\n".join(batches)
    assert "Scope: full snapshot" in joined
    assert "FILE backend/repo.py" in joined
    assert "SELECT" in joined


def test_model_findings_accept_wrapped_json():
    raw = """```json
    {"findings":[{"severity":"HIGH","category":"SECURITY","title":"Token stored in the page","file":"frontend/checkout.js","line":4,"evidence":"innerHTML","impact":"","recommendation":"","confidence":0.7}]}
    ```"""
    findings = _findings_from_document(_parse_model_json(raw), {"frontend/checkout.js", "backend/routes.py"})
    assert len(findings) == 1
    assert findings[0]["source"] == "llm"
    assert findings[0]["file"] == "frontend/checkout.js"


def test_correlation_merges_repeated_sql_signals(trees):
    base, head = trees
    state = analyze_directories(base, head, get_settings())
    sql = [item for item in state.findings if item["rule_id"] == "SEC-SQLI"]
    assert len(sql) == 1
    assert len(sql[0]["checks"]) >= 1


def test_sql_fix_drops_quotes_around_placeholders():
    source = (
        "def f(conn, cid, status):\n"
        "    return conn.execute(f\"SELECT * FROM t WHERE c = '{cid}' AND s = {status}\").fetchall()\n"
    )
    fixed, _note = fstring_sql(source, "")
    assert "'{" not in fixed and "'?'" not in fixed
    assert 'c = ? AND s = ?", (cid, status,)' in fixed
    compile(fixed, "fixed.py", "exec")


def test_focus_graph_stays_inside_the_limit_when_every_node_changed():
    nodes = [
        {"id": f"n{index}", "kind": "function" if index % 2 else "file", "changed": True}
        for index in range(500)
    ]
    edges = [
        {"id": f"e{index}", "source": f"n{index}", "target": f"n{index + 1}", "kind": "calls"}
        for index in range(499)
    ]
    focused = _focus_graph(nodes, edges, 80)
    assert focused["truncated"] is True
    assert len(focused["nodes"]) <= 80


def test_scan_tree_reports_why_files_are_skipped(tmp_path: Path):
    settings = get_settings()
    (tmp_path / "app.py").write_text("print('x')\n", encoding="utf-8")
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\0\0")
    (tmp_path / "huge.txt").write_text("x" * (settings.max_file_bytes + 1), encoding="utf-8")
    texts, skipped = scan_tree(tmp_path, settings)
    assert list(texts) == ["app.py"]
    assert {item["path"]: item["reason"] for item in skipped} == {"logo.png": "binary", "huge.txt": "too large"}


def test_notebook_is_flattened_to_code_cells(tmp_path: Path):
    settings = get_settings()
    cells = [
        {"cell_type": "markdown", "source": ["# title"]},
        {"cell_type": "code", "source": ["!pip install x\n", "x = 1\n"], "outputs": [{"data": {"image/png": "A" * 400000}}]},
    ]
    (tmp_path / "ml.ipynb").write_text(json.dumps({"cells": cells}), encoding="utf-8")
    texts, skipped = scan_tree(tmp_path, settings)
    assert skipped == []
    assert "x = 1" in texts["ml.ipynb"] and "# !pip install x" in texts["ml.ipynb"]
    assert "title" not in texts["ml.ipynb"] and "AAAA" not in texts["ml.ipynb"]
    state = AnalysisState(workspace=str(tmp_path), base=texts, head=texts)
    stage_parse(state, settings)
    assert state.head_files and state.head_files[0].language == "python"


def test_critical_finding_blocks_release_in_any_category():
    settings = get_settings()
    state = AnalysisState(workspace=".", base={}, head={})
    state.findings = [
        {"id": "Q-1", "severity": "CRITICAL", "category": "QUALITY", "title": "t", "file": "a.md", "line": 1, "recommendation": "r"}
    ]
    stage_risk(state, settings)
    assert state.risk["decision"] == "NOT_READY"
    state.findings[0]["severity"] = "MEDIUM"
    stage_risk(state, settings)
    assert state.risk["decision"] == "READY_WITH_WARNINGS"


def test_review_stops_waiting_when_the_budget_is_spent(trees, monkeypatch):
    import time

    from app.analysis import llm

    settings = get_settings()
    base, head = trees
    state = analyze_directories(base, head, settings)
    monkeypatch.setattr(settings, "llm_total_budget", 0.3)
    monkeypatch.setattr(settings, "api_key", "test")

    class Slow(llm.LLMProvider):
        def complete(self, system, user):
            time.sleep(3)
            return "{}"

    monkeypatch.setattr(llm, "provider_for", lambda _settings: Slow())
    started = time.monotonic()
    with pytest.raises(RuntimeError):
        llm.review(state, settings)
    assert time.monotonic() - started < 2.5


def test_paths_the_host_cannot_hold_are_detected(monkeypatch):
    from app.analysis import snapshots

    monkeypatch.setattr(snapshots.os, "name", "nt")
    assert snapshots.portable_path("src/app.py")
    for bad in ("contracts/PIBank.sol:", "tests/test\\_example.py", "docs/con.txt", "a/b?.py", "dir./x.py"):
        assert not snapshots.portable_path(bad), bad
    monkeypatch.setattr(snapshots.os, "name", "posix")
    assert snapshots.portable_path("tests/test\\_example.py")


def test_overlong_paths_are_skipped_on_windows(monkeypatch):
    from app.analysis import snapshots

    monkeypatch.setattr(snapshots.os, "name", "nt")
    assert snapshots.portable_path("a" * 100, root_len=100, max_len=250)
    assert not snapshots.portable_path("a" * 160, root_len=100, max_len=250)


def test_parent_snapshot_differs_only_by_the_commit(tmp_path: Path):
    import subprocess

    from app.analysis.snapshots import parent_texts

    settings = get_settings()

    def run(*args):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=tmp_path, check=True, capture_output=True)

    run("init", "-q")
    for index in range(6):
        (tmp_path / f"f{index}.py").write_text(f"x = {index}\n", encoding="utf-8")
    run("add", "-A")
    run("commit", "-q", "-m", "one")
    (tmp_path / "f0.py").write_text("x = 100\n", encoding="utf-8")
    (tmp_path / "new.py").write_text("y = 1\n", encoding="utf-8")
    (tmp_path / "f5.py").unlink()
    run("add", "-A")
    run("commit", "-q", "-m", "two")
    head = read_tree(tmp_path, settings)
    base = parent_texts(tmp_path, "HEAD~1", head, settings)
    assert base["f0.py"] == "x = 0\n" and "new.py" not in base and base["f5.py"] == "x = 5\n"
    state = AnalysisState(workspace=str(tmp_path), base=base, head=head)
    stage_parse(state, settings)
    stage_diff(state, settings)
    assert {item["path"]: item["status"] for item in state.diff["changed_files"]} == {"f0.py": "modified", "new.py": "added", "f5.py": "deleted"}


def test_secret_rule_ignores_fixtures_and_placeholders_but_keeps_real_keys():
    settings = get_settings()
    head = {
        "app/config.py": "api_key = 'your_api_key_here'\nstripe = 'sk_live_abcdefgh12345678'\ndb_password = 'Zk39sd8Qpx02mLw'\n",
        "app/tests/test_auth.py": "password = 'mysecretpassword'\n",
        "tests/test_x.py": "api_key = 'abcdefghijklmnop'\n",
        "bank/auth_test.py": "secret = 'abcdefghijklmnop'\n",
    }
    state = AnalysisState(workspace=".", base=dict(head), head=head)
    stage_parse(state, settings)
    from app.analysis.hooks import run_rules

    hits = run_rules(settings.rules, state, settings, "static")
    secrets = sorted((item["file"], item["line"]) for item in hits if item["rule_id"] == "SEC-SECRET")
    assert secrets == [("app/config.py", 2), ("app/config.py", 3)]


def test_interrupted_runs_are_closed_on_startup(tmp_path: Path):
    from app.db import Database

    db = Database(tmp_path / "t.db")
    db.insert_repository({"id": "r"})
    for run_id, status in (("a", "RUNNING"), ("b", "QUEUED"), ("c", "COMPLETED")):
        db.insert_run(run_id, "r")
        db.update_run(run_id, status)
    assert db.fail_interrupted("restart") == 2
    assert [db.run(i)["status"] for i in "abc"] == ["FAILED", "FAILED", "COMPLETED"]


def test_degraded_model_result_is_not_cacheable(monkeypatch):
    from app.analysis import llm

    settings = get_settings()
    monkeypatch.setattr(settings, "api_key", "test")
    monkeypatch.setattr(llm, "review", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("model request failed")))
    result = llm.stage_ai(AnalysisState(workspace=".", base={}, head={}), settings)
    assert result["degraded"] is True and result["ai_findings"] == []


def test_retention_removes_old_runs_but_never_paths_outside_the_workspaces(tmp_path: Path, monkeypatch):
    from app.db import Database
    from app.pipeline.retention import prune

    settings = get_settings()
    monkeypatch.setattr(settings, "workspaces", tmp_path / "ws")
    monkeypatch.setattr(settings, "retain_runs", 1)
    outside = tmp_path / "precious"
    outside.mkdir()
    (outside / "keep.txt").write_text("x", encoding="utf-8")
    inside = settings.workspaces / "old"
    inside.mkdir(parents=True)
    db = Database(tmp_path / "t.db")
    for run_id, repo_id, workspace in (("old", "r1", inside), ("evil", "r2", outside), ("new", "r3", settings.workspaces / "new")):
        db.insert_repository({"id": repo_id})
        db.update_repository(repo_id, workspace=str(workspace))
        db.insert_run(run_id, repo_id)
        db.update_run(run_id, "COMPLETED", finished=True)
        db.execute("UPDATE runs SET started_at = ? WHERE id = ?", ({"old": "2026-01-01", "evil": "2026-01-02", "new": "2026-01-03"}[run_id], run_id))
    assert prune(settings, db) == 2
    assert not inside.exists()
    assert (outside / "keep.txt").exists()
    assert db.run("new") is not None and db.run("old") is None and db.repository("r1") is None


def test_file_limit_keeps_source_code_before_data(tmp_path: Path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "max_files", 2)
    for name in ("a.json", "b.md", "z_service.py", "y_handler.js"):
        (tmp_path / name).write_text("x = 1\n", encoding="utf-8")
    texts, skipped = scan_tree(tmp_path, settings)
    assert sorted(texts) == ["y_handler.js", "z_service.py"]
    assert {item["path"] for item in skipped if item["reason"] == "file limit reached"} == {"a.json", "b.md"}


def test_retention_deletes_readonly_git_files_and_sweeps_orphans(tmp_path: Path, monkeypatch):
    import os
    import stat

    from app.db import Database
    from app.pipeline.retention import prune

    settings = get_settings()
    monkeypatch.setattr(settings, "workspaces", tmp_path / "ws")
    monkeypatch.setattr(settings, "retain_runs", 5)
    db = Database(tmp_path / "t.db")
    db.insert_repository({"id": "live"})
    db.insert_run("run1", "live")
    (settings.workspaces / "live").mkdir(parents=True)
    orphan = settings.workspaces / "gone"
    packed = orphan / ".git" / "objects" / "ab"
    packed.mkdir(parents=True)
    obj = packed / "cdef"
    obj.write_text("x", encoding="utf-8")
    os.chmod(obj, stat.S_IREAD)
    (settings.workspaces / "gone-fixed").mkdir()
    prune(settings, db)
    assert not orphan.exists() and not (settings.workspaces / "gone-fixed").exists()
    assert (settings.workspaces / "live").exists()


def _risk_for(findings: list[dict]) -> dict:
    state = AnalysisState(workspace=".", base={}, head={})
    state.findings = findings
    stage_risk(state, get_settings())
    return state.risk


def _finding(index: int, severity="HIGH", category="SECURITY", rule="R", file=None) -> dict:
    return {
        "id": f"F-{index}", "rule_id": rule, "severity": severity, "category": category,
        "file": file or f"f{index}.py", "line": 1, "title": "t", "recommendation": "r",
    }


def test_score_never_decreases_when_findings_are_added():
    findings, previous = [], -1
    for index in range(60):
        findings.append(_finding(index, severity=("CRITICAL", "HIGH", "MEDIUM")[index % 3], category=("SECURITY", "REGRESSION", "CONFIG")[index % 3]))
        score = _risk_for(findings)["score"]
        assert score >= previous, (index, previous, score)
        previous = score


def test_more_findings_score_higher_even_past_the_old_cap():
    five_hundred = _risk_for([_finding(i) for i in range(20)])["dimensions"]["security"]["score"]
    thousand = _risk_for([_finding(i) for i in range(40)])["dimensions"]["security"]["score"]
    assert thousand > five_hundred


def test_repeats_inside_one_finding_count_less_than_distinct_issues():
    merged = dict(_finding(0), checks=[{}] * 8)
    one_finding_eight_hits = _risk_for([merged])["dimensions"]["security"]["score"]
    single = _risk_for([_finding(0)])["dimensions"]["security"]["score"]
    eight_distinct = _risk_for([_finding(i) for i in range(8)])["dimensions"]["security"]["score"]
    assert single < one_finding_eight_hits < eight_distinct


def test_model_call_has_a_hard_wall_clock_limit(monkeypatch):
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, HTTPServer

    import httpx

    from app.analysis.llm import OpenRouterProvider

    class Trickle(BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            try:
                for _ in range(40):
                    self.wfile.write(b" ")
                    self.wfile.flush()
                    time.sleep(0.25)
            except OSError:
                pass

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Trickle)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_base_url", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setattr(settings, "llm_timeout", 1.0)
    monkeypatch.setattr(settings, "llm_retries", 0)
    monkeypatch.setattr(settings, "api_key", "k")
    started = time.monotonic()
    with pytest.raises(httpx.TimeoutException):
        OpenRouterProvider(settings).complete("s", "u")
    server.shutdown()
    assert time.monotonic() - started < 4


def test_api_token_gates_everything_except_health(monkeypatch):
    from fastapi.testclient import TestClient

    from app import runtime
    from app.main import app

    client = TestClient(app)
    settings = runtime.settings
    monkeypatch.setattr(settings, "api_token", "")
    assert client.get("/api/runs").status_code == 200
    monkeypatch.setattr(settings, "api_token", "s3cret")
    assert client.get("/api/health").json()["auth_required"] is True
    assert client.get("/api/runs").status_code == 401
    assert client.get("/api/runs", headers={"x-api-key": "wrong"}).status_code == 401
    assert client.get("/api/runs", headers={"x-api-key": "s3cret"}).status_code == 200
    assert client.get("/api/runs?api_key=s3cret").status_code == 200
    assert client.get("/api/runs/nope/events").status_code == 401


def test_graph_focus_keeps_connected_hubs_over_isolated_flagged_nodes():
    from app.analysis.stages import _focus_graph

    isolated = [
        {"id": f"iso{i}", "label": f"iso{i}", "kind": "endpoint", "severity": "HIGH", "file": "a.py"} for i in range(40)
    ]
    hub = {"id": "hub", "label": "hub", "kind": "function", "severity": None, "file": "b.py"}
    spokes = [{"id": f"s{i}", "label": f"s{i}", "kind": "function", "severity": None, "file": "b.py"} for i in range(6)]
    edges = [{"id": f"e{i}", "source": "hub", "target": f"s{i}", "kind": "calls"} for i in range(6)]
    focus = _focus_graph([*isolated, hub, *spokes], edges, limit=20)
    kept = {node["id"] for node in focus["nodes"]}
    assert "hub" in kept and {f"s{i}" for i in range(6)} <= kept
    assert focus["truncated"] is True and len(kept) <= 20


def test_minified_bundles_are_skipped_with_a_reason(tmp_path: Path):
    settings = get_settings()
    (tmp_path / "app.js").write_text("function a() {\n  return 1;\n}\n" * 400, encoding="utf-8")
    (tmp_path / "vendor.js").write_text("var a=function(b){return b};" * 400 + "\n", encoding="utf-8")
    (tmp_path / "lib.min.js").write_text("x=1;\n", encoding="utf-8")
    texts, skipped = scan_tree(tmp_path, settings)
    assert list(texts) == ["app.js"]
    assert {item["path"]: item["reason"] for item in skipped} == {
        "vendor.js": "minified or generated",
        "lib.min.js": "minified or generated",
    }


def test_calls_do_not_link_unrelated_code_that_shares_a_name():
    from app.analysis.stages import build_graph

    settings = get_settings()
    head = {
        "svc/main.py": "import time\n\ndef run():\n    sleep(1)\n    helper()\n\ndef helper():\n    return 1\n",
        "web/utils.js": "export function sleep(ms) { return ms; }\n",
        "other/helper.py": "def helper():\n    return 2\n",
        "svc/util.py": "def sleep(x):\n    return x\n",
    }
    state = AnalysisState(workspace=".", base=dict(head), head=head)
    stage_parse(state, settings)
    stage_diff(state, settings)
    graph = build_graph(state, settings)
    calls = {(e["source"].split("::")[-1], e["target"]) for e in graph["edges"] if e["kind"] == "calls"}
    targets = {t for _s, t in calls}
    assert "sym:svc/main.py::helper" in targets            # same file wins
    assert "sym:svc/util.py::sleep" in targets             # same folder, same language
    assert not any("web/utils.js" in t or "other/helper.py" in t for t in targets)
