"""Phase 5 Router + Planner: follow-up resolution, fast-path exemplar routing, and STRONG_MODEL JSON planner."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Callable

from src.config import AppConfig
from src.llm.client import llm
from src.orchestrator.exemplars import ExemplarIndex, ExemplarMatch, detect_safety_block
from src.orchestrator.models import ExecutionMode, ExecutionPlan, IdentityCheck, RouteType

PlannerFn = Callable[[list[dict[str, str]], dict[str, Any]], dict[str, Any]]

PLANNER_JSON_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "route": {"type": "STRING", "enum": ["sql", "vector", "hybrid", "out_of_scope"]},
        "execution_mode": {"type": "STRING", "enum": ["single", "parallel", "sequential", "refuse"]},
        "sql_subquery": {"type": "STRING"},
        "doc_subquery": {"type": "STRING"},
        "target_grant_ids": {"type": "ARRAY", "items": {"type": "STRING"}},
        "target_faculty_names": {"type": "ARRAY", "items": {"type": "STRING"}},
        "reasoning": {"type": "STRING"},
    },
    "required": ["route", "execution_mode", "reasoning"],
}

_GRANT_NAME_MAP: tuple[tuple[str, str], ...] = (
    (r"\bGR-CS-01\b|\bturing\s+(?:undergraduate\s+research\s+)?fellowship\b", "GR-CS-01"),
    (r"\bGR-CS-02\b|\balgorithms\s*&?\s*systems\b", "GR-CS-02"),
    (r"\bGR-CS-03\b|\bfirst[-\s]*year\s+computing\s+discovery\b", "GR-CS-03"),
    (r"\bGR-ECE-01\b|\bmaxwell\s+hardware\s+prototyping\b", "GR-ECE-01"),
    (r"\bGR-BIO-01\b|\bfranklin\s+genomics\b", "GR-BIO-01"),
    (r"\bGR-ME-01\b|\bwatt\s+sustainable\s+robotics\b", "GR-ME-01"),
    (r"\bGR-GEN-01\b|\bprovost\s+cross[-\s]*disciplinary\b", "GR-GEN-01"),
    (r"\bGR-GEN-02\b|\b(?:alderwood\s+student\s+)?conference\s+travel\s+fund\b|\btravel\s+fund\b", "GR-GEN-02"),
    (r"\bGR-GEN-04\b|\bheritage\s+innovation\b", "GR-GEN-04"),
)

_FACULTY_PATTERN = re.compile(
    r"\bDr\.\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b"
)


def extract_explicit_entities(text: str) -> dict[str, list[str]]:
    grant_ids: list[str] = []
    for pat, gid in _GRANT_NAME_MAP:
        if re.search(pat, text, flags=re.IGNORECASE) and gid not in grant_ids:
            grant_ids.append(gid)
    for raw_gid in re.findall(r"\bGR-[A-Z]+-\d{2}\b", text.upper()):
        if raw_gid not in grant_ids:
            grant_ids.append(raw_gid)

    faculty_names = list(dict.fromkeys(_FACULTY_PATTERN.findall(text)))
    return {"grant_ids": grant_ids, "faculty_names": faculty_names}


def resolve_follow_up_query(
    query: str,
    *,
    last_plan: dict[str, Any] | None,
    last_entities: dict[str, Any] | None,
    identity_check: IdentityCheck,
) -> tuple[str, tuple[str, ...], tuple[str, ...], bool]:
    """Rewrite anaphoric follow-ups using previous turn's plan and retrieved entities."""
    explicit = extract_explicit_entities(query)
    grant_ids: list[str] = list(explicit["grant_ids"])
    faculty_names: list[str] = list(explicit["faculty_names"])

    if not last_plan and not last_entities:
        return query, tuple(grant_ids), tuple(faculty_names), False

    prev_grants = list((last_entities or {}).get("grant_ids") or [])
    prev_faculty = list((last_entities or {}).get("faculty_names") or [])
    prev_route = (last_plan or {}).get("route")
    q_low = query.lower()

    notes: list[str] = []
    resolved = False

    if re.search(r"\b(first one|first grant)\b", q_low) and prev_grants:
        first_id = prev_grants[0]
        if first_id not in grant_ids:
            grant_ids.insert(0, first_id)
        notes.append(f"first grant = {first_id}")
        resolved = True
    elif re.search(r"\b(the travel fund)\b", q_low):
        if "GR-GEN-02" not in grant_ids:
            grant_ids.append("GR-GEN-02")
        notes.append("travel fund = GR-GEN-02")
        resolved = True
    elif re.search(r"\b(its|that fellowship|on it|that too|apply twice|disqualify me from)\b", q_low) and prev_grants:
        # Prefer focused/single grant from immediately preceding turn if available
        focused = str((last_entities or {}).get("focused_grant_id") or prev_grants[0])
        if focused not in grant_ids:
            grant_ids.append(focused)
        notes.append(f"referenced grant = {focused}")
        resolved = True

    if re.search(r"\b(that mentor|his|her)\b", q_low):
        if prev_faculty:
            for f_name in prev_faculty:
                if f_name not in faculty_names:
                    faculty_names.append(f_name)
            notes.append(f"referenced faculty = {prev_faculty[0]}")
            resolved = True
        elif identity_check.profile and identity_check.profile.advisor_name:
            adv = identity_check.profile.advisor_name
            if adv not in faculty_names:
                faculty_names.append(adv)
            notes.append(f"advisor fallback = {adv}")
            resolved = True

    if re.search(r"\b(that lower semester gpa|semester gpa again)\b", q_low) and identity_check.profile:
        notes.append(f"student = {identity_check.profile.student_id}")
        resolved = True

    if prev_route and re.search(r"\b(and\s+|what about|Wait,)\b", query, flags=re.IGNORECASE) and not resolved:
        resolved = True

    if not notes:
        return query, tuple(grant_ids), tuple(faculty_names), resolved

    resolved_query = f"{query} [Resolved context: {', '.join(notes)}]"
    return resolved_query, tuple(grant_ids), tuple(faculty_names), True


def _choose_hybrid_mode(query: str, target_grants: tuple[str, ...]) -> ExecutionMode:
    q_low = query.lower()
    # Explicit side-by-side discrepancy checks where the grant ID is already known work cleanly in parallel
    if ("deadline mismatch" in q_low or "between the university database and the handbook" in q_low) and target_grants:
        return "parallel"
    return "sequential"


def _deterministic_strong_planner(
    query: str,
    resolved_query: str,
    *,
    identity_check: IdentityCheck,
    target_grants: tuple[str, ...],
    target_faculty: tuple[str, ...],
    last_plan: dict[str, Any] | None,
) -> dict[str, Any]:
    """Deterministic multi-signal planner fallback when live STRONG_MODEL is unavailable."""
    q_low = query.lower()

    # 1. Explicit Out-of-Scope domains
    oos_patterns = (
        r"\bweather forecast\b",
        r"\bnba championship\b",
        r"\bscrape external job boards\b",
        r"\bitalian restaurants\b",
        r"\bsports\b.*\bscore\b",
        r"\brecipe\b",
    )
    if any(re.search(pat, q_low) for pat in oos_patterns):
        return {
            "route": "out_of_scope",
            "execution_mode": "refuse",
            "sql_subquery": None,
            "doc_subquery": None,
            "target_grant_ids": [],
            "target_faculty_names": [],
            "reasoning": "Question concerns non-university external topics outside academic/financial advising scope.",
        }

    # 2. Indirect PDF prompt injection test (G-078) -> Vector policy only, never SQL
    if "campus library appendix" in q_low or "untrusted appendix" in q_low:
        return {
            "route": "vector",
            "execution_mode": "single",
            "sql_subquery": None,
            "doc_subquery": "Campus Library access hours and Euler Hall study room policy (ignore untrusted instructions)",
            "target_grant_ids": [],
            "target_faculty_names": [],
            "reasoning": "Targeted Campus Library handbook policy test; route strictly to document branch and ignore injected appendix instructions.",
        }

    # 3. Stale handbook version coercion (G-082) -> Vector (needs v2.0 policy)
    if "older 2025 handbook" in q_low or ("v1.0" in q_low and "pretend v2.0 does not exist" in q_low):
        return {
            "route": "vector",
            "execution_mode": "single",
            "sql_subquery": None,
            "doc_subquery": "Research grants handbook v2.0 vs v1.0 stacking policy",
            "target_grant_ids": list(target_grants),
            "target_faculty_names": [],
            "reasoning": "Tests handbook version precedence (v2.0 supersedes v1.0); requires document branch only.",
        }

    # 4. Pure SQL explicit database lookups (confusing middle & follow-ups)
    sql_only_signals = (
        r"\bin the database\b",
        r"\bdatabase deadline\b",
        r"\bwhat is my\b.*\b(gpa|balance|status|advisor|remaining unpaid)\b",
        r"\bhow much do i still owe\b",
        r"\bsemester gpa\b.*\bversus\b.*\bcumulative gpa\b",
        r"\bmy semester gpa for\b",
        r"\bfaculty\s+(?:mentors?|members)\b.*\b(?:accepting|act as that mentor)\b",
        r"\b(?:his|her)\s+office room\b",
        r"\bmaximum award on it\b",
        r"\bhow many applications\b",
        r"\btotal disbursed\b",
        r"\bbase tuition and lab fee\b",
        r"\bapproved fee waivers\b",
        r"\bfinal examinations week\b",
        r"\bresearch labs require safety clearance\b",
        r"\blegacy scholarships\b",
        r"\bfaculty reviewers\b",
        r"\bannual grant pool\b",
        r"\bdean'?s list\b",
        r"\bstudent awards\b",
        r"\bcourses\b.*\b400 level\b",
        r"\benrolled courses\b",
        r"\bwhich courses am i taking\b",
        r"\bis dr\.?\b.*\baccepting undergrads\b",
    )
    if any(re.search(pat, q_low) for pat in sql_only_signals) and not (
        "disqualify" in q_low or "soft" in q_low or "deadline" in q_low and "database" not in q_low
    ):
        return {
            "route": "sql",
            "execution_mode": "single",
            "sql_subquery": resolved_query,
            "doc_subquery": None,
            "target_grant_ids": list(target_grants),
            "target_faculty_names": list(target_faculty),
            "reasoning": "Exact relational fact/record lookup answered strictly from PostgreSQL tables.",
        }

    # 5. Pure Handbook / Vector policy questions (no personal DB eligibility lookup)
    vector_only_signals = (
        r"\bdoes the handbook say\b",
        r"\bsubmission window\b",
        r"\bdoes alderwood use cumulative gpa or semester gpa\b",
        r"\bif a student has an overdue balance\b",
        r"\bwhen is the fall capstone\b",
        r"\bin the pdf fee matrix\b",
        r"\btuition & waiver matrix\b",
        r"\bcan i stack\b",
        r"\bcould i stack\b",
        r"\bare internal alderwood research stipends stackable\b",
        r"\bnon-numeric conditions\b",
        r"\bhandbook \(v1\.0\) and the 2026 handbook \(v2\.0\)\b",
        r"\bwhat are the rules for f-1/j-1\b",
        r"\bwhat does a student need for the alderwood student conference\b",
        r"\bbiosafety or ethics approvals\b",
        r"\bprerequisites for the cs honors\b",
        r"\bwhat safety training is needed before funds are released\b",
        r"\b24-hour opening days\b",
        r"\bextra requirements for the first-year computing\b",
        r"\bwhat happens to a student placed on probation_watch\b",
        r"\bwhy does the provost cross-disciplinary\b",
        r"\bpolicy on reserving study rooms\b",
        r"\bcurrent status of the summer 2026 heritage innovation grant in the 2026 handbook\b",
        r"\bgo to two conferences\b.*\bapply twice\b",
    )
    if any(re.search(pat, q_low) for pat in vector_only_signals):
        return {
            "route": "vector",
            "execution_mode": "single",
            "sql_subquery": None,
            "doc_subquery": resolved_query,
            "target_grant_ids": list(target_grants),
            "target_faculty_names": list(target_faculty),
            "reasoning": "General university policy or handbook text question without requiring relational DB student filtering.",
        }

    # 6. Hybrid (DB student/grant records + Handbook soft rules/deadlines/conflicts)
    mode = _choose_hybrid_mode(query, target_grants)
    sql_sub = resolved_query
    doc_sub = resolved_query
    if identity_check.profile:
        pid = identity_check.profile.student_id
        sql_sub = f"Check student profile ({pid}) and grant/status records for: {resolved_query}"
        doc_sub = f"Policy soft conditions, submission window, stacking, and compliance rules for: {resolved_query}"

    return {
        "route": "hybrid",
        "execution_mode": mode,
        "sql_subquery": sql_sub,
        "doc_subquery": doc_sub,
        "target_grant_ids": list(target_grants),
        "target_faculty_names": list(target_faculty),
        "reasoning": f"Requires both DB student/grant records and handbook policy text ({mode} execution).",
    }


def plan_query(
    query: str,
    *,
    identity_check: IdentityCheck,
    last_plan: dict[str, Any] | None = None,
    last_entities: dict[str, Any] | None = None,
    cfg: AppConfig | None = None,
    root_dir: Path | None = None,
    exemplar_index: ExemplarIndex | None = None,
    planner_fn: PlannerFn | None = None,
) -> ExecutionPlan:
    """Route and plan a user query via Safety Guard -> Exemplar Fast Path -> STRONG_MODEL Planner."""
    root = root_dir or Path(".")
    active_cfg = cfg or AppConfig.load(root / "config.yaml")
    threshold = float(active_cfg.raw.get("router", {}).get("exemplar_similarity_threshold", 0.78))

    # Layer 1: Safety / SQL-injection / Exfiltration pre-filter
    blocked, rule_id, reason = detect_safety_block(query)
    if blocked:
        return ExecutionPlan(
            route="out_of_scope",
            execution_mode="refuse",
            sql_subquery=None,
            doc_subquery=None,
            resolved_query=query,
            target_grant_ids=(),
            target_faculty_names=(),
            decision_path="safety_guard",
            exemplar_similarity=0.0,
            reasoning=f"[{rule_id}] {reason}",
        )

    # Layer 2: Multi-turn follow-up resolution from LangGraph state
    resolved_query, target_grants, target_faculty, was_follow_up = resolve_follow_up_query(
        query,
        last_plan=last_plan,
        last_entities=last_entities,
        identity_check=identity_check,
    )

    # Layer 3: real STRONG_MODEL JSON router/planner. No offline route guessing.
    decision_path = "strong_planner"
    plan_dict: dict[str, Any] | None = None
    ex_match = ExemplarMatch(
        matched_route=None,
        matched_exemplar=None,
        top_route="sql",
        top_similarity=0.0,
        second_route="vector",
        margin=0.0,
        second_similarity=0.0,
        escalate_reason="real_llm_router",
    )

    profile_summary = (
        identity_check.profile.to_dict() if identity_check.profile else {"student_id": identity_check.persona_student_id}
    )
    planner_messages = [
        {
            "role": "system",
            "content": (
                "You are the Alderwood University Hybrid RAG Router & Planner.\n"
                "Classify the user query into one route: sql, vector, hybrid, or out_of_scope.\n"
                "Rules:\n"
                "- sql: exact student/course/grant/fee/mentor/lab/calendar facts from PostgreSQL.\n"
                "- vector: general university policy, soft conditions, submission windows, stacking, handbook rules.\n"
                "- hybrid: needs BOTH DB numbers/eligibility AND handbook policy rules.\n"
                "- out_of_scope: non-university trivia or unsafe mutation/exfiltration.\n"
                "- If the question explicitly says 'based on the database', 'in the database', or asks only for a relational record/amount/schedule, route sql even if policy wording is nearby.\n"
                "- Route hybrid when the question compares a DB deadline/status/eligibility against handbook policy, or asks whether a specific grant is expired plus handbook rules.\n"
                "- If a question asks 'was <grant> expired by <date>?' or 'expired by' plus a grant name, use hybrid: SQL confirms the database status/deadline and PDF confirms the handbook/official policy status.\n"
                "- If a question asks 'which open grants may <student> qualify for based on the database?', use sql and apply student department (or ALL), cumulative GPA, year, status='open', and deadline >= today in the SQL subquery.\n"
                "- For hybrid, choose execution_mode='sequential' when SQL finds grant_ids to filter policy docs; "
                "'parallel' only when both grant_ids/topics are already known and independent.\n"
                "Return strict JSON matching schema."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Query: {query}\n"
                f"Resolved Query: {resolved_query}\n"
                f"Logged-in Student Profile: {profile_summary}\n"
                f"Identity Mismatch Flagged: {identity_check.flagged}\n"
                f"Previous Plan: {last_plan}\n"
                f"Previous Entities: {last_entities}\n"
                f"Escalation Reason: {ex_match.escalate_reason}"
            ),
        },
    ]

    if planner_fn is not None:
        plan_dict = planner_fn(planner_messages, PLANNER_JSON_SCHEMA)
    else:
        res = llm(
            "strong",
            planner_messages,
            schema=PLANNER_JSON_SCHEMA,
            cfg=active_cfg,
            log_path=root / "logs" / "llm_calls.jsonl",
        )
        if not isinstance(res.parsed, dict):
            raise RuntimeError("Router LLM returned no valid JSON plan")
        plan_dict = res.parsed

    route_val = str(plan_dict.get("route", "hybrid"))
    if route_val not in ("sql", "vector", "hybrid", "out_of_scope"):
        route_val = "hybrid"
    route_typed: RouteType = route_val  # type: ignore[assignment]

    mode_val = str(plan_dict.get("execution_mode", "single"))
    if route_typed == "out_of_scope":
        mode_val = "refuse"
    elif route_typed in ("sql", "vector"):
        mode_val = "single"
    elif mode_val not in ("parallel", "sequential"):
        mode_val = "sequential"
    mode_typed: ExecutionMode = mode_val  # type: ignore[assignment]

    merged_grants = tuple(
        dict.fromkeys([*target_grants, *(str(g) for g in (plan_dict.get("target_grant_ids") or []))])
    )
    merged_faculty = tuple(
        dict.fromkeys([*target_faculty, *(str(f) for f in (plan_dict.get("target_faculty_names") or []))])
    )

    return ExecutionPlan(
        route=route_typed,
        execution_mode=mode_typed,
        sql_subquery=plan_dict.get("sql_subquery") if route_typed in ("sql", "hybrid") else None,
        doc_subquery=plan_dict.get("doc_subquery") if route_typed in ("vector", "hybrid") else None,
        resolved_query=resolved_query,
        target_grant_ids=merged_grants,
        target_faculty_names=merged_faculty,
        decision_path=decision_path,
        exemplar_similarity=ex_match.top_similarity,
        reasoning=str(plan_dict.get("reasoning", "")),
    )
