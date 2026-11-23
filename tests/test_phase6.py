"""Phase 6 verification tests: JSON claims, own-source grounding, policy citations, LLM claim check, conflicts/expiry/missing evidence, structured sections, and 1-retry regeneration."""
from __future__ import annotations

import unittest
from pathlib import Path

from src.config import AppConfig
from src.orchestrator import build_orchestrator_graph, run_orchestrator_turn
from src.synthesis import (
    Claim,
    SourceRegistry,
    synthesize_answer,
    verify_claims,
)

ROOT = Path(__file__).resolve().parent.parent


class TestPhase6SynthesisAndVerification(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cfg = AppConfig.load(ROOT / "config.yaml")
        cls.graph = build_orchestrator_graph(cfg=cls.cfg, root_dir=ROOT)

    def test_structured_sections_and_never_flat_eligible(self) -> None:
        state, _ = run_orchestrator_turn(
            "I'm a 3rd-year CS student. Which research grants can I apply for and what are the deadlines?",
            persona_student_id="STU-1001",
            graph=self.graph,
        )
        syn = synthesize_answer(state, cfg=self.cfg, root_dir=ROOT)
        self.assertTrue(syn.verification.passed)
        self.assertEqual(syn.regeneration_count, 0)
        self.assertGreaterEqual(len(syn.claims), 6)
        self.assertIn("## Meets hard criteria", syn.answer_markdown)
        self.assertIn("## Still verify", syn.answer_markdown)
        self.assertNotIn("you're eligible", syn.answer_markdown.lower())
        self.assertNotIn("you are eligible", syn.answer_markdown.lower())
        # Every policy claim carries an explicit handbook citation
        for c in syn.claims:
            if c.claim_type == "policy":
                self.assertTrue(c.citation)

    def test_code_verifier_enforces_own_source_row_and_passage_not_global_presence(self) -> None:
        reg = SourceRegistry(
            sql_rows={
                "sql:row:0": {"grant_id": "GR-CS-01", "award_amount": 5500, "deadline": "2026-12-15"},
                "sql:row:1": {"grant_id": "GR-CS-02", "award_amount": 4000, "deadline": "2026-12-20"},
            },
            doc_passages={
                "doc:chunk_a": {
                    "chunk_id": "chunk_a",
                    "doc_id": "HANDBOOK-RESEARCH-GRANTS",
                    "version": "v2.0",
                    "citation": "[HANDBOOK-RESEARCH-GRANTS v2.0, p.1, GR-CS-01]",
                    "text": "GR-CS-01 needs faculty mentor sponsorship and is not stackable.",
                },
                "doc:chunk_b": {
                    "chunk_id": "chunk_b",
                    "doc_id": "HANDBOOK-ETHICS-TRAVEL",
                    "version": "v1.0",
                    "citation": "[HANDBOOK-ETHICS-TRAVEL v1.0, p.1, GR-BIO-01]",
                    "text": "GR-BIO-01 requires IBC or IRB protocol approval before release.",
                },
            },
        )

        # Value 4000 exists in sql:row:1, NOT in sql:row:0 -> MUST fail own-source check!
        cross_row_sql_claim = Claim(
            entity="GR-CS-01",
            field="award_amount",
            value=4000,
            source_id="sql:row:0",
            claim_type="sql",
            section="meets_hard_criteria",
        )
        # Value "IBC or IRB protocol approval" exists in doc:chunk_b, NOT in doc:chunk_a -> MUST fail own-source check!
        cross_passage_policy_claim = Claim(
            entity="GR-CS-01",
            field="policy_rule",
            value="IBC or IRB protocol approval required",
            source_id="doc:chunk_a",
            claim_type="policy",
            section="still_verify",
            citation="[HANDBOOK-RESEARCH-GRANTS v2.0, p.1, GR-CS-01]",
        )
        # Missing citation on policy claim -> MUST fail missing_citation check!
        uncited_policy_claim = Claim(
            entity="GR-CS-01",
            field="policy_rule",
            value="needs faculty mentor sponsorship",
            source_id="doc:chunk_a",
            claim_type="policy",
            section="still_verify",
            citation="",
        )

        ver = verify_claims(
            [cross_row_sql_claim, cross_passage_policy_claim, uncited_policy_claim],
            reg,
            cfg=self.cfg,
            use_llm_claim_check=False,
        )
        self.assertFalse(ver.passed)
        self.assertEqual(len(ver.issues), 3)
        types = [i.check_type for i in ver.issues]
        self.assertEqual(types, ["value_mismatch", "value_mismatch", "missing_citation"])

    def test_llm_claim_check_flag_runs_and_blocks_contradiction(self) -> None:
        reg = SourceRegistry(
            doc_passages={
                "doc:chunk_a": {
                    "chunk_id": "chunk_a",
                    "doc_id": "HANDBOOK-RESEARCH-GRANTS",
                    "version": "v2.0",
                    "citation": "[HANDBOOK-RESEARCH-GRANTS v2.0, p.1, GR-CS-01]",
                    "text": "GR-CS-01 is not stackable with other internal awards.",
                }
            }
        )
        # Claim lexically overlaps ("stackable", "internal", "awards") cleanly unless LLM check catches contradiction/unsupported nuance
        subtle_claim = Claim(
            entity="GR-CS-01",
            field="policy_rule",
            value="internal awards stackable GR-CS-01",
            source_id="doc:chunk_a",
            claim_type="policy",
            section="still_verify",
            citation="[HANDBOOK-RESEARCH-GRANTS v2.0, p.1, GR-CS-01]",
        )

        # Flag ON triggers LLM claim check
        calls = {"n": 0}

        def strict_checker(_claim, _passage):
            calls["n"] += 1
            return {"supported": False, "contradiction": True, "reason": "Passage explicitly says NOT stackable."}

        ver_on = verify_claims(
            [subtle_claim],
            reg,
            cfg=self.cfg,
            use_llm_claim_check=True,
            claim_checker_fn=strict_checker,
        )
        self.assertTrue(ver_on.llm_check_ran)
        self.assertEqual(calls["n"], 1)
        self.assertFalse(ver_on.passed)
        self.assertEqual(ver_on.issues[0].check_type, "llm_claim_check")

        # Flag OFF skips LLM claim check
        calls["n"] = 0
        ver_off = verify_claims(
            [subtle_claim],
            reg,
            cfg=self.cfg,
            use_llm_claim_check=False,
            claim_checker_fn=strict_checker,
        )
        self.assertFalse(ver_off.llm_check_ran)
        self.assertEqual(ver_off.llm_check_backend, "disabled")
        self.assertEqual(calls["n"], 0)

    def test_conflict_deadline_passed_and_missing_evidence_checks(self) -> None:
        # 1. DB vs PDF conflict on GR-CS-01 (2026-12-15 vs December 1, 2026)
        st_conflict, _ = run_orchestrator_turn(
            "Why is there a deadline mismatch on GR-CS-01 between the university database and the handbook?",
            persona_student_id="STU-1001",
            graph=self.graph,
        )
        syn_conflict = synthesize_answer(st_conflict, cfg=self.cfg, root_dir=ROOT)
        self.assertTrue(any(c.entity == "GR-CS-01" and c.field == "deadline" for c in syn_conflict.conflicts))
        self.assertIn("2026-12-15", syn_conflict.answer_markdown)
        self.assertIn("December 1, 2026", syn_conflict.answer_markdown)

        # 2. Expired grant check on GR-GEN-04 (deadline 2026-06-30 < 2026-11-23)
        st_exp, _ = run_orchestrator_turn(
            "Can I still apply for the Summer 2026 Heritage Innovation Grant (GR-GEN-04)?",
            persona_student_id="STU-1001",
            graph=self.graph,
        )
        syn_exp = synthesize_answer(st_exp, cfg=self.cfg, root_dir=ROOT)
        self.assertTrue(any(d.entity == "GR-GEN-04" and d.status == "expired" for d in syn_exp.deadline_notices))
        self.assertIn("Deadline Passed", syn_exp.answer_markdown)

        # 3. Zero-row sequential missing evidence check
        st_zero, _ = run_orchestrator_turn(
            "I'm a 3rd-year CS student. Which open research grants require a minimum GPA of 4.90 and what are their rules?",
            persona_student_id="STU-1001",
            graph=self.graph,
        )
        syn_zero = synthesize_answer(st_zero, cfg=self.cfg, root_dir=ROOT)
        self.assertTrue(any("0 matching records" in m for m in syn_zero.missing_evidence_notices))

    def test_regeneration_once_then_pass_or_return_with_warning(self) -> None:
        st, _ = run_orchestrator_turn(
            "What is the database deadline and award amount for GR-CS-02?",
            persona_student_id="STU-1001",
            graph=self.graph,
        )

        # Scenario A: Attempt 1 fails grounded check, Attempt 2 fixes -> passes with regeneration_count == 1
        attempts_a = {"n": 0}

        def heal_on_second_writer(msgs, _schema):
            attempts_a["n"] += 1
            if attempts_a["n"] == 1:
                return {
                    "claims": [
                        {
                            "entity": "GR-CS-02",
                            "field": "award_amount",
                            "value": "999999",  # fabricated!
                            "source_id": "sql:row:0",
                            "claim_type": "sql",
                            "section": "meets_hard_criteria",
                        }
                    ]
                }
            # Verify error feedback was fed back into retry prompt
            joined = "\n".join(m["content"] for m in msgs)
            self.assertIn("PREVIOUS ATTEMPT FAILED VERIFICATION", joined)
            return {
                "claims": [
                    {
                        "entity": "GR-CS-02",
                        "field": "award_amount",
                        "value": "4000",
                        "source_id": "sql:row:0",
                        "claim_type": "sql",
                        "section": "meets_hard_criteria",
                    }
                ]
            }

        syn_healed = synthesize_answer(st, cfg=self.cfg, root_dir=ROOT, writer_fn=heal_on_second_writer)
        self.assertEqual(attempts_a["n"], 2)
        self.assertEqual(syn_healed.regeneration_count, 1)
        self.assertTrue(syn_healed.verification.passed)
        self.assertEqual(syn_healed.warnings, [])

        # Scenario B: Both Attempt 1 and Attempt 2 stay ungrounded -> stop after 1 regeneration and return warning!
        attempts_b = {"n": 0}

        def stubborn_bad_writer(_msgs, _schema):
            attempts_b["n"] += 1
            return {
                "claims": [
                    {
                        "entity": "GR-CS-02",
                        "field": "award_amount",
                        "value": "888888",
                        "source_id": "sql:row:0",
                        "claim_type": "sql",
                        "section": "meets_hard_criteria",
                    }
                ]
            }

        syn_warn = synthesize_answer(st, cfg=self.cfg, root_dir=ROOT, writer_fn=stubborn_bad_writer)
        self.assertEqual(attempts_b["n"], 2)  # Initial + max 1 regeneration
        self.assertEqual(syn_warn.regeneration_count, 1)
        self.assertFalse(syn_warn.verification.passed)
        self.assertGreaterEqual(len(syn_warn.warnings), 1)
        self.assertIn("Verification Warning", syn_warn.answer_markdown)


if __name__ == "__main__":
    unittest.main()
