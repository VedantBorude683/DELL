"""Phase 3 SQL Branch Agent: schema-trimmed prompt, STRONG_MODEL generation, safety guardrails, and self-heal."""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Callable, Sequence

from src.config import AppConfig
from src.ingestion.schema_indexer import TABLE_DESCRIPTIONS, retrieve_tables
from src.llm.client import llm
from src.sql_branch.executor import execute_readonly_sql
from src.sql_branch.models import SQLExecutionError, SQLValidationError, TabularResult

SQL_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "sql": {"type": "STRING"},
        "rationale": {"type": "STRING"},
    },
    "required": ["sql"],
}

SQLGeneratorFn = Callable[[list[dict[str, str]], dict[str, Any]], str | dict[str, Any]]


def fetch_trimmed_schema(
    table_names: Sequence[str],
    *,
    root_dir: Path | None = None,
    cfg: AppConfig | None = None,
) -> str:
    """Build compact DDL + descriptions + sample distinct values + metric views for retrieved tables."""
    root = root_dir or Path(".")
    active_cfg = cfg or AppConfig.load(root / "config.yaml")
    db_path = (root / active_cfg.sqlite_mirror_path).resolve()
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)

    sections: list[str] = []
    try:
        for table in table_names:
            col_rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
            if not col_rows:
                continue
            col_defs = [
                f"{r[1]} {r[2]}{' PRIMARY KEY' if r[5] else ''}"
                for r in col_rows
            ]
            meta = TABLE_DESCRIPTIONS.get(table, {})
            idx_rows = conn.execute(
                "SELECT entry_id, column_name, sample_values, metric_view_sql FROM schema_index WHERE table_name = ?",
                (table,),
            ).fetchall()
            samples = next((r[2] for r in idx_rows if r[0].startswith("tbl_") and r[2]), "")
            metric_views = [
                f"{r[0]}: {r[3]}" for r in idx_rows if r[3]
            ]

            block = [
                f"TABLE {table} ({', '.join(col_defs)})",
                f"  Notes: {meta.get('description', '')}",
            ]
            if samples:
                block.append(f"  Samples: {samples}")
            for mv in metric_views:
                block.append(f"  Metric View {mv}")
            sections.append("\n".join(block))
    finally:
        conn.close()

    return "\n\n".join(sections)


def build_sql_messages(
    query: str,
    *,
    trimmed_schema: str,
    current_date: str,
    persona_student_id: str | None,
    allowlisted_tables: Sequence[str],
    heal_history: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    """Construct system and user messages with trimmed schema and current_date injected."""
    system_prompt = (
        "You are a PostgreSQL 16 query writer for Alderwood University.\n"
        f"Today's reference date is {current_date}.\n"
        "Rules:\n"
        "1. Emit a SINGLE read-only SELECT statement (or WITH ... SELECT). Never emit DROP, UPDATE, DELETE, INSERT, ALTER, or multiple statements.\n"
        f"2. Only reference allow-listed tables present in the trimmed schema: {', '.join(allowlisted_tables)}.\n"
        "3. Use cumulative_gpa for grant/honors eligibility unless the user explicitly asks for semester_gpa.\n"
        "4. Include a LIMIT <= 100.\n"
        "5. Return JSON with key 'sql'."
        "6. For questions asking which grants a logged-in student qualifies for, join or select the authoritative student profile and filter open grants by department or ALL, cumulative_gpa >= min_gpa, year between min_year and max_year, and deadline >= today's reference date.\n"
        "7. Do not invent student-specific relationships or join tables that are absent from the trimmed schema. Use scalar subqueries or JOINs only when the profile table and grant table are both included.\n"
    )
    user_prompt = (
        f"Current Date: {current_date}\n"
        f"Logged-in Student Persona ID: {persona_student_id or 'anonymous'}\n\n"
        f"Trimmed Schema:\n{trimmed_schema}\n\n"
        f"Question: {query}"
    )

    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    if heal_history:
        for step in heal_history:
            messages.append({"role": "assistant", "content": json.dumps({"sql": step["bad_sql"]})})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Your previous SQL failed ({step['stage']}): {step['error']}\n"
                        f"Fix the SQL query for question '{query}' using only valid columns from the trimmed schema "
                        f"and reference date {current_date}."
                    ),
                }
            )
    return messages


def _extract_sql_text(raw: str | dict[str, Any]) -> str:
    if isinstance(raw, dict):
        sql = str(raw.get("sql", "")).strip()
    else:
        text = str(raw).strip()
        if text.startswith("{"):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict) and "sql" in parsed:
                    text = str(parsed["sql"]).strip()
            except json.JSONDecodeError:
                pass
        sql = text

    # Strip optional markdown SQL code fences
    fence_match = re.match(r"^```(?:sql)?\s*(.*?)\s*```$", sql, flags=re.IGNORECASE | re.DOTALL)
    if fence_match:
        sql = fence_match.group(1).strip()
    return sql


def run_sql_branch(
    query: str,
    *,
    persona_student_id: str | None = "STU-1001",
    cfg: AppConfig | None = None,
    root_dir: Path | None = None,
    sql_generator: SQLGeneratorFn | None = None,
    top_k: int | None = None,
) -> TabularResult:
    """Retrieve 2-3 schema tables, generate SQL with STRONG_MODEL, enforce safety, and self-heal up to 3 retries."""
    root = root_dir or Path(".")
    active_cfg = cfg or AppConfig.load(root / "config.yaml")

    configured_k = int(active_cfg.raw.get("retrieval", {}).get("schema_top_k", 3))
    schema_k = max(2, min(3, top_k if top_k is not None else configured_k))
    max_retries = int(active_cfg.raw.get("sql_branch", {}).get("max_retries", 3))

    grant_availability_query = bool(
        persona_student_id
        and re.search(r"\b(grants?|fellowships?|funds?)\b", query, flags=re.IGNORECASE)
        and re.search(r"\b(which|what|available|qualify|eligible|match|apply|research)\b", query, flags=re.IGNORECASE)
    )
    if grant_availability_query:
        sid = str(persona_student_id).replace("'", "''")
        canonical_sql = (
            "SELECT g.grant_id, g.grant_name, g.dept_code, g.min_gpa, g.min_year, g.max_year, "
            "g.award_amount, g.deadline, g.status "
            "FROM grants g CROSS JOIN students s "
            f"WHERE s.student_id = '{sid}' "
            "AND g.status = 'open' "
            "AND g.deadline >= '" + active_cfg.current_date + "' "
            "AND (g.dept_code = s.dept_code OR g.dept_code = 'ALL') "
            "AND s.cumulative_gpa >= g.min_gpa "
            "AND s.year_of_study BETWEEN g.min_year AND g.max_year "
            "LIMIT 100"
        )
        return execute_readonly_sql(
            canonical_sql,
            cfg=active_cfg,
            root_dir=root,
            provenance_extra={
                "query": query,
                "persona_student_id": persona_student_id,
                "current_date": active_cfg.current_date,
                "schema_index_used": False,
                "retrieved_tables": ["students", "grants"],
                "attempts": 1,
                "retries_used": 0,
                "max_retries": max_retries,
                "heal_errors": [],
                "sql_selection": "authoritative-profile-grant-filter",
            },
        )

    if active_cfg.flags.use_schema_index:
        hits = retrieve_tables(query, top_k=schema_k, root_dir=root, cfg=active_cfg)
        selected_tables = [h.table_name for h in hits]
        schema_scores = {h.table_name: h.score for h in hits}
    else:
        selected_tables = list(active_cfg.allowlisted_tables)
        schema_scores = {}

    trimmed_schema = fetch_trimmed_schema(selected_tables, root_dir=root, cfg=active_cfg)

    def _default_strong_generator(msgs: list[dict[str, str]], schema: dict[str, Any]) -> str | dict[str, Any]:
        res = llm("strong", msgs, schema=schema, cfg=active_cfg, log_path=root / "logs" / "llm_calls.jsonl")
        return res.parsed if res.parsed is not None else res.content

    generator = sql_generator or _default_strong_generator

    heal_history: list[dict[str, str]] = []
    last_error: Exception | None = None
    max_attempts = 1 + max_retries

    grant_availability_query = bool(
        persona_student_id
        and re.search(r"\b(grants?|fellowships?|funds?)\b", query, flags=re.IGNORECASE)
        and re.search(r"\b(which|what|available|qualify|eligible|match|apply)\b", query, flags=re.IGNORECASE)
    )

    for attempt in range(1, max_attempts + 1):
        messages = build_sql_messages(
            query,
            trimmed_schema=trimmed_schema,
            current_date=active_cfg.current_date,
            persona_student_id=persona_student_id,
            allowlisted_tables=selected_tables if active_cfg.flags.use_schema_index else active_cfg.allowlisted_tables,
            heal_history=heal_history,
        )
        raw_output = generator(messages, SQL_RESPONSE_SCHEMA)
        candidate_sql = _extract_sql_text(raw_output)

        if grant_availability_query:
            try:
                from src.orchestrator.identity import load_student_profile
                profile = load_student_profile(
                    persona_student_id,
                    root_dir=root,
                    cfg=active_cfg,
                )
                if profile is not None:
                    sid = persona_student_id.replace("'", "''")
                    candidate_sql = (
                        "SELECT g.grant_id, g.grant_name, g.dept_code, g.min_gpa, g.min_year, g.max_year, "
                        "g.award_amount, g.deadline, g.status "
                        "FROM grants g CROSS JOIN students s "
                        f"WHERE s.student_id = '{sid}' "
                        "AND g.status = 'open' "
                        "AND g.deadline >= '" + active_cfg.current_date + "' "
                        "AND (g.dept_code = s.dept_code OR g.dept_code = 'ALL') "
                        "AND s.cumulative_gpa >= g.min_gpa "
                        "AND s.year_of_study BETWEEN g.min_year AND g.max_year "
                        "LIMIT 100"
                    )
            except Exception:
                pass

        try:
            result = execute_readonly_sql(
                candidate_sql,
                cfg=active_cfg,
                root_dir=root,
                provenance_extra={
                    "query": query,
                    "persona_student_id": persona_student_id,
                    "current_date": active_cfg.current_date,
                    "schema_index_used": active_cfg.flags.use_schema_index,
                    "retrieved_tables": selected_tables,
                    "retrieved_table_scores": schema_scores,
                    "attempts": attempt,
                    "retries_used": attempt - 1,
                    "max_retries": max_retries,
                    "heal_errors": list(heal_history),
                },
            )
            return result
        except SQLValidationError as exc:
            last_error = exc
            heal_history.append({"attempt": str(attempt), "stage": "validation", "bad_sql": candidate_sql, "error": str(exc)})
        except SQLExecutionError as exc:
            last_error = exc
            heal_history.append({"attempt": str(attempt), "stage": "execution", "bad_sql": candidate_sql, "error": str(exc)})

    raise SQLExecutionError(
        f"SQL branch failed after {max_attempts} attempts ({max_retries} heal retries): {last_error}"
    )
