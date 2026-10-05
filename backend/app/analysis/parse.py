from __future__ import annotations

import ast
import re
from pathlib import Path

from app.analysis.pyast import call_name, cyclomatic, walk_functions
from app.analysis.types import ParsedFile, Symbol
from app.config import Settings

_JS_FUNC = re.compile(
    r"(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)|const\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_][A-Za-z0-9_]*)\s*=>"
)
_JS_CALL = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_JS_IMPORT = re.compile(r"""import\s+(?:[^'"]+from\s+)?['"]([^'"]+)['"]|require\(\s*['"]([^'"]+)['"]\s*\)""")
_SKIP_CALLS = {
    "if", "for", "while", "switch", "catch", "function", "return", "await",
    "print", "len", "range", "str", "int", "float", "list", "dict", "set", "tuple",
    "isinstance", "hasattr", "super", "enumerate", "zip", "map", "filter", "sorted",
    "min", "max", "sum", "open", "type", "bool", "any", "all",
}


def language_of(path: str, settings: Settings) -> str:
    suffix = Path(path).suffix.lower()
    return settings.extensions.get(suffix, "text")


def _parsers() -> dict:
    parsers: dict = {}
    try:
        import tree_sitter_javascript as javascript
        import tree_sitter_python as python
        from tree_sitter import Language, Parser

        parsers["python"] = Parser(Language(python.language()))
        parsers["javascript"] = Parser(Language(javascript.language()))
    except Exception:
        return {}
    return parsers


PARSERS = _parsers()


def syntax_ok(language: str, source: str) -> bool:
    parser = PARSERS.get(language)
    if parser is None:
        return False
    try:
        tree = parser.parse(source.encode("utf-8"))
    except Exception:
        return False
    return not tree.root_node.has_error


def _endpoint(path: str, name: str, settings: Settings) -> bool:
    if name.startswith("_") or name.startswith("test_"):
        return False
    lowered = path.lower()
    return any(pattern in lowered for pattern in settings.endpoint_file_patterns)


def parse_python(path: str, source: str, settings: Settings) -> ParsedFile:
    symbols: list[Symbol] = []
    imports: list[str] = []
    tree = None
    try:
        tree = ast.parse(source)
    except SyntaxError:
        tree = None
    parser_name = "tree-sitter+ast" if syntax_ok("python", source) else "ast"
    if tree is None:
        return ParsedFile(path, "python", [], [], "unparsed")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    is_test_file = "/tests/" in f"/{path}" or Path(path).name.startswith("test_")
    for fn, qual in walk_functions(tree):
        calls = sorted({call_name(child) for child in ast.walk(fn) if isinstance(child, ast.Call) and call_name(child) and call_name(child) not in _SKIP_CALLS})
        kind = "endpoint" if _endpoint(path, fn.name, settings) else "function"
        symbols.append(
            Symbol(
                sid=f"sym:{path}::{qual}",
                name=fn.name,
                qualname=qual,
                kind=kind,
                file=path,
                start=fn.lineno,
                end=getattr(fn, "end_lineno", fn.lineno) or fn.lineno,
                complexity=cyclomatic(fn),
                calls=calls,
                params=[arg.arg for arg in fn.args.args],
                is_test=is_test_file or fn.name.startswith("test_"),
            )
        )
    return ParsedFile(path, "python", symbols, imports, parser_name)


def _js_from_tree(path: str, source: str, settings: Settings) -> ParsedFile | None:
    parser = PARSERS.get("javascript")
    if parser is None:
        return None
    try:
        tree = parser.parse(source.encode("utf-8"))
    except Exception:
        return None
    spans: list[dict] = []
    imports: list[str] = []
    calls: list[tuple[str, int]] = []

    def walk(node) -> None:
        if node.type == "import_statement":
            for child in node.children:
                if child.type == "string":
                    fragment = "".join(part.text.decode() for part in child.children if part.type == "string_fragment")
                    if fragment:
                        imports.append(fragment)
        if node.type in {"function_declaration", "method_definition"}:
            ident = node.child_by_field_name("name")
            if ident is not None:
                spans.append(
                    {
                        "name": ident.text.decode(),
                        "start": node.start_point.row + 1,
                        "end": node.end_point.row + 1,
                    }
                )
        if node.type == "variable_declarator":
            ident = node.child_by_field_name("name")
            value = node.child_by_field_name("value")
            if ident is not None and value is not None and value.type in {"arrow_function", "function_expression"}:
                spans.append(
                    {
                        "name": ident.text.decode(),
                        "start": node.start_point.row + 1,
                        "end": node.end_point.row + 1,
                    }
                )
        if node.type == "call_expression":
            func = node.child_by_field_name("function")
            if func is not None and func.type == "identifier":
                calls.append((func.text.decode(), node.start_point.row + 1))
        for child in node.children:
            walk(child)

    walk(tree.root_node)
    symbols = []
    for span in spans:
        owned = sorted({name for name, line in calls if span["start"] <= line <= span["end"] and name not in _SKIP_CALLS and name != span["name"]})
        symbols.append(
            Symbol(
                sid=f"sym:{path}::{span['name']}",
                name=span["name"],
                qualname=span["name"],
                kind="function",
                file=path,
                start=span["start"],
                end=span["end"],
                calls=owned,
            )
        )
    return ParsedFile(path, "javascript", symbols, imports, "tree-sitter")


def parse_javascript(path: str, source: str, settings: Settings) -> ParsedFile:
    parsed = _js_from_tree(path, source, settings)
    if parsed is not None:
        return parsed
    symbols = []
    for match in _JS_FUNC.finditer(source):
        name = match.group(1) or match.group(2)
        line = source.count("\n", 0, match.start()) + 1
        symbols.append(
            Symbol(
                sid=f"sym:{path}::{name}",
                name=name,
                qualname=name,
                kind="function",
                file=path,
                start=line,
                end=line,
            )
        )
    imports = [left or right for left, right in _JS_IMPORT.findall(source)]
    return ParsedFile(path, "javascript", symbols, imports, "regex")


def parse_source(path: str, source: str, settings: Settings) -> ParsedFile | None:
    language = language_of(path, settings)
    if language == "python":
        return parse_python(path, source, settings)
    if language == "javascript":
        return parse_javascript(path, source, settings)
    return None
