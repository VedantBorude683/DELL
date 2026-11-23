"""Data models for Phase 4 Document Branch: Passage[], MetadataFilter, and DocumentSearchResult."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MetadataFilter:
    """Metadata constraints applied prior to hybrid vector + FTS fusion."""

    grant_ids: tuple[str, ...] = ()
    doc_ids: tuple[str, ...] = ()
    version: str | None = None
    dept_code: str | None = None
    year_scope: str | None = None
    exclude_title_banners: bool = False


@dataclass(frozen=True)
class Passage:
    """Retrieved handbook passage with provenance and scoring metadata."""

    text: str
    doc_id: str
    version: str
    page: int
    citation: str
    chunk_id: str = ""
    chunk_type: str = "prose"
    grant_id: str | None = None
    dept_code: str | None = None
    effective_date: str = ""
    structured_table_json: dict[str, Any] | None = None
    injection_flagged: bool = False
    vector_rank: int | None = None
    fts_rank: int | None = None
    rrf_score: float = 0.0
    rerank_score: float = 0.0
    crag_grade: str = "not_run"

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "doc_id": self.doc_id,
            "version": self.version,
            "page": self.page,
            "citation": self.citation,
            "chunk_id": self.chunk_id,
            "chunk_type": self.chunk_type,
            "grant_id": self.grant_id,
            "dept_code": self.dept_code,
            "effective_date": self.effective_date,
            "structured_table_json": self.structured_table_json,
            "injection_flagged": self.injection_flagged,
            "vector_rank": self.vector_rank,
            "fts_rank": self.fts_rank,
            "rrf_score": self.rrf_score,
            "rerank_score": self.rerank_score,
            "crag_grade": self.crag_grade,
        }


@dataclass(frozen=True)
class DocumentSearchResult:
    """Output bundle containing Passage[] plus hybrid/rerank/HyDE/CRAG execution trace."""

    passages: list[Passage]
    trace: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passages": [p.to_dict() for p in self.passages],
            "trace": self.trace,
        }
