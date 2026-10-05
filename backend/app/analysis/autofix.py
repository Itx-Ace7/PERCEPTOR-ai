from __future__ import annotations

import ast
import json
import re

from app.analysis.pyast import (
    call_name,
    call_names,
    first_value_guard,
    functions_by_name,
    joined_sql,
    lookup_risks,
    parse,
    return_int_nodes,
    return_ints,
    walk_functions,
)

STRATEGY_ORDER = [
    "fstring_sql",
    "secret_to_env",
    "harden_config",
    "shell_to_argv",
    "innerhtml_to_text",
    "restore_validation",
    "guard_lookup",
    "restore_auth",
    "restore_status",
    "restore_tests",
    "restore_dependency",
]

AUTH_CALLS = {"require_auth", "verify_token", "login_required", "authenticate", "ensure_auth"}
SQL_KEYWORDS = ["SELECT", "INSERT", "UPDATE", "DELETE", "DROP", "ALTER"]
LOOKUP_MARKERS = ["lookup", "get", "find", "fetch"]
VALUE_NAMES = {"amount", "value", "qty", "quantity", "price", "total"}


def _line_offsets(source: str) -> list[int]:
    offsets = [0]
    for index, char in enumerate(source):
        if char == "\n":
            offsets.append(index + 1)
    return offsets


def _apply_spans(source: str, spans: list[tuple[int, int, int, int, str]]) -> str:
    for lineno, col, end_lineno, end_col, new in sorted(spans, key=lambda item: (item[0], item[1]), reverse=True):
        offsets = _line_offsets(source)
        start = offsets[lineno - 1] + col
        end = offsets[end_lineno - 1] + end_col
        source = source[:start] + new + source[end:]
    return source


def _as_block(segment: str, indent: str) -> str:
    lines = segment.strip("\n").splitlines()
    indents = [len(line) - len(line.lstrip()) for line in lines if line.strip()]
    common = min(indents) if indents else 0
    rebuilt = []
    for line in lines:
        rebuilt.append(indent + line[common:] if line.strip() else "")
    return "\n".join(rebuilt)


def _indent_of(source: str, fn: ast.FunctionDef) -> str:
    if fn.body:
        segment = ast.get_source_segment(source, fn.body[0]) or ""
        raw = source.splitlines()[fn.body[0].lineno - 1]
        return raw[: len(raw) - len(raw.lstrip())] or "    "
    return "    " if segment is None else "    "


def _insert_after_def(source: str, fn: ast.FunctionDef, statement: str) -> str:
    lines = source.splitlines()
    indent = _indent_of(source, fn)
    lines.insert(fn.lineno, indent + statement.strip())
    return "\n".join(lines) + ("\n" if source.endswith("\n") else "")


def fstring_sql(head: str, _base: str) -> tuple[str, str]:
    tree = parse(head)
    if tree is None:
        return head, "skipped, file does not parse"
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    spans = []
    pending: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr):
            continue
        built = joined_sql(node, SQL_KEYWORDS)
        if not built:
            continue
        sql, params = built
        parent = parents.get(node)
        literal = json.dumps(sql)
        if isinstance(parent, ast.Call) and call_name(parent) in {"execute", "executemany", "query"} and parent.args and parent.args[0] is node:
            extra = f", ({', '.join(params)},)" if params else ""
            spans.append((node.lineno, node.col_offset, node.end_lineno, node.end_col_offset, literal + extra))
        elif isinstance(parent, ast.Assign):
            spans.append((node.lineno, node.col_offset, node.end_lineno, node.end_col_offset, literal))
            for target in parent.targets:
                if isinstance(target, ast.Name) and params:
                    pending[target.id] = params
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or call_name(node) not in {"execute", "executemany", "query"}:
            continue
        if len(node.args) != 1 or not isinstance(node.args[0], ast.Name):
            continue
        params = pending.get(node.args[0].id)
        if not params:
            continue
        arg = node.args[0]
        spans.append((arg.lineno, arg.col_offset, arg.end_lineno, arg.end_col_offset, f"{arg.id}, ({', '.join(params)},)"))
    if not spans:
        return head, "no interpolated SQL to rewrite"
    return _apply_spans(head, spans), f"rewrote {len(spans)} SQL span{'s' if len(spans) != 1 else ''}"


def secret_to_env(head: str, _base: str) -> tuple[str, str]:
    changed = 0
    lines = []
    pattern = re.compile(r"^(\s*)([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([\"'])(.+)\3\s*$")
    secretish = re.compile(r"sk_(?:live|test)_|AKIA[0-9A-Z]{16}|api_key|secret|password|private_key|access_token", re.IGNORECASE)
    for line in head.splitlines():
        match = pattern.match(line)
        if match and secretish.search(match.group(2) + match.group(4)):
            lines.append(f'{match.group(1)}{match.group(2)} = os.getenv("{match.group(2)}", "")')
            changed += 1
        else:
            lines.append(line)
    if not changed:
        return head, "no secret assignment to lift"
    text = "\n".join(lines) + ("\n" if head.endswith("\n") else "")
    if not re.search(r"^\s*import os\b", text, re.MULTILINE):
        text = "import os\n" + text
    return text, f"moved {changed} secret{'s' if changed != 1 else ''} to the environment"


def harden_config(head: str, _base: str) -> tuple[str, str]:
    text = re.sub(r"\bDEBUG\s*=\s*True\b", "DEBUG = False", head)
    text = text.replace("0.0.0.0", "127.0.0.1")
    text = re.sub(r"""allow_origins\s*=\s*\[\s*["']\*["']\s*\]""", "allow_origins = []", text)
    if text == head:
        return head, "configuration already hardened"
    return text, "disabled debug mode and closed the bind address"


def shell_to_argv(head: str, _base: str) -> tuple[str, str]:
    text, count = re.subn(r"\bos\.system\s*\(", "subprocess.run(", head)
    if not count:
        return head, "no shell call to rewrite"
    if "import subprocess" not in text:
        text = "import subprocess\n" + text
    return text, "replaced os.system with subprocess.run"


def innerhtml_to_text(head: str, _base: str) -> tuple[str, str]:
    text = head.replace(".innerHTML", ".textContent")
    if text == head:
        return head, "no innerHTML write"
    return text, "wrote text instead of HTML"


def restore_validation(head: str, base: str) -> tuple[str, str]:
    if not base.strip():
        return head, "no baseline"
    before = functions_by_name(base)
    after = functions_by_name(head)
    text = head
    restored = 0
    # Insert from the bottom so line numbers stay valid for earlier functions.
    edits = []
    for qual, fn in after.items():
        old = before.get(qual)
        if old is None:
            continue
        guard = first_value_guard(old, VALUE_NAMES)
        if guard is None or first_value_guard(fn, VALUE_NAMES) is not None:
            continue
        segment = ast.get_source_segment(base, guard)
        if not segment:
            continue
        edits.append((fn.lineno, segment))
    for lineno, segment in sorted(edits, reverse=True):
        lines = text.splitlines()
        lines.insert(lineno, _as_block(segment, "    "))
        text = "\n".join(lines) + ("\n" if text.endswith("\n") or head.endswith("\n") else "")
        restored += 1
    if not restored:
        return head, "no validation to restore"
    return text, f"restored {restored} validation guard{'s' if restored != 1 else ''}"


def guard_lookup(head: str, base: str) -> tuple[str, str]:
    risks = lookup_risks(head, LOOKUP_MARKERS)
    if not risks:
        return head, "no unguarded lookup"
    before = functions_by_name(base) if base.strip() else {}
    text = head
    restored = 0
    edits = []
    current = functions_by_name(text)
    for risk in risks:
        fn = current.get(risk["qualname"])
        if fn is None:
            continue
        old = before.get(risk["qualname"])
        segment = None
        if old is not None:
            for statement in old.body:
                if isinstance(statement, ast.If) and risk["name"] in ast.unparse(statement.test):
                    segment = ast.get_source_segment(base, statement)
                    break
        if not segment:
            segment = f'if {risk["name"]} is None:\n    raise ValueError("missing {risk["name"]}")'
        edits.append((risk["line"], segment))
    seen_lines = set()
    for line, segment in sorted(edits, reverse=True):
        if line in seen_lines:
            continue
        seen_lines.add(line)
        rows = text.splitlines()
        indent = "    "
        if 1 <= line <= len(rows):
            raw = rows[line - 1]
            indent = raw[: len(raw) - len(raw.lstrip())] or "    "
        rows.insert(line - 1, _as_block(segment, indent))
        text = "\n".join(rows) + ("\n" if head.endswith("\n") else "")
        restored += 1
    if not restored:
        return head, "no guard inserted"
    return text, f"guarded {restored} lookup{'s' if restored != 1 else ''}"


def restore_auth(head: str, base: str) -> tuple[str, str]:
    if not base.strip():
        return head, "no baseline"
    before = functions_by_name(base)
    after = functions_by_name(head)
    text = head
    restored = 0
    needed: set[str] = set()
    edits = []
    for qual, fn in after.items():
        old = before.get(qual)
        if old is None:
            continue
        missing = (call_names(old) & AUTH_CALLS) - call_names(fn)
        if not missing:
            continue
        needed |= missing
        segment = None
        for statement in old.body:
            if call_names(statement) & missing:
                segment = ast.get_source_segment(base, statement)
                break
        if segment:
            edits.append((fn.lineno, segment.strip()))
    for lineno, segment in sorted(edits, reverse=True):
        lines = text.splitlines()
        lines.insert(lineno, "    " + segment)
        text = "\n".join(lines) + ("\n" if head.endswith("\n") else "")
        restored += 1
    if needed:
        for line in base.splitlines():
            if line.startswith(("import ", "from ")) and any(name in line for name in needed) and line not in text:
                text = line + "\n" + text
    if not restored:
        return head, "no authentication call to restore"
    return text, f"restored {restored} authentication check{'s' if restored != 1 else ''}"


def restore_status(head: str, base: str) -> tuple[str, str]:
    if not base.strip():
        return head, "no baseline"
    before = functions_by_name(base)
    after = functions_by_name(head)
    spans = []
    for qual, fn in after.items():
        old = before.get(qual)
        if old is None:
            continue
        old_values = return_ints(old)
        new_nodes = return_int_nodes(fn)
        if len(old_values) != len(new_nodes):
            continue
        for value, node in zip(old_values, new_nodes):
            if node.value != value:
                spans.append((node.lineno, node.col_offset, node.end_lineno, node.end_col_offset, str(value)))
    if not spans:
        return head, "no status code to restore"
    return _apply_spans(head, spans), f"restored {len(spans)} response status{'es' if len(spans) != 1 else ''}"


def restore_tests(head: str, base: str) -> tuple[str, str]:
    if not base.strip():
        return head, "no baseline"
    before = functions_by_name(base)
    after = set(functions_by_name(head))
    blocks = []
    for qual, fn in before.items():
        if not fn.name.startswith("test_") or qual in after:
            continue
        segment = ast.get_source_segment(base, fn)
        if segment:
            blocks.append(segment.strip())
    if not blocks:
        return head, "no test to restore"
    text = head
    for line in base.splitlines():
        if line.startswith(("import ", "from ")) and line not in text:
            text = line + "\n" + text
    text = text.rstrip() + "\n\n" + "\n\n".join(blocks) + "\n"
    return text, f"restored {len(blocks)} test{'s' if len(blocks) != 1 else ''}"


def _requirements(text: str) -> dict[str, str]:
    found = {}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        match = re.match(r"([A-Za-z0-9_.-]+)\s*==\s*([A-Za-z0-9_.*+\-]+)", line)
        if match:
            found[match.group(1).lower()] = match.group(2)
    return found


def restore_dependency(head: str, base: str) -> tuple[str, str]:
    if not base.strip():
        return head, "no baseline"
    if PathLikeJson(head):
        return _restore_package_json(head, base)
    old = _requirements(base)
    new = _requirements(head)
    text = head
    restored = 0
    for name, version in new.items():
        previous = old.get(name)
        if previous and version != previous:
            text = re.sub(rf"({re.escape(name)}\s*==\s*){re.escape(version)}", rf"\g<1>{previous}", text, flags=re.IGNORECASE)
            restored += 1
    if not restored:
        return head, "no dependency pin to restore"
    return text, f"restored {restored} dependency pin{'s' if restored != 1 else ''}"


def PathLikeJson(text: str) -> bool:
    stripped = text.lstrip()
    return stripped.startswith("{") and "dependencies" in stripped


def _restore_package_json(head: str, base: str) -> tuple[str, str]:
    try:
        old = json.loads(base)
        new = json.loads(head)
    except json.JSONDecodeError:
        return head, "package.json did not parse"
    restored = 0
    for section in ("dependencies", "devDependencies"):
        for name, version in list((new.get(section) or {}).items()):
            previous = (old.get(section) or {}).get(name)
            if previous and previous != version:
                new[section][name] = previous
                restored += 1
    if not restored:
        return head, "no package pin to restore"
    return json.dumps(new, indent=2) + "\n", f"restored {restored} package pin{'s' if restored != 1 else ''}"


STRATEGIES = {
    "fstring_sql": fstring_sql,
    "secret_to_env": secret_to_env,
    "harden_config": harden_config,
    "shell_to_argv": shell_to_argv,
    "innerhtml_to_text": innerhtml_to_text,
    "restore_validation": restore_validation,
    "guard_lookup": guard_lookup,
    "restore_auth": restore_auth,
    "restore_status": restore_status,
    "restore_tests": restore_tests,
    "restore_dependency": restore_dependency,
}


def apply_fixes(files: dict[str, str], base: dict[str, str], findings: list[dict], rules: list[dict]) -> tuple[dict[str, str], list[dict]]:
    by_id = {rule["id"]: rule for rule in rules}
    wanted: dict[str, list[str]] = {}
    for finding in findings:
        rule = by_id.get(finding.get("rule_id"))
        strategy = ((rule or {}).get("autofix") or {}).get("strategy")
        if strategy and finding.get("file"):
            wanted.setdefault(finding["file"], [])
            if strategy not in wanted[finding["file"]]:
                wanted[finding["file"]].append(strategy)
    updated = dict(files)
    notes = []
    for path, strategies in wanted.items():
        if path not in updated:
            notes.append({"file": path, "strategy": ",".join(strategies), "note": "file missing from the tree"})
            continue
        text = updated[path]
        original = base.get(path, "")
        ordered = [name for name in STRATEGY_ORDER if name in strategies]
        for name in ordered:
            text, note = STRATEGIES[name](text, original)
            notes.append({"file": path, "strategy": name, "note": note})
        updated[path] = text
    return updated, notes
