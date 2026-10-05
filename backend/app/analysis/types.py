from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field


_SECRET = re.compile(r"sk_(?:live|test)_[A-Za-z0-9]+|AKIA[0-9A-Z]{16}")


def redact(text: str) -> str:
    return _SECRET.sub("[REDACTED]", text)


@dataclass
class Symbol:
    sid: str
    name: str
    qualname: str
    kind: str
    file: str
    start: int
    end: int
    complexity: int = 1
    calls: list[str] = field(default_factory=list)
    params: list[str] = field(default_factory=list)
    is_test: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Symbol":
        return cls(**data)


@dataclass
class ParsedFile:
    path: str
    language: str
    symbols: list[Symbol]
    imports: list[str]
    parser: str

    def to_dict(self) -> dict:
        payload = asdict(self)
        return payload

    @classmethod
    def from_dict(cls, data: dict) -> "ParsedFile":
        symbols = [Symbol.from_dict(item) for item in data.get("symbols", [])]
        return cls(
            path=data["path"],
            language=data["language"],
            symbols=symbols,
            imports=list(data.get("imports", [])),
            parser=data.get("parser", "builtin"),
        )


@dataclass
class AnalysisState:
    workspace: str
    base: dict[str, str]
    head: dict[str, str]
    commit_sha: str = ""
    skipped: list[dict] = field(default_factory=list)
    head_files: list[ParsedFile] = field(default_factory=list)
    base_files: list[ParsedFile] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    diff: dict = field(default_factory=dict)
    static_findings: list[dict] = field(default_factory=list)
    test_findings: list[dict] = field(default_factory=list)
    ai_findings: list[dict] = field(default_factory=list)
    ai_note: str = ""
    findings: list[dict] = field(default_factory=list)
    graph: dict = field(default_factory=dict)
    impact: dict = field(default_factory=dict)
    risk: dict | None = None


def finding_dict(
    rule: dict,
    file: str,
    line: int,
    evidence: str,
    symbol: str | None = None,
    source: str = "static",
    severity: str | None = None,
) -> dict:
    return {
        "rule_id": rule["id"],
        "severity": severity or rule["severity"],
        "category": rule["category"],
        "file": file,
        "line": int(line or 1),
        "title": rule["title"],
        "evidence": redact(evidence).strip()[:800],
        "impact": rule.get("impact", ""),
        "recommendation": rule.get("recommendation", ""),
        "confidence": float(rule.get("confidence", 0.8)),
        "source": source,
        "symbol": symbol,
    }
