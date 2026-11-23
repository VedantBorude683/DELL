"""Build Phase 6 Synthesis + Verification evaluation report -> data/phase6_report.json."""
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
from src.orchestrator.models import ConversationMemory
from src.synthesis import synthesize_answer


def main() -> None:
    cfg = AppConfig.load(ROOT / "config.yaml")
    gold_path = ROOT / cfg.gold_path
    gold_items = [
        json.loads(line)
        for line in gold_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    by_qid = {item["query_id"]: item for item in gold_items}

    graph = build_orchestrator_graph(cfg=cfg, root_dir=ROOT)
    starter_for_conv = {
        "CONV-01": by_qid["G-047"],
        "CONV-02": by_qid["G-049"],
        "CONV-03": by_qid["G-047"],
    }
    conv_memories: dict[str, ConversationMemory] = {}
    for cid, starter in starter_for_conv.items():
        _, mem = run_orchestrator_turn(
            starter["query"],
            persona_student_id=starter["persona_student_id"],
            graph=graph,
        )
        conv_memories[cid] = mem

    records: list[dict[str, Any]] = []
    verified_pass_count = 0
    format_compliant_count = 0
    conflict_detected_qids: list[str] = []
    expired_detected_qids: list[str] = []
    missing_notice_qids: list[str] = []
    total_claims = 0
    total_policy_claims = 0

    for item in gold_items:
        qid = item["query_id"]
        cid = item.get("conversation_id")
        if item.get("is_follow_up") and cid and cid in conv_memories:
            state_out, updated_mem = run_orchestrator_turn(
                item["query"],
                persona_student_id=item["persona_student_id"],
                memory=conv_memories[cid],
                graph=graph,
            )
            conv_memories[cid] = updated_mem
        else:
            state_out, _ = run_orchestrator_turn(
                item["query"],
                persona_student_id=item["persona_student_id"],
                graph=graph,
            )

        syn = synthesize_answer(state_out, cfg=cfg, root_dir=ROOT)
        total_claims += len(syn.claims)
        total_policy_claims += syn.verification.policy_claims_count
        if syn.verification.passed:
            verified_pass_count += 1

        has_sections = (
            "## Meets hard criteria" in syn.answer_markdown
            and "## Still verify" in syn.answer_markdown
            and "you're eligible" not in syn.answer_markdown.lower()
            and "you are eligible" not in syn.answer_markdown.lower()
        )
        if has_sections:
            format_compliant_count += 1
        if syn.conflicts:
            conflict_detected_qids.append(qid)
        if syn.deadline_notices:
            expired_detected_qids.append(qid)
        if syn.missing_evidence_notices:
            missing_notice_qids.append(qid)

        records.append(
            {
                "query_id": qid,
                "route": state_out["plan"]["route"],
                "claims_count": len(syn.claims),
                "meets_hard_count": len(syn.meets_hard_criteria),
                "still_verify_count": len(syn.still_verify),
                "verification_passed": syn.verification.passed,
                "format_compliant": has_sections,
                "conflicts_count": len(syn.conflicts),
                "expired_count": len(syn.deadline_notices),
                "missing_evidence_count": len(syn.missing_evidence_notices),
                "regeneration_count": syn.regeneration_count,
                "latency_ms": syn.latency_ms,
            }
        )

    # Capture rich showcase samples for UI & report
    showcase_samples: dict[str, Any] = {}
    for sample_qid in ("G-047", "G-049", "G-055", "G-056", "G-080"):
        it = by_qid[sample_qid]
        st, _ = run_orchestrator_turn(it["query"], persona_student_id=it["persona_student_id"], graph=graph)
        sy = synthesize_answer(st, cfg=cfg, root_dir=ROOT)
        showcase_samples[sample_qid] = {
            "query": it["query"],
            "persona_student_id": it["persona_student_id"],
            "route": st["plan"]["route"],
            "execution_mode": st["plan"]["execution_mode"],
            "synthesis": sy.to_dict(),
        }

    total = len(gold_items)
    report = {
        "evaluated_queries": total,
        "verification_pass_count": verified_pass_count,
        "verification_pass_rate": round(verified_pass_count / total, 4) if total else 0.0,
        "format_compliant_count": format_compliant_count,
        "format_compliant_rate": round(format_compliant_count / total, 4) if total else 0.0,
        "total_claims_generated": total_claims,
        "total_policy_claims_checked": total_policy_claims,
        "conflict_detected_qids": conflict_detected_qids,
        "expired_detected_qids": expired_detected_qids,
        "missing_evidence_qids": missing_notice_qids,
        "showcase_samples": showcase_samples,
        "records": records,
    }

    out_path = ROOT / "data" / "phase6_report.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "evaluated_queries": total,
                "verification_pass_rate": report["verification_pass_rate"],
                "format_compliant_rate": report["format_compliant_rate"],
                "total_claims_generated": total_claims,
                "total_policy_claims_checked": total_policy_claims,
                "conflict_detected_qids": conflict_detected_qids,
                "expired_detected_qids": expired_detected_qids,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
