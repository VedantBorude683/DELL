"""HyDE query expansion (single retry on low rerank score) and optional CRAG passage grader."""
from __future__ import annotations

import re
from typing import Any, Callable

from src.config import AppConfig
from src.doc_branch.models import Passage
from src.llm.client import llm

HydeGeneratorFn = Callable[[str], str]
CragGraderFn = Callable[[str, list[Passage]], list[dict[str, str]]]

_CRAG_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "grades": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "chunk_id": {"type": "STRING"},
                    "grade": {"type": "STRING"},
                    "reason": {"type": "STRING"},
                },
                "required": ["chunk_id", "grade"],
            },
        }
    },
    "required": ["grades"],
}

_HYDE_DOMAIN_BRIDGES: tuple[tuple[str, str], ...] = (
    ("deadline|deadlines|due|close|closes|cutoff|when", "submission window closing date Committee Amendment effective_date December 1, 2026"),
    ("grant|grants|fellowship|stipend|funding|eligible|qualify", "research grants minimum cumulative_gpa faculty mentor sponsorship not stackable"),
    ("turing|gr-cs-01", "Turing Undergraduate Research Fellowship GR-CS-01 submission window December 1, 2026 faculty endorsement"),
    ("ai systems|gr-cs-02", "Alderwood AI Systems Innovation Stipend GR-CS-02 submission window faculty co-signer"),
    ("discovery|first-year|gr-cs-03", "First-Year Computing Discovery Award GR-CS-03 faculty orientation workshop two-page project pitch"),
    ("travel|conference|gr-gen-02", "Alderwood Student Conference Travel Fund GR-GEN-02 paper acceptance notice advisor sign-off not stackable"),
    ("genomics|bio|irb|biosafety|gr-bio-01", "Franklin Genomics Fieldwork Grant GR-BIO-01 IBC IRB protocol approval faculty mentor sponsorship"),
    ("hardware|cleanroom|ece|gr-ece-01", "Maxwell Hardware Prototyping Grant GR-ECE-01 Cleanroom Lab Safety Clearance ECE faculty mentor"),
    ("robotics|wind tunnel|me|gr-me-01", "Watt Sustainable Robotics Fellowship GR-ME-01 wind-tunnel safety certification"),
    ("provost|cross-disciplinary|gr-gen-01", "Provost Cross-Disciplinary Research Grant GR-GEN-01 two faculty co-mentors from distinct departments"),
    ("heritage|expired|discontinued|gr-gen-04", "Summer 2026 Heritage Innovation Grant GR-GEN-04 discontinued closed June 30, 2026"),
    ("stack|stackable|combine|both", "not stackable internal research stipends Dean Entrance Waiver"),
    ("fee|tuition|waiver|matrix|overdue|unpaid|balance", "Tuition Waiver Policy Handbook Structured Table matrix overdue balance hardship waiver cash grant disbursements"),
    ("gpa|cumulative|semester|probation", "Cumulative GPA vs. Semester GPA Academic Standing Dean's List probation_watch 3.00 ineligible"),
    ("international|f-1|j-1|visa|cpt", "International Student Funding F-1 J-1 ISS CPT on-campus work authorization max 20 hours per week"),
    ("library|study room|euler|hours", "Turing Science Library 24 hours Monday through Thursday Euler Hall 7 days in advance 2-hour blocks"),
    ("honors|capstone|charter", "CS Honors Research Track 3.50 cumulative GPA CS-301 capstone project charter October 15 to November 30, 2026"),
)


def _offline_hyde_expand(query: str) -> str:
    q_low = query.lower()
    expansions: list[str] = []
    for pattern, snippet in _HYDE_DOMAIN_BRIDGES:
        if re.search(pattern, q_low):
            expansions.append(snippet)
    if not expansions:
        expansions.append("submission window eligibility cumulative_gpa faculty mentor sponsorship not stackable")
    return " ; ".join(expansions)


def generate_hyde_passage(
    query: str,
    *,
    cfg: AppConfig | None = None,
    hyde_generator: HydeGeneratorFn | None = None,
) -> tuple[str, str]:
    """Generate a single hypothetical policy passage to bridge query-to-handbook vocabulary mismatch."""
    if hyde_generator is not None:
        return hyde_generator(query).strip(), "custom_hyde_generator"

    active_cfg = cfg or AppConfig.load("config.yaml")
    messages = [
        {
            "role": "system",
            "content": (
                "Write one concise (3-4 sentence) hypothetical Alderwood University policy handbook excerpt "
                "that would directly answer the student's question using formal registrar/grant policy terminology "
                "(e.g., submission window, faculty mentor sponsorship, cumulative_gpa, not stackable, ISS CPT)."
            ),
        },
        {"role": "user", "content": query},
    ]
    try:
        res = llm("fast", messages, cfg=active_cfg)
        if res.content.strip():
            return res.content.strip(), f"llm_fast:{res.model}"
    except Exception:
        pass

    return _offline_hyde_expand(query), "offline_handbook_expander"


def grade_passages_crag(
    query: str,
    passages: list[Passage],
    *,
    cfg: AppConfig | None = None,
    crag_grader: CragGraderFn | None = None,
    min_relevance_score: float = 0.12,
) -> tuple[list[Passage], list[dict[str, str]], str]:
    """Evaluate retrieved passages via CRAG (relevant | ambiguous | irrelevant) and filter irrelevant ones."""
    if not passages:
        return [], [], "empty"

    if crag_grader is not None:
        raw_grades = crag_grader(query, passages)
        backend = "custom_crag_grader"
    else:
        raw_grades = []
        backend = ""
        active_cfg = cfg or AppConfig.load("config.yaml")
        # Attempt fast-tier CRAG grading when GEMINI_API_KEY is available
        try:
            items_txt = "\n\n".join(
                f"[{p.chunk_id}] ({p.doc_id} {p.version}): {p.text}" for p in passages
            )
            messages = [
                {
                    "role": "system",
                    "content": (
                        "Grade each passage for answering the user query as 'relevant', 'ambiguous', or 'irrelevant'. "
                        "Return JSON array 'grades'."
                    ),
                },
                {"role": "user", "content": f"Query: {query}\n\nPassages:\n{items_txt}"},
            ]
            res = llm("fast", messages, schema=_CRAG_SCHEMA, cfg=active_cfg)
            if isinstance(res.parsed, dict) and isinstance(res.parsed.get("grades"), list):
                raw_grades = res.parsed["grades"]
                backend = f"llm_fast:{res.model}"
        except Exception:
            raw_grades = []

        if not raw_grades:
            backend = "offline_crag_rubric"
            q_terms = {
                t
                for t in re.findall(r"[a-z0-9_-]{3,}", query.lower())
                if t not in {"what", "when", "which", "does", "how", "are", "the", "and", "for", "with", "about", "that", "this"}
            }
            for p in passages:
                p_low = p.text.lower()
                term_hits = sum(1 for t in q_terms if t in p_low)
                if p.rerank_score >= 0.35 or (p.rerank_score >= min_relevance_score and term_hits >= 1):
                    grade = "relevant" if (p.rerank_score >= 0.42 or term_hits >= 2) else "ambiguous"
                    reason = f"score={p.rerank_score:.3f}, term_hits={term_hits}"
                elif p.rrf_score >= 0.025 and term_hits >= 1:
                    grade = "ambiguous"
                    reason = f"rrf={p.rrf_score:.4f}, term_hits={term_hits}"
                else:
                    grade = "irrelevant"
                    reason = f"low_overlap(score={p.rerank_score:.3f}, term_hits={term_hits})"
                raw_grades.append({"chunk_id": p.chunk_id, "grade": grade, "reason": reason})

    grade_by_id = {str(g.get("chunk_id", "")): g for g in raw_grades}
    kept: list[Passage] = []
    trace_grades: list[dict[str, str]] = []

    for p in passages:
        g = grade_by_id.get(p.chunk_id, {"grade": "ambiguous", "reason": "ungraded_default"})
        grade_val = str(g.get("grade", "ambiguous")).lower()
        if grade_val not in ("relevant", "ambiguous", "irrelevant"):
            grade_val = "ambiguous"
        updated = Passage(
            text=p.text,
            doc_id=p.doc_id,
            version=p.version,
            page=p.page,
            citation=p.citation,
            chunk_id=p.chunk_id,
            chunk_type=p.chunk_type,
            grant_id=p.grant_id,
            dept_code=p.dept_code,
            effective_date=p.effective_date,
            structured_table_json=p.structured_table_json,
            injection_flagged=p.injection_flagged,
            vector_rank=p.vector_rank,
            fts_rank=p.fts_rank,
            rrf_score=p.rrf_score,
            rerank_score=p.rerank_score,
            crag_grade=grade_val,
        )
        trace_grades.append(
            {
                "chunk_id": p.chunk_id,
                "doc_id": p.doc_id,
                "grade": grade_val,
                "reason": str(g.get("reason", "")),
            }
        )
        if grade_val != "irrelevant":
            kept.append(updated)

    return kept, trace_grades, backend
