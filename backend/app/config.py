from __future__ import annotations

import hashlib
import os
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]


def read_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a mapping")
    return data


def load_rules(rules_dir: Path) -> list[dict]:
    rules: list[dict] = []
    for path in sorted(rules_dir.glob("*.yaml")):
        document = read_yaml(path)
        for rule in document.get("rules", []):
            rule.setdefault("stage", "static")
            rule.setdefault("confidence", 0.8)
            rules.append(rule)
    return rules


class Settings:
    def __init__(self) -> None:
        load_dotenv(ROOT / ".env")
        self.root = ROOT
        self.raw = read_yaml(ROOT / "config" / "settings.yaml")
        self.policy = read_yaml(ROOT / "config" / "policy.yaml")
        self.pipeline = read_yaml(ROOT / "config" / "pipeline.yaml")
        self.rules = load_rules(ROOT / "rules")
        product = self.raw.get("product", {})
        self.product = {
            "name": product.get("name", "Perceptor.AI"),
            "version": str(product.get("version", "1.0.0")),
            "tagline": product.get("tagline", ""),
            "short": product.get("short", ""),
        }
        server = self.raw.get("server", {})
        self.host = str(server.get("host", "127.0.0.1"))
        self.port = int(server.get("port", 8787))
        self.cors_origins = list(self.raw.get("cors_origins", ["http://localhost:3000"]))
        self.database = ROOT / str(self.raw.get("database", "data/perceptor.db"))
        self.workspaces = ROOT / str(self.raw.get("workspaces", "data/workspaces"))
        self.logs = ROOT / str(self.raw.get("logs", "logs/perceptor.log"))
        self.rules_dir = ROOT / "rules"
        llm = self.raw.get("llm", {})
        self.llm_base_url = os.getenv("OPENROUTER_BASE_URL", llm.get("base_url", "https://openrouter.ai/api/v1")).rstrip("/")
        self.llm_model = os.getenv("PERCEPTOR_MODEL", llm.get("model", "openai/gpt-4o-mini"))
        self.llm_timeout = float(llm.get("timeout_seconds", 45))
        self.llm_retries = max(0, int(llm.get("retries", 1)))
        self.llm_total_budget = float(llm.get("total_budget_seconds", 120))
        self.llm_workers = max(1, int(llm.get("max_workers", 3)))
        self.llm_context_chars = int(llm.get("max_context_chars", 14000))
        self.llm_excerpt_chars = int(llm.get("file_excerpt_chars", 4000))
        self.llm_max_files = int(llm.get("max_review_files", 120))
        self.llm_temperature = float(llm.get("temperature", 0.1))
        self.api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        # Optional shared secret for the API. Unset keeps local development frictionless.
        self.api_token = os.getenv("PERCEPTOR_API_TOKEN", "").strip()
        analysis = self.raw.get("analysis", {})
        self.impact_depth = int(analysis.get("impact_depth", 3))
        self.complexity_threshold = int(analysis.get("complexity_threshold", 12))
        self.function_length_threshold = int(analysis.get("function_length_threshold", 80))
        self.max_files = int(analysis.get("max_files", 5000))
        self.max_file_bytes = int(analysis.get("max_file_bytes", 300000))
        self.minified_avg_line_chars = int(analysis.get("minified_avg_line_chars", 300))
        self.minified_min_bytes = int(analysis.get("minified_min_bytes", 4000))
        self.minified_name_markers = [str(item).lower() for item in analysis.get("minified_name_markers", [".min."])]
        self.read_workers = max(1, int(analysis.get("read_workers", 16)))
        self.read_chunk = max(1, int(analysis.get("read_chunk", 256)))
        self.max_notebook_bytes = int(analysis.get("max_notebook_bytes", self.max_file_bytes))
        self.notebook_extensions = {str(item).lower() for item in analysis.get("notebook_extensions", [])}
        self.max_graph_nodes = int(analysis.get("max_graph_nodes", 280))
        self.suppress_markers = [str(item).lower() for item in analysis.get("suppress_markers", [])]
        self.endpoint_file_patterns = [str(item).lower() for item in analysis.get("endpoint_file_patterns", ["route"])]
        self.review_languages = {str(item) for item in analysis.get("review_languages", ["python", "javascript"])}
        self.review_code_languages = {str(item) for item in analysis.get("review_code_languages", ["python", "javascript", "sql"])}
        self.review_skip_names = {str(item) for item in analysis.get("review_skip_names", [])}
        sandbox = self.raw.get("sandbox", {})
        # Copying arbitrary server directories is only safe when the API is bound to loopback.
        self.allow_local_paths = bool(server.get("allow_local_paths", self.host in {"127.0.0.1", "localhost", "::1"}))
        retention = self.raw.get("retention", {})
        self.retain_runs = max(1, int(retention.get("keep_runs", 20)))
        self.retain_cache_entries = max(0, int(retention.get("keep_cache_entries", 200)))
        self.max_concurrent_runs = max(1, int(sandbox.get("max_concurrent_runs", 2)))
        self.max_path_length = int(sandbox.get("max_path_length", 250))
        self.clone_depth = max(2, int(sandbox.get("clone_depth", 40)))
        self.sandbox_timeout = int(sandbox.get("timeout_seconds", 90))
        self.upload_max_bytes = int(sandbox.get("upload_max_mb", 30)) * 1024 * 1024
        self.extensions = {str(key): str(value) for key, value in self.raw.get("languages", {}).items()}
        self.skip_dirs = set(self.raw.get("skip_dirs", []))
        self.regex_languages = set(self.raw.get("regex_languages", []))
        self.prompt_path = ROOT / "config" / "prompts" / "review.txt"
        self.fix_prompt_path = ROOT / "config" / "prompts" / "fix.txt"
        self.workspaces.mkdir(parents=True, exist_ok=True)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.logs.parent.mkdir(parents=True, exist_ok=True)

    def config_hash(self) -> str:
        digest = hashlib.sha256()
        for folder in (self.root / "config", self.root / "rules", self.root / "backend" / "app"):
            for path in sorted(folder.rglob("*")):
                if path.is_file():
                    digest.update(path.relative_to(self.root).as_posix().encode())
                    digest.update(path.read_bytes())
        digest.update(self.llm_model.encode())
        digest.update(b"1" if self.api_key else b"0")
        return digest.hexdigest()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
