"""Read-only SQL executor with timeouts, row cap, and TabularResult output."""
from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from src.config import AppConfig
from src.sql_branch.models import SQLExecutionError, TabularResult, ValidatedSQL
from src.sql_branch.validator import validate_select_sql


def _normalize_sqlite_booleans(sql: str) -> str:
    """Translate PostgreSQL boolean/ILIKE/CURRENT_DATE tokens cleanly when targeting SQLite mirror."""
    import re

    out = re.sub(r"\bTRUE\b", "1", sql)
    out = re.sub(r"\bFALSE\b", "0", out)
    out = re.sub(r"\bILIKE\b", "LIKE", out, flags=re.IGNORECASE)
    out = re.sub(r"\bCURRENT_DATE\b", "'2026-11-23'", out)
    return out


def execute_readonly_sql(
    sql: str,
    *,
    cfg: AppConfig | None = None,
    root_dir: Path | None = None,
    provenance_extra: dict[str, Any] | None = None,
) -> TabularResult:
    """Validate SQL and execute only against the configured read-only PostgreSQL role."""
    root = root_dir or Path(".")
    active_cfg = cfg or AppConfig.load(root / "config.yaml")
    db_cfg = active_cfg.raw.get("database", {})
    max_rows = int(db_cfg.get("max_rows", 100))
    statement_timeout_ms = int(db_cfg.get("statement_timeout_ms", 5000))
    lock_timeout_ms = int(db_cfg.get("lock_timeout_ms", 2000))

    validated: ValidatedSQL = validate_select_sql(
        sql,
        active_cfg.allowlisted_tables,
        max_rows=max_rows,
    )

    ro_pg_url = os.environ.get("READONLY_DATABASE_URL", "").strip()
    started = time.perf_counter()

    if not ro_pg_url:
        raise SQLExecutionError("READONLY_DATABASE_URL is required; SQLite fallback is disabled")
    try:
        from sqlalchemy import create_engine, text  # type: ignore

        engine = create_engine(ro_pg_url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("BEGIN READ ONLY"))
            conn.execute(text(f"SET LOCAL statement_timeout = {statement_timeout_ms}"))
            conn.execute(text(f"SET LOCAL lock_timeout = {lock_timeout_ms}"))
            result = conn.execute(text(validated.sql))
            columns = list(result.keys())
            raw_rows = result.fetchmany(max_rows)
            rows = [dict(zip(columns, r)) for r in raw_rows]
            conn.rollback()
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        return TabularResult(
            columns=columns,
            rows=rows,
            sql=validated.sql,
            tables=list(validated.tables),
            provenance={
                "engine": "postgresql_readonly",
                "validator_backend": validated.validator_backend,
                "limit_applied": validated.limit_applied,
                "statement_timeout_ms": statement_timeout_ms,
                "lock_timeout_ms": lock_timeout_ms,
                "latency_ms": latency_ms,
                **(provenance_extra or {}),
            },
        )
    except Exception as exc:
        raise SQLExecutionError(f"PostgreSQL execution error: {exc}") from exc
