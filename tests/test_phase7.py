"""Phase 7 tests: Assistant telemetry, FastMCP Inspector stdio JSON-RPC, FastAPI handlers, Streamlit trace model, and eval.run."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app_streamlit import build_trace_panel_payload
from eval.run import run_gold_evaluation
from mcp_server.inspector_client import run_mcp_stdio_session
from src.api.main import handle_chat, handle_health, handle_mcp_inspect, handle_personas
from src.assistant import run_assistant_query
from src.config import AppConfig

ROOT = Path(__file__).resolve().parent.parent


class TestPhase7UiMcpAndEvals(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cfg = AppConfig.load(ROOT / "config.yaml")

    def test_assistant_runner_trace_latency_and_multi_turn(self) -> None:
        t1 = run_assistant_query(
            "I'm a 3rd-year CS student. Which research grants can I apply for and what are the deadlines?",
            persona_student_id="STU-1001",
            feature_flags_override={"use_llm_claim_check": False},
            cfg=self.cfg,
            root_dir=ROOT,
        )
        self.assertEqual(t1["plan"]["route"], "hybrid")
        self.assertEqual(t1["synthesis"]["verification"]["llm_check_backend"], "disabled")
        self.assertTrue(t1["synthesis"]["verification"]["passed"])
        steps = [s["step"] for s in t1["step_trace"]]
        self.assertEqual(
            steps,
            [
                "Identity Check",
                "Router & Planner",
                "SQL Branch",
                "Document Branch",
                "Synthesis & Verifier",
            ],
        )
        self.assertIn("total_latency_ms", t1["token_summary"])
        self.assertGreater(t1["token_summary"]["total_latency_ms"], 0.0)

        # Follow-up turn preserves memory
        t2 = run_assistant_query(
            "What about GR-CS-01 — is it stackable with my department lab stipend?",
            persona_student_id="STU-1001",
            memory=t1["memory"],
            feature_flags_override={"use_llm_claim_check": True},
            cfg=self.cfg,
            root_dir=ROOT,
        )
        self.assertEqual(t2["plan"]["target_grant_ids"][0], "GR-CS-01")
        self.assertTrue(t2["synthesis"]["verification"]["passed"])

        # Streamlit trace view-model matches all required fields
        vm = build_trace_panel_payload(t2)
        for key in ("route", "plan", "sql", "retrieved_chunks", "verification_result", "step_latency", "token_cost"):
            self.assertIn(key, vm)

    def test_fastmcp_server_stdio_inspector_safe_sql_and_blocks_mutations(self) -> None:
        session = run_mcp_stdio_session(
            tool_calls=[
                {"name": "list_allowlisted_tables", "arguments": {}},
                {
                    "name": "safe_sql_query",
                    "arguments": {"sql": "SELECT grant_id, grant_name, award_amount, deadline FROM grants WHERE status = 'open' ORDER BY grant_id"},
                },
                {
                    "name": "safe_sql_query",
                    "arguments": {"sql": "DROP TABLE students; --"},
                },
                {
                    "name": "safe_sql_query",
                    "arguments": {"sql": "SELECT * FROM students; DELETE FROM students;"},
                },
            ],
            root_dir=ROOT,
        )
        self.assertEqual(session["returncode"], 0)
        self.assertEqual(session["server_info"]["name"], "alderwood-hybrid-rag")
        tool_names = [t["name"] for t in session["tools"]]
        self.assertIn("safe_sql_query", tool_names)
        self.assertIn("list_allowlisted_tables", tool_names)
        self.assertIn("search_schema_index", tool_names)

        # Tool call 0: allowlisted tables (18 operational tables)
        allow_res = session["call_results"][0]
        self.assertFalse(allow_res["isError"])
        self.assertEqual(allow_res["output"]["count"], 18)

        # Tool call 1: valid SELECT succeeds
        ok_sql = session["call_results"][1]
        self.assertFalse(ok_sql["isError"])
        self.assertTrue(ok_sql["output"]["ok"])
        self.assertGreaterEqual(ok_sql["output"]["row_count"], 4)

        # Tool call 2 & 3: destructive SQL mutations strictly blocked
        for blocked_call in (session["call_results"][2], session["call_results"][3]):
            self.assertTrue(blocked_call["isError"])
            self.assertTrue(blocked_call["output"]["blocked"])
            self.assertEqual(blocked_call["output"]["stage"], "sqlglot_guard")

    def test_fastapi_backend_handlers(self) -> None:
        health = handle_health()
        self.assertEqual(health["status"], "ok")
        personas = handle_personas()
        self.assertGreaterEqual(len(personas["personas"]), 12)
        chat_res = handle_chat(
            {"query": "What is my current cumulative GPA and academic year?", "persona_student_id": "STU-1001"}
        )
        self.assertEqual(chat_res["plan"]["route"], "sql")
        self.assertTrue(chat_res["synthesis"]["verification"]["passed"])
        mcp_res = handle_mcp_inspect(
            {"tool_calls": [{"name": "search_schema_index", "arguments": {"query": "grant deadline", "top_k": 3}}]}
        )
        self.assertEqual(mcp_res["returncode"], 0)
        self.assertFalse(mcp_res["call_results"][0]["isError"])

    def test_eval_run_harness_subset_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "eval_subset.json"
            report = run_gold_evaluation(
                root_dir=ROOT,
                cfg=self.cfg,
                limit=10,
                output_path=out_file,
            )
            self.assertTrue(out_file.exists())
            self.assertEqual(report["total_queries"], 10)
            self.assertEqual(report["route_accuracy"], 1.0)
            self.assertEqual(report["verification_pass_rate"], 1.0)
            self.assertEqual(report["format_compliant_rate"], 1.0)
            self.assertGreaterEqual(report["table_recall_at_3"], 0.85)
            self.assertGreaterEqual(report["answer_fact_coverage"], 0.90)


if __name__ == "__main__":
    unittest.main()
