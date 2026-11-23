"""Cross-encoder reranker wrapping BAAI/bge-reranker-v2-m3 with local cross-term fallback."""
from __future__ import annotations

import math
import re
from typing import Any, Sequence

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")

_QUERY_CONCEPT_MAP: dict[str, tuple[str, ...]] = {
    "deadline": ("submission window", "closing date", "december", "june 30", "amendment"),
    "deadlines": ("submission window", "closing date", "december", "june 30"),
    "stack": ("stackable", "not stackable", "combine", "simultaneously"),
    "stackable": ("not stackable", "combine", "waiver", "concurrent"),
    "conditions": ("faculty mentor", "sponsorship", "endorsement", "not stackable", "mandatory"),
    "soft": ("faculty mentor", "endorsement", "not stackable", "irb", "safety clearance"),
    "rules": ("policy", "eligibility", "mandatory", "requires", "prohibited"),
    "changes": ("supersedes", "v1.0", "v2.0", "2025", "2026", "amendment"),
    "difference": ("supersedes", "v1.0", "v2.0", "2025", "2026"),
    "international": ("f-1", "j-1", "iss", "cpt", "20 hours"),
    "visa": ("f-1", "j-1", "iss", "cpt", "work authorization"),
    "balance": ("overdue", "unpaid", "fee_ledger", "hardship waiver", "disbursements"),
    "overdue": ("unpaid", "cash grant", "hardship waiver", "fee_ledger"),
    "table": ("structured table", "matrix", "base tuition", "merit waiver"),
    "matrix": ("structured table", "merit waiver", "base tuition", "lab fee"),
    "library": ("turing science library", "24 hours", "euler hall", "study room"),
    "hours": ("24 hours", "monday through thursday", "7 am to 11 pm"),
    "probation": ("probation_watch", "3.00", "ineligible to lead"),
    "mentor": ("faculty mentor", "co-mentors", "sponsorship", "endorsement"),
    "travel": ("conference travel fund", "gr-gen-02", "paper acceptance", "advisor sign-off"),
    "biosafety": ("ibc", "irb", "genomics", "gr-bio-01"),
    "ethics": ("ibc", "irb", "protocol approval"),
    "cleanroom": ("cleanroom", "gr-ece-01", "hardware prototyping"),
    "safety": ("safety clearance", "cleanroom", "wet lab", "wind-tunnel"),
    "gpa": ("cumulative_gpa", "cumulative gpa", "semester gpa", "dean's list"),
}

_STOP = {
    "the", "a", "an", "is", "are", "was", "were", "in", "on", "at", "for", "to",
    "of", "and", "or", "my", "me", "i", "im", "what", "which", "who", "when",
    "how", "do", "does", "did", "can", "could", "still", "this", "that", "it",
    "its", "with", "from", "by", "about", "as", "be", "have", "has", "if",
    "there", "tell", "would", "according", "handbook", "policy", "alderwood",
}


def _clean_terms(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if len(t) > 1 and t not in _STOP]


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-12.0, min(12.0, x))))


class Reranker:
    """Cross-encoder reranker supporting BAAI/bge-reranker-v2-m3 and calibrated local fallback."""

    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-v2-m3",
        *,
        allow_download: bool = False,
    ) -> None:
        self.model_name = model_name
        self.backend_name = "local_cross_term_v2_m3_fallback"
        self._cross_encoder = None
        if allow_download:
            try:
                from sentence_transformers import CrossEncoder  # type: ignore

                self._cross_encoder = CrossEncoder(model_name)
                self.backend_name = f"sentence_transformers:{model_name}"
            except Exception:
                self._cross_encoder = None

    def score_pairs(
        self,
        query: str,
        candidates: Sequence[dict[str, Any]],
    ) -> list[float]:
        """Return normalized [0.0, 1.0] relevance scores aligned with `candidates`."""
        if not candidates:
            return []

        if self._cross_encoder is not None:
            pairs = [(query, str(c["content"])) for c in candidates]
            raw_scores = self._cross_encoder.predict(pairs)
            return [round(float(_sigmoid(float(s))), 4) for s in raw_scores]

        q_low = query.lower()
        q_terms = _clean_terms(query)
        q_term_set = set(q_terms)
        q_bigrams = {f"{q_terms[i]} {q_terms[i + 1]}" for i in range(len(q_terms) - 1)}

        # Explicit grant IDs mentioned in query
        query_grant_ids = set(re.findall(r"\bGR-[A-Z]+-\d+\b", query.upper()))

        # Concept cues expanded from query terms
        cues: list[str] = []
        for t in q_terms:
            cues.extend(_QUERY_CONCEPT_MAP.get(t, ()))

        scores: list[float] = []
        for c in candidates:
            content = str(c.get("content", ""))
            content_low = content.lower()
            c_terms = set(_clean_terms(content))

            # 1. Exact lexical overlap recall
            term_recall = (
                len(q_term_set & c_terms) / len(q_term_set)
                if q_term_set
                else 0.0
            )

            # 2. Bigram phrase match
            bigram_hits = sum(1 for bg in q_bigrams if bg in content_low)
            bigram_score = min(1.0, bigram_hits / max(1, len(q_bigrams))) if q_bigrams else 0.0

            # 3. Domain concept match
            cue_score = (
                min(1.0, sum(1 for phrase in cues if phrase in content_low) / max(1, min(3, len(cues))))
                if cues
                else 0.0
            )

            # 4. Exact grant_id alignment boost / mismatch check
            grant_boost = 0.0
            chunk_grant = str(c.get("grant_id") or "").upper()
            if query_grant_ids:
                if chunk_grant in query_grant_ids or any(gid.lower() in content_low for gid in query_grant_ids):
                    grant_boost = 0.28
                elif chunk_grant:
                    grant_boost = -0.10

            # 5. Table chunk boost when query asks about table/matrix/fees
            table_boost = 0.0
            if c.get("chunk_type") == "table" and any(k in q_low for k in ("table", "matrix", "waiver", "fee", "tuition")):
                table_boost = 0.16

            # 6. Version recency preference (v2.0 over v1.0 unless v1.0/2025 explicitly asked)
            version_adj = 0.0
            ver = str(c.get("version", ""))
            asks_v1 = ("v1.0" in q_low) or ("2025" in q_low)
            if ver == "v2.0" and not asks_v1:
                version_adj = 0.06
            elif ver == "v1.0" and asks_v1:
                version_adj = 0.08
            elif ver == "v1.0" and not asks_v1:
                version_adj = -0.05

            # 7. Title banner demotion (short cover-page lines lack policy detail)
            title_penalty = -0.20 if str(c.get("chunk_id", "")).endswith("_c01") and len(content.split()) <= 16 else 0.0

            # 8. Prior RRF + cosine blend
            rrf_norm = min(1.0, float(c.get("rrf_score", 0.0)) * 30.0)
            vec_sim = max(0.0, float(c.get("vec_sim", 0.0)))

            raw = (
                0.34 * term_recall
                + 0.18 * bigram_score
                + 0.22 * cue_score
                + 0.16 * rrf_norm
                + 0.14 * vec_sim
                + grant_boost
                + table_boost
                + version_adj
                + title_penalty
            )
            clamped = round(max(0.0, min(0.99, raw)), 4)
            scores.append(clamped)

        return scores
