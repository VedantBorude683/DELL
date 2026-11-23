"""Schema index builder and table retriever with metric views and distinct sample values."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.config import AppConfig
from src.rag.embeddings import Embedder, cosine_similarity

TABLE_DESCRIPTIONS: dict[str, dict[str, Any]] = {
    "departments": {
        "description": "Academic departments, department codes (CS, ECE, BIO, MATH, ECON, ME), dean names, buildings, and annual grant pool funding totals.",
        "keywords": "department dean building annual grant pool budget across all departments",
        "sample_cols": ("dept_code", "dept_name", "dean_name", "building"),
    },
    "students": {
        "description": "Enrolled student profiles: student_id, full_name, email, dept_code, year_of_study (1-4), cumulative_gpa, semester_gpa, advisor_name, enrollment_status (active, probation_watch), residency_status (in_state, out_of_state, international).",
        "keywords": "my gpa cumulative gpa overall gpa class standing academic year advisor enrollment status probation_watch residency student profile",
        "sample_cols": ("dept_code", "enrollment_status", "residency_status"),
    },
    "courses": {
        "description": "University course catalog with course_id (CS-301, CS-410, ECE-420), dept_code, title, credits, course_level (200, 300, 400), instructor_name, max_capacity.",
        "keywords": "course catalog title credits 400 level 300 level instructor taught",
        "sample_cols": ("course_id", "dept_code", "course_level"),
    },
    "enrollments": {
        "description": "Student course enrollments linking student_id to course_id per term, letter_grade, grade_points, and enrollment status.",
        "keywords": "enrolled courses taking this semester registered classes grade letter_grade",
        "sample_cols": ("term", "letter_grade", "status"),
    },
    "grants": {
        "description": "Active and expired research grants catalog with grant_id (GR-CS-01, GR-CS-02, GR-GEN-02, GR-GEN-04), grant_name, dept_code, min_gpa, min_year, max_year, award_amount, deadline, status (open, expired), funding_cycle. Canonical source for grant eligibility and current deadlines.",
        "keywords": "research grants fellowships stipends award amount deadline qualify eligible min_gpa min_year open grants travel fund",
        "sample_cols": ("grant_id", "dept_code", "status", "funding_cycle"),
    },
    "fee_ledger": {
        "description": "Per-student tuition and lab billing ledger tracking student_id, term, category, amount_due, amount_paid, remaining unpaid balance (amount_due - amount_paid), due_date, and payment status (paid, partial, unpaid_balance, overdue). Canonical source for how much a student owes.",
        "keywords": "owe remaining unpaid balance fee ledger amount due amount paid overdue billing statement",
        "sample_cols": ("term", "category", "status"),
    },
    "timetable": {
        "description": "Class meeting schedule per course_id and term: day_of_week, start_time, end_time, room (TH-204, TH-108), and building (Turing Hall).",
        "keywords": "timetable class schedule meeting times rooms building where is class held",
        "sample_cols": ("day_of_week", "building", "room"),
    },
    "grant_applications": {
        "description": "Individual student grant applications already submitted (application_id, grant_id, student_id, submitted_at, decision_status, requested_amount). NOT the master grant eligibility catalog.",
        "keywords": "submitted applications applied how many applications decision status under_review pending_mentor_signature",
        "sample_cols": ("decision_status", "grant_id"),
    },
    "grant_history": {
        "description": "Historical past fiscal-year grant disbursement aggregates (fiscal_year 2025, total_disbursed, recipients_count, archived_deadline). NOT current deadlines.",
        "keywords": "fiscal year 2025 total disbursed recipients count past historical archived deadline",
        "sample_cols": ("fiscal_year", "grant_id"),
    },
    "grant_reviewers": {
        "description": "Faculty committee reviewers assigned to evaluate grant_id proposals and review_round (Round 1, Final).",
        "keywords": "faculty reviewers assigned review round committee",
        "sample_cols": ("grant_id", "faculty_name", "review_round"),
    },
    "fees": {
        "description": "Published university baseline tuition and lab fee rate schedule by dept_code, residency_status (in_state, out_of_state, international), and term (base_tuition, lab_fee, health_fee). NOT personal student balances.",
        "keywords": "published base tuition lab fee health fee schedule rate table residency",
        "sample_cols": ("dept_code", "residency_status", "term"),
    },
    "fee_waivers": {
        "description": "Individual student fee waivers (waiver_id, student_id, waiver_type, waiver_amount, approved_by, status approved/pending).",
        "keywords": "approved fee waivers merit lab fee waiver dean entrance waiver hardship waiver",
        "sample_cols": ("waiver_type", "status"),
    },
    "student_semester_gpas": {
        "description": "Per-term historical semester GPA records for each student (student_id, term, semester_gpa, credits_attempted, deans_list_flag). Use for term-specific semester GPA and Dean's List queries.",
        "keywords": "semester gpa term gpa deans list dean's list Fall 2026 Spring 2026 credits attempted",
        "sample_cols": ("term", "deans_list_flag"),
    },
    "student_awards": {
        "description": "Academic honors and one-time student prizes already awarded (award_title, awarded_term, stipend_amount).",
        "keywords": "student awards received prizes hardware medal olympiad scholarship",
        "sample_cols": ("award_title", "awarded_term"),
    },
    "faculty_mentors": {
        "description": "Directory of faculty mentors (faculty_name, dept_code, research_area, accepting_undergrads boolean, office_room).",
        "keywords": "faculty mentor mentors accepting undergraduate researchers office room research area",
        "sample_cols": ("faculty_name", "dept_code", "accepting_undergrads", "office_room"),
    },
    "research_labs": {
        "description": "University research laboratories (lab_name, dept_code, pi_name, building, safety_clearance_required boolean).",
        "keywords": "research labs safety clearance required cleanroom wet lab wind tunnel",
        "sample_cols": ("lab_name", "dept_code", "safety_clearance_required"),
    },
    "academic_calendar": {
        "description": "Official academic term key dates: Fall Classes Begin, Add/Drop Deadline, Thanksgiving Recess, Final Examinations Week, Spring Term Opens.",
        "keywords": "academic calendar final examinations week classes begin add drop deadline holiday event date",
        "sample_cols": ("term", "event_name", "category"),
    },
    "scholarships_archive": {
        "description": "Discontinued legacy scholarships from 2021-2023 (legacy_code, title, discontinued_year, old_min_gpa). Not active grants.",
        "keywords": "legacy scholarships discontinued between 2021 and 2023 archive",
        "sample_cols": ("legacy_code", "discontinued_year"),
    },
}

METRIC_VIEWS: tuple[dict[str, str], ...] = (
    {
        "entry_id": "mv_cumulative_gpa",
        "table_name": "students",
        "column_name": "cumulative_gpa",
        "description": "Metric View cumulative_gpa: Official overall cumulative GPA on students table used for research grant and honors eligibility, academic year, and class standing.",
        "sample_values": "3.74, 3.38, 3.89, 3.61, 3.92",
        "metric_view_sql": "SELECT student_id, full_name, dept_code, year_of_study, cumulative_gpa FROM students",
    },
    {
        "entry_id": "mv_semester_gpa_deans_list",
        "table_name": "student_semester_gpas",
        "column_name": "semester_gpa",
        "description": "Metric View semester_gpa_deans_list: Per-term semester GPA and Dean's List recognition (deans_list_flag = 1) in student_semester_gpas joined with students.",
        "sample_values": "Fall 2026, Spring 2026, 3.85, deans_list_flag=1",
        "metric_view_sql": "SELECT s.full_name, g.term, g.semester_gpa, g.deans_list_flag FROM student_semester_gpas g JOIN students s ON s.student_id = g.student_id",
    },
    {
        "entry_id": "mv_active_grant_window",
        "table_name": "grants",
        "column_name": "deadline",
        "description": "Metric View active_grant_window: Active open grants matching student department, cumulative GPA >= min_gpa, year between min_year and max_year, and deadline >= current_date.",
        "sample_values": "GR-CS-01 (2026-12-15), GR-CS-02 (2026-12-20), GR-GEN-01 (2026-12-30), GR-GEN-04 (expired 2026-06-30)",
        "metric_view_sql": "SELECT grant_id, grant_name, dept_code, min_gpa, award_amount, deadline FROM grants WHERE status = 'open'",
    },
    {
        "entry_id": "mv_outstanding_fee_balance",
        "table_name": "fee_ledger",
        "column_name": "amount_due",
        "description": "Metric View outstanding_fee_balance: Student-specific remaining balance owed (amount_due - amount_paid) in fee_ledger for Fall 2026.",
        "sample_values": "LED-2026-002 owes 2800 (partial), LED-2026-005 unpaid_balance, LED-2026-007 overdue",
        "metric_view_sql": "SELECT student_id, term, amount_due, amount_paid, (amount_due - amount_paid) AS balance_owed, status FROM fee_ledger",
    },
    {
        "entry_id": "mv_student_course_timetable",
        "table_name": "timetable",
        "column_name": "room",
        "description": "Metric View student_course_timetable: Enrolled courses joined with timetable rooms, days, and buildings for a student.",
        "sample_values": "CS-301 TH-204 Turing Hall Monday 09:30, CS-340 TH-108",
        "metric_view_sql": "SELECT e.student_id, c.course_id, c.title, t.day_of_week, t.start_time, t.room, t.building FROM enrollments e JOIN courses c ON c.course_id = e.course_id JOIN timetable t ON t.course_id = e.course_id",
    },
    {
        "entry_id": "mv_available_faculty_mentors",
        "table_name": "faculty_mentors",
        "column_name": "accepting_undergrads",
        "description": "Metric View available_faculty_mentors: Faculty mentors currently accepting undergraduate researchers with office room and research area.",
        "sample_values": "Dr. Aris Thorne (CS, TH-402, accepting=1), Dr. Nadia Patel (CS, TH-415, accepting=1), Dr. Hannah Sato (ME, accepting=0)",
        "metric_view_sql": "SELECT faculty_name, dept_code, research_area, accepting_undergrads, office_room FROM faculty_mentors",
    },
)


@dataclass(frozen=True)
class SchemaTableHit:
    table_name: str
    score: float
    matched_entry_id: str
    description: str
    sample_values: str
    metric_view_sql: str | None


def _distinct_samples(conn: sqlite3.Connection, table: str, cols: tuple[str, ...]) -> str:
    parts: list[str] = []
    for col in cols:
        vals = [
            str(r[0])
            for r in conn.execute(f"SELECT DISTINCT {col} FROM {table} WHERE {col} IS NOT NULL LIMIT 5").fetchall()
        ]
        if vals:
            parts.append(f"{col}: {', '.join(vals)}")
    return " | ".join(parts)


def build_schema_index(
    root_dir: Path | None = None,
    *,
    cfg: AppConfig | None = None,
    embedder: Embedder | None = None,
) -> dict[str, Any]:
    """Populate schema_index table with table, column, sample-value, and metric-view embeddings."""
    root = root_dir or Path(".")
    active_cfg = cfg or AppConfig.load(root / "config.yaml")
    active_embedder = embedder or Embedder(
        model_name=str(active_cfg.raw.get("models", {}).get("embedding_model", "BAAI/bge-m3"))
    )

    db_path = root / active_cfg.sqlite_mirror_path
    conn = sqlite3.connect(str(db_path))

    # Ensure embedding_json column exists
    cols = {row[1] for row in conn.execute("PRAGMA table_info(schema_index)").fetchall()}
    if "embedding_json" not in cols:
        conn.execute("ALTER TABLE schema_index ADD COLUMN embedding_json TEXT")

    entries: list[dict[str, Any]] = []
    for table_name in active_cfg.allowlisted_tables:
        meta = TABLE_DESCRIPTIONS.get(table_name, {})
        col_rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        col_names = [c[1] for c in col_rows]
        samples = _distinct_samples(conn, table_name, meta.get("sample_cols", tuple(col_names[:3])))
        desc = (
            f"Table {table_name}. {meta.get('description', '')} "
            f"Columns: {', '.join(col_names)}. "
            f"Keywords: {meta.get('keywords', '')}. "
            f"Sample values: {samples}"
        )
        entries.append(
            {
                "entry_id": f"tbl_{table_name}",
                "table_name": table_name,
                "column_name": None,
                "description": desc,
                "sample_values": samples,
                "metric_view_sql": None,
            }
        )

        # Also index key columns individually with distinct values
        for col_name in meta.get("sample_cols", ()):
            col_samples = _distinct_samples(conn, table_name, (col_name,))
            entries.append(
                {
                    "entry_id": f"col_{table_name}_{col_name}",
                    "table_name": table_name,
                    "column_name": col_name,
                    "description": f"Column {table_name}.{col_name}. {meta.get('description', '')} Distinct values: {col_samples}",
                    "sample_values": col_samples,
                    "metric_view_sql": None,
                }
            )

    # Add metric views
    for mv in METRIC_VIEWS:
        entries.append(dict(mv))

    embeddings = active_embedder.embed_batch([e["description"] for e in entries])
    conn.execute("DELETE FROM schema_index")
    for entry, emb in zip(entries, embeddings):
        conn.execute(
            """
            INSERT INTO schema_index (entry_id, table_name, column_name, description, sample_values, metric_view_sql, embedding_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry["entry_id"],
                entry["table_name"],
                entry["column_name"],
                entry["description"],
                entry["sample_values"],
                entry["metric_view_sql"],
                json.dumps(emb),
            ),
        )
    conn.commit()
    conn.close()

    return {
        "total_entries": len(entries),
        "tables_indexed": len(active_cfg.allowlisted_tables),
        "metric_views_indexed": len(METRIC_VIEWS),
        "embedder_backend": active_embedder.backend_name,
    }


def retrieve_tables(
    query: str,
    *,
    top_k: int = 3,
    root_dir: Path | None = None,
    cfg: AppConfig | None = None,
    embedder: Embedder | None = None,
    cached_entries: list[dict[str, Any]] | None = None,
) -> list[SchemaTableHit]:
    """Retrieve top-k tables from schema_index using embedding cosine similarity."""
    root = root_dir or Path(".")
    active_cfg = cfg or AppConfig.load(root / "config.yaml")
    active_embedder = embedder or Embedder(
        model_name=str(active_cfg.raw.get("models", {}).get("embedding_model", "BAAI/bge-m3"))
    )

    if cached_entries is None:
        conn = sqlite3.connect(str(root / active_cfg.sqlite_mirror_path))
        rows = conn.execute(
            "SELECT entry_id, table_name, column_name, description, sample_values, metric_view_sql, embedding_json FROM schema_index"
        ).fetchall()
        conn.close()
        cached_entries = [
            {
                "entry_id": r[0],
                "table_name": r[1],
                "column_name": r[2],
                "description": r[3],
                "sample_values": r[4],
                "metric_view_sql": r[5],
                "embedding": json.loads(r[6]),
            }
            for r in rows
        ]

    q_vec = active_embedder.embed_one(query)
    best_by_table: dict[str, SchemaTableHit] = {}

    for entry in cached_entries:
        sim = cosine_similarity(q_vec, entry["embedding"])
        tbl = entry["table_name"]
        # Slight boost for explicit table/metric-view entries
        if entry["entry_id"].startswith("mv_"):
            sim += 0.02
        existing = best_by_table.get(tbl)
        if existing is None or sim > existing.score:
            best_by_table[tbl] = SchemaTableHit(
                table_name=tbl,
                score=round(sim, 4),
                matched_entry_id=entry["entry_id"],
                description=entry["description"],
                sample_values=entry["sample_values"],
                metric_view_sql=entry["metric_view_sql"],
            )

    ranked = sorted(best_by_table.values(), key=lambda h: h.score, reverse=True)
    return ranked[:top_k]


def evaluate_table_recall_at_k(
    root_dir: Path | None = None,
    *,
    k: int = 3,
    cfg: AppConfig | None = None,
    embedder: Embedder | None = None,
) -> dict[str, Any]:
    """Evaluate table-retrieval Recall@k on all gold queries that specify expected_tables."""
    root = root_dir or Path(".")
    active_cfg = cfg or AppConfig.load(root / "config.yaml")
    active_embedder = embedder or Embedder(
        model_name=str(active_cfg.raw.get("models", {}).get("embedding_model", "BAAI/bge-m3"))
    )

    conn = sqlite3.connect(str(root / active_cfg.sqlite_mirror_path))
    rows = conn.execute(
        "SELECT entry_id, table_name, column_name, description, sample_values, metric_view_sql, embedding_json FROM schema_index"
    ).fetchall()
    conn.close()
    cached_entries = [
        {
            "entry_id": r[0],
            "table_name": r[1],
            "column_name": r[2],
            "description": r[3],
            "sample_values": r[4],
            "metric_view_sql": r[5],
            "embedding": json.loads(r[6]),
        }
        for r in rows
    ]

    gold_rows = [
        json.loads(line)
        for line in (root / active_cfg.gold_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    eval_rows = [r for r in gold_rows if r.get("expected_tables")]

    recalls: list[float] = []
    any_hit_count = 0
    misses: list[dict[str, Any]] = []

    for r in eval_rows:
        expected = set(r["expected_tables"])
        hits = retrieve_tables(
            r["query"],
            top_k=k,
            root_dir=root,
            cfg=active_cfg,
            embedder=active_embedder,
            cached_entries=cached_entries,
        )
        retrieved = [h.table_name for h in hits]
        overlap = expected.intersection(retrieved)
        recall = len(overlap) / len(expected)
        recalls.append(recall)
        if overlap:
            any_hit_count += 1
        if recall < 1.0:
            misses.append(
                {
                    "query_id": r["query_id"],
                    "query": r["query"],
                    "expected": sorted(expected),
                    "retrieved_top_k": retrieved,
                    "recall": round(recall, 4),
                }
            )

    mean_recall = round(sum(recalls) / len(recalls), 4) if recalls else 0.0
    hit_rate = round(any_hit_count / len(eval_rows), 4) if eval_rows else 0.0

    return {
        "k": k,
        "evaluated_queries": len(eval_rows),
        "mean_recall_at_k": mean_recall,
        "any_expected_hit_rate": hit_rate,
        "perfect_recall_queries": sum(1 for r in recalls if r == 1.0),
        "misses_sample": misses[:8],
    }
