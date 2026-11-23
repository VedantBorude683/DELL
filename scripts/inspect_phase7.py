"""Read-only JSON bridge for Express API to run Phase 7 Assistant, MCP Inspector, and eval.run."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.run import run_gold_evaluation
from mcp_server.inspector_client import run_mcp_stdio_session
from src.assistant import run_assistant_query
from src.config import AppConfig
from src.orchestrator.identity import list_student_personas


def get_phase7_overview() -> dict[str, Any]:
    cfg = AppConfig.load(ROOT / "config.yaml")
    eval_path = ROOT / cfg.raw.get("eval", {}).get("report_output_path", "eval/latest_report.json")
    eval_report = json.loads(eval_path.read_text(encoding="utf-8")) if eval_path.exists() else None
    if eval_report is not None:
        eval_summary = {k: v for k, v in eval_report.items() if k != "records"}
        eval_records = eval_report.get("records") or []
    else:
        eval_summary = None
        eval_records = []

    mcp_probe = run_mcp_stdio_session(
        tool_calls=[
            {"name": "list_allowlisted_tables", "arguments": {}},
        ],
        root_dir=ROOT,
    )
    return {
        "eval_summary": eval_summary,
        "eval_records": eval_records,
        "personas": list_student_personas(root_dir=ROOT),
        "feature_flags": {
            "use_hyde": cfg.flags.use_hyde,
            "use_reranker": cfg.flags.use_reranker,
            "use_crag_grader": cfg.flags.use_crag_grader,
            "use_llm_claim_check": cfg.flags.use_llm_claim_check,
            "use_schema_index": cfg.flags.use_schema_index,
        },
        "current_date": cfg.current_date,
        "mcp_server_info": mcp_probe.get("server_info"),
        "mcp_protocol_version": mcp_probe.get("protocol_version"),
        "mcp_tools": mcp_probe.get("tools") or [],
    }


def run_chat_turn(payload_json: str) -> dict[str, Any]:
    payload = json.loads(payload_json) if payload_json else {}
    query = str(payload.get("query") or "").strip()
    persona_id = str(payload.get("persona_student_id") or "STU-1001").strip() or "STU-1001"
    memory = payload.get("memory") or None
    ff_override = payload.get("feature_flags") or None
    return run_assistant_query(
        query,
        persona_student_id=persona_id,
        memory=memory,
        feature_flags_override=ff_override,
        root_dir=ROOT,
    )


def run_mcp_inspect(payload_json: str) -> dict[str, Any]:
    payload = json.loads(payload_json) if payload_json else {}
    tool_name = str(payload.get("tool") or "safe_sql_query")
    arguments = payload.get("arguments") or {}
    return run_mcp_stdio_session(
        tool_calls=[{"name": tool_name, "arguments": arguments}],
        root_dir=ROOT,
    )


def run_eval_now() -> dict[str, Any]:
    report = run_gold_evaluation(root_dir=ROOT)
    return {
        "eval_summary": {k: v for k, v in report.items() if k != "records"},
        "eval_records": report.get("records") or [],
    }


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "overview"
    if cmd == "overview":
        print(json.dumps(get_phase7_overview()))
    elif cmd == "chat":
        arg = sys.argv[2] if len(sys.argv) > 2 else "{}"
        print(json.dumps(run_chat_turn(arg)))
    elif cmd == "mcp":
        arg = sys.argv[2] if len(sys.argv) > 2 else "{}"
        print(json.dumps(run_mcp_inspect(arg)))
    elif cmd == "eval":
        print(json.dumps(run_eval_now()))
