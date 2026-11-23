"""Build Phase 5 orchestrator evaluation report -> data/phase5_report.json."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import AppConfig
from src.orchestrator.evaluator import evaluate_phase5_routing
from src.orchestrator.graph import build_orchestrator_graph, run_orchestrator_turn


def main() -> None:
    cfg = AppConfig.load(ROOT / "config.yaml")
    report = evaluate_phase5_routing(ROOT, cfg=cfg, run_end_to_end_conversations=True)

    # Also capture a concrete sample sequential trace (G-047) and sequential 0-row trace
    graph = build_orchestrator_graph(cfg=cfg, root_dir=ROOT)
    seq_state, _ = run_orchestrator_turn(
        "I'm a 3rd-year CS student. Which research grants can I apply for and what are the deadlines?",
        persona_student_id="STU-1001",
        graph=graph,
    )
    zero_row_state, _ = run_orchestrator_turn(
        "I'm a 3rd-year CS student. Which open research grants require a minimum GPA of 4.90 and what are their rules?",
        persona_student_id="STU-1001",
        graph=graph,
    )

    report["sample_sequential_trace"] = {
        "query_id": "G-047",
        "plan": seq_state["plan"],
        "identity_check": seq_state["identity_check"],
        "sql_row_count": len((seq_state.get("sql_result") or {}).get("rows") or []),
        "sql_tables": (seq_state.get("sql_result") or {}).get("tables") or [],
        "sequential_filter": (seq_state.get("trace") or {}).get("sequential_filter"),
        "doc_citations": [p["citation"] for p in ((seq_state.get("doc_result") or {}).get("passages") or [])],
    }
    report["sample_zero_row_trace"] = {
        "query": zero_row_state["query"],
        "plan": zero_row_state["plan"],
        "status_notice": zero_row_state.get("status_notice"),
        "sequential_filter": (zero_row_state.get("trace") or {}).get("sequential_filter"),
        "doc_result_is_none": zero_row_state.get("doc_result") is None,
    }

    out_path = ROOT / "data" / "phase5_report.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "total_queries": report["total_queries"],
                "overall_route_accuracy": report["overall_route_accuracy"],
                "per_class_accuracy": report["per_class_accuracy"],
                "confusing_middle_accuracy": report["confusing_middle_cases"]["accuracy"],
                "follow_up_accuracy": report["follow_up_eval"]["accuracy"],
                "identity_mismatches": len(report["identity_mismatch_detections"]),
                "decision_path_breakdown": report["decision_path_breakdown"],
                "misses": report["misses"],
                "zero_row_status": report["sample_zero_row_trace"]["status_notice"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
