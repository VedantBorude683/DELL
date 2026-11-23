"""Phase 6 Conflict Check (SQL vs PDF), Deadline-Passed Check, and Missing-Evidence Detector."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from src.synthesis.models import ConflictNotice, DeadlineNotice, SourceRegistry

_MONTH_DATE_RE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
    r"(\d{1,2}),\s*(\d{4})\b",
    flags=re.IGNORECASE,
)
_ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")

_SOFT_CONDITION_PATTERNS: tuple[tuple[str, str], ...] = (
    ("faculty mentor sponsorship", r"\b(?:needs|requires|mandatory)\s+.*?(?:faculty\s+(?:mentor|endorsement|sponsorship|co-mentors))"),
    ("signed advisor / mentor endorsement", r"\bsigned\s+(?:endorsement|advisor\s+sign-off)\b"),
    ("not stackable with other internal awards", r"\bnot\s+stackable\b|\bno\s+longer\s+stackable\b"),
    ("cleanroom / lab safety clearance", r"\b(?:cleanroom|wet\s+lab|wind-tunnel)\s+(?:lab\s+)?safety\s+(?:clearance|training|certification)\b"),
    ("IBC or IRB ethics approval", r"\bibc\s+or\s+irb\s+protocol\b"),
    ("ISS CPT / on-campus work authorization (> $2,000 stipends, 20h cap)", r"\biss\s+cpt\b|\bmax(?:imum)?\s+20\s+hours\b"),
    ("paper acceptance notice for travel funding", r"\bpaper\s+acceptance\s+notice\b"),
    ("overdue fee ledger balance block on cash disbursements", r"\boverdue\s+balance\b.*?\bcash\s+grant\s+disbursements\b"),
)


def _to_iso_date(raw_date: str) -> str | None:
    raw = raw_date.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return raw
    m = _MONTH_DATE_RE.search(raw)
    if m:
        try:
            dt = datetime.strptime(f"{m.group(1)} {int(m.group(2))} {m.group(3)}", "%B %d %Y")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            return None
    return None


def _extract_passage_deadlines(text: str) -> list[tuple[str, str]]:
    """Return list of (iso_date, original_display) found near deadline/window/closes phrases."""
    results: list[tuple[str, str]] = []
    for m in _MONTH_DATE_RE.finditer(text):
        disp = m.group(0)
        iso = _to_iso_date(disp)
        ctx = text[max(0, m.start() - 80) : min(len(text), m.end() + 40)].lower()
        if iso and any(k in ctx for k in ("window", "close", "deadline", "amendment", "due", "june 30")):
            results.append((iso, disp))
    for m in _ISO_DATE_RE.finditer(text):
        iso = m.group(1)
        ctx = text[max(0, m.start() - 80) : min(len(text), m.end() + 40)].lower()
        if any(k in ctx for k in ("window", "close", "deadline", "amendment", "due")):
            results.append((iso, iso))
    return list(dict.fromkeys(results))


def detect_sql_vs_pdf_conflicts(registry: SourceRegistry) -> list[ConflictNotice]:
    """Compare SQL grant deadlines against retrieved PDF handbook submission windows."""
    conflicts: list[ConflictNotice] = []
    seen_keys: set[tuple[str, str]] = set()

    # Collect latest-version passages per grant_id
    passages_by_grant: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for src_id, passage in registry.doc_passages.items():
        gid = passage.get("grant_id")
        if gid:
            passages_by_grant.setdefault(str(gid), []).append((src_id, passage))

    for sql_src_id, row in registry.sql_rows.items():
        if sql_src_id.startswith("sql:identity:"):
            continue
        gid = str(row.get("grant_id") or "").strip()
        sql_deadline = str(row.get("deadline") or "").strip()
        if not gid or not sql_deadline:
            continue
        sql_iso = _to_iso_date(sql_deadline)
        if not sql_iso:
            continue

        # Sort passages newest version/effective_date first so v2.0 supersedes v1.0
        cand_passages = sorted(
            passages_by_grant.get(gid, []),
            key=lambda pair: (str(pair[1].get("effective_date") or ""), str(pair[1].get("version") or "")),
            reverse=True,
        )
        for doc_src_id, p in cand_passages:
            text = str(p.get("text") or "")
            doc_dates = _extract_passage_deadlines(text)
            for doc_iso, doc_disp in doc_dates:
                # Ignore historical v1.0 effective-date boilerplate unless explicitly referencing deadline
                if doc_iso != sql_iso and (gid, "deadline") not in seen_keys:
                    # Prefer explicit v2.0 amendment conflict over older v1.0 date if v2.0 is present
                    if str(p.get("version") or "") == "v1.0" and any(
                        str(op[1].get("version") or "") == "v2.0" for op in cand_passages
                    ):
                        continue
                    seen_keys.add((gid, "deadline"))
                    citation = str(p.get("citation") or f"[{p.get('doc_id')} {p.get('version')}]")
                    conflicts.append(
                        ConflictNotice(
                            entity=gid,
                            field="deadline",
                            sql_value=sql_iso,
                            doc_value=f"{doc_disp} ({doc_iso})",
                            sql_source_id=sql_src_id,
                            doc_source_id=doc_src_id,
                            doc_citation=citation,
                            summary=(
                                f"Conflict for {gid} deadline: database records '{sql_iso}' [{sql_src_id}], "
                                f"while {citation} states '{doc_disp}' ({doc_iso}) [{doc_src_id}]."
                            ),
                        )
                    )
                    break

    return conflicts


def detect_expired_deadlines(
    registry: SourceRegistry,
    *,
    current_date: str,
) -> list[DeadlineNotice]:
    """Identify expired grants/deadlines relative to current_date."""
    notices: list[DeadlineNotice] = []
    seen_entities: set[str] = set()

    for src_id, row in registry.sql_rows.items():
        if src_id.startswith("sql:identity:"):
            continue
        gid = str(row.get("grant_id") or "").strip()
        gname = str(row.get("grant_name") or gid or "Grant")
        deadline_raw = str(row.get("deadline") or "").strip()
        status_raw = str(row.get("status") or "").lower()
        iso = _to_iso_date(deadline_raw)
        if gid and iso and iso < current_date and gid not in seen_entities:
            seen_entities.add(gid)
            notices.append(
                DeadlineNotice(
                    entity=gid,
                    grant_name=gname,
                    deadline=iso,
                    current_date=current_date,
                    source_id=src_id,
                    status="expired",
                    summary=(
                        f"Deadline passed for {gid} ({gname}): deadline {iso} precedes "
                        f"reference date {current_date} (DB status: {status_raw or 'expired'}) [{src_id}]."
                    ),
                )
            )

    for src_id, p in registry.doc_passages.items():
        gid = str(p.get("grant_id") or "").strip()
        text = str(p.get("text") or "")
        if gid and gid not in seen_entities and ("discontinued" in text.lower() or "closed june 30, 2026" in text.lower()):
            for iso, disp in _extract_passage_deadlines(text):
                if iso < current_date:
                    seen_entities.add(gid)
                    citation = str(p.get("citation") or src_id)
                    notices.append(
                        DeadlineNotice(
                            entity=gid,
                            grant_name=gid,
                            deadline=iso,
                            current_date=current_date,
                            source_id=src_id,
                            status="expired",
                            summary=f"Handbook {citation} notes {gid} closed/discontinued on {disp} ({iso}) [{src_id}].",
                        )
                    )
                    break

    return notices


def detect_missing_evidence(
    state: dict[str, Any],
    registry: SourceRegistry,
) -> list[str]:
    """Emit explicit notices for missing records, skipped searches, or DB-invisible soft requirements."""
    notices: list[str] = []
    plan = state.get("plan") or {}
    route = str(plan.get("route") or "")
    status_notice = state.get("status_notice")

    if status_notice == "no matching records":
        notices.append(
            "Missing evidence: SQL returned 0 matching records for this student/criteria; "
            "document search was intentionally skipped without generic fallback."
        )
        return notices

    non_identity_sql = [k for k in registry.sql_rows if not k.startswith("sql:identity:")]
    if route in ("sql", "hybrid") and not non_identity_sql:
        notices.append("Missing evidence: No relational SQL records were retrieved for this query.")

    if route in ("vector", "hybrid") and not registry.doc_passages:
        notices.append("Missing evidence: No handbook policy passages matched the metadata filters.")

    # Detect soft policy conditions present in passages whose fulfillment cannot be confirmed from SQL alone
    combined_doc_text = "\n".join(str(p.get("text") or "") for p in registry.doc_passages.values())
    found_soft: list[str] = []
    for label, pattern in _SOFT_CONDITION_PATTERNS:
        if re.search(pattern, combined_doc_text, flags=re.IGNORECASE) and label not in found_soft:
            found_soft.append(label)

    if route in ("hybrid", "vector") and found_soft:
        notices.append(
            "Database does not track completion of non-numeric policy prerequisites ("
            + "; ".join(found_soft[:5])
            + ") — verify documentation directly with advisor/office."
        )

    return notices
