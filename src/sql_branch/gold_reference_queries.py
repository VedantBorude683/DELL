"""Canonical SQL reference queries and accuracy evaluator for the 24 Phase 1-3 SQL gold queries."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from src.config import AppConfig
from src.sql_branch.executor import execute_readonly_sql
from src.sql_branch.models import SQLExecutionError, SQLValidationError
from src.sql_branch.validator import validate_select_sql

# Exact canonical SELECT statements for G-001..G-024 (postgres + SQLite compatible)
GOLD_SQL_STATEMENTS: dict[str, str] = {
    "G-001": "SELECT student_id, full_name, dept_code, year_of_study, cumulative_gpa FROM students WHERE student_id = 'STU-1001'",
    "G-002": "SELECT student_id, full_name, dept_code, year_of_study, cumulative_gpa FROM students WHERE student_id = 'STU-1001'",
    "G-003": (
        "SELECT s.full_name, s.cumulative_gpa, g.term, g.semester_gpa "
        "FROM students s "
        "JOIN student_semester_gpas g ON s.student_id = g.student_id "
        "WHERE s.student_id = 'STU-1002' AND g.term = 'Fall 2026'"
    ),
    "G-004": (
        "SELECT fl.ledger_id, fl.term, fl.amount_due, fl.amount_paid, "
        "(fl.amount_due - fl.amount_paid) AS remaining_balance, fl.status "
        "FROM fee_ledger fl WHERE fl.student_id = 'STU-1002' AND fl.term = 'Fall 2026'"
    ),
    "G-005": (
        "SELECT fl.ledger_id, fl.term, (fl.amount_due - fl.amount_paid) AS remaining_balance, fl.status "
        "FROM fee_ledger fl WHERE fl.student_id = 'STU-1002' AND fl.term = 'Fall 2026'"
    ),
    "G-006": (
        "SELECT e.course_id, c.title, t.day_of_week, t.start_time, t.end_time, t.room, t.building "
        "FROM enrollments e "
        "JOIN courses c ON e.course_id = c.course_id "
        "JOIN timetable t ON e.course_id = t.course_id AND e.term = t.term "
        "WHERE e.student_id = 'STU-1001' AND e.term = 'Fall 2026' "
        "ORDER BY e.course_id, t.day_of_week"
    ),
    "G-007": (
        "SELECT e.course_id, t.day_of_week, t.start_time, t.room, t.building "
        "FROM enrollments e "
        "JOIN timetable t ON e.course_id = t.course_id AND e.term = t.term "
        "WHERE e.student_id = 'STU-1001' AND e.term = 'Fall 2026' "
        "ORDER BY e.course_id, t.day_of_week"
    ),
    "G-008": (
        "SELECT grant_id, grant_name, dept_code, min_gpa, min_year, max_year, award_amount, deadline "
        "FROM grants "
        "WHERE status = 'open' AND deadline >= '2026-11-23' "
        "AND (dept_code = 'CS' OR dept_code = 'ALL') "
        "AND min_gpa <= 3.74 AND 3 BETWEEN min_year AND max_year "
        "ORDER BY grant_id"
    ),
    "G-009": "SELECT grant_id, grant_name, deadline, award_amount FROM grants WHERE grant_id = 'GR-CS-02'",
    "G-010": (
        "SELECT mentor_id, faculty_name, research_area, office_room "
        "FROM faculty_mentors WHERE dept_code = 'CS' AND accepting_undergrads = TRUE ORDER BY mentor_id"
    ),
    "G-011": (
        "SELECT faculty_name, dept_code, accepting_undergrads, office_room "
        "FROM faculty_mentors WHERE faculty_name = 'Dr. Hannah Sato' AND dept_code = 'ME'"
    ),
    "G-012": (
        "SELECT COUNT(*) AS application_count, MAX(application_id) AS application_id, MAX(decision_status) AS decision_status "
        "FROM grant_applications WHERE grant_id = 'GR-CS-01'"
    ),
    "G-013": (
        "SELECT grant_id, fiscal_year, total_disbursed, recipients_count, archived_deadline "
        "FROM grant_history WHERE grant_id = 'GR-CS-01' AND fiscal_year = 2025"
    ),
    "G-014": (
        "SELECT fee_schedule_id, dept_code, residency_status, term, base_tuition, lab_fee, health_fee "
        "FROM fees WHERE dept_code = 'CS' AND residency_status = 'in_state' AND term = 'Fall 2026'"
    ),
    "G-015": (
        "SELECT waiver_id, waiver_type, waiver_amount, status, approved_by "
        "FROM fee_waivers WHERE student_id = 'STU-1001' AND term = 'Fall 2026'"
    ),
    "G-016": (
        "SELECT event_id, term, event_name, event_date "
        "FROM academic_calendar WHERE event_name = 'Final Examinations Week' AND term = 'Fall 2026'"
    ),
    "G-017": (
        "SELECT lab_id, lab_name, dept_code, pi_name, building, safety_clearance_required "
        "FROM research_labs WHERE safety_clearance_required = TRUE ORDER BY lab_id"
    ),
    "G-018": (
        "SELECT student_id, full_name, advisor_name, enrollment_status "
        "FROM students WHERE student_id = 'STU-1011'"
    ),
    "G-019": (
        "SELECT archive_id, legacy_code, title, discontinued_year, old_min_gpa "
        "FROM scholarships_archive WHERE discontinued_year BETWEEN 2021 AND 2023 ORDER BY archive_id"
    ),
    "G-020": (
        "SELECT reviewer_id, grant_id, faculty_name, dept_code, review_round "
        "FROM grant_reviewers WHERE grant_id = 'GR-ECE-01'"
    ),
    "G-021": "SELECT SUM(annual_grant_pool) AS total_annual_grant_pool FROM departments",
    "G-022": (
        "SELECT s.student_id, s.full_name, g.term, g.semester_gpa, g.deans_list_flag "
        "FROM student_semester_gpas g JOIN students s ON s.student_id = g.student_id "
        "WHERE g.term = 'Fall 2026' AND g.deans_list_flag = TRUE ORDER BY s.student_id"
    ),
    "G-023": (
        "SELECT a.award_id, s.full_name, a.award_title, a.awarded_term, a.stipend_amount "
        "FROM student_awards a JOIN students s ON s.student_id = a.student_id "
        "WHERE s.full_name = 'Sofia Alvarez'"
    ),
    "G-024": (
        "SELECT course_id, title, credits, course_level, instructor_name "
        "FROM courses WHERE dept_code = 'CS' AND course_level = 400 ORDER BY course_id"
    ),
}

# Safety adversarial probes (must all be rejected by validate_select_sql)
SAFETY_ATTACK_PROBES: list[dict[str, str]] = [
    {"id": "ATK-DROP", "label": "Direct DROP TABLE", "sql": "DROP TABLE students;"},
    {"id": "ATK-UPDATE", "label": "Direct UPDATE grants", "sql": "UPDATE grants SET min_gpa = 0.0 WHERE grant_id = 'GR-CS-01';"},
    {"id": "ATK-DELETE", "label": "Direct DELETE fee_ledger", "sql": "DELETE FROM fee_ledger WHERE student_id = 'STU-1011';"},
    {"id": "ATK-INSERT", "label": "Direct INSERT students", "sql": "INSERT INTO students (student_id, full_name) VALUES ('STU-9999', 'Attacker');"},
    {"id": "ATK-MULTI", "label": "Stacked multi-statement DROP", "sql": "SELECT * FROM students; DROP TABLE fee_ledger;--"},
    {"id": "ATK-UNION", "label": "UNION exfiltration", "sql": "SELECT grant_name FROM grants UNION SELECT email FROM students"},
    {"id": "ATK-CHUNKS", "label": "Non-allowlisted RAG table", "sql": "SELECT chunk_id, content FROM document_chunks LIMIT 10"},
    {"id": "ATK-CATALOG", "label": "System catalog probe", "sql": "SELECT name FROM sqlite_master WHERE type='table'"},
]


def _normalize_blob(rows: list[dict[str, Any]]) -> str:
    """Create searchable string normalization (numbers formatted with and without commas/.00)."""
    tokens: list[str] = []
    for row in rows:
        for k, v in row.items():
            if v is None:
                continue
            s = str(v)
            tokens.append(s)
            if isinstance(v, (int, float)):
                tokens.append(f"{v:,.0f}")
                tokens.append(f"{v:,.2f}")
                tokens.append(f"{v:.2f}")
                if k == "year_of_study":
                    tokens.append(f"Year {int(v)}")
                if k == "recipients_count":
                    tokens.append(f"{int(v)} recipients")
                if k == "accepting_undergrads" and v in (0, False):
                    tokens.extend(["No", "accepting_undergrads = false"])
    return " | ".join(tokens).lower()


def _fact_matches_blob(fact: str, blob: str) -> bool:
    f = fact.lower().strip()
    if f in blob:
        return True
    # Normalize dollar prefix like "$2,800" -> "2800"
    cleaned = re.sub(r"[\$,]", "", f)
    if cleaned and cleaned in re.sub(r"[\$,]", "", blob):
        return True
    return False


def evaluate_sql_branch_gold(
    root_dir: Path | None = None,
    *,
    cfg: AppConfig | None = None,
) -> dict[str, Any]:
    """Execute canonical SQL over all 24 standalone SQL gold queries + verify safety probes."""
    root = root_dir or Path(".")
    active_cfg = cfg or AppConfig.load(root / "config.yaml")

    gold_rows = [
        json.loads(line)
        for line in (root / active_cfg.gold_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    sql_gold = [r for r in gold_rows if r["query_id"] in GOLD_SQL_STATEMENTS]

    query_results: list[dict[str, Any]] = []
    exact_pass_count = 0
    execution_ok_count = 0

    for item in sql_gold:
        qid = item["query_id"]
        sql = GOLD_SQL_STATEMENTS[qid]
        try:
            res = execute_readonly_sql(sql, cfg=active_cfg, root_dir=root)
            execution_ok_count += 1
            blob = _normalize_blob(res.rows)
            missing = [f for f in item["expected_answer_facts"] if not _fact_matches_blob(f, blob)]
            passed = len(res.rows) > 0 and len(missing) == 0
            if passed:
                exact_pass_count += 1
            query_results.append(
                {
                    "query_id": qid,
                    "query": item["query"],
                    "sql": res.sql,
                    "tables": res.tables,
                    "row_count": len(res.rows),
                    "expected_facts": item["expected_answer_facts"],
                    "missing_facts": missing,
                    "passed": passed,
                    "latency_ms": res.provenance.get("latency_ms", 0.0),
                    "engine": res.provenance.get("engine"),
                    "validator_backend": res.provenance.get("validator_backend"),
                    "sample_row": res.rows[0] if res.rows else None,
                }
            )
        except (SQLValidationError, SQLExecutionError) as exc:
            query_results.append(
                {
                    "query_id": qid,
                    "query": item["query"],
                    "sql": sql,
                    "tables": [],
                    "row_count": 0,
                    "expected_facts": item["expected_answer_facts"],
                    "missing_facts": item["expected_answer_facts"],
                    "passed": False,
                    "error": str(exc),
                }
            )

    safety_results: list[dict[str, Any]] = []
    blocked_count = 0
    for probe in SAFETY_ATTACK_PROBES:
        try:
            validate_select_sql(
                probe["sql"],
                active_cfg.allowlisted_tables,
                max_rows=int(active_cfg.raw.get("database", {}).get("max_rows", 100)),
            )
            safety_results.append(
                {
                    "id": probe["id"],
                    "label": probe["label"],
                    "sql": probe["sql"],
                    "blocked": False,
                    "reason": "Unexpectedly permitted!",
                }
            )
        except SQLValidationError as exc:
            blocked_count += 1
            safety_results.append(
                {
                    "id": probe["id"],
                    "label": probe["label"],
                    "sql": probe["sql"],
                    "blocked": True,
                    "reason": str(exc),
                }
            )

    total = len(sql_gold)
    return {
        "evaluated_sql_queries": total,
        "execution_ok_count": execution_ok_count,
        "fact_accurate_count": exact_pass_count,
        "execution_accuracy": round(exact_pass_count / total, 4) if total else 0.0,
        "safety_probes_total": len(SAFETY_ATTACK_PROBES),
        "safety_probes_blocked": blocked_count,
        "results": query_results,
        "safety_results": safety_results,
    }
