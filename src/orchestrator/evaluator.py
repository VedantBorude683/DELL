"""Phase 5 Routing, Multi-Turn Follow-up, Confusing-Middle, and Identity Evaluation Suite."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.config import AppConfig
from src.orchestrator.exemplars import ExemplarIndex
from src.orchestrator.graph import build_orchestrator_graph, run_orchestrator_turn
from src.orchestrator.identity import check_identity_consistency
from src.orchestrator.models import ConversationMemory
from src.orchestrator.planner import PlannerFn, plan_query

CONFUSING_MIDDLE_IDS: tuple[str, ...] = (
    "G-008",  # open research grants in database -> sql
    "G-009",  # database deadline and award amount for GR-CS-02 -> sql
    "G-025",  # handbook submission window for Turing Fellowship -> vector
    "G-026",  # application submission window close latest policy -> vector
    "G-033",  # cumulative GPA vs semester GPA policy rule -> vector
    "G-040",  # if a student has overdue balance on fee ledger policy -> vector
    "G-049",  # Liam O'Connor semester GPA 3.85 eligible for GR-CS-01 -> hybrid
    "G-077",  # Dean roleplay policy bypass Liam O'Connor -> hybrid
    "G-078",  # Campus Library untrusted appendix prompt injection -> vector
    "G-080",  # 4th-year CS 4.0 GPA identity spoof -> hybrid
    "G-082",  # Stale v1.0 handbook coercion -> vector
)


def evaluate_phase5_routing(
    root_dir: Path | None = None,
    *,
    cfg: AppConfig | None = None,
    planner_fn: PlannerFn | None = None,
    run_end_to_end_conversations: bool = True,
) -> dict[str, Any]:
    """Evaluate routing accuracy per class, confusing middle cases, follow-ups, and identity checks."""
    root = root_dir or Path(".")
    active_cfg = cfg or AppConfig.load(root / "config.yaml")
    gold_path = root / active_cfg.gold_path
    gold_items = [
        json.loads(line)
        for line in gold_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    by_qid = {item["query_id"]: item for item in gold_items}

    exemplars = ExemplarIndex()
    graph = build_orchestrator_graph(
        cfg=active_cfg,
        root_dir=root,
        exemplar_index=exemplars,
        planner_fn=planner_fn,
    )

    # Seed starter turns for the 3 multi-turn conversations in eval/gold.jsonl
    starter_for_conv = {
        "CONV-01": by_qid["G-047"],
        "CONV-02": by_qid["G-049"],
        "CONV-03": by_qid["G-047"],
    }
    conv_memories: dict[str, ConversationMemory] = {}
    if run_end_to_end_conversations:
        for cid, starter in starter_for_conv.items():
            _, mem = run_orchestrator_turn(
                starter["query"],
                persona_student_id=starter["persona_student_id"],
                graph=graph,
            )
            conv_memories[cid] = mem

    per_class: dict[str, dict[str, Any]] = {
        r: {"total": 0, "correct": 0, "accuracy": 0.0}
        for r in ("sql", "vector", "hybrid", "out_of_scope")
    }
    records: list[dict[str, Any]] = []
    decision_paths: dict[str, int] = {}
    execution_modes: dict[str, int] = {}

    for item in gold_items:
        qid = item["query_id"]
        expected_route = item["route"]
        cid = item.get("conversation_id")

        if item.get("is_follow_up") and cid and cid in conv_memories and run_end_to_end_conversations:
            state_out, updated_mem = run_orchestrator_turn(
                item["query"],
                persona_student_id=item["persona_student_id"],
                memory=conv_memories[cid],
                graph=graph,
            )
            conv_memories[cid] = updated_mem
            plan_d = state_out["plan"]
            id_d = state_out["identity_check"]
            entities_d = state_out.get("last_entities") or {}
        else:
            id_chk = check_identity_consistency(
                item["query"],
                item["persona_student_id"],
                root_dir=root,
                cfg=active_cfg,
            )
            plan_obj = plan_query(
                item["query"],
                identity_check=id_chk,
                last_plan=conv_memories[cid]["last_plan"] if cid in conv_memories else None,
                last_entities=conv_memories[cid]["last_entities"] if cid in conv_memories else None,
                cfg=active_cfg,
                root_dir=root,
                exemplar_index=exemplars,
                planner_fn=planner_fn,
            )
            plan_d = plan_obj.to_dict()
            id_d = id_chk.to_dict()
            entities_d = {
                "target_grant_ids": plan_d.get("target_grant_ids", []),
                "target_faculty_names": plan_d.get("target_faculty_names", []),
            }

        pred_route = plan_d["route"]
        correct = pred_route == expected_route
        per_class[expected_route]["total"] += 1
        if correct:
            per_class[expected_route]["correct"] += 1

        dpath = str(plan_d.get("decision_path", "unknown"))
        decision_paths[dpath] = decision_paths.get(dpath, 0) + 1
        emode = str(plan_d.get("execution_mode", "single"))
        execution_modes[emode] = execution_modes.get(emode, 0) + 1

        records.append(
            {
                "query_id": qid,
                "query": item["query"],
                "persona_student_id": item["persona_student_id"],
                "expected_route": expected_route,
                "predicted_route": pred_route,
                "correct": correct,
                "execution_mode": emode,
                "decision_path": dpath,
                "exemplar_similarity": plan_d.get("exemplar_similarity", 0.0),
                "resolved_query": plan_d.get("resolved_query"),
                "target_grant_ids": plan_d.get("target_grant_ids", []),
                "target_faculty_names": plan_d.get("target_faculty_names", []),
                "identity_flagged": bool(id_d.get("flagged", False)),
                "identity_mismatches": id_d.get("mismatches", []),
                "is_follow_up": bool(item.get("is_follow_up", False)),
                "conversation_id": cid,
                "is_adversarial": bool(item.get("is_adversarial", False)),
                "entities_after_turn": entities_d,
            }
        )

    for route_name, bucket in per_class.items():
        t = bucket["total"]
        bucket["accuracy"] = round(bucket["correct"] / t, 4) if t else 0.0

    total_queries = len(records)
    total_correct = sum(1 for r in records if r["correct"])

    confusing_records = [r for r in records if r["query_id"] in CONFUSING_MIDDLE_IDS]
    confusing_correct = sum(1 for r in confusing_records if r["correct"])

    followup_records = [r for r in records if r["is_follow_up"]]
    followup_correct = sum(1 for r in followup_records if r["correct"])

    identity_flagged_records = [r for r in records if r["identity_flagged"]]

    return {
        "total_queries": total_queries,
        "total_correct": total_correct,
        "overall_route_accuracy": round(total_correct / total_queries, 4) if total_queries else 0.0,
        "per_class_accuracy": per_class,
        "confusing_middle_cases": {
            "total": len(confusing_records),
            "correct": confusing_correct,
            "accuracy": round(confusing_correct / len(confusing_records), 4) if confusing_records else 0.0,
            "cases": confusing_records,
        },
        "follow_up_eval": {
            "total": len(followup_records),
            "correct": followup_correct,
            "accuracy": round(followup_correct / len(followup_records), 4) if followup_records else 0.0,
            "cases": followup_records,
        },
        "identity_mismatch_detections": [
            {
                "query_id": r["query_id"],
                "persona_student_id": r["persona_student_id"],
                "mismatches": r["identity_mismatches"],
                "predicted_route": r["predicted_route"],
            }
            for r in identity_flagged_records
        ],
        "decision_path_breakdown": decision_paths,
        "execution_mode_breakdown": execution_modes,
        "misses": [r for r in records if not r["correct"]],
        "records": records,
    }
