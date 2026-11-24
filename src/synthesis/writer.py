"""Phase 6 Structured JSON Claims Writer and Deterministic Markdown Renderer."""
from __future__ import annotations

import os
import re
from typing import Any, Callable

from src.config import AppConfig
from src.llm.client import llm
from src.synthesis.models import (
    Claim,
    ClaimSection,
    ConflictNotice,
    DeadlineNotice,
    SourceRegistry,
    VerificationResult,
)

WriterFn = Callable[[list[dict[str, str]], dict[str, Any]], dict[str, Any]]

WRITER_CLAIMS_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "claims": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "entity": {"type": "STRING"},
                    "field": {"type": "STRING"},
                    "value": {"type": "STRING"},
                    "source_id": {"type": "STRING"},
                    "claim_type": {"type": "STRING", "enum": ["sql", "policy"]},
                    "section": {
                        "type": "STRING",
                        "enum": ["meets_hard_criteria", "still_verify", "conflict", "expired"],
                    },
                    "citation": {"type": "STRING"},
                },
                "required": ["entity", "field", "value", "source_id", "claim_type", "section"],
            },
        }
    },
    "required": ["claims"],
}

_POLICY_SENTENCE_KEYWORDS = re.compile(
    r"(not\s+stackable|no\s+longer\s+stackable|faculty\s+mentor|signed\s+endorsement|"
    r"submission\s+window|cleanroom|safety\s+clearance|safety\s+training|ibc\s+or\s+irb|"
    r"iss\s+cpt|20\s+hours|cumulative_gpa|semester\s+gpa|overdue\s+balance|discontinued|"
    r"closed\s+june|advisor\s+sign-off|paper\s+acceptance|24\s+hours|2-hour\s+blocks|"
    r"two\s+faculty\s+co-mentors|probation_watch|orientation\s+workshop|amendment\s+2026-b)",
    flags=re.IGNORECASE,
)


def _split_sentences(text: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    return [p.strip() for p in parts if len(p.strip()) >= 12]


def build_grounded_claims_from_sources(
    state: dict[str, Any],
    registry: SourceRegistry,
    *,
    conflicts: list[ConflictNotice],
    deadline_notices: list[DeadlineNotice],
    current_date: str,
) -> list[Claim]:
    """Deterministically build verified JSON claims strictly anchored to SourceRegistry rows & passages."""
    claims: list[Claim] = []
    id_check = state.get("identity_check") or {}
    profile = id_check.get("profile") if isinstance(id_check, dict) else None
    expired_gids = {d.entity for d in deadline_notices if d.status == "expired"}
    conflict_gids = {c.entity for c in conflicts}

    # 1. Identity profile claims (when SQL or hybrid query uses student profile)
    if isinstance(profile, dict) and profile.get("student_id"):
        sid = str(profile["student_id"])
        id_src = f"sql:identity:{sid}"
        if id_src in registry.sql_rows:
            name = str(profile.get("full_name") or sid)
            claims.append(
                Claim(
                    entity=name,
                    field="cumulative_gpa",
                    value=profile["cumulative_gpa"],
                    source_id=id_src,
                    claim_type="sql",
                    section="meets_hard_criteria",
                )
            )
            claims.append(
                Claim(
                    entity=name,
                    field="year_of_study",
                    value=profile["year_of_study"],
                    source_id=id_src,
                    claim_type="sql",
                    section="meets_hard_criteria",
                )
            )
            claims.append(
                Claim(
                    entity=name,
                    field="dept_code",
                    value=profile["dept_code"],
                    source_id=id_src,
                    claim_type="sql",
                    section="meets_hard_criteria",
                )
            )

    # 2. SQL result row claims
    for src_id, row in registry.sql_rows.items():
        if src_id.startswith("sql:identity:"):
            continue

        if "grant_id" in row:
            gid = str(row["grant_id"])
            is_expired = gid in expired_gids or (
                bool(row.get("deadline")) and str(row.get("deadline")) < current_date
            )
            gpa_ok = True
            year_ok = True
            if isinstance(profile, dict):
                if row.get("min_gpa") is not None and profile.get("cumulative_gpa") is not None:
                    gpa_ok = float(profile["cumulative_gpa"]) >= float(row["min_gpa"])
                if row.get("min_year") is not None and row.get("max_year") is not None and profile.get("year_of_study") is not None:
                    yr = int(profile["year_of_study"])
                    year_ok = int(row["min_year"]) <= yr <= int(row["max_year"])

            row_section: ClaimSection = (
                "expired"
                if is_expired
                else ("meets_hard_criteria" if (gpa_ok and year_ok) else "still_verify")
            )

            for col in ("grant_name", "min_gpa", "award_amount", "deadline", "status"):
                if col in row and row[col] is not None:
                    sec: ClaimSection = (
                        "conflict"
                        if (col == "deadline" and gid in conflict_gids)
                        else row_section
                    )
                    claims.append(
                        Claim(
                            entity=gid,
                            field=col,
                            value=row[col],
                            source_id=src_id,
                            claim_type="sql",
                            section=sec,
                        )
                    )
            if "unpaid_balance" in row and row["unpaid_balance"] is not None:
                bal = float(row["unpaid_balance"])
                claims.append(
                    Claim(
                        entity=gid,
                        field="unpaid_balance",
                        value=row["unpaid_balance"],
                        source_id=src_id,
                        claim_type="sql",
                        section="still_verify" if bal > 0 else "meets_hard_criteria",
                    )
                )
        else:
            # Generic relational row (courses, timetable, mentors, fee_ledger, etc.)
            entity = str(
                row.get("faculty_name")
                or row.get("course_id")
                or row.get("ledger_id")
                or row.get("waiver_id")
                or row.get("lab_id")
                or row.get("full_name")
                or row.get("student_id")
                or "aggregate"
            )
            count_added = 0
            for k, v in row.items():
                if v is None or k in ("student_id", "full_name") and entity != str(v):
                    continue
                claims.append(
                    Claim(
                        entity=entity,
                        field=k,
                        value=v,
                        source_id=src_id,
                        claim_type="sql",
                        section="meets_hard_criteria",
                    )
                )
                count_added += 1
                if count_added >= 5:
                    break

    # 3. Document passage policy claims (capped neatly to top relevant sentences per passage)
    for doc_src_id, passage in registry.doc_passages.items():
        citation = str(passage.get("citation") or f"[{passage.get('doc_id')} {passage.get('version')}]")
        entity = str(passage.get("grant_id") or passage.get("doc_id") or "University Policy")
        text = str(passage.get("text") or "")

        # Prefer structured table rows if chunk_type == 'table'
        tbl = passage.get("structured_table_json")
        if passage.get("chunk_type") == "table" and isinstance(tbl, dict) and tbl.get("rows"):
            for r in (tbl.get("rows") or [])[:3]:
                if isinstance(r, dict):
                    summary_val = " | ".join(f"{k}: {v}" for k, v in r.items())
                    claims.append(
                        Claim(
                            entity=entity,
                            field="matrix_policy_row",
                            value=summary_val,
                            source_id=doc_src_id,
                            claim_type="policy",
                            section="still_verify",
                            citation=citation,
                        )
                    )
            continue

        sentences = _split_sentences(text)
        picked: list[str] = [s for s in sentences if _POLICY_SENTENCE_KEYWORDS.search(s)]
        if not picked and sentences:
            picked = sentences[:1]

        for s in picked[:2]:
            sec_pol: ClaimSection = "still_verify"
            if entity in conflict_gids and re.search(r"(December 1, 2026|submission window|Amendment 2026-B)", s, re.IGNORECASE):
                sec_pol = "conflict"
            elif entity in expired_gids and re.search(r"(discontinued|closed June 30, 2026)", s, re.IGNORECASE):
                sec_pol = "expired"
            claims.append(
                Claim(
                    entity=entity,
                    field="policy_rule",
                    value=s,
                    source_id=doc_src_id,
                    claim_type="policy",
                    section=sec_pol,
                    citation=citation,
                )
            )

    return claims


def generate_claims_with_writer(
    state: dict[str, Any],
    registry: SourceRegistry,
    *,
    cfg: AppConfig,
    conflicts: list[ConflictNotice],
    deadline_notices: list[DeadlineNotice],
    writer_fn: WriterFn | None = None,
    previous_errors: list[str] | None = None,
) -> tuple[list[Claim], str]:
    """Generate structured JSON claims via custom writer / STRONG_MODEL LLM or deterministic builder."""
    query = str(state.get("query") or "")
    # Build explicit source bundle prompt for STRONG_MODEL JSON writer (or unit-test writer_fn)
    sql_lines = [
        f"- source_id={sid}: {row}" for sid, row in registry.sql_rows.items()
    ]
    doc_lines = [
        f"- source_id={sid}, citation={p.get('citation')}: {p.get('text')}"
        for sid, p in registry.doc_passages.items()
    ]
    error_feedback = ""
    if previous_errors:
        error_feedback = (
            "\n\nPREVIOUS ATTEMPT FAILED VERIFICATION WITH THESE ERRORS:\n"
            + "\n".join(f"- {e}" for e in previous_errors)
            + "\nFix every claim so its value strictly matches ONLY its own source_id row/passage."
        )

    messages = [
        {
            "role": "system",
            "content": (
                "You are the Alderwood University Hybrid RAG Claim Writer.\n"
                "Output STRICT JSON matching the schema with structured claims: "
                "{entity, field, value, source_id, claim_type, section, citation}.\n"
                "Rules:\n"
                "1. Every claim value MUST appear verbatim or numerically inside its OWN cited source_id.\n"
                "2. Every policy claim MUST include the exact handbook citation.\n"
                "3. Categorize hard DB facts/eligibility thresholds under 'meets_hard_criteria', "
                "and soft rules/mentor/IRB/visa/stacking/Gaps under 'still_verify' (or 'conflict'/'expired').\n"
                "4. NEVER output a flat 'you are eligible' or 'you're eligible' verdict."
                "5. Use human names in entity fields: student full name, grant name, course name, or policy topic. "
                "Never use source IDs such as 'sql:row:0' as the entity."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Question: {query}\n"
                f"Reference Date: {cfg.current_date}\n\n"
                f"SQL Sources:\n" + ("\n".join(sql_lines) if sql_lines else "(none)") + "\n\n"
                f"Document Sources:\n" + ("\n".join(doc_lines) if doc_lines else "(none)")
                + error_feedback
            ),
        },
    ]

    raw_payload: dict[str, Any] | None = None
    backend = "custom_writer"
    if writer_fn is not None:
        raw_payload = writer_fn(messages, WRITER_CLAIMS_SCHEMA)
    else:
        try:
            res = llm("strong", messages, schema=WRITER_CLAIMS_SCHEMA, cfg=cfg)
            if isinstance(res.parsed, dict):
                raw_payload = res.parsed
                backend = f"llm_strong:{res.model}"
        except Exception:
            raw_payload = None

    if not raw_payload or not isinstance(raw_payload.get("claims"), list):
        raise RuntimeError("Synthesis LLM returned no valid JSON claims")

    parsed_claims: list[Claim] = []
    for item in raw_payload["claims"]:
        if not isinstance(item, dict):
            continue
        ctype = "policy" if item.get("claim_type") == "policy" else "sql"
        sec_raw = str(item.get("section") or "meets_hard_criteria")
        sec: ClaimSection = (
            sec_raw
            if sec_raw in ("meets_hard_criteria", "still_verify", "conflict", "expired")
            else "meets_hard_criteria"
        )  # type: ignore[assignment]
        parsed_claims.append(
            Claim(
                entity=str(item.get("entity") or ""),
                field=str(item.get("field") or ""),
                value=item.get("value"),
                source_id=str(item.get("source_id") or ""),
                claim_type=ctype,  # type: ignore[arg-type]
                section=sec,
                citation=item.get("citation"),
            )
        )
    return parsed_claims, backend


def render_answer_from_claims(
    claims: list[Claim],
    *,
    state: dict[str, Any],
    conflicts: list[ConflictNotice],
    deadline_notices: list[DeadlineNotice],
    missing_evidence_notices: list[str],
    verification: VerificationResult,
    warnings: list[str],
) -> str:
    """Render user-facing Markdown answer strictly from structured claims and verification notices."""
    lines: list[str] = []
    id_check = state.get("identity_check") or {}
    plan = state.get("plan") or {}
    status_notice = state.get("status_notice")

    if warnings:
        lines.append("> **Verification Warning:** " + " ".join(warnings))
        lines.append("")

    if id_check.get("flagged") and id_check.get("warning_message"):
        lines.append(f"> **Identity Notice:** {id_check['warning_message']}")
        lines.append("")

    if plan.get("route") == "out_of_scope":
        lines.append("## Out of Scope")
        lines.append(
            str(
                status_notice
                or "This request falls outside verified Alderwood University academic, grant, and policy advising."
            )
        )
        lines.append("")
        lines.append("## Meets hard criteria")
        lines.append("- None (request declined prior to data retrieval).")
        lines.append("")
        lines.append("## Still verify")
        lines.append("- Submit an academic, grant eligibility, fee, or campus policy question instead.")
        return "\n".join(lines)

    if status_notice == "no matching records":
        lines.append("## Meets hard criteria")
        lines.append("- **Status:** No matching records found in the university database.")
        lines.append("")
        lines.append("## Still verify")
        for msg in missing_evidence_notices:
            lines.append(f"- {msg}")
        return "\n".join(lines)

    meets = [c for c in claims if c.section == "meets_hard_criteria"]
    verify = [c for c in claims if c.section in ("still_verify", "conflict", "expired")]

    sql_res = state.get("sql_result") or {}
    sql_rows = sql_res.get("rows") or []
    grant_rows = [row for row in sql_rows if isinstance(row, dict) and row.get("grant_id")]
    profile = (id_check.get("profile") or {}) if isinstance(id_check, dict) else {}
    query_low = str(state.get("query") or "").lower()

    if grant_rows and ("grant" in query_low or "fellowship" in query_low or "fund" in query_low):
        if profile:
            student_gpa = float(profile.get("cumulative_gpa") or 0)
            student_year = int(profile.get("year_of_study") or 0)
            student_dept = str(profile.get("dept_code") or "")
            filtered_grant_rows = []
            for row in grant_rows:
                if str(row.get("status") or "").lower() != "open":
                    continue
                dept = str(row.get("dept_code") or "")
                if dept not in ("ALL", student_dept):
                    continue
                try:
                    min_gpa = float(row.get("min_gpa") or 0)
                    min_year = int(row.get("min_year") or 0)
                    max_year = int(row.get("max_year") or 99)
                except (TypeError, ValueError):
                    continue
                if student_gpa >= min_gpa and min_year <= student_year <= max_year:
                    filtered_grant_rows.append(row)
            grant_rows = filtered_grant_rows

        name = str(profile.get("full_name") or "the student")
        gpa = float(profile.get("cumulative_gpa") or 0)
        year = int(profile.get("year_of_study") or 0)
        dept = str(profile.get("dept_code") or "your department")
        if not grant_rows:
            lines.append(
                f"{name} does not currently match any open research grants in the database. "
                f"Based on the available records, {name} is in Year {year} in {dept}, with a cumulative GPA of {gpa:.2f}, "
                "and no listed grant satisfies the department, GPA, year, and deadline requirements."
            )
        else:
            names_and_details: list[str] = []
            for row in grant_rows:
                grant_name = str(row.get("grant_name") or row.get("grant_id") or "Unnamed grant")
                amount = row.get("award_amount")
                deadline = row.get("deadline")
                description = grant_name
                if amount is not None:
                    description += f" (${float(amount):,.2f})"
                if deadline is not None:
                    description += f", with a database deadline of {deadline}"
                names_and_details.append(description)
            joined = "; ".join(names_and_details[:-1])
            if names_and_details:
                joined += ("; and " if joined else "") + names_and_details[-1]
            lines.append(
                f"Based on the university database, {name} is a numerical match for the following open research grants: "
                f"{joined}."
            )
            lines.append(
                f"{name}'s profile is Year {year}, {dept}, with a cumulative GPA of {gpa:.2f}. "
                "These matches are based on the database criteria; handbook requirements such as mentor approval, "
                "proposal content, or application timing may still need to be checked."
            )
    else:
        lines.append("## Key result")
        if meets:
            for c in meets:
                cit = f" {c.citation}" if c.citation else ""
                entity = c.entity if c.entity not in ("sql:row:" + str(i) for i in range(100)) else "Database result"
                lines.append(
                    f"- **{entity}:** {c.value}"
                    f" *(source: `{c.source_id}`{cit})*"
                )
        else:
            lines.append("- No directly grounded numeric/database result was returned.")

        if verify:
            lines.append("")
            lines.append("## Needs verification")
            for c in verify:
                cit = f" {c.citation}" if c.citation else ""
                lines.append(
                    f"- **{c.entity}:** {c.value}"
                    f" *(source: `{c.source_id}`{cit})*"
                )

    for conf in conflicts:
        lines.append(f"- **DB vs. PDF Conflict:** {conf.summary}")
    for dl in deadline_notices:
        lines.append(f"- **Deadline Passed:** {dl.summary}")
    for miss in missing_evidence_notices:
        lines.append(f"- **Missing Evidence / Prerequisite:** {miss}")

    if not verify and not conflicts and not deadline_notices and not missing_evidence_notices:
        if not (grant_rows and ("grant" in query_low or "fellowship" in query_low or "fund" in query_low)):
            lines.append("- Confirm final enrollment and advisor records at submission time.")

    if not verification.passed:
        lines.append("")
        lines.append(
            "> **Verification notice:** This answer may contain unverified claim details. "
            "Use the evidence trace before acting."
        )

    return "\n".join(lines)
