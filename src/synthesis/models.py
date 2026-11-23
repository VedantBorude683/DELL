"""Data models and SourceRegistry for Phase 6 Synthesis + Verification."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ClaimType = Literal["sql", "policy"]
ClaimSection = Literal["meets_hard_criteria", "still_verify", "conflict", "expired"]


@dataclass(frozen=True)
class Claim:
    """Structured factual or policy claim anchored to a specific SQL row or PDF passage."""

    entity: str
    field: str
    value: Any
    source_id: str
    claim_type: ClaimType = "sql"
    section: ClaimSection = "meets_hard_criteria"
    citation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity": self.entity,
            "field": self.field,
            "value": self.value,
            "source_id": self.source_id,
            "claim_type": self.claim_type,
            "section": self.section,
            "citation": self.citation,
        }


@dataclass(frozen=True)
class ConflictNotice:
    entity: str
    field: str
    sql_value: str
    doc_value: str
    sql_source_id: str
    doc_source_id: str
    doc_citation: str
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity": self.entity,
            "field": self.field,
            "sql_value": self.sql_value,
            "doc_value": self.doc_value,
            "sql_source_id": self.sql_source_id,
            "doc_source_id": self.doc_source_id,
            "doc_citation": self.doc_citation,
            "summary": self.summary,
        }


@dataclass(frozen=True)
class DeadlineNotice:
    entity: str
    grant_name: str
    deadline: str
    current_date: str
    source_id: str
    status: Literal["expired", "active"]
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity": self.entity,
            "grant_name": self.grant_name,
            "deadline": self.deadline,
            "current_date": self.current_date,
            "source_id": self.source_id,
            "status": self.status,
            "summary": self.summary,
        }


@dataclass(frozen=True)
class VerificationIssue:
    claim_index: int
    entity: str
    field: str
    source_id: str
    check_type: Literal[
        "source_missing",
        "value_mismatch",
        "missing_citation",
        "llm_claim_check",
        "flat_eligibility_phrase",
    ]
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_index": self.claim_index,
            "entity": self.entity,
            "field": self.field,
            "source_id": self.source_id,
            "check_type": self.check_type,
            "message": self.message,
        }


@dataclass(frozen=True)
class VerificationResult:
    passed: bool
    issues: list[VerificationIssue] = field(default_factory=list)
    llm_check_ran: bool = False
    llm_check_backend: str = "disabled"
    checked_claims_count: int = 0
    policy_claims_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "issues": [i.to_dict() for i in self.issues],
            "llm_check_ran": self.llm_check_ran,
            "llm_check_backend": self.llm_check_backend,
            "checked_claims_count": self.checked_claims_count,
            "policy_claims_count": self.policy_claims_count,
        }


@dataclass
class SourceRegistry:
    """Lookup table mapping source_id -> exact retrieved SQL row or PDF Passage."""

    sql_rows: dict[str, dict[str, Any]] = field(default_factory=dict)
    doc_passages: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_orchestrator_state(cls, state: dict[str, Any]) -> "SourceRegistry":
        reg = cls()
        id_check = state.get("identity_check") or {}
        profile = id_check.get("profile")
        if isinstance(profile, dict) and profile.get("student_id"):
            sid = str(profile["student_id"])
            reg.sql_rows[f"sql:identity:{sid}"] = dict(profile)

        sql_res = state.get("sql_result") or {}
        for idx, row in enumerate(sql_res.get("rows") or []):
            if isinstance(row, dict):
                reg.sql_rows[f"sql:row:{idx}"] = dict(row)

        doc_res = state.get("doc_result") or {}
        for p in doc_res.get("passages") or []:
            if isinstance(p, dict) and p.get("chunk_id"):
                cid = str(p["chunk_id"])
                reg.doc_passages[f"doc:{cid}"] = dict(p)
        return reg


@dataclass(frozen=True)
class SynthesisResult:
    answer_markdown: str
    claims: list[Claim]
    meets_hard_criteria: list[Claim]
    still_verify: list[Claim]
    conflicts: list[ConflictNotice]
    deadline_notices: list[DeadlineNotice]
    missing_evidence_notices: list[str]
    verification: VerificationResult
    regeneration_count: int
    warnings: list[str]
    writer_backend: str
    latency_ms: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer_markdown": self.answer_markdown,
            "claims": [c.to_dict() for c in self.claims],
            "meets_hard_criteria": [c.to_dict() for c in self.meets_hard_criteria],
            "still_verify": [c.to_dict() for c in self.still_verify],
            "conflicts": [c.to_dict() for c in self.conflicts],
            "deadline_notices": [d.to_dict() for d in self.deadline_notices],
            "missing_evidence_notices": self.missing_evidence_notices,
            "verification": self.verification.to_dict(),
            "regeneration_count": self.regeneration_count,
            "warnings": self.warnings,
            "writer_backend": self.writer_backend,
            "latency_ms": self.latency_ms,
        }
