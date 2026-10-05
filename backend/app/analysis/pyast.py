from __future__ import annotations

import ast


def parse(source: str) -> ast.AST | None:
    try:
        return ast.parse(source)
    except SyntaxError:
        return None


def walk_functions(tree: ast.AST) -> list[tuple[ast.FunctionDef, str]]:
    found: list[tuple[ast.FunctionDef, str]] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.stack: list[str] = []

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self.stack.append(node.name)
            found.append((node, ".".join(self.stack)))
            self.generic_visit(node)
            self.stack.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

    Visitor().visit(tree)
    return found


def functions_by_name(source: str) -> dict[str, ast.FunctionDef]:
    tree = parse(source)
    if tree is None:
        return {}
    return {qual: node for node, qual in walk_functions(tree)}


def call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def call_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            name = call_name(child)
            if name:
                names.add(name)
    return names


def cyclomatic(node: ast.AST) -> int:
    score = 1
    for child in ast.walk(node):
        if isinstance(child, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.IfExp, ast.Assert)):
            score += 1
        elif isinstance(child, ast.BoolOp):
            score += max(len(child.values) - 1, 0)
        elif isinstance(child, (ast.comprehension,)):
            score += 1
    return score


def return_ints(node: ast.AST) -> list[int]:
    values: list[tuple[int, int, int]] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Return) or child.value is None:
            continue
        for item in ast.walk(child.value):
            if isinstance(item, ast.Constant) and type(item.value) is int:
                values.append((item.lineno, item.col_offset, item.value))
    values.sort()
    return [value for _, _, value in values]


def return_int_nodes(node: ast.AST) -> list[ast.Constant]:
    found: list[ast.Constant] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Return) or child.value is None:
            continue
        for item in ast.walk(child.value):
            if isinstance(item, ast.Constant) and type(item.value) is int:
                found.append(item)
    found.sort(key=lambda item: (item.lineno, item.col_offset))
    return found


def _is_lookup(call: ast.Call, markers: list[str]) -> bool:
    name = call_name(call).lower()
    return any(marker in name for marker in markers)


def _exits(statements: list[ast.stmt]) -> bool:
    return any(isinstance(statement, (ast.Raise, ast.Return)) for statement in statements)


def _none_names(test: ast.AST) -> set[str]:
    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or):
        names: set[str] = set()
        for value in test.values:
            names |= _none_names(value)
        return names
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not) and isinstance(test.operand, ast.Name):
        return {test.operand.id}
    if isinstance(test, ast.Compare) and isinstance(test.left, ast.Name):
        none_cmp = any(isinstance(item, ast.Constant) and item.value is None for item in test.comparators)
        identity = any(isinstance(op, (ast.Is, ast.Eq)) for op in test.ops)
        if none_cmp and identity:
            return {test.left.id}
    return set()


def _guard_names(statement: ast.stmt) -> set[str]:
    if isinstance(statement, ast.If) and _exits(statement.body):
        return _none_names(statement.test)
    return set()


def _uses(statement: ast.stmt, tainted: set[str]) -> list[tuple[str, int]]:
    hits: list[tuple[str, int]] = []
    for node in ast.walk(statement):
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id in tainted:
            hits.append((node.value.id, getattr(node, "lineno", statement.lineno)))
    return hits


def _scan_block(statements: list[ast.stmt], tainted: set[str], markers: list[str]) -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []
    live = set(tainted)
    for statement in statements:
        discarded = _guard_names(statement)
        if not discarded:
            found.extend(_uses(statement, live))
        if isinstance(statement, ast.Assign) and isinstance(statement.value, ast.Call) and _is_lookup(statement.value, markers):
            for target in statement.targets:
                if isinstance(target, ast.Name):
                    live.add(target.id)
        live -= discarded
        if isinstance(statement, (ast.For, ast.While, ast.AsyncFor)):
            found.extend(_scan_block(statement.body, live, markers))
        elif isinstance(statement, ast.If):
            if not discarded:
                found.extend(_scan_block(statement.body, live, markers))
            found.extend(_scan_block(statement.orelse, live, markers))
        elif isinstance(statement, (ast.With, ast.AsyncWith, ast.Try)):
            body = getattr(statement, "body", [])
            found.extend(_scan_block(body, live, markers))
    return found


def lookup_risks(source: str, markers: list[str]) -> list[dict]:
    tree = parse(source)
    if tree is None:
        return []
    risks = []
    for fn, qual in walk_functions(tree):
        hits = _scan_block(fn.body, set(), markers)
        if not hits:
            continue
        name, line = hits[0]
        risks.append({"qualname": qual, "name": name, "line": line})
    return risks


def value_guard(fn: ast.FunctionDef, names: set[str]) -> bool:
    params = {arg.arg for arg in fn.args.args}
    watched = params & names if names else params
    if not watched:
        watched = names
    for node in ast.walk(fn):
        if not isinstance(node, ast.Compare):
            continue
        used = {item.id for item in ast.walk(node) if isinstance(item, ast.Name)}
        constants = {item.value for item in ast.walk(node) if isinstance(item, ast.Constant)}
        if used & watched and (0 in constants or None in constants):
            return True
    return False


def first_value_guard(fn: ast.FunctionDef, names: set[str]) -> ast.If | None:
    params = {arg.arg for arg in fn.args.args}
    watched = (params & names) or names
    for statement in fn.body:
        if not isinstance(statement, ast.If):
            continue
        used = {item.id for item in ast.walk(statement.test) if isinstance(item, ast.Name)}
        constants = {item.value for item in ast.walk(statement.test) if isinstance(item, ast.Constant)}
        if used & watched and (0 in constants or None in constants):
            return statement
    return None


def queries_in_loops(fn: ast.FunctionDef, call_names_wanted: set[str]) -> list[int]:
    lines = []
    for node in ast.walk(fn):
        if not isinstance(node, (ast.For, ast.While, ast.AsyncFor)):
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Call) and call_name(child) in call_names_wanted:
                lines.append(child.lineno)
    return lines


def joined_sql(node: ast.JoinedStr, keywords: list[str]) -> tuple[str, list[str]] | None:
    if not any(isinstance(part, ast.FormattedValue) for part in node.values):
        return None
    chunks: list[str] = []
    params: list[str] = []
    parts = node.values
    drop_quote = ""
    for index, part in enumerate(parts):
        if isinstance(part, ast.Constant) and isinstance(part.value, str):
            text = part.value
            if drop_quote and text.startswith(drop_quote):
                text = text[1:]
            drop_quote = ""
            chunks.append(text)
        elif isinstance(part, ast.FormattedValue):
            # A placeholder must not stay inside SQL quotes, or it becomes a literal "?".
            following = parts[index + 1] if index + 1 < len(parts) else None
            quote = chunks[-1][-1:] if chunks else ""
            if (
                quote in {"'", '"'}
                and isinstance(following, ast.Constant)
                and isinstance(following.value, str)
                and following.value.startswith(quote)
            ):
                chunks[-1] = chunks[-1][:-1]
                drop_quote = quote
            chunks.append("?")
            params.append(ast.unparse(part.value))
    text = "".join(chunks)
    upper = text.upper()
    if not any(keyword in upper for keyword in keywords):
        return None
    return text, params
