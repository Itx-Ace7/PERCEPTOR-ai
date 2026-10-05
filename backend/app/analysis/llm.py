from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

import httpx

from app.analysis.types import AnalysisState, finding_dict, redact
from app.config import Settings


class LLMProvider:
    def complete(self, system: str, user: str) -> str:
        raise NotImplementedError


class OpenRouterProvider(LLMProvider):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _post(self, system: str, user: str) -> dict:
        """One request with a hard wall-clock limit.

        httpx's timeout bounds each wait for data, not the whole call, so a response that
        trickles in can run far past it. Reading in chunks lets the total be enforced.
        """
        limit = self.settings.llm_timeout
        deadline = time.monotonic() + limit
        body = {
            "model": self.settings.llm_model,
            "temperature": self.settings.llm_temperature,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        headers = {"Authorization": f"Bearer {self.settings.api_key}", "Content-Type": "application/json"}
        timeout = httpx.Timeout(limit, connect=min(10.0, limit))
        with httpx.stream("POST", f"{self.settings.llm_base_url}/chat/completions", headers=headers, json=body, timeout=timeout) as response:
            chunks = []
            for chunk in response.iter_bytes():
                chunks.append(chunk)
                if time.monotonic() > deadline:
                    raise httpx.ReadTimeout(f"model call exceeded {limit:.0f}s")
            response.read() if not chunks else None
            if response.status_code >= 400:
                raise httpx.HTTPStatusError(f"model returned {response.status_code}", request=response.request, response=response)
        return json.loads(b"".join(chunks))

    def complete(self, system: str, user: str) -> str:
        last: Exception | None = None
        for _attempt in range(1 + self.settings.llm_retries):
            try:
                payload = self._post(system, user)
                break
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last = exc
        else:
            raise last  # type: ignore[misc]
        message = payload["choices"][0]["message"]
        content = message.get("content")
        if isinstance(content, list):
            pieces = []
            for part in content:
                if isinstance(part, dict):
                    pieces.append(str(part.get("text") or part.get("content") or ""))
                else:
                    pieces.append(str(part))
            content = "\n".join(pieces)
        if not isinstance(content, str) or not content.strip():
            content = message.get("reasoning_content") or message.get("reasoning") or ""
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("empty model response")
        return content


def provider_for(settings: Settings) -> LLMProvider:
    return OpenRouterProvider(settings)


def _prompt(settings: Settings, path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8")
    marker = "OUTPUT:"
    if "SYSTEM:" in text and "TASK:" in text:
        system = text.split("TASK:", 1)[0].replace("SYSTEM:", "", 1).strip()
        user_prefix = "TASK:" + text.split("TASK:", 1)[1]
        return system, user_prefix
    return text, ""


def _review_paths(state: AnalysisState) -> list[str]:
    listed = [path for path in state.diff.get("review_files", []) if path in state.head]
    if listed:
        return listed
    return [item["path"] for item in state.diff.get("changed_files", []) if item["path"] in state.head]


def _focus_lines(state: AnalysisState, path: str) -> list[int]:
    lines = []
    for finding in state.static_findings:
        if finding.get("file") == path:
            try:
                lines.append(int(finding.get("line") or 1))
            except (TypeError, ValueError):
                continue
    for symbol in state.diff.get("changed_symbols", []):
        if symbol.get("file") == path:
            lines.append(int(symbol.get("start") or 1))
    return lines


def _excerpt(source: str, focus: list[int], limit: int) -> str:
    rows = source.splitlines()
    if not rows:
        return ""
    numbered = [f"{index}|{line}" for index, line in enumerate(rows, start=1)]
    whole = "\n".join(numbered)
    if len(whole) <= limit:
        return whole
    chosen: set[int] = set()
    anchors = focus or [1]
    for line in anchors:
        for number in range(max(1, line - 12), min(len(rows), line + 12) + 1):
            chosen.add(number)
    if not focus:
        chosen.update(range(1, min(len(rows), 90) + 1))
    pieces = []
    size = 0
    for number in sorted(chosen):
        piece = numbered[number - 1]
        if pieces and size + len(piece) > limit:
            break
        pieces.append(piece)
        size += len(piece) + 1
    return "\n".join(pieces)


def build_batches(state: AnalysisState, settings: Settings) -> list[str]:
    paths = _review_paths(state)
    scope = state.diff.get("scope") or ("diff" if state.diff.get("changed_files") else "snapshot")
    header = [f"Scope: {'full snapshot' if scope == 'snapshot' else 'change review'}"]
    if scope == "snapshot":
        header.append(f"Files in this upload selected for review: {len(paths)}")
    else:
        changed = state.diff.get("changed_files", [])
        header.append("Changed files: " + ", ".join(item["path"] for item in changed) if changed else "Changed files: none")
    chain = (state.impact.get("failure_chains") or [None])[0]
    if chain:
        header.append("Impact chain: " + " -> ".join(node["label"] for node in chain["nodes"]))
    static_lines = []
    for finding in state.static_findings[:40]:
        static_lines.append(f"- {finding['severity']} {finding['file']}:{finding['line']} {finding['title']}")
    if static_lines:
        header.append("Static findings already recorded:\n" + "\n".join(static_lines))
    preamble = "\n".join(header)
    batches: list[str] = []
    current = [preamble]
    size = len(preamble)
    budget = settings.llm_context_chars
    for path in paths:
        body = _excerpt(state.head.get(path, ""), _focus_lines(state, path), settings.llm_excerpt_chars)
        block = f"\nFILE {path}\n{body}"
        if current and size + len(block) > budget and len(current) > 1:
            batches.append(redact("\n".join(current))[:budget])
            current = [preamble]
            size = len(preamble)
        current.append(block)
        size += len(block)
    if len(current) > 1:
        batches.append(redact("\n".join(current))[:budget])
    return batches


def build_context(state: AnalysisState, settings: Settings) -> str:
    batches = build_batches(state, settings)
    return batches[0] if batches else ""


def _parse_model_json(raw: str) -> dict:
    if not isinstance(raw, str):
        return {"findings": []}
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return {"findings": []}
    try:
        document = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {"findings": []}
    if isinstance(document, list):
        return {"findings": document}
    if not isinstance(document, dict):
        return {"findings": []}
    if "findings" not in document and isinstance(document.get("issues"), list):
        document["findings"] = document["issues"]
    return document


def _resolve_path(path: str, allowed: set[str]) -> str | None:
    cleaned = path.replace("\\", "/").lstrip("./")
    if cleaned in allowed:
        return cleaned
    matches = [item for item in allowed if item == cleaned or item.endswith("/" + cleaned)]
    if len(matches) == 1:
        return matches[0]
    return None


def _findings_from_document(document: dict, allowed: set[str]) -> list[dict]:
    findings = []
    seen: set[tuple[str, int, str]] = set()
    for item in document.get("findings") or []:
        if not isinstance(item, dict):
            continue
        path = _resolve_path(str(item.get("file") or ""), allowed)
        if path is None:
            continue
        try:
            line = int(item.get("line") or 1)
        except (TypeError, ValueError):
            line = 1
        title = str(item.get("title") or "Model review finding")
        key = (path, line, title.lower())
        if key in seen:
            continue
        seen.add(key)
        try:
            confidence = float(item.get("confidence") or 0.5)
        except (TypeError, ValueError):
            confidence = 0.5
        rule = {
            "id": "AI-REVIEW",
            "severity": str(item.get("severity") or "MEDIUM").upper(),
            "category": str(item.get("category") or "QUALITY").upper(),
            "title": title,
            "impact": str(item.get("impact") or ""),
            "recommendation": str(item.get("recommendation") or ""),
            "confidence": min(max(confidence, 0), 1),
        }
        if rule["severity"] not in {"CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"}:
            rule["severity"] = "MEDIUM"
        findings.append(
            finding_dict(
                rule,
                path,
                line,
                str(item.get("evidence") or ""),
                symbol=item.get("symbol"),
                source="llm",
            )
        )
    return findings


Progress = Callable[[int, int], None]


def review(state: AnalysisState, settings: Settings, progress: Progress | None = None) -> list[dict]:
    system, instructions = _prompt(settings, settings.prompt_path)
    batches = build_batches(state, settings)
    if not batches:
        return []
    provider = provider_for(settings)
    allowed = set(state.head)
    prompt = instructions + "\n\nEVIDENCE:\n"

    reasons: list[str] = []

    def _one(batch: str) -> tuple[list[dict], bool]:
        try:
            raw = provider.complete(system, prompt + batch)
            return _findings_from_document(_parse_model_json(raw), allowed), False
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", "")
            reasons.append(f"{exc.__class__.__name__}{f' {status}' if status else ''}: {str(exc)[:120]}")
            return [], True

    workers = min(settings.llm_workers, len(batches))
    pool = ThreadPoolExecutor(max_workers=workers)
    futures = [pool.submit(_one, batch) for batch in batches]
    deadline = time.monotonic() + settings.llm_total_budget
    findings: list[dict] = []
    failures = 0
    done = 0
    for future in futures:
        try:
            batch_findings, failed = future.result(timeout=max(0.0, deadline - time.monotonic()))
        except FutureTimeout:
            failures += 1
            continue
        findings.extend(batch_findings)
        failures += 1 if failed else 0
        done += 1
        if progress:
            progress(done, len(batches))
    # Do not wait for stragglers: a slow provider must not hold the release decision.
    pool.shutdown(wait=False, cancel_futures=True)
    if failures and failures == len(batches):
        raise RuntimeError(f"model request failed ({reasons[0] if reasons else 'timed out'})")
    note = f"{len(findings)} model findings | {len(_review_paths(state))} files | {len(batches) - failures}/{len(batches)} passes"
    if failures:
        note += f" | {failures} timed out or failed"
    state.ai_note = note
    return findings


def stage_ai(state: AnalysisState, settings: Settings, progress: Progress | None = None) -> dict:
    if not settings.api_key:
        state.ai_findings = []
        state.ai_note = "Awaiting OPENROUTER_API_KEY. Deterministic findings still stand."
        return {"preview": ["Awaiting API key"], "ai_findings": [], "ai_note": state.ai_note}
    try:
        state.ai_findings = review(state, settings, progress)
        if not state.ai_note:
            state.ai_note = f"{len(state.ai_findings)} model findings"
    except Exception as exc:  # the rest of the release decision must not depend on the provider
        state.ai_findings = []
        state.ai_note = f"Model skipped: {exc}" if isinstance(exc, RuntimeError) else f"Model skipped: {exc.__class__.__name__}"
        return {"preview": [state.ai_note], "ai_findings": [], "ai_note": state.ai_note, "degraded": True}
    return {"preview": [state.ai_note], "ai_findings": state.ai_findings, "ai_note": state.ai_note}


def restore_ai(state: AnalysisState, payload: dict) -> None:
    state.ai_findings = list(payload.get("ai_findings", []))
    state.ai_note = payload.get("ai_note", "")
