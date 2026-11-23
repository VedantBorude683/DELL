"""Phase 6 Synthesis + Verification package."""
from src.synthesis.checks import (
    detect_expired_deadlines,
    detect_missing_evidence,
    detect_sql_vs_pdf_conflicts,
)
from src.synthesis.models import (
    Claim,
    ConflictNotice,
    DeadlineNotice,
    SourceRegistry,
    SynthesisResult,
    VerificationIssue,
    VerificationResult,
)
from src.synthesis.synthesizer import synthesize_answer
from src.synthesis.verifier import (
    ClaimCheckerFn,
    LLM_CLAIM_CHECK_SCHEMA,
    check_rendered_text_safety,
    verify_claims,
)
from src.synthesis.writer import (
    WRITER_CLAIMS_SCHEMA,
    WriterFn,
    build_grounded_claims_from_sources,
    generate_claims_with_writer,
    render_answer_from_claims,
)

__all__ = [
    "Claim",
    "ClaimCheckerFn",
    "ConflictNotice",
    "DeadlineNotice",
    "LLM_CLAIM_CHECK_SCHEMA",
    "SourceRegistry",
    "SynthesisResult",
    "VerificationIssue",
    "VerificationResult",
    "WRITER_CLAIMS_SCHEMA",
    "WriterFn",
    "build_grounded_claims_from_sources",
    "check_rendered_text_safety",
    "detect_expired_deadlines",
    "detect_missing_evidence",
    "detect_sql_vs_pdf_conflicts",
    "generate_claims_with_writer",
    "render_answer_from_claims",
    "synthesize_answer",
    "verify_claims",
]
