"""Phase 4 verification tests: hybrid vector+FTS RRF, metadata filters, reranker, 1x HyDE retry, CRAG, and Recall@k ablation."""
from __future__ import annotations

import sqlite3
import unittest
from dataclasses import replace
from pathlib import Path

from src.config import AppConfig
from src.doc_branch import (
    MetadataFilter,
    Passage,
    evaluate_doc_recall_ablation,
    hybrid_search_chunks,
    retrieve_passages,
    search_documents,
)
from src.ingestion.pdf_ingestor import ingest_pdfs
from src.ingestion.schema_indexer import build_schema_index

ROOT = Path(__file__).resolve().parent.parent


class TestPhase4DocumentBranch(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cfg = AppConfig.load(ROOT / "config.yaml")
        db_path = ROOT / cls.cfg.sqlite_mirror_path
        conn = sqlite3.connect(str(db_path))
        chunk_count = conn.execute("SELECT COUNT(*) FROM document_chunks").fetchone()[0]
        conn.close()
        if chunk_count == 0:
            ingest_pdfs(ROOT, cfg=cls.cfg, use_llm_fallback=False)
            build_schema_index(ROOT, cfg=cls.cfg)

    def test_passage_contract_citation_and_pdf_table_retrieval(self) -> None:
        passages = retrieve_passages(
            "According to the Tuition & Waiver matrix table, what is the maximum merit waiver for CS Out-of-State students?",
            cfg=self.cfg,
            root_dir=ROOT,
        )
        self.assertGreaterEqual(len(passages), 1)
        for p in passages:
            self.assertIsInstance(p, Passage)
            self.assertTrue(p.text)
            self.assertTrue(p.doc_id)
            self.assertTrue(p.version)
            self.assertGreaterEqual(p.page, 1)
            self.assertIn(p.doc_id, p.citation)
            self.assertIn(p.version, p.citation)

        tbl_hits = [p for p in passages if p.chunk_type == "table"]
        self.assertGreaterEqual(len(tbl_hits), 1)
        self.assertEqual(tbl_hits[0].doc_id, "HANDBOOK-FEES-WAIVERS")
        self.assertIsNotNone(tbl_hits[0].structured_table_json)

    def test_hybrid_rrf_tracks_vector_and_fts_ranks(self) -> None:
        fused, backend = hybrid_search_chunks(
            "submission window Turing Undergraduate Research Fellowship GR-CS-01",
            vector_top_k=12,
            fts_top_k=12,
            rrf_k=60,
            cfg=self.cfg,
            root_dir=ROOT,
        )
        self.assertIn("rrf", backend)
        self.assertGreaterEqual(len(fused), 3)
        top = fused[0]
        self.assertIsNotNone(top["vector_rank"])
        self.assertIsNotNone(top["fts_rank"])
        expected_rrf = round((1.0 / (60 + top["vector_rank"])) + (1.0 / (60 + top["fts_rank"])), 6)
        self.assertAlmostEqual(top["rrf_score"], expected_rrf, places=6)

    def test_metadata_filters_restrict_candidates_before_fusion(self) -> None:
        flt = MetadataFilter(grant_ids=("GR-CS-01",), version="v2.0")
        res = search_documents(
            "What is the submission window and mentor rule?",
            filters=flt,
            cfg=self.cfg,
            root_dir=ROOT,
        )
        self.assertGreaterEqual(len(res.passages), 1)
        for p in res.passages:
            self.assertEqual(p.grant_id, "GR-CS-01")
            self.assertEqual(p.version, "v2.0")

        # Version-only filter on v1.0
        res_v1 = search_documents(
            "submission window Turing Fellowship",
            filters=MetadataFilter(doc_ids=("HANDBOOK-RESEARCH-GRANTS",), version="v1.0"),
            cfg=self.cfg,
            root_dir=ROOT,
        )
        self.assertGreaterEqual(len(res_v1.passages), 1)
        self.assertTrue(all(p.version == "v1.0" for p in res_v1.passages))

    def test_hyde_single_retry_triggered_below_threshold_and_respects_flag(self) -> None:
        hyde_calls = {"n": 0}

        def custom_hyde(q: str) -> str:
            hyde_calls["n"] += 1
            return "Turing Undergraduate Research Fellowship GR-CS-01 submission window December 1, 2026 faculty mentor sponsorship"

        # Raise threshold so HyDE is guaranteed to trigger at most once
        high_thresh_cfg = replace(
            self.cfg,
            raw={
                **self.cfg.raw,
                "retrieval": {**self.cfg.raw["retrieval"], "rerank_score_threshold": 0.98},
            },
        )
        res = search_documents(
            "When can third year computing undergrads turn in Turing materials?",
            cfg=high_thresh_cfg,
            root_dir=ROOT,
            hyde_generator=custom_hyde,
        )
        self.assertEqual(hyde_calls["n"], 1)
        self.assertTrue(res.trace["hyde_triggered"])
        self.assertEqual(res.trace["hyde_retry_count"], 1)
        self.assertGreaterEqual(len(res.passages), 1)
        self.assertEqual(res.passages[0].doc_id, "HANDBOOK-RESEARCH-GRANTS")

        # Verify use_hyde=False skips HyDE even when score < threshold
        no_hyde_cfg = replace(
            high_thresh_cfg,
            flags=replace(high_thresh_cfg.flags, use_hyde=False),
        )
        hyde_calls["n"] = 0
        res_off = search_documents(
            "When can third year computing undergrads turn in Turing materials?",
            cfg=no_hyde_cfg,
            root_dir=ROOT,
            hyde_generator=custom_hyde,
        )
        self.assertEqual(hyde_calls["n"], 0)
        self.assertFalse(res_off.trace["hyde_triggered"])
        self.assertEqual(res_off.trace["hyde_retry_count"], 0)

    def test_crag_grader_filters_irrelevant_passages_and_respects_flag(self) -> None:
        def strict_crag(_q: str, passages: list[Passage]) -> list[dict[str, str]]:
            out = []
            for p in passages:
                grade = "relevant" if p.doc_id == "HANDBOOK-INTL-FUNDING" else "irrelevant"
                out.append({"chunk_id": p.chunk_id, "grade": grade, "reason": "unit_test"})
            return out

        res_crag = search_documents(
            "What are the rules for F-1/J-1 international students receiving research stipends above $2,000?",
            cfg=self.cfg,
            root_dir=ROOT,
            crag_grader=strict_crag,
        )
        self.assertGreaterEqual(len(res_crag.passages), 1)
        self.assertTrue(all(p.doc_id == "HANDBOOK-INTL-FUNDING" for p in res_crag.passages))
        self.assertTrue(all(p.crag_grade == "relevant" for p in res_crag.passages))

        # Flag OFF skips CRAG grading
        no_crag_cfg = replace(self.cfg, flags=replace(self.cfg.flags, use_crag_grader=False))
        res_no_crag = search_documents(
            "What are the rules for F-1/J-1 international students receiving research stipends above $2,000?",
            cfg=no_crag_cfg,
            root_dir=ROOT,
            crag_grader=strict_crag,
        )
        self.assertTrue(all(p.crag_grade == "not_run" for p in res_no_crag.passages))

    def test_recall_at_k_ablation_hyde_and_reranker_on_and_off(self) -> None:
        report = evaluate_doc_recall_ablation(ROOT, cfg=self.cfg, k_values=(3, 5))
        self.assertGreaterEqual(report["evaluated_queries"], 45)
        by_mode = {m["mode"]: m for m in report["ablation"]}
        self.assertEqual(set(by_mode.keys()), {"rrf_only", "rrf_rerank", "rrf_hyde", "full_phase4"})

        # Reranker improves Recall@5 and MRR over plain RRF
        self.assertGreater(by_mode["rrf_rerank"]["recall_at_5"], by_mode["rrf_only"]["recall_at_5"])
        self.assertGreater(by_mode["rrf_rerank"]["mrr"], by_mode["rrf_only"]["mrr"])

        # Full Phase 4 meets strong Recall@3/5 and MRR targets
        full = by_mode["full_phase4"]
        self.assertGreaterEqual(full["recall_at_3"], 0.90)
        self.assertGreaterEqual(full["recall_at_5"], 0.95)
        self.assertEqual(full["any_hit_at_5"], 1.0)
        self.assertGreaterEqual(full["mrr"], 0.95)
        self.assertGreaterEqual(full["hyde_triggers"], 1)


if __name__ == "__main__":
    unittest.main()
