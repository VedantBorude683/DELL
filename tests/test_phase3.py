"""Phase 3 verification tests: schema-trimmed SQL generation, multi-layer safety, self-heal, and gold SQL accuracy."""
from __future__ import annotations

import os
import sqlite3
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from src.config import AppConfig
from src.ingestion.pdf_ingestor import ingest_pdfs
from src.ingestion.schema_indexer import build_schema_index
from src.sql_branch import (
    SQLExecutionError,
    SQLValidationError,
    TabularResult,
    execute_readonly_sql,
    run_sql_branch,
    validate_select_sql,
)
from src.sql_branch.gold_reference_queries import (
    GOLD_SQL_STATEMENTS,
    evaluate_sql_branch_gold,
)

ROOT = Path(__file__).resolve().parent.parent


class TestPhase3SqlBranch(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cfg = AppConfig.load(ROOT / "config.yaml")
        db_path = ROOT / cls.cfg.sqlite_mirror_path
        conn = sqlite3.connect(str(db_path))
        idx_count = conn.execute("SELECT COUNT(*) FROM schema_index").fetchone()[0]
        conn.close()
        if idx_count == 0:
            ingest_pdfs(ROOT, cfg=cls.cfg, use_llm_fallback=False)
            build_schema_index(ROOT, cfg=cls.cfg)

    def test_schema_trimmed_prompt_and_date_injection(self) -> None:
        captured: dict[str, object] = {}

        def fake_gen(msgs, _schema):
            captured["msgs"] = msgs
            return {"sql": GOLD_SQL_STATEMENTS["G-008"]}

        res = run_sql_branch(
            "Which open research grants in the database match a 3rd-year CS student with a 3.74 GPA?",
            persona_student_id="STU-1001",
            cfg=self.cfg,
            root_dir=ROOT,
            sql_generator=fake_gen,
        )
        self.assertIsInstance(res, TabularResult)
        self.assertTrue(2 <= len(res.provenance["retrieved_tables"]) <= 3)
        self.assertIn("grants", res.provenance["retrieved_tables"])

        msgs = captured["msgs"]
        joined = "\n".join(m["content"] for m in msgs)
        self.assertIn(self.cfg.current_date, joined)
        self.assertIn("STU-1001", joined)
        self.assertIn("TABLE grants", joined)
        # Disallowed RAG tables must never appear in trimmed schema
        self.assertNotIn("TABLE document_chunks", joined)

        # Verify use_schema_index=False includes all 18 allowlisted tables
        no_idx_cfg = replace(self.cfg, flags=replace(self.cfg.flags, use_schema_index=False))
        captured_all: dict[str, object] = {}

        def fake_gen_all(msgs, _schema):
            captured_all["msgs"] = msgs
            return GOLD_SQL_STATEMENTS["G-001"]

        res_all = run_sql_branch(
            "What is my cumulative GPA?",
            cfg=no_idx_cfg,
            root_dir=ROOT,
            sql_generator=fake_gen_all,
        )
        self.assertEqual(len(res_all.provenance["retrieved_tables"]), 18)

    def test_safety_blocks_drop_update_multistatement_union_and_disallowed_tables(self) -> None:
        allow = self.cfg.allowlisted_tables
        malicious_queries = [
            "DROP TABLE students",
            "UPDATE grants SET min_gpa = 0.0 WHERE grant_id = 'GR-CS-01'",
            "DELETE FROM fee_ledger WHERE student_id = 'STU-1011'",
            "INSERT INTO students (student_id, full_name) VALUES ('X', 'Y')",
            "SELECT * FROM students; DROP TABLE fee_ledger;--",
            "SELECT grant_name FROM grants UNION SELECT email FROM students",
            "SELECT * FROM document_chunks",
            "SELECT * FROM schema_index",
            "SELECT name FROM sqlite_master WHERE type = 'table'",
            "SELECT * FROM pg_catalog.pg_roles",
            "SELECT * FROM students s, document_chunks d WHERE s.student_id = 'STU-1001'",
            "WITH x AS (DELETE FROM students RETURNING *) SELECT * FROM x",
            "PRAGMA table_info(students)",
        ]
        for bad_sql in malicious_queries:
            with self.subTest(bad_sql=bad_sql):
                with self.assertRaises(SQLValidationError):
                    validate_select_sql(bad_sql, allow, max_rows=100)

    def test_row_cap_and_sqlite_readonly_protection(self) -> None:
        v = validate_select_sql(
            "SELECT student_id, full_name FROM students LIMIT 9999",
            self.cfg.allowlisted_tables,
            max_rows=100,
        )
        self.assertEqual(v.limit_applied, 100)
        self.assertIn("LIMIT 100", v.sql.upper())

        v_implicit = validate_select_sql(
            "SELECT student_id, full_name FROM students",
            self.cfg.allowlisted_tables,
            max_rows=100,
        )
        self.assertEqual(v_implicit.limit_applied, 100)
        self.assertIn("LIMIT 100", v_implicit.sql.upper())

        # Direct RO connection sanity check: Layer 2 read-only URI rejects writes
        db_path = (ROOT / self.cfg.sqlite_mirror_path).resolve()
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            conn.execute("PRAGMA query_only = ON;")
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("UPDATE students SET cumulative_gpa = 4.00 WHERE student_id = 'STU-1001'")
        finally:
            conn.close()

    def test_self_heal_retries_and_tabular_result_provenance(self) -> None:
        call_log: list[list[dict[str, str]]] = []

        def flaky_generator(msgs, _schema):
            call_log.append(msgs)
            attempt = len(call_log)
            if attempt == 1:
                # Layer 1 validation error: forbidden UPDATE
                return "UPDATE grants SET min_gpa = 0.0"
            if attempt == 2:
                # DB execution error: nonexistent column `gpa`
                return "SELECT student_id, gpa FROM students WHERE student_id = 'STU-1001'"
            # Attempt 3: valid corrected SQL
            return {"sql": GOLD_SQL_STATEMENTS["G-001"]}

        res = run_sql_branch(
            "What is my current cumulative GPA and academic year?",
            persona_student_id="STU-1001",
            cfg=self.cfg,
            root_dir=ROOT,
            sql_generator=flaky_generator,
        )
        self.assertEqual(res.provenance["attempts"], 3)
        self.assertEqual(res.provenance["retries_used"], 2)
        self.assertEqual(len(res.provenance["heal_errors"]), 2)
        self.assertEqual(res.provenance["heal_errors"][0]["stage"], "validation")
        self.assertEqual(res.provenance["heal_errors"][1]["stage"], "execution")
        self.assertEqual(res.rows[0]["cumulative_gpa"], 3.74)
        self.assertEqual(res.tables, ["students"])
        # Confirm error text was actually fed back in retry message
        self.assertIn("no such column", call_log[2][-1]["content"].lower())

        # Exhausting max_retries=3 (4 total failed attempts) raises SQLExecutionError
        attempts_always_bad = {"n": 0}

        def always_bad(_msgs, _schema):
            attempts_always_bad["n"] += 1
            return "SELECT nonexistent_column FROM students"

        with self.assertRaises(SQLExecutionError):
            run_sql_branch(
                "What is my GPA?",
                cfg=self.cfg,
                root_dir=ROOT,
                sql_generator=always_bad,
            )
        self.assertEqual(attempts_always_bad["n"], 4)

    def test_gold_sql_execution_accuracy_and_safety_probes(self) -> None:
        report = evaluate_sql_branch_gold(ROOT, cfg=self.cfg)
        self.assertEqual(report["evaluated_sql_queries"], 24)
        self.assertEqual(report["execution_ok_count"], 24, f"Failures: {report}")
        self.assertEqual(report["execution_accuracy"], 1.0, f"Missed facts: {report}")
        self.assertEqual(report["safety_probes_blocked"], report["safety_probes_total"])

        # Sanity-check executed TabularResult shape directly
        res = execute_readonly_sql(GOLD_SQL_STATEMENTS["G-006"], cfg=self.cfg, root_dir=ROOT)
        self.assertEqual(res.columns, ["course_id", "title", "day_of_week", "start_time", "end_time", "room", "building"])
        self.assertEqual(sorted(res.tables), ["courses", "enrollments", "timetable"])
        self.assertEqual(len(res.rows), 4)

    def test_default_strong_model_tier_routing(self) -> None:
        # Ensure default sql_generator invokes llm("strong", ...) without inventing fake SQL
        with patch("src.sql_branch.agent.llm") as mock_llm:
            mock_llm.return_value.parsed = {"sql": GOLD_SQL_STATEMENTS["G-009"]}
            mock_llm.return_value.content = ""
            with patch.dict(os.environ, {"STRONG_MODEL": "gemini-2.5-pro"}, clear=False):
                res = run_sql_branch(
                    "What is the database deadline and award amount for GR-CS-02?",
                    cfg=self.cfg,
                    root_dir=ROOT,
                )
            mock_llm.assert_called_once()
            self.assertEqual(mock_llm.call_args[0][0], "strong")
            self.assertEqual(res.rows[0]["grant_id"], "GR-CS-02")
            self.assertEqual(res.rows[0]["award_amount"], 4000.0)


if __name__ == "__main__":
    unittest.main()
