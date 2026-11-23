"""Phase 6 Synthesis + Verification Pipeline with 1-retry regeneration and warning fallback."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from src.config import AppConfig
from src.llm.client import llm_step_context
from src.synthesis.checks import (
    detect_expired_deadlines,
    detect_missing_evidence,
    detect_sql_vs_pdf_conflicts,
)
from src.synthesis.models import SourceRegistry, SynthesisResult
from src.synthesis.verifier import (
    ClaimCheckerFn,
    check_rendered_text_safety,
    verify_claims,
)
from src.synthesis.writer import (
    WriterFn,
    generate_claims_with_writer,
    render_answer_from_claims,
)


def synthesize_answer(
    orchestrator_state: dict[str, Any],
    *,
    cfg: AppConfig | None = None,
    root_dir: Path | None = None,
    writer_fn: WriterFn | None = None,
    claim_checker_fn: ClaimCheckerFn | None = None,
    use_llm_claim_check: bool | None = None,
) -> SynthesisResult:
    """Synthesize verified structured claims -> verify own-source & policy checks -> max 1 regeneration."""
    t0 = time.perf_counter()
    root = root_dir or Path(".")
    active_cfg = cfg or AppConfig.load(root / "config.yaml")
    max_regen = int(active_cfg.raw.get("synthesis", {}).get("max_regeneration_attempts", 1))

    registry = SourceRegistry.from_orchestrator_state(orchestrator_state)
    conflicts = detect_sql_vs_pdf_conflicts(registry)
    deadline_notices = detect_expired_deadlines(registry, current_date=active_cfg.current_date)
    missing_notices = detect_missing_evidence(orchestrator_state, registry)

    plan = orchestrator_state.get("plan") or {}
    if plan.get("route") == "out_of_scope" or orchestrator_state.get("status_notice") == "no matching records":
        ver = verify_claims([], registry, cfg=active_cfg, use_llm_claim_check=use_llm_claim_check)
        rendered = render_answer_from_claims(
            [],
            state=orchestrator_state,
            conflicts=conflicts,
            deadline_notices=deadline_notices,
            missing_evidence_notices=missing_notices,
            verification=ver,
            warnings=[],
        )
        return SynthesisResult(
            answer_markdown=rendered,
            claims=[],
            meets_hard_criteria=[],
            still_verify=[],
            conflicts=conflicts,
            deadline_notices=deadline_notices,
            missing_evidence_notices=missing_notices,
            verification=ver,
            regeneration_count=0,
            warnings=[],
            writer_backend="status_renderer",
            latency_ms=round((time.perf_counter() - t0) * 1000, 2),
        )

    # Attempt 1
    with llm_step_context("synthesis_writer"):
        claims, writer_backend = generate_claims_with_writer(
            orchestrator_state,
            registry,
            cfg=active_cfg,
            conflicts=conflicts,
            deadline_notices=deadline_notices,
            writer_fn=writer_fn,
            previous_errors=None,
        )
    with llm_step_context("synthesis_claim_check"):
        ver = verify_claims(
            claims,
            registry,
            cfg=active_cfg,
            use_llm_claim_check=use_llm_claim_check,
            claim_checker_fn=claim_checker_fn,
        )
    rendered_candidate = render_answer_from_claims(
        claims,
        state=orchestrator_state,
        conflicts=conflicts,
        deadline_notices=deadline_notices,
        missing_evidence_notices=missing_notices,
        verification=ver,
        warnings=[],
    )
    text_issues = check_rendered_text_safety(rendered_candidate)
    if text_issues:
        ver_issues = [*ver.issues, *text_issues]
        ver = type(ver)(
            passed=False,
            issues=ver_issues,
            llm_check_ran=ver.llm_check_ran,
            llm_check_backend=ver.llm_check_backend,
            checked_claims_count=ver.checked_claims_count,
            policy_claims_count=ver.policy_claims_count,
        )

    regeneration_count = 0
    while not ver.passed and regeneration_count < max_regen:
        regeneration_count += 1
        err_msgs = [
            f"{i.entity}.{i.field} (source={i.source_id}, {i.check_type}): {i.message}"
            for i in ver.issues
        ]
        with llm_step_context("synthesis_writer"):
            claims, writer_backend = generate_claims_with_writer(
                orchestrator_state,
                registry,
                cfg=active_cfg,
                conflicts=conflicts,
                deadline_notices=deadline_notices,
                writer_fn=writer_fn,
                previous_errors=err_msgs,
            )
        with llm_step_context("synthesis_claim_check"):
            ver = verify_claims(
                claims,
                registry,
                cfg=active_cfg,
                use_llm_claim_check=use_llm_claim_check,
                claim_checker_fn=claim_checker_fn,
            )

    warnings: list[str] = []
    if not ver.passed:
        warnings.append(
            f"Verification failed after {regeneration_count} regeneration attempt(s) "
            f"with {len(ver.issues)} ungrounded or unsupported claim issue(s). Review sources manually."
        )

    final_markdown = render_answer_from_claims(
        claims,
        state=orchestrator_state,
        conflicts=conflicts,
        deadline_notices=deadline_notices,
        missing_evidence_notices=missing_notices,
        verification=ver,
        warnings=warnings,
    )
    meets = [c for c in claims if c.section == "meets_hard_criteria"]
    still = [c for c in claims if c.section in ("still_verify", "conflict", "expired")]

    return SynthesisResult(
        answer_markdown=final_markdown,
        claims=claims,
        meets_hard_criteria=meets,
        still_verify=still,
        conflicts=conflicts,
        deadline_notices=deadline_notices,
        missing_evidence_notices=missing_notices,
        verification=ver,
        regeneration_count=regeneration_count,
        warnings=warnings,
        writer_backend=writer_backend,
        latency_ms=round((time.perf_counter() - t0) * 1000, 2),
    )
