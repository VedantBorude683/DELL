"""Student identity loader from DB and self-reported claim mismatch detector."""
from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from typing import Any

from src.config import AppConfig
from src.orchestrator.models import IdentityCheck, StudentIdentity

_YEAR_WORD_TO_INT = {
    "first": 1, "1st": 1, "freshman": 1,
    "second": 2, "2nd": 2, "sophomore": 2,
    "third": 3, "3rd": 3, "junior": 3,
    "fourth": 4, "4th": 4, "senior": 4,
}

_DEPT_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\b(?:CS|computer\s+science)\b", "CS"),
    (r"\b(?:ECE|electrical(?:\s+&\s+|\s+and\s+)?computer\s+engineering)\b", "ECE"),
    (r"\b(?:BIO|biological\s+sciences?|biology)\b", "BIO"),
    (r"\b(?:MATH|applied\s+mathematics|mathematics)\b", "MATH"),
    (r"\b(?:ECON|economics)\b", "ECON"),
    (r"\b(?:ME|mechanical\s+engineering)\b", "ME"),
)


def load_student_profile(
    persona_student_id: str,
    *,
    root_dir: Path | None = None,
    cfg: AppConfig | None = None,
) -> StudentIdentity | None:
    """Load authoritative student identity from Postgres or SQLite read-only DB."""
    if not persona_student_id:
        return None
    root = root_dir or Path(".")
    active_cfg = cfg or AppConfig.load(root / "config.yaml")

    ro_pg_url = os.environ.get("READONLY_DATABASE_URL", "").strip()
    use_postgres = os.environ.get("USE_POSTGRES", "").lower() == "true"
    row_dict: dict[str, Any] | None = None

    if ro_pg_url and ("alderwood_ro_password" not in ro_pg_url or use_postgres):
        try:
            from sqlalchemy import create_engine, text  # type: ignore

            engine = create_engine(ro_pg_url, pool_pre_ping=True)
            with engine.connect() as conn:
                res = conn.execute(
                    text(
                        "SELECT student_id, full_name, email, dept_code, year_of_study, "
                        "cumulative_gpa, semester_gpa, advisor_name, enrollment_status, residency_status "
                        "FROM students WHERE student_id = :sid"
                    ),
                    {"sid": persona_student_id},
                ).mappings().first()
                if res:
                    row_dict = dict(res)
        except Exception:
            row_dict = None

    if row_dict is None:
        db_path = (root / active_cfg.sqlite_mirror_path).resolve()
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            r = conn.execute(
                "SELECT student_id, full_name, email, dept_code, year_of_study, "
                "cumulative_gpa, semester_gpa, advisor_name, enrollment_status, residency_status "
                "FROM students WHERE student_id = ?",
                (persona_student_id,),
            ).fetchone()
            if r:
                row_dict = dict(r)
        finally:
            conn.close()

    if row_dict is None:
        return None

    return StudentIdentity(
        student_id=str(row_dict["student_id"]),
        full_name=str(row_dict["full_name"]),
        email=str(row_dict["email"]),
        dept_code=str(row_dict["dept_code"]),
        year_of_study=int(row_dict["year_of_study"]),
        cumulative_gpa=float(row_dict["cumulative_gpa"]),
        semester_gpa=float(row_dict["semester_gpa"]),
        advisor_name=str(row_dict["advisor_name"]),
        enrollment_status=str(row_dict["enrollment_status"]),
        residency_status=str(row_dict["residency_status"]),
    )


def extract_self_reported_claims(query: str) -> dict[str, Any]:
    """Extract self-reported GPA, year_of_study, and dept_code claims made in the query."""
    claims: dict[str, Any] = {}
    q = query.strip()
    q_low = q.lower()

    # Self-reported first-person GPA patterns (skip third-person statements about a named different student)
    first_person = bool(
        re.search(r"\b(i am|i'm|im|my|me)\b", q_low)
        or re.search(r"reporting my gpa|with a \d\.\d+\s*gpa", q_low)
    )
    if first_person:
        # Semester GPA explicit self-report
        sem_match = re.search(
            r"\b(?:my\s+)?semester\s+gpa\s+(?:is|of|=|as)?\s*([0-4]\.\d{1,2})\b",
            q_low,
        )
        if sem_match and "minimum" not in q_low[max(0, sem_match.start() - 12) : sem_match.start()]:
            claims["semester_gpa"] = float(sem_match.group(1))
        else:
            gpa_match = (
                re.search(
                    r"\b(?:my(?:\s+cumulative)?\s+gpa\s+(?:is|of|as|=)|reporting\s+my\s+gpa\s+(?:as|is))\s*([0-4]\.\d{1,2})\b",
                    q_low,
                )
                or re.search(
                    r"\b(?:i\s+have\s+a|with\s+a)\s+([0-4]\.\d{1,2})\s*(?:cumulative\s+)?gpa\b",
                    q_low,
                )
            )
            if gpa_match:
                claims["cumulative_gpa"] = float(gpa_match.group(1))

        # Year of study claim
        year_match = (
            re.search(r"\b(1st|2nd|3rd|4th|first|second|third|fourth)[-\s]*year\b", q_low)
            or re.search(r"\b(?:freshman|sophomore|junior|senior)\b", q_low)
            or re.search(r"\byear\s*([1-4])\b", q_low)
        )
        if year_match:
            raw_y = (year_match.group(1) if year_match.lastindex else year_match.group(0)).lower()
            if raw_y.isdigit():
                claims["year_of_study"] = int(raw_y)
            elif raw_y in _YEAR_WORD_TO_INT:
                claims["year_of_study"] = _YEAR_WORD_TO_INT[raw_y]

        # Dept claim when saying "I'm a ... <DEPT> student"
        if re.search(r"\b(i am|i'm|im)\b.*\bstudent\b", q_low):
            for pattern, code in _DEPT_PATTERNS:
                if re.search(pattern, q, flags=re.IGNORECASE):
                    claims["dept_code"] = code
                    break

    return claims


def check_identity_consistency(
    query: str,
    persona_student_id: str,
    *,
    root_dir: Path | None = None,
    cfg: AppConfig | None = None,
) -> IdentityCheck:
    """Load DB profile for persona and flag any mismatch against self-reported query values."""
    profile = load_student_profile(persona_student_id, root_dir=root_dir, cfg=cfg)
    if profile is None:
        return IdentityCheck(
            persona_student_id=persona_student_id,
            profile=None,
            self_reported={},
            mismatches=[{"field": "student_id", "self_reported": persona_student_id, "db_value": None}],
            flagged=True,
            warning_message=f"Student persona '{persona_student_id}' not found in database.",
        )

    claims = extract_self_reported_claims(query)
    mismatches: list[dict[str, Any]] = []

    if "cumulative_gpa" in claims:
        claimed_gpa = float(claims["cumulative_gpa"])
        if abs(claimed_gpa - profile.cumulative_gpa) > 0.015:
            mismatches.append(
                {
                    "field": "cumulative_gpa",
                    "self_reported": claimed_gpa,
                    "db_value": profile.cumulative_gpa,
                }
            )

    if "semester_gpa" in claims:
        claimed_sem = float(claims["semester_gpa"])
        if abs(claimed_sem - profile.semester_gpa) > 0.015:
            mismatches.append(
                {
                    "field": "semester_gpa",
                    "self_reported": claimed_sem,
                    "db_value": profile.semester_gpa,
                }
            )

    if "year_of_study" in claims:
        claimed_year = int(claims["year_of_study"])
        if claimed_year != profile.year_of_study:
            mismatches.append(
                {
                    "field": "year_of_study",
                    "self_reported": claimed_year,
                    "db_value": profile.year_of_study,
                }
            )

    if "dept_code" in claims:
        claimed_dept = str(claims["dept_code"])
        if claimed_dept != profile.dept_code:
            mismatches.append(
                {
                    "field": "dept_code",
                    "self_reported": claimed_dept,
                    "db_value": profile.dept_code,
                }
            )

    flagged = len(mismatches) > 0
    warning: str | None = None
    if flagged:
        parts = [
            f"{m['field']} (query claimed {m['self_reported']!r}, DB record is {m['db_value']!r})"
            for m in mismatches
        ]
        warning = (
            f"Identity mismatch detected for {profile.full_name} ({profile.student_id}): "
            + "; ".join(parts)
            + ". Using authoritative DB profile values."
        )

    return IdentityCheck(
        persona_student_id=persona_student_id,
        profile=profile,
        self_reported=claims,
        mismatches=mismatches,
        flagged=flagged,
        warning_message=warning,
    )


def list_student_personas(
    *,
    root_dir: Path | None = None,
    cfg: AppConfig | None = None,
) -> list[dict[str, Any]]:
    """Return ordered list of student personas from read-only DB."""
    root = root_dir or Path(".")
    active_cfg = cfg or AppConfig.load(root / "config.yaml")
    db_path = (root / active_cfg.sqlite_mirror_path).resolve()
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT student_id, full_name, dept_code, year_of_study, cumulative_gpa, semester_gpa, enrollment_status "
            "FROM students ORDER BY student_id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
