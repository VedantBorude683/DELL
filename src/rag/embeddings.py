"""BGE-M3 embedding engine with deterministic 1024-dim semantic projection fallback.

Uses `BAAI/bge-m3` via `sentence_transformers` when available in the runtime
environment, and falls back cleanly to a deterministic 1024-dim multi-scale
lexical + domain-synonym hash encoder in dependency-minimal sandboxes.
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import Sequence
from functools import lru_cache

EMBEDDING_DIM = 1024

_DOMAIN_SYNONYMS: dict[str, tuple[str, ...]] = {
    "deadline": ("submission", "window", "closes", "due", "date", "grants"),
    "submission": ("deadline", "window", "apply", "grants"),
    "window": ("deadline", "submission", "closes"),
    "gpa": ("cumulative_gpa", "semester_gpa", "grade", "students", "min_gpa", "deans_list"),
    "cumulative": ("cumulative_gpa", "overall", "students"),
    "semester": ("semester_gpa", "term", "student_semester_gpas", "deans_list"),
    "owe": ("fee_ledger", "amount_due", "amount_paid", "unpaid", "balance", "tuition"),
    "balance": ("fee_ledger", "amount_due", "amount_paid", "unpaid", "overdue"),
    "tuition": ("fee_ledger", "fees", "base_tuition", "amount_due"),
    "waiver": ("fee_waivers", "waiver_amount", "waiver_type"),
    "grant": ("grants", "fellowship", "stipend", "award", "grant_id"),
    "grants": ("grant", "fellowship", "stipend", "award", "min_gpa", "min_year"),
    "fellowship": ("grants", "grant_name", "award_amount"),
    "stipend": ("grants", "award_amount", "student_awards"),
    "mentor": ("faculty_mentors", "accepting_undergrads", "advisor", "advisor_name"),
    "mentors": ("faculty_mentors", "accepting_undergrads", "office_room"),
    "advisor": ("students", "advisor_name", "faculty_mentors"),
    "office": ("faculty_mentors", "office_room"),
    "schedule": ("timetable", "start_time", "end_time", "day_of_week", "room"),
    "timetable": ("timetable", "courses", "enrollments", "room", "building"),
    "class": ("timetable", "courses", "enrollments", "room"),
    "classes": ("timetable", "courses", "enrollments"),
    "taking": ("enrollments", "courses", "timetable"),
    "enrolled": ("enrollments", "courses"),
    "course": ("courses", "course_id", "course_level", "credits"),
    "courses": ("courses", "enrollments", "timetable"),
    "lab": ("research_labs", "safety_clearance_required", "lab_fee"),
    "labs": ("research_labs", "safety_clearance_required"),
    "safety": ("research_labs", "safety_clearance_required"),
    "clearance": ("research_labs", "safety_clearance_required"),
    "exam": ("academic_calendar", "event_date", "event_name"),
    "exams": ("academic_calendar", "event_date", "event_name"),
    "calendar": ("academic_calendar", "event_date"),
    "discontinued": ("scholarships_archive", "legacy_code", "discontinued_year"),
    "legacy": ("scholarships_archive", "legacy_code"),
    "archived": ("grant_history", "scholarships_archive", "archived_deadline"),
    "history": ("grant_history", "fiscal_year", "total_disbursed"),
    "disbursed": ("grant_history", "total_disbursed", "recipients_count"),
    "applications": ("grant_applications", "application_id", "decision_status"),
    "applied": ("grant_applications", "submitted_at"),
    "reviewer": ("grant_reviewers", "review_round"),
    "reviewers": ("grant_reviewers", "faculty_name", "review_round"),
    "department": ("departments", "dept_code", "dept_name", "annual_grant_pool"),
    "departments": ("departments", "annual_grant_pool", "dean_name"),
    "pool": ("departments", "annual_grant_pool"),
    "dean": ("student_semester_gpas", "deans_list_flag", "departments", "dean_name"),
    "award": ("grants", "student_awards", "award_amount"),
    "awards": ("student_awards", "grants"),
    "standing": ("students", "year_of_study", "enrollment_status", "cumulative_gpa"),
    "probation": ("students", "enrollment_status", "student_semester_gpas"),
    "year": ("students", "year_of_study", "min_year", "max_year"),
}

_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "in", "on", "at", "for", "to",
    "of", "and", "or", "my", "me", "i", "am", "im", "what", "which", "who", "when",
    "how", "do", "does", "did", "can", "could", "still", "this", "that", "it",
    "its", "with", "from", "by", "about", "as", "be", "have", "has", "if",
}


def _tokenize(text: str) -> list[str]:
    raw_tokens = re.findall(r"[a-z0-9_]+", text.lower())
    expanded: list[str] = []
    for tok in raw_tokens:
        if tok in _STOPWORDS and len(tok) <= 3:
            continue
        expanded.append(tok)
        if "_" in tok:
            expanded.extend(part for part in tok.split("_") if part)
        for syn in _DOMAIN_SYNONYMS.get(tok, ()):
            expanded.append(syn)
    return expanded


def _signed_hash_index(feature: str, dim: int = EMBEDDING_DIM) -> tuple[int, float]:
    digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
    val = int.from_bytes(digest, "little")
    idx = val % dim
    sign = 1.0 if ((val >> 1) & 1) == 0 else -1.0
    return idx, sign


def _encode_fallback(text: str, dim: int = EMBEDDING_DIM) -> list[float]:
    vec = [0.0] * dim
    tokens = _tokenize(text)
    if not tokens:
        return vec

    # Unigrams (weight 1.0) + exact identifier tokens (weight 1.6)
    for tok in tokens:
        weight = 1.6 if ("_" in tok or "-" in tok or any(c.isdigit() for c in tok)) else 1.0
        idx, sign = _signed_hash_index(f"u:{tok}", dim)
        vec[idx] += sign * weight

    # Word bigrams (weight 0.7)
    for i in range(len(tokens) - 1):
        idx, sign = _signed_hash_index(f"b:{tokens[i]}_{tokens[i + 1]}", dim)
        vec[idx] += sign * 0.7

    # Character 4-grams on clean words for morphological robustness (weight 0.35)
    for word in re.findall(r"[a-z0-9_]{4,}", text.lower()):
        for i in range(len(word) - 3):
            idx, sign = _signed_hash_index(f"c:{word[i : i + 4]}", dim)
            vec[idx] += sign * 0.35

    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0.0:
        vec = [round(v / norm, 6) for v in vec]
    return vec


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class Embedder:
    """Local sentence-transformer embedder. No synthetic or fallback vectors."""

    def __init__(self, model_name: str = "BAAI/bge-m3", allow_download: bool = True) -> None:
        self.model_name = model_name
        self.backend_name = "not_loaded"
        self._st_model = None
        if not allow_download:
            raise RuntimeError("Local embeddings require sentence-transformers; allow_download=False is not supported")
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
            self._st_model = SentenceTransformer(model_name, device="cpu")
            self.backend_name = f"sentence_transformers:{model_name}"
        except Exception as exc:
            raise RuntimeError(
                f"Could not load local embedding model '{model_name}'. "
                "The model must be available locally or downloadable at startup."
            ) from exc

    def embed_one(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        if self._st_model is not None:
            arr = self._st_model.encode(list(texts), normalize_embeddings=True)
            return [row.tolist() for row in arr]
        return [_encode_fallback(t) for t in texts]


@lru_cache(maxsize=2)
def get_embedder(model_name: str = "BAAI/bge-m3") -> "Embedder":
    """Reuse one local embedding model across all chat turns."""
    return Embedder(model_name=model_name)
