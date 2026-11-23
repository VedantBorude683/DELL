"""Entity linker matching PDF chunks to grant_id, dept_code, and year_scope."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Sequence

from src.llm.client import llm

GRANT_CATALOG: tuple[dict[str, str], ...] = (
    {
        "grant_id": "GR-CS-01",
        "grant_name": "Turing Undergraduate Research Fellowship",
        "aliases": "turing fellowship,turing undergraduate research fellowship",
        "dept_code": "CS",
        "year_scope": "2-4",
    },
    {
        "grant_id": "GR-CS-02",
        "grant_name": "Alderwood AI Systems Innovation Stipend",
        "aliases": "ai systems innovation stipend,alderwood ai systems",
        "dept_code": "CS",
        "year_scope": "3-4",
    },
    {
        "grant_id": "GR-CS-03",
        "grant_name": "First-Year Computing Discovery Award",
        "aliases": "first-year computing discovery award",
        "dept_code": "CS",
        "year_scope": "1-2",
    },
    {
        "grant_id": "GR-ECE-01",
        "grant_name": "Maxwell Hardware Prototyping Grant",
        "aliases": "maxwell hardware prototyping grant",
        "dept_code": "ECE",
        "year_scope": "2-4",
    },
    {
        "grant_id": "GR-BIO-01",
        "grant_name": "Franklin Genomics Fieldwork Grant",
        "aliases": "franklin genomics fieldwork grant",
        "dept_code": "BIO",
        "year_scope": "2-4",
    },
    {
        "grant_id": "GR-ME-01",
        "grant_name": "Watt Sustainable Robotics Fellowship",
        "aliases": "watt sustainable robotics fellowship",
        "dept_code": "ME",
        "year_scope": "3-4",
    },
    {
        "grant_id": "GR-GEN-01",
        "grant_name": "Provost Cross-Disciplinary Research Grant",
        "aliases": "provost cross-disciplinary research grant,provost cross-disciplinary grant",
        "dept_code": "ALL",
        "year_scope": "2-4",
    },
    {
        "grant_id": "GR-GEN-02",
        "grant_name": "Alderwood Student Conference Travel Fund",
        "aliases": "conference travel fund,alderwood student conference travel fund",
        "dept_code": "ALL",
        "year_scope": "1-4",
    },
    {
        "grant_id": "GR-GEN-04",
        "grant_name": "Summer 2026 Heritage Innovation Grant",
        "aliases": "heritage innovation grant,summer 2026 heritage innovation grant",
        "dept_code": "ALL",
        "year_scope": "2-4",
    },
)

_GRANT_ID_RE = re.compile(r"\bGR-(?:CS|ECE|BIO|ME|GEN)-\d{2}\b")


@dataclass(frozen=True)
class EntityLinkResult:
    grant_ids: tuple[str, ...]
    primary_grant_id: str | None
    dept_code: str | None
    year_scope: str | None
    method: str  # "id_or_name" | "llm_fallback" | "none"


def _infer_dept(text: str, matched_grants: Sequence[dict[str, str]], doc_grant_ids: Sequence[str]) -> str | None:
    if matched_grants:
        depts = {g["dept_code"] for g in matched_grants}
        if len(depts) == 1:
            return next(iter(depts))
    low = text.lower()
    if "computer science" in low or "cs-" in low or "cs " in low:
        return "CS"
    if "electrical" in low or "ece" in low or "maxwell" in low:
        return "ECE"
    if "biological" in low or "genomics" in low or "bio-" in low:
        return "BIO"
    if "mechanical" in low or "watt" in low:
        return "ME"
    if "economics" in low or "econ" in low:
        return "ECON"
    if "international" in low or "f-1" in low or "visa" in low:
        return "ALL"
    if doc_grant_ids:
        return "ALL"
    return None


def _infer_year_scope(text: str, matched_grants: Sequence[dict[str, str]]) -> str | None:
    low = text.lower()
    m = re.search(r"years?\s+(\d)\s+through\s+(\d)", low)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    if "third- and fourth-year" in low or "3rd-year" in low:
        return "3-4"
    if "first-year" in low:
        return "1-2"
    if matched_grants:
        return matched_grants[0]["year_scope"]
    return None


def link_chunk_entities(
    text: str,
    *,
    doc_grant_ids: Sequence[str] = (),
    use_llm_fallback: bool = True,
) -> EntityLinkResult:
    """Match chunk text to grant_id(s) via ID/name matching first, then LLM fallback if needed."""
    matched_ids: list[str] = []

    # Stage 1a: Explicit grant IDs (GR-*)
    for gid in _GRANT_ID_RE.findall(text):
        if gid not in matched_ids:
            matched_ids.append(gid)

    # Stage 1b: Exact/alias grant name matching
    low = " ".join(text.lower().split())
    for entry in GRANT_CATALOG:
        aliases = [a.strip() for a in entry["aliases"].split(",") if a.strip()]
        if entry["grant_name"].lower() in low or any(a in low for a in aliases):
            if entry["grant_id"] not in matched_ids:
                matched_ids.append(entry["grant_id"])

    method = "id_or_name" if matched_ids else "none"

    # Stage 2: LLM fallback only if chunk appears grant-related, no deterministic match, and key is set
    looks_grant_related = any(
        kw in low for kw in ("fellowship", "stipend", "research grant", "travel fund", "award")
    )
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not matched_ids and looks_grant_related and use_llm_fallback and api_key and api_key != "MY_GEMINI_API_KEY":
        try:
            catalog_lines = "\n".join(f"- {g['grant_id']}: {g['grant_name']}" for g in GRANT_CATALOG)
            resp = llm(
                "fast",
                [
                    {
                        "role": "system",
                        "content": "Match the handbook excerpt to one grant_id from the catalog or return null.",
                    },
                    {
                        "role": "user",
                        "content": f"Catalog:\n{catalog_lines}\n\nExcerpt:\n{text[:900]}",
                    },
                ],
                schema={
                    "type": "OBJECT",
                    "properties": {"grant_id": {"type": "STRING", "nullable": True}},
                    "required": ["grant_id"],
                },
            )
            if isinstance(resp.parsed, dict) and resp.parsed.get("grant_id"):
                gid = str(resp.parsed["grant_id"])
                if any(g["grant_id"] == gid for g in GRANT_CATALOG):
                    matched_ids.append(gid)
                    method = "llm_fallback"
        except Exception:
            pass

    matched_entries = [g for g in GRANT_CATALOG if g["grant_id"] in matched_ids]
    dept_code = _infer_dept(text, matched_entries, doc_grant_ids)
    year_scope = _infer_year_scope(text, matched_entries)

    return EntityLinkResult(
        grant_ids=tuple(matched_ids),
        primary_grant_id=matched_ids[0] if matched_ids else None,
        dept_code=dept_code,
        year_scope=year_scope,
        method=method,
    )
