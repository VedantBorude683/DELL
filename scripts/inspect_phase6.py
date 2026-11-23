"""Read-only JSON bridge for Express API to run and inspect Phase 6 Synthesis + Verification."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import AppConfig
from src.orchestrator.graph import build_orchestrator_graph, run_orchestrator_turn
from src.synthesis import synthesize_answer


def get_phase6_overview() -> dict[str, Any]:
    cfg = AppConfig.load(ROOT / "config.yaml")
    report_path = ROOT / "data" / "phase6_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    return {
        "report": report,
        "use_llm_claim_check": cfg.flags.use_llm_claim_check,
        "max_regeneration_attempts": int(cfg.raw.get("synthesis", {}).get("max_regeneration_attempts", 1)),
        "current_date": cfg.current_date,
    }


def run_end_to_end_synthesis(payload_json: str) -> dict[str, Any]:
    payload = json.loads(payload_json) if payload_json else {}
    query = str(payload.get("query", "")).strip()
    persona_id = str(payload.get("persona_student_id", "STU-1001")).strip() or "STU-1001"
    memory = payload.get("memory") or None
    use_llm_claim_check = payload.get("use_llm_claim_check")

    cfg = AppConfig.load(ROOT / "config.yaml")
    graph = build_orchestrator_graph(cfg=cfg, root_dir=ROOT)
    state, updated_memory = run_orchestrator_turn(
        query,
        persona_student_id=persona_id,
        memory=memory,
        graph=graph,
    )
    syn = synthesize_answer(
        state,
        cfg=cfg,
        root_dir=ROOT,
        use_llm_claim_check=bool(use_llm_claim_check) if use_llm_claim_check is not None else None,
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
        "synthesis": syn.to_dict(),
    }


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "overview"
    if cmd == "overview":
        print(json.dumps(get_phase6_overview()))
    elif cmd == "synthesize":
        arg = sys.argv[2] if len(sys.argv) > 2 else "{}"
        print(json.dumps(run_end_to_end_synthesis(arg)))
