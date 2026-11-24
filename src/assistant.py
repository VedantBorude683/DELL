"""Unified Phase 7 Assistant Runner with per-step latency and LLM token/cost attribution."""
from __future__ import annotations

import dataclasses
import time
from pathlib import Path
from typing import Any
from functools import lru_cache

from src.config import AppConfig, FeatureFlags
from src.llm.client import capture_llm_usage
from src.orchestrator.graph import build_orchestrator_graph, run_orchestrator_turn
from src.orchestrator.models import ConversationMemory
from src.synthesis import synthesize_answer


@lru_cache(maxsize=4)
def _cached_graph(root_dir: str, cfg_signature: str) -> Any:
    root = Path(root_dir)
    cfg = AppConfig.load(root / "config.yaml")
    return build_orchestrator_graph(cfg=cfg, root_dir=root)


def apply_feature_flag_overrides(
    cfg: AppConfig,
    overrides: dict[str, Any] | None = None,
) -> AppConfig:
    """Return an AppConfig copy with explicit feature_flags overrides applied cleanly."""
    if not overrides:
        return cfg
    ff = cfg.flags
    new_flags = FeatureFlags(
        use_hyde=bool(overrides.get("use_hyde", ff.use_hyde)),
        use_reranker=bool(overrides.get("use_reranker", ff.use_reranker)),
        use_crag_grader=bool(overrides.get("use_crag_grader", ff.use_crag_grader)),
        use_llm_claim_check=bool(overrides.get("use_llm_claim_check", ff.use_llm_claim_check)),
        use_schema_index=bool(overrides.get("use_schema_index", ff.use_schema_index)),
    )
    raw_copy = dict(cfg.raw)
    raw_flags = dict(raw_copy.get("feature_flags") or {})
    raw_flags.update(
        {
            "use_hyde": new_flags.use_hyde,
            "use_reranker": new_flags.use_reranker,
            "use_crag_grader": new_flags.use_crag_grader,
            "use_llm_claim_check": new_flags.use_llm_claim_check,
            "use_schema_index": new_flags.use_schema_index,
        }
    )
    raw_copy["feature_flags"] = raw_flags
    return dataclasses.replace(cfg, raw=raw_copy, flags=new_flags)


def _aggregate_step_telemetry(
    calls: list[dict[str, Any]],
    *,
    orch_trace: dict[str, Any],
    plan: dict[str, Any],
    sql_result: dict[str, Any] | None,
    doc_result: dict[str, Any] | None,
    synthesis_dict: dict[str, Any],
    total_ms: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_step: dict[str, dict[str, Any]] = {}
    total_prompt = 0
    total_completion = 0
    total_cost = 0.0

    for c in calls:
        st = str(c.get("step") or "general")
        pt = int(c.get("prompt_tokens") or 0)
        ct = int(c.get("completion_tokens") or 0)
        cost = float(c.get("cost_usd") or 0.0)
        total_prompt += pt
        total_completion += ct
        total_cost += cost
        bucket = by_step.setdefault(
            st,
            {"prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0, "calls": 0},
        )
        bucket["prompt_tokens"] += pt
        bucket["completion_tokens"] += ct
        bucket["cost_usd"] = round(bucket["cost_usd"] + cost, 6)
        bucket["calls"] += 1

    id_ms = float(orch_trace.get("identity_latency_ms") or 0.0)
    plan_ms = float(orch_trace.get("planner_latency_ms") or 0.0)
    sql_ms = float(orch_trace.get("sql_latency_ms") or 0.0)
    doc_ms = float(orch_trace.get("doc_latency_ms") or 0.0)
    syn_ms = float(synthesis_dict.get("latency_ms") or 0.0)

    seq_info = orch_trace.get("sequential_filter") or {}
    if doc_result is None and seq_info.get("doc_search_skipped"):
        doc_status = "skipped_zero_rows"
    elif doc_result is None:
        doc_status = "skipped"
    else:
        doc_status = "ran"

    sql_status = "skipped" if sql_result is None else "ran"

    syn_stats = {
        "prompt_tokens": (
            by_step.get("synthesis_writer", {}).get("prompt_tokens", 0)
            + by_step.get("synthesis_claim_check", {}).get("prompt_tokens", 0)
        ),
        "completion_tokens": (
            by_step.get("synthesis_writer", {}).get("completion_tokens", 0)
            + by_step.get("synthesis_claim_check", {}).get("completion_tokens", 0)
        ),
        "cost_usd": round(
            by_step.get("synthesis_writer", {}).get("cost_usd", 0.0)
            + by_step.get("synthesis_claim_check", {}).get("cost_usd", 0.0),
            6,
        ),
    }

    steps = [
        {
            "step": "Identity Check",
            "status": "ran",
            "latency_ms": round(id_ms, 2),
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cost_usd": 0.0,
            "detail": "DB student profile loaded & consistency verified",
        },
        {
            "step": "Router & Planner",
            "status": "ran",
            "latency_ms": round(plan_ms, 2),
            "prompt_tokens": by_step.get("router_planner", {}).get("prompt_tokens", 0),
            "completion_tokens": by_step.get("router_planner", {}).get("completion_tokens", 0),
            "cost_usd": by_step.get("router_planner", {}).get("cost_usd", 0.0),
            "detail": f"{plan.get('route')} · {plan.get('execution_mode')} ({plan.get('decision_path')})",
        },
        {
            "step": "SQL Branch",
            "status": sql_status,
            "latency_ms": round(sql_ms, 2),
            "prompt_tokens": by_step.get("sql_branch", {}).get("prompt_tokens", 0),
            "completion_tokens": by_step.get("sql_branch", {}).get("completion_tokens", 0),
            "cost_usd": by_step.get("sql_branch", {}).get("cost_usd", 0.0),
            "detail": (
                f"{len((sql_result or {}).get('rows') or [])} row(s) from {', '.join((sql_result or {}).get('tables') or []) or 'db'}"
                if sql_result is not None
                else "Not executed for this route"
            ),
        },
        {
            "step": "Document Branch",
            "status": doc_status,
            "latency_ms": round(doc_ms, 2),
            "prompt_tokens": by_step.get("doc_branch", {}).get("prompt_tokens", 0),
            "completion_tokens": by_step.get("doc_branch", {}).get("completion_tokens", 0),
            "cost_usd": by_step.get("doc_branch", {}).get("cost_usd", 0.0),
            "detail": (
                f"{len((doc_result or {}).get('passages') or [])} passage(s)"
                if doc_result is not None
                else ("Skipped on 0 SQL rows (no fallback)" if doc_status == "skipped_zero_rows" else "Not executed for this route")
            ),
        },
        {
            "step": "Synthesis & Verifier",
            "status": "ran",
            "latency_ms": round(syn_ms, 2),
            "prompt_tokens": syn_stats["prompt_tokens"],
            "completion_tokens": syn_stats["completion_tokens"],
            "cost_usd": syn_stats["cost_usd"],
            "detail": (
                f"{len(synthesis_dict.get('claims') or [])} claims · "
                f"{'PASS' if synthesis_dict.get('verification', {}).get('passed') else 'WARN'} · "
                f"regen {synthesis_dict.get('regeneration_count', 0)}"
            ),
        },
    ]

    token_summary = {
        "total_prompt_tokens": total_prompt,
        "total_completion_tokens": total_completion,
        "total_tokens": total_prompt + total_completion,
        "total_cost_usd": round(total_cost, 6),
        "llm_calls": calls,
        "total_latency_ms": round(total_ms, 2),
    }
    return steps, token_summary


def run_assistant_query(
    query: str,
    *,
    persona_student_id: str = "STU-1001",
    memory: ConversationMemory | None = None,
    feature_flags_override: dict[str, Any] | None = None,
    graph: Any | None = None,
    cfg: AppConfig | None = None,
    root_dir: Path | None = None,
) -> dict[str, Any]:
    """Run one complete user turn (Identity -> LangGraph -> SQL/Doc -> Synthesis + Verification + Trace)."""
    root = root_dir or Path(".")
    base_cfg = cfg or AppConfig.load(root / "config.yaml")
    active_cfg = apply_feature_flag_overrides(base_cfg, feature_flags_override)
    if graph is not None:
        active_graph = graph
    elif feature_flags_override:
        active_graph = build_orchestrator_graph(cfg=active_cfg, root_dir=root)
    else:
        cfg_signature = str(sorted((active_cfg.raw.get("feature_flags") or {}).items()))
        active_graph = _cached_graph(str(root.resolve()), cfg_signature)

    t0 = time.perf_counter()
    with capture_llm_usage() as llm_calls:
        state_out, updated_memory = run_orchestrator_turn(
            query,
            persona_student_id=persona_student_id,
            memory=memory,
            graph=active_graph,
            cfg=active_cfg,
            root_dir=root,
        )
        syn = synthesize_answer(
            state_out,
            cfg=active_cfg,
            root_dir=root,
            use_llm_claim_check=active_cfg.flags.use_llm_claim_check,
        )
    total_ms = round((time.perf_counter() - t0) * 1000, 2)

    syn_dict = syn.to_dict()
    orch_trace = dict(state_out.get("trace") or {})
    step_trace, token_summary = _aggregate_step_telemetry(
        llm_calls,
        orch_trace=orch_trace,
        plan=state_out.get("plan") or {},
        sql_result=state_out.get("sql_result"),
        doc_result=state_out.get("doc_result"),
        synthesis_dict=syn_dict,
        total_ms=total_ms,
    )

    return {
        "query": query,
        "persona_student_id": persona_student_id,
        "feature_flags": dataclasses.asdict(active_cfg.flags),
        "identity_check": state_out.get("identity_check"),
        "plan": state_out.get("plan"),
        "sql_result": state_out.get("sql_result"),
        "doc_result": state_out.get("doc_result"),
        "status_notice": state_out.get("status_notice"),
        "synthesis": syn_dict,
        "trace": orch_trace,
        "step_trace": step_trace,
        "token_summary": token_summary,
        "memory": updated_memory,
    }
