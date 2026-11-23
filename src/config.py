"""Configuration loader for config.yaml without hidden global state."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _load_yaml_or_fallback(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text) or {}
    except ImportError:
        return _minimal_yaml_parse(text)


def _parse_scalar(raw: str) -> Any:
    val = raw.strip()
    if not val:
        return ""
    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
        return val[1:-1]
    if val.lower() == "true":
        return True
    if val.lower() == "false":
        return False
    try:
        return int(val)
    except ValueError:
        pass
    try:
        return float(val)
    except ValueError:
        pass
    return val


def _minimal_yaml_parse(text: str) -> dict[str, Any]:
    """Deterministic subset YAML parser for standard dict/list config.yaml without PyYAML."""
    root: dict[str, Any] = {}
    stack: list[tuple[int, Any]] = [(-1, root)]
    lines = text.splitlines()
    for idx, raw_line in enumerate(lines):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if stripped.startswith("- "):
            item_val = _parse_scalar(stripped[2:])
            if isinstance(parent, list):
                parent.append(item_val)
            continue
        if ":" in stripped:
            key, rest = stripped.split(":", 1)
            key = key.strip()
            rest = rest.strip()
            if rest:
                if isinstance(parent, dict):
                    parent[key] = _parse_scalar(rest)
            else:
                # Look ahead to determine if child is list or dict
                next_is_list = False
                for look_line in lines[idx + 1 :]:
                    s = look_line.strip()
                    if not s or s.startswith("#"):
                        continue
                    next_is_list = s.startswith("- ")
                    break
                container: Any = [] if next_is_list else {}
                if isinstance(parent, dict):
                    parent[key] = container
                    stack.append((indent, container))
    return root


@dataclass(frozen=True)
class FeatureFlags:
    use_hyde: bool = True
    use_reranker: bool = True
    use_crag_grader: bool = True
    use_llm_claim_check: bool = True
    use_schema_index: bool = True


@dataclass(frozen=True)
class AppConfig:
    raw: dict[str, Any] = field(default_factory=dict)
    flags: FeatureFlags = field(default_factory=FeatureFlags)
    current_date: str = "2026-11-23"
    allowlisted_tables: tuple[str, ...] = ()
    sqlite_mirror_path: str = "data/university.db"
    pdf_dir: str = "data/pdfs"
    gold_path: str = "eval/gold.jsonl"

    @classmethod
    def load(cls, config_path: str | Path = "config.yaml") -> "AppConfig":
        path = Path(config_path)
        data = _load_yaml_or_fallback(path)
        ff = data.get("feature_flags", {})
        db = data.get("database", {})
        app = data.get("app", {})
        ing = data.get("ingestion", {})
        ev = data.get("eval", {})
        return cls(
            raw=data,
            flags=FeatureFlags(
                use_hyde=bool(ff.get("use_hyde", True)),
                use_reranker=bool(ff.get("use_reranker", True)),
                use_crag_grader=bool(ff.get("use_crag_grader", True)),
                use_llm_claim_check=bool(ff.get("use_llm_claim_check", True)),
                use_schema_index=bool(ff.get("use_schema_index", True)),
            ),
            current_date=str(app.get("current_date_override", "2026-11-23")),
            allowlisted_tables=tuple(db.get("allowlisted_tables", [])),
            sqlite_mirror_path=str(db.get("sqlite_mirror_path", "data/university.db")),
            pdf_dir=str(ing.get("pdf_dir", "data/pdfs")),
            gold_path=str(ev.get("gold_path", "eval/gold.jsonl")),
        )

    def to_json(self) -> str:
        return json.dumps(self.raw, indent=2)


def get_model_name(tier: str, cfg: AppConfig | None = None) -> str:
    models = (cfg.raw.get("models", {}) if cfg else {})
    if tier == "fast":
        env_key = str(models.get("fast_model_env", "FAST_MODEL"))
        return os.environ.get(env_key, str(models.get("default_fast_model", "gemini-2.5-flash")))
    if tier == "strong":
        env_key = str(models.get("strong_model_env", "STRONG_MODEL"))
        return os.environ.get(env_key, str(models.get("default_strong_model", "gemini-2.5-pro")))
    raise ValueError(f"Unknown model_tier: {tier!r}. Expected 'fast' or 'strong'.")
