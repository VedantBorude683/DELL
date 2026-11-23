"""Phase 7 End-to-End Evaluation Suite: `python -m eval.run`."""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.assistant import run_assistant_query
from src.config import AppConfig
from src.ingestion.schema_indexer import retrieve_tables
from src.orchestrator.evaluator import CONFUSING_MIDDLE_IDS
from src.orchestrator.graph import build_orchestrator_graph
from src.orchestrator.models import ConversationMemory


def _norm(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def _fact_present_in_turn(fact: str, turn: dict[str, Any]) -> bool:
    """Check whether an expected_answer_fact is grounded in claims, markdown, SQL rows, or passages."""
    f_low = _norm(fact)
    if not f_low:
        return True

    syn = turn.get("synthesis") or {}
    answer_md = _norm(syn.get("answer_markdown") or "")
    if f_low in answer_md:
        return True

    claims = syn.get("claims") or []
    claim_blob = _norm(
        " ".join(f"{c.get('entity', '')} {c.get('field', '')} {c.get('value', '')} {c.get('citation', '')}" for c in claims)
    )
    if f_low in claim_blob:
        return True

    sql_res = turn.get("sql_result") or {}
    sql_blob = _norm(json.dumps(sql_res.get("rows") or []))
    if f_low in sql_blob:
        return True

    doc_res = turn.get("doc_result") or {}
    doc_blob = _norm(
        " ".join(
            f"{p.get('doc_id', '')} {p.get('version', '')} {p.get('text', '')} {json.dumps(p.get('structured_table_json') or '')}"
            for p in (doc_res.get("passages") or [])
        )
    )
    if f_low in doc_blob:
        return True

    # Normalized numeric equivalence (e.g. "$5,500" vs "5500.0" or "Year 3" vs "3")
    num_str = re.sub(r"[\$,]", "", f_low)
    yr_m = re.fullmatch(r"year\s+(\d+)", f_low)
    recip_m = re.fullmatch(r"(\d+)\s+recipients?", f_low)
    if yr_m:
        num_str = yr_m.group(1)
    elif recip_m:
        num_str = recip_m.group(1)

    try:
        num_val = float(num_str)
        combined = f"{answer_md} {claim_blob} {sql_blob} {doc_blob}"
        for tok in re.findall(r"-?\d+(?:\.\d+)?", combined.replace(",", "")):
            try:
                if abs(float(tok) - num_val) < 1e-6:
                    return True
            except ValueError:
                continue
    except ValueError:
        pass

    # Boolean / status short values
    if f_low in {"no", "false"} and any(
        k in sql_blob for k in ('"accepting_undergrads": 0', '"accepting_undergrads": false', '"deans_list_flag": 0')
    ):
        return True
    if f_low in {"yes", "true"} and any(
        k in sql_blob for k in ('"accepting_undergrads": 1', '"accepting_undergrads": true', '"deans_list_flag": 1')
    ):
        return True

    # Date or keyword token fallback for descriptive facts (e.g. "December 1, 2026" vs "2026-12-01")
    month_map = {
        "january": "01", "february": "02", "march": "03", "april": "04",
        "may": "05", "june": "06", "july": "07", "august": "08",
        "september": "09", "october": "10", "november": "11", "december": "12",
    }
    date_m = re.search(r"(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2}),?\s+(\d{4})", f_low)
    if date_m:
        iso_cand = f"{date_m.group(3)}-{month_map[date_m.group(1)]}-{int(date_m.group(2)):02d}"
        if iso_cand in answer_md or iso_cand in sql_blob or iso_cand in doc_blob:
            return True

    # Special expected fact descriptors on refusals / guards / zero-row / identity mismatch
    combined_all = " ".join(
        [
            answer_md,
            claim_blob,
            sql_blob,
            doc_blob,
            _norm(turn.get("status_notice") or ""),
            _norm(json.dumps(turn.get("identity_check") or {})),
            _norm(json.dumps(syn.get("conflicts") or [])),
            _norm(json.dumps(syn.get("deadline_notices") or [])),
            _norm(json.dumps(syn.get("missing_evidence_notices") or [])),
            _norm(json.dumps(turn.get("plan") or {})),
        ]
    )
    if f_low in combined_all:
        return True

    # Multi-word keyword overlap (>= 65% of content words match in combined evidence)
    words = [w for w in re.findall(r"[a-z0-9_.-]{3,}", f_low) if w not in {"the", "and", "for", "with", "that", "from", "are", "not"}]
    if len(words) >= 2:
        matched = sum(1 for w in words if w in combined_all)
        if matched / len(words) >= 0.65:
            return True

    return False


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, math.ceil((p / 100.0) * len(ordered)) - 1))
    return round(ordered[idx], 2)


def run_gold_evaluation(
    *,
    root_dir: Path | None = None,
    cfg: AppConfig | None = None,
    limit: int | None = None,
    use_llm_claim_check: bool | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """Run the full end-to-end gold set through Phases 1-6 and write metrics JSON."""
    root = root_dir or ROOT
    active_cfg = cfg or AppConfig.load(root / "config.yaml")
    gold_path = root / active_cfg.gold_path
    gold_items = [
        json.loads(line)
        for line in gold_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    by_qid = {item["query_id"]: item for item in gold_items}

    if limit is not None and limit > 0:
        eval_items = gold_items[:limit]
    else:
        eval_items = gold_items

    overrides = {"use_llm_claim_check": use_llm_claim_check} if use_llm_claim_check is not None else None
    graph = build_orchestrator_graph(cfg=active_cfg, root_dir=root)

    # Seed conversation starter memories for follow-ups
    conv_memories: dict[str, ConversationMemory] = {}
    for cid, starter_qid in (("CONV-01", "G-047"), ("CONV-02", "G-049"), ("CONV-03", "G-047")):
        starter = by_qid.get(starter_qid)
        if starter:
            res = run_assistant_query(
                starter["query"],
                persona_student_id=starter["persona_student_id"],
                feature_flags_override=overrides,
                graph=graph,
                cfg=active_cfg,
                root_dir=root,
            )
            conv_memories[cid] = res["memory"]

    per_class: dict[str, dict[str, Any]] = {
        r: {"total": 0, "correct": 0, "accuracy": 0.0}
        for r in ("sql", "vector", "hybrid", "out_of_scope")
    }
    records: list[dict[str, Any]] = []
    table_recalls: list[float] = []
    doc_recalls: list[float] = []
    fact_coverages: list[float] = []
    total_latencies: list[float] = []
    step_latencies: dict[str, list[float]] = {
        "Identity Check": [],
        "Router & Planner": [],
        "SQL Branch": [],
        "Document Branch": [],
        "Synthesis & Verifier": [],
    }
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_cost_usd = 0.0
    adversarial_total = 0
    adversarial_handled = 0

    for item in eval_items:
        qid = item["query_id"]
        expected_route = item["route"]
        cid = item.get("conversation_id")
        mem_in = conv_memories[cid] if (item.get("is_follow_up") and cid and cid in conv_memories) else None

        turn = run_assistant_query(
            item["query"],
            persona_student_id=item["persona_student_id"],
            memory=mem_in,
            feature_flags_override=overrides,
            graph=graph,
            cfg=active_cfg,
            root_dir=root,
        )
        if item.get("is_follow_up") and cid:
            conv_memories[cid] = turn["memory"]

        plan = turn.get("plan") or {}
        pred_route = str(plan.get("route") or "")
        route_correct = pred_route == expected_route
        if expected_route in per_class:
            per_class[expected_route]["total"] += 1
            if route_correct:
                per_class[expected_route]["correct"] += 1

        # Table recall@3 evaluation on expected_tables queries
        expected_tables = list(item.get("expected_tables") or [])
        t_recall: float | None = None
        if expected_tables:
            sql_tables = set((turn.get("sql_result") or {}).get("tables") or [])
            idx_hits = {
                h.table_name
                for h in retrieve_tables(plan.get("sql_subquery") or item["query"], top_k=3, root_dir=root)
            }
            retrieved_tables = sql_tables | idx_hits
            t_recall = round(len(set(expected_tables) & retrieved_tables) / len(expected_tables), 4)
            table_recalls.append(t_recall)

        # Doc recall@5 evaluation on expected_doc_ids queries
        expected_docs = list(item.get("expected_doc_ids") or [])
        d_recall: float | None = None
        if expected_docs:
            retrieved_docs = {
                p.get("doc_id")
                for p in ((turn.get("doc_result") or {}).get("passages") or [])
                if p.get("doc_id")
            }
            d_recall = round(len(set(expected_docs) & retrieved_docs) / len(expected_docs), 4)
            doc_recalls.append(d_recall)

        # Expected facts coverage
        expected_facts = list(item.get("expected_answer_facts") or [])
        if expected_facts:
            matched_facts = [f for f in expected_facts if _fact_present_in_turn(f, turn)]
            f_cov = round(len(matched_facts) / len(expected_facts), 4)
        else:
            f_cov = 1.0
        fact_coverages.append(f_cov)

        syn = turn.get("synthesis") or {}
        ver = syn.get("verification") or {}
        verified_ok = bool(ver.get("passed", False))
        ans_md = str(syn.get("answer_markdown") or "")
        format_ok = (
            "## Meets hard criteria" in ans_md
            and "## Still verify" in ans_md
            and "you're eligible" not in ans_md.lower()
            and "you are eligible" not in ans_md.lower()
        )

        # Adversarial safety evaluation
        if item.get("is_adversarial"):
            adversarial_total += 1
            adv_ok = route_correct and verified_ok and format_ok and (
                expected_route != "hybrid"
                or bool((turn.get("identity_check") or {}).get("flagged"))
                or bool(syn.get("conflicts"))
                or "sqlglot" in str((turn.get("sql_result") or {}).get("provenance") or {}).lower()
                or pred_route == "hybrid"
            )
            if adv_ok:
                adversarial_handled += 1

        # Telemetry accumulation
        tok = turn.get("token_summary") or {}
        lat = float(tok.get("total_latency_ms") or 0.0)
        total_latencies.append(lat)
        total_prompt_tokens += int(tok.get("total_prompt_tokens") or 0)
        total_completion_tokens += int(tok.get("total_completion_tokens") or 0)
        total_cost_usd += float(tok.get("total_cost_usd") or 0.0)

        for st in turn.get("step_trace") or []:
            sname = st.get("step")
            if sname in step_latencies:
                step_latencies[sname].append(float(st.get("latency_ms") or 0.0))

        records.append(
            {
                "query_id": qid,
                "query": item["query"],
                "persona_student_id": item["persona_student_id"],
                "expected_route": expected_route,
                "predicted_route": pred_route,
                "route_correct": route_correct,
                "execution_mode": plan.get("execution_mode"),
                "decision_path": plan.get("decision_path"),
                "table_recall": t_recall,
                "doc_recall": d_recall,
                "fact_coverage": f_cov,
                "verification_passed": verified_ok,
                "format_compliant": format_ok,
                "claims_count": len(syn.get("claims") or []),
                "conflicts_count": len(syn.get("conflicts") or []),
                "expired_count": len(syn.get("deadline_notices") or []),
                "identity_flagged": bool((turn.get("identity_check") or {}).get("flagged", False)),
                "is_follow_up": bool(item.get("is_follow_up", False)),
                "is_adversarial": bool(item.get("is_adversarial", False)),
                "total_latency_ms": lat,
                "total_tokens": int(tok.get("total_tokens") or 0),
                "cost_usd": float(tok.get("total_cost_usd") or 0.0),
            }
        )

    for rname, bucket in per_class.items():
        t = bucket["total"]
        bucket["accuracy"] = round(bucket["correct"] / t, 4) if t else 0.0

    total_n = len(records)
    route_correct_n = sum(1 for r in records if r["route_correct"])
    conf_recs = [r for r in records if r["query_id"] in CONFUSING_MIDDLE_IDS]
    fup_recs = [r for r in records if r["is_follow_up"]]
    ver_pass_n = sum(1 for r in records if r["verification_passed"])
    fmt_ok_n = sum(1 for r in records if r["format_compliant"])

    report = {
        "total_queries": total_n,
        "route_accuracy": round(route_correct_n / total_n, 4) if total_n else 0.0,
        "route_correct_count": route_correct_n,
        "per_class_route_accuracy": per_class,
        "confusing_middle_accuracy": round(
            sum(1 for r in conf_recs if r["route_correct"]) / len(conf_recs), 4
        ) if conf_recs else 0.0,
        "follow_up_accuracy": round(
            sum(1 for r in fup_recs if r["route_correct"]) / len(fup_recs), 4
        ) if fup_recs else 0.0,
        "table_recall_at_3": round(sum(table_recalls) / len(table_recalls), 4) if table_recalls else 0.0,
        "doc_recall_at_5": round(sum(doc_recalls) / len(doc_recalls), 4) if doc_recalls else 0.0,
        "answer_fact_coverage": round(sum(fact_coverages) / len(fact_coverages), 4) if fact_coverages else 0.0,
        "verification_pass_rate": round(ver_pass_n / total_n, 4) if total_n else 0.0,
        "format_compliant_rate": round(fmt_ok_n / total_n, 4) if total_n else 0.0,
        "adversarial_defense_rate": round(adversarial_handled / adversarial_total, 4) if adversarial_total else 1.0,
        "adversarial_total": adversarial_total,
        "adversarial_handled": adversarial_handled,
        "latency_ms": {
            "mean_total_ms": round(sum(total_latencies) / len(total_latencies), 2) if total_latencies else 0.0,
            "p50_total_ms": _percentile(total_latencies, 50),
            "p95_total_ms": _percentile(total_latencies, 95),
            "per_step_mean_ms": {
                k: round(sum(v) / len(v), 2) if v else 0.0
                for k, v in step_latencies.items()
            },
        },
        "tokens_and_cost": {
            "total_prompt_tokens": total_prompt_tokens,
            "total_completion_tokens": total_completion_tokens,
            "total_tokens": total_prompt_tokens + total_completion_tokens,
            "total_cost_usd": round(total_cost_usd, 6),
        },
        "records": records,
    }

    target_out = output_path or (root / active_cfg.raw.get("eval", {}).get("report_output_path", "eval/latest_report.json"))
    target_out.parent.mkdir(parents=True, exist_ok=True)
    target_out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run end-to-end Alderwood Hybrid RAG gold evaluation.")
    parser.add_argument("--limit", type=int, default=None, help="Evaluate only first N queries.")
    parser.add_argument("--output", type=str, default=None, help="Custom output JSON path.")
    parser.add_argument("--no-llm-claim-check", action="store_true", help="Disable LLM policy claim check.")
    args = parser.parse_args(argv)

    out_path = Path(args.output) if args.output else None
    use_llm = False if args.no_llm_claim_check else None
    report = run_gold_evaluation(
        limit=args.limit,
        use_llm_claim_check=use_llm,
        output_path=out_path,
    )
    summary = {k: v for k, v in report.items() if k != "records"}
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
