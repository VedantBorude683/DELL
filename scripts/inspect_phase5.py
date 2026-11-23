"""Read-only JSON bridge for Express API to inspect and run Phase 5 Router + Planner."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import AppConfig
from src.orchestrator.graph import build_orchestrator_graph, run_orchestrator_turn


def get_phase5_overview() -> dict[str, Any]:
    cfg = AppConfig.load(ROOT / "config.yaml")
    report_path = ROOT / "data" / "phase5_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}

    conn = sqlite3.connect(f"file:{ROOT / cfg.sqlite_mirror_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    personas = [
        dict(r)
        for r in conn.execute(
            "SELECT student_id, full_name, dept_code, year_of_study, cumulative_gpa, semester_gpa, enrollment_status "
            "FROM students ORDER BY student_id"
        ).fetchall()
    ]
    conn.close()

    return {
        "report": report,
        "personas": personas,
        "router_threshold": float(cfg.raw.get("router", {}).get("exemplar_similarity_threshold", 0.78)),
        "sequential_max_grant_ids": int(cfg.raw.get("retrieval", {}).get("sequential_max_grant_ids", 5)),
    }


def route_and_execute(payload_json: str) -> dict[str, Any]:
    payload = json.loads(payload_json) if payload_json else {}
    query = str(payload.get("query", "")).strip()
    persona_id = str(payload.get("persona_student_id", "STU-1001")).strip() or "STU-1001"
    memory = payload.get("memory") or None

    cfg = AppConfig.load(ROOT / "config.yaml")
    graph = build_orchestrator_graph(cfg=cfg, root_dir=ROOT)
    state, updated_memory = run_orchestrator_turn(
        query,
        persona_student_id=persona_id,
        memory=memory,
        graph=graph,
    )
    return {
        "query": query,
        "persona_student_id": persona_id,
        "identity_check": state.get("identity_check"),
        "plan": state.get("plan"),
        "sql_result": state.get("sql_result"),
        "doc_result": state.get("doc_result"),
        "status_notice": state.get("status_notice"),
        "trace": state.get("trace"),
        "memory": updated_memory,
    }


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "overview"
    if cmd == "overview":
        print(json.dumps(get_phase5_overview()))
    elif cmd == "route":
        arg = sys.argv[2] if len(sys.argv) > 2 else "{}"
        print(json.dumps(route_and_execute(arg)))
