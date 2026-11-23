"""Read-only JSON bridge for Express API to inspect and test Phase 3 SQL Branch."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import AppConfig
from src.sql_branch.agent import fetch_trimmed_schema, run_sql_branch
from src.sql_branch.executor import execute_readonly_sql
from src.sql_branch.gold_reference_queries import GOLD_SQL_STATEMENTS, evaluate_sql_branch_gold
from src.sql_branch.models import SQLExecutionError, SQLValidationError


def get_phase3_overview() -> dict:
    cfg = AppConfig.load(ROOT / "config.yaml")
    report_path = ROOT / "data" / "phase3_report.json"
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
    else:
        report = evaluate_sql_branch_gold(ROOT, cfg=cfg)

    # Also build a live TabularResult preview with self-heal demo using schema index
    demo_query = "Which open research grants in the database match a 3rd-year CS student with a 3.74 GPA?"
    attempts = {"n": 0}

    def _demo_self_heal_generator(_msgs, _schema):
        attempts["n"] += 1
        if attempts["n"] == 1:
            return "SELECT grant_id, bad_col FROM grants WHERE status = 'open'"
        return GOLD_SQL_STATEMENTS["G-008"]

    demo_result = run_sql_branch(
        demo_query,
        persona_student_id="STU-1001",
        cfg=cfg,
        root_dir=ROOT,
        sql_generator=_demo_self_heal_generator,
    )
    trimmed_preview = fetch_trimmed_schema(
        demo_result.provenance["retrieved_tables"],
        root_dir=ROOT,
        cfg=cfg,
    )

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    live_llm_available = bool(api_key and api_key != "MY_GEMINI_API_KEY")

    return {
        "report": report,
        "demo_self_heal": demo_result.to_dict(),
        "trimmed_schema_preview": trimmed_preview,
        "live_llm_available": live_llm_available,
        "allowlisted_tables": list(cfg.allowlisted_tables),
        "max_rows": int(cfg.raw.get("database", {}).get("max_rows", 100)),
        "statement_timeout_ms": int(cfg.raw.get("database", {}).get("statement_timeout_ms", 5000)),
        "lock_timeout_ms": int(cfg.raw.get("database", {}).get("lock_timeout_ms", 2000)),
    }


def validate_and_execute_sql(sql: str) -> dict:
    cfg = AppConfig.load(ROOT / "config.yaml")
    try:
        res = execute_readonly_sql(sql, cfg=cfg, root_dir=ROOT)
        return {"ok": True, "blocked": False, "result": res.to_dict()}
    except SQLValidationError as exc:
        return {"ok": False, "blocked": True, "stage": "validation", "error": str(exc)}
    except SQLExecutionError as exc:
        return {"ok": False, "blocked": False, "stage": "execution", "error": str(exc)}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "overview"
    if cmd == "overview":
        print(json.dumps(get_phase3_overview()))
    elif cmd == "execute":
        raw_sql = sys.argv[2] if len(sys.argv) > 2 else ""
        print(json.dumps(validate_and_execute_sql(raw_sql)))
