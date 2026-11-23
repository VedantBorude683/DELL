"""Data models and LangGraph state definition for Phase 5 Router + Planner."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

RouteType = Literal["sql", "vector", "hybrid", "out_of_scope"]
ExecutionMode = Literal["single", "parallel", "sequential", "refuse"]


@dataclass(frozen=True)
class StudentIdentity:
    student_id: str
    full_name: str
    email: str
    dept_code: str
    year_of_study: int
    cumulative_gpa: float
    semester_gpa: float
    advisor_name: str
    enrollment_status: str
    residency_status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "student_id": self.student_id,
            "full_name": self.full_name,
            "email": self.email,
            "dept_code": self.dept_code,
            "year_of_study": self.year_of_study,
            "cumulative_gpa": self.cumulative_gpa,
            "semester_gpa": self.semester_gpa,
            "advisor_name": self.advisor_name,
            "enrollment_status": self.enrollment_status,
            "residency_status": self.residency_status,
        }


@dataclass(frozen=True)
class IdentityCheck:
    persona_student_id: str
    profile: StudentIdentity | None
    self_reported: dict[str, Any] = field(default_factory=dict)
    mismatches: list[dict[str, Any]] = field(default_factory=list)
    flagged: bool = False
    warning_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "persona_student_id": self.persona_student_id,
            "profile": self.profile.to_dict() if self.profile else None,
            "self_reported": self.self_reported,
            "mismatches": self.mismatches,
            "flagged": self.flagged,
            "warning_message": self.warning_message,
        }


@dataclass(frozen=True)
class ExecutionPlan:
    route: RouteType
    execution_mode: ExecutionMode
    sql_subquery: str | None
    doc_subquery: str | None
    resolved_query: str
    target_grant_ids: tuple[str, ...] = ()
    target_faculty_names: tuple[str, ...] = ()
    decision_path: str = "fast_path_exemplar"  # fast_path_exemplar | strong_planner | safety_guard
    exemplar_similarity: float = 0.0
    reasoning: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "route": self.route,
            "execution_mode": self.execution_mode,
            "sql_subquery": self.sql_subquery,
            "doc_subquery": self.doc_subquery,
            "resolved_query": self.resolved_query,
            "target_grant_ids": list(self.target_grant_ids),
            "target_faculty_names": list(self.target_faculty_names),
            "decision_path": self.decision_path,
            "exemplar_similarity": self.exemplar_similarity,
            "reasoning": self.reasoning,
        }


class ConversationMemory(TypedDict, total=False):
    last_plan: dict[str, Any] | None
    last_entities: dict[str, Any]
    turns: list[dict[str, Any]]


class OrchestratorState(TypedDict, total=False):
    query: str
    persona_student_id: str
    last_plan: dict[str, Any] | None
    last_entities: dict[str, Any]
    history: list[dict[str, Any]]
    identity_check: dict[str, Any]
    plan: dict[str, Any]
    sql_result: dict[str, Any] | None
    doc_result: dict[str, Any] | None
    status_notice: str | None
    trace: dict[str, Any]
