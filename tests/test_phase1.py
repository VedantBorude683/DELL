"""Phase 1 verification tests (compatible with both pytest and python3 -m unittest)."""
from __future__ import annotations

import json
import re
import sqlite3
import unittest
from collections import Counter
from pathlib import Path

from src.config import AppConfig
from src.data_gen.pdf_writer import extract_pdf_text_simple

ROOT = Path(__file__).resolve().parent.parent


class TestPhase1Artifacts(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cfg = AppConfig.load(ROOT / "config.yaml")
        cls.schema_sql = (ROOT / "db" / "schema.sql").read_text(encoding="utf-8")
        cls.db_path = ROOT / cls.cfg.sqlite_mirror_path
        cls.pdf_dir = ROOT / cls.cfg.pdf_dir
        cls.gold_path = ROOT / cls.cfg.gold_path

    def test_postgres_schema_has_15_to_25_tables_and_distractors(self) -> None:
        tables = re.findall(r"CREATE TABLE IF NOT EXISTS\s+([a-zA-Z0-9_]+)", self.schema_sql)
        self.assertGreaterEqual(len(tables), 15)
        self.assertLessEqual(len(tables), 25)
        self.assertEqual(len(tables), 20)

        required_core = {
            "students",
            "departments",
            "courses",
            "enrollments",
            "grants",
            "fee_ledger",
            "timetable",
        }
        required_distractors = {
            "grant_applications",
            "grant_history",
            "fees",
            "fee_waivers",
            "student_semester_gpas",
            "scholarships_archive",
        }
        self.assertTrue(required_core.issubset(set(tables)))
        self.assertTrue(required_distractors.issubset(set(tables)))

        # GPA ambiguity columns on students
        self.assertIn("cumulative_gpa", self.schema_sql)
        self.assertIn("semester_gpa", self.schema_sql)
        # Soft conditions must NOT be columns on grants
        grants_block = self.schema_sql.split("CREATE TABLE IF NOT EXISTS grants")[1].split(");")[0]
        self.assertNotIn("requires_mentor", grants_block)
        self.assertNotIn("is_stackable", grants_block)

    def test_sqlite_mirror_populated_and_gpa_ambiguity_real(self) -> None:
        self.assertTrue(self.db_path.exists(), "SQLite mirror DB missing; run scripts/build_phase1.py")
        conn = sqlite3.connect(str(self.db_path))
        cur = conn.cursor()

        for table in self.cfg.allowlisted_tables:
            count = cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            self.assertGreater(count, 0, f"Table {table} should have seeded rows")

        # Liam O'Connor deliberately has cumulative_gpa (3.38) < 3.50 while semester_gpa (3.85) >= 3.50
        row = cur.execute(
            "SELECT cumulative_gpa, semester_gpa FROM students WHERE student_id = 'STU-1002'"
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertLess(row[0], 3.50)
        self.assertGreater(row[1], 3.50)

        # Expired grant GR-GEN-04
        expired = cur.execute(
            "SELECT deadline, status FROM grants WHERE grant_id = 'GR-GEN-04'"
        ).fetchone()
        self.assertEqual(expired, ("2026-06-30", "expired"))
        conn.close()

    def test_pdfs_generated_with_all_planted_cases(self) -> None:
        pdfs = sorted(self.pdf_dir.glob("*.pdf"))
        self.assertGreaterEqual(len(pdfs), 8)
        self.assertLessEqual(len(pdfs), 10)
        self.assertEqual(len(pdfs), 9)

        all_text_by_name: dict[str, str] = {}
        for pdf in pdfs:
            raw_head = pdf.read_bytes()[:8]
            self.assertTrue(raw_head.startswith(b"%PDF-1."), f"{pdf.name} is not a valid PDF")
            pages = extract_pdf_text_simple(pdf)
            joined = "\n".join(pages)
            self.assertGreater(len(joined.strip()), 100, f"{pdf.name} text extraction empty")
            all_text_by_name[pdf.name] = joined

        v1 = " ".join(all_text_by_name["01_undergrad_research_grants_v1_2025.pdf"].split())
        v2 = " ".join(all_text_by_name["02_undergrad_research_grants_v2_2026.pdf"].split())
        fees_pdf = " ".join(all_text_by_name["05_tuition_fees_and_waiver_handbook.pdf"].split())
        lib_pdf = " ".join(all_text_by_name["09_campus_code_and_library_access.pdf"].split())

        # Two versions with different effective dates
        self.assertIn("2025-09-01", v1)
        self.assertIn("2026-09-01", v2)

        # Vocabulary mismatch: submission window instead of deadline
        self.assertIn("submission window", v2.lower())

        # Soft conditions invisible to SQL
        self.assertIn("needs faculty mentor", v2.lower())
        self.assertIn("not stackable", v2.lower())

        # Conflict between PDF (December 1, 2026) and DB (2026-12-15) for GR-CS-01
        self.assertIn("December 1, 2026", v2)

        # Expired grant
        self.assertIn("GR-GEN-04", v2)
        self.assertIn("June 30, 2026", v2)

        # Embedded table inside PDF
        self.assertIn("Program / Residency", fees_pdf)
        self.assertIn("CS Out-of-State", fees_pdf)
        self.assertIn("$14,150", fees_pdf)

        # Indirect prompt injection test snippet present for Phase 2 ingestion guard
        self.assertIn("UNTRUSTED APPENDIX TEST SNIPPET", lib_pdf)

    def test_gold_set_stats_and_integrity(self) -> None:
        self.assertTrue(self.gold_path.exists())
        rows = [json.loads(line) for line in self.gold_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertGreaterEqual(len(rows), 80)

        routes = Counter(r["route"] for r in rows)
        for req_route in ("sql", "vector", "hybrid", "out_of_scope"):
            self.assertGreater(routes[req_route], 0, f"Missing route {req_route}")

        follow_ups = [r for r in rows if r["is_follow_up"]]
        adversarial = [r for r in rows if r["is_adversarial"]]
        paraphrases = [r for r in rows if r.get("paraphrase_group")]

        self.assertGreaterEqual(len(follow_ups), 10)
        self.assertGreaterEqual(len(adversarial), 10)
        self.assertGreaterEqual(len(paraphrases), 6)

        allowlisted = set(self.cfg.allowlisted_tables)
        for r in rows:
            for t in r.get("expected_tables", []):
                self.assertIn(t, allowlisted, f"Unknown expected table {t} in {r['query_id']}")


if __name__ == "__main__":
    unittest.main()
