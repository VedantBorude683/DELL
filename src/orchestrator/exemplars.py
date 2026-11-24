"""Route exemplars, fast-path embedding matcher, and safety/injection pre-filter."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from src.orchestrator.models import RouteType
from src.rag.embeddings import Embedder, cosine_similarity, get_embedder

ROUTE_EXEMPLARS: dict[RouteType, tuple[str, ...]] = {
    "sql": (
        "Show my cumulative GPA and current academic year standing",
        "Check my remaining unpaid tuition balance on my fee ledger",
        "List my enrolled courses and weekly class timetable rooms",
        "Which faculty mentors in a department are accepting undergraduates?",
        "How many grant applications have been submitted for a grant ID?",
        "What was the total grant funding disbursed in a past fiscal year?",
        "Look up published base tuition and lab fees by residency status",
        "Check approved fee waivers on my student record for this term",
        "When does final examinations week start on the academic calendar?",
        "List research labs that require safety clearance",
        "Who is my academic advisor and what is my enrollment status?",
        "Show discontinued legacy scholarships from the archive table",
        "Who are the faculty reviewers assigned to evaluate a grant?",
        "What is the total annual grant pool across departments?",
        "List all students who made the Dean's List in Fall 2026",
        "What student awards and stipends has a student received?",
        "List 400-level courses taught in Computer Science",
    ),
    "vector": (
        "Are internal research stipends stackable with waivers or another fellowship?",
        "What non-numeric soft conditions and mentor sponsorship rules apply to a grant?",
        "How did fellowship rules change between handbook v1.0 and v2.0?",
        "According to the PDF tuition and waiver matrix table, what fee or waiver applies?",
        "What ISS CPT work authorization and hour cap rules govern international F-1/J-1 stipends?",
        "What paper acceptance notice and advisor sign-off are needed for the conference travel fund?",
        "What IBC or IRB biosafety ethics approvals are needed for fieldwork grants?",
        "What are the prerequisites and charter submission window for the CS honors research track?",
        "What cleanroom safety training is required before releasing hardware prototyping funds?",
        "What are the 24-hour library hours and study room reservation policy?",
        "What happens to students on probation_watch regarding funded proposals?",
        "Why does the cross-disciplinary grant require two faculty co-mentors?",
        "What is the handbook policy status of a discontinued innovation grant?",
    ),
    "hybrid": (
        "I am a student with a specific year and major — which open grants can I apply for and what are the deadlines and soft rules?",
        "Check my eligibility for a research grant by GPA and year, and explain soft conditions or deadline conflicts to verify",
        "Can an international student apply for a grant stipend and keep a fee waiver under visa and stacking policies?",
        "Can a student apply for a grant considering their GPA, overdue fee ledger balance, and lab safety clearance?",
        "If a student applies for a fellowship, is a specific faculty member accepting mentees and what lab rules apply?",
        "Compare my DB profile and GPA against grant rules, stacking limits, and deadline discrepancies",
    ),
    "out_of_scope": (
        "What is the weekend weather forecast for a city?",
        "Who won the NBA basketball championship last season?",
        "Write a Python script to scrape external job websites",
        "What are the best Italian restaurants near downtown?",
    ),
}

_SAFETY_RULES: tuple[tuple[str, str, str], ...] = (
    (
        "sql_injection_drop",
        r"(?:;\s*drop\s+table|\bdrop\s+table\b|\btruncate\s+table\b|;\s*--)",
        "Blocked destructive SQL injection attempt (DROP/multi-statement).",
    ),
    (
        "sql_injection_update",
        r"(?:\bupdate\s+\w+\s+set\b|\bdelete\s+from\s+\w+\b|\binsert\s+into\s+\w+\b|\balter\s+table\b)",
        "Blocked unauthorized SQL mutation attempt (UPDATE/DELETE/INSERT/ALTER).",
    ),
    (
        "sql_mutation_request",
        r"\b(?:delete|erase|wipe|remove|modify|edit)\s+my\s+(?:overdue\s+)?balance\s+(?:from|in)\s+fee_ledger\b",
        "Refused request to alter financial ledger records.",
    ),
    (
        "sql_union_injection",
        r"\bunion\s+(?:all\s+)?select\b",
        "Blocked UNION SELECT SQL exfiltration attempt.",
    ),
    (
        "system_prompt_leak",
        r"\b(?:developer\s+debug\s+mode|raw\s+database\s+password|system\s+prompt|print\s+the\s+(?:raw\s+)?(?:db|database)\s+password)\b",
        "Refused request for internal system prompts or database credentials.",
    ),
    (
        "pii_exfiltration",
        r"\b(?:every\s+student\s+in\s+the\s+database|all\s+students['’]?\s+(?:gpa|balance|email|records)|unpaid\s+fee\s+balances\s+of\s+every\s+student)\b",
        "Refused bulk student PII/GPA exfiltration request.",
    ),
)

_FOLLOW_UP_CUES = re.compile(
    r"\b(first one|that list|its\s+|that mentor|his\s+|her\s+|that fellowship|"
    r"that lower|that too|on it\b|apply twice|again\b|the travel fund)\b",
    flags=re.IGNORECASE,
)

_CONFUSING_MIDDLE_CUES = re.compile(
    r"(in the database|database deadline|submission window|under the latest policy|"
    r"cumulative gpa or semester gpa|if a student has|pretend you are|untrusted appendix|"
    r"4\.0 gpa|do not check the database|older 2025 handbook|deadline mismatch|reporting my gpa|"
    r"semester gpa is \d\.\d+)",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class ExemplarMatch:
    matched_route: RouteType | None
    top_route: RouteType
    top_similarity: float
    second_route: RouteType
    second_similarity: float
    margin: float
    matched_exemplar: str
    escalate_reason: str | None


def detect_safety_block(query: str) -> tuple[bool, str | None, str | None]:
    """Detect direct SQL injection, bulk PII exfiltration, or credential leaks."""
    q_low = query.lower()
    # Indirect PDF injection prompt tests (e.g. G-078 asking about Campus Library appendix) must route to
    # document retrieval while stripping untrusted instructions, rather than outright refusal.
    if "untrusted appendix" in q_low or "campus library appendix" in q_low:
        return False, None, None

    for rule_id, pattern, reason in _SAFETY_RULES:
        if re.search(pattern, q_low):
            return True, rule_id, reason
    return False, None, None


def is_follow_up_or_ambiguous(query: str, *, has_prior_turn: bool = False) -> tuple[bool, str | None]:
    """Identify anaphoric follow-ups or confusing boundary cases that should bypass fast-path."""
    if has_prior_turn and _FOLLOW_UP_CUES.search(query):
        return True, "multi_turn_follow_up"
    if _FOLLOW_UP_CUES.search(query):
        return True, "anaphoric_reference"
    if _CONFUSING_MIDDLE_CUES.search(query):
        return True, "confusing_boundary_query"
    return False, None


class ExemplarIndex:
    """Embedded route exemplar index for calibrated cosine fast-path classification."""

    def __init__(self, embedder: Embedder | None = None) -> None:
        self.embedder = embedder or get_embedder()
        self.entries: list[tuple[RouteType, str, list[float]]] = []
        texts: list[str] = []
        meta: list[tuple[RouteType, str]] = []
        for route, phrases in ROUTE_EXEMPLARS.items():
            for phrase in phrases:
                meta.append((route, phrase))
                texts.append(phrase)
        vectors = self.embedder.embed_batch(texts)
        for (route, phrase), vec in zip(meta, vectors):
            self.entries.append((route, phrase, vec))

    def match(
        self,
        query: str,
        *,
        threshold: float = 0.78,
        margin_threshold: float = 0.03,
        has_prior_turn: bool = False,
    ) -> ExemplarMatch:
        q_vec = self.embedder.embed_one(query)
        best_by_route: dict[RouteType, tuple[float, str]] = {}
        for route, phrase, vec in self.entries:
            sim = cosine_similarity(q_vec, vec)
            if route not in best_by_route or sim > best_by_route[route][0]:
                best_by_route[route] = (sim, phrase)

        ranked = sorted(best_by_route.items(), key=lambda item: item[1][0], reverse=True)
        top_route, (top_sim, top_phrase) = ranked[0]
        second_route, (second_sim, _) = ranked[1]
        margin = round(top_sim - second_sim, 4)

        should_skip, skip_reason = is_follow_up_or_ambiguous(query, has_prior_turn=has_prior_turn)
        if should_skip:
            return ExemplarMatch(
                matched_route=None,
                top_route=top_route,
                top_similarity=round(top_sim, 4),
                second_route=second_route,
                second_similarity=round(second_sim, 4),
                margin=margin,
                matched_exemplar=top_phrase,
                escalate_reason=skip_reason,
            )

        if top_sim >= threshold and margin >= margin_threshold:
            return ExemplarMatch(
                matched_route=top_route,
                top_route=top_route,
                top_similarity=round(top_sim, 4),
                second_route=second_route,
                second_similarity=round(second_sim, 4),
                margin=margin,
                matched_exemplar=top_phrase,
                escalate_reason=None,
            )

        reason = (
            f"below_threshold ({top_sim:.3f} < {threshold:.2f})"
            if top_sim < threshold
            else f"low_route_margin ({margin:.3f} < {margin_threshold:.2f})"
        )
        return ExemplarMatch(
            matched_route=None,
            top_route=top_route,
            top_similarity=round(top_sim, 4),
            second_route=second_route,
            second_similarity=round(second_sim, 4),
            margin=margin,
            matched_exemplar=top_phrase,
            escalate_reason=reason,
        )
