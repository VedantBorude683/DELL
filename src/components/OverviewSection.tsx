import { useState } from "react";
import type { ActiveSection, Phase1Overview, Phase1VerifyResult } from "../types/phase1";
import { AssistantTraceExplorer } from "./AssistantTraceExplorer";
import { SynthesisExplorer } from "./SynthesisExplorer";

interface OverviewSectionProps {
  overview: Phase1Overview;
  verifyResult: Phase1VerifyResult | null;
  onNavigate: (section: ActiveSection) => void;
}

export function OverviewSection({
  overview,
  verifyResult,
  onNavigate,
}: OverviewSectionProps) {
  const [subTab, setSubTab] = useState<"assistant" | "synthesis" | "corpus">("assistant");
  const operationalRows = overview.tables.reduce((acc, t) => acc + t.row_count, 0);
  const distractorCount = overview.tables.filter((t) => t.category === "distractor").length;

  const plantedCases = [
    {
      title: "GPA Column Ambiguity",
      detail: "students carries both cumulative_gpa and semester_gpa; Liam O'Connor (STU-1002) has 3.38 cumulative vs 3.85 semester GPA.",
      location: "students · HANDBOOK-ACADEMIC-STANDING",
    },
    {
      title: "Vocabulary Mismatch",
      detail: "Policy handbooks specify 'submission window' instead of the SQL column term 'deadline' across active fellowship guides.",
      location: "02_undergrad_research_grants_v2_2026.pdf",
    },
    {
      title: "DB vs. PDF Deadline Conflict",
      detail: "Turing Fellowship (GR-CS-01) lists 2026-12-15 in Postgres grants, while Committee Amendment 2026-B sets December 1, 2026.",
      location: "grants vs HANDBOOK-RESEARCH-GRANTS v2.0",
    },
    {
      title: "Soft Conditions Invisible to SQL",
      detail: "Grants require faculty mentor sponsorship, cleanroom/IRB clearance, and non-stackable rules omitted from SQL columns.",
      location: "Handbooks 02, 04, 07, 08",
    },
    {
      title: "Embedded PDF Matrix & Expired Grant",
      detail: "Tuition & Waiver Handbook embeds a 5-row structured fee matrix; GR-GEN-04 expired on 2026-06-30.",
      location: "05_tuition_fees_and_waiver_handbook.pdf · GR-GEN-04",
    },
    {
      title: "Two Versioned Handbooks",
      detail: "Research Grants Handbook v1.0 (2025-09-01) is superseded by v2.0 (2026-09-01) with updated caps and stacking rules.",
      location: "01_..._v1_2025.pdf · 02_..._v2_2026.pdf",
    },
  ];

  return (
    <div className="space-y-12">
      {/* Header + Segmented View Switcher */}
      <section className="border-b border-black/[0.08] pb-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-[13px] font-medium tracking-[0.01em] text-[#0071E3]">
              {subTab === "assistant"
                ? "Phase 7 · Unified Assistant, Trace Panel, FastMCP & Gold Eval"
                : subTab === "synthesis"
                ? "Phase 6 · Grounded Claim Synthesis & Code Verification"
                : "Phase 1 · Synthetic Data & Gold Evaluation Corpus"}
            </p>
            <h1 className="mt-2 max-w-3xl text-[36px] font-semibold leading-[1.1] tracking-[-0.03em] text-[#1D1D1F] sm:text-[44px]">
              Exact relational records meet verified policy handbooks.
            </h1>
          </div>

          <div
            role="tablist"
            aria-label="Overview workspace views"
            className="flex flex-wrap items-center gap-1 rounded-lg bg-[#F5F5F7] p-1"
          >
            <button
              type="button"
              role="tab"
              aria-selected={subTab === "assistant"}
              onClick={() => setSubTab("assistant")}
              className={`rounded-md px-3.5 py-1.5 text-[12px] font-medium transition-colors whitespace-nowrap shrink-0 ${
                subTab === "assistant"
                  ? "bg-white text-[#1D1D1F] shadow-xs"
                  : "text-[#6E6E73] hover:text-[#1D1D1F]"
              }`}
            >
              Assistant & Trace (Phase 7)
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={subTab === "synthesis"}
              onClick={() => setSubTab("synthesis")}
              className={`rounded-md px-3.5 py-1.5 text-[12px] font-medium transition-colors whitespace-nowrap shrink-0 ${
                subTab === "synthesis"
                  ? "bg-white text-[#1D1D1F] shadow-xs"
                  : "text-[#6E6E73] hover:text-[#1D1D1F]"
              }`}
            >
              Synthesis & Verifier
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={subTab === "corpus"}
              onClick={() => setSubTab("corpus")}
              className={`rounded-md px-3.5 py-1.5 text-[12px] font-medium transition-colors whitespace-nowrap shrink-0 ${
                subTab === "corpus"
                  ? "bg-white text-[#1D1D1F] shadow-xs"
                  : "text-[#6E6E73] hover:text-[#1D1D1F]"
              }`}
            >
              Corpus Overview
            </button>
          </div>
        </div>
      </section>

      {subTab === "assistant" && !verifyResult ? (
        <AssistantTraceExplorer />
      ) : subTab === "synthesis" && !verifyResult ? (
        <SynthesisExplorer />
      ) : (
        <div className="space-y-20">
          <section>
            <p className="max-w-2xl text-[17px] leading-[1.6] text-[#6E6E73]">
              Built for Alderwood University as a reproducible foundation: 20 PostgreSQL 16 tables with deliberate distractors, 9 generated PDF handbooks with planted policy conflicts, and an 86-query evaluation set.
            </p>

        {/* 4-column summary figures */}
        <div className="mt-12 grid grid-cols-2 gap-6 border-t border-black/[0.08] pt-8 sm:grid-cols-4">
          <button
            type="button"
            onClick={() => onNavigate("tables")}
            className="text-left transition-opacity hover:opacity-75 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[#0071E3]"
          >
            <div className="font-mono-tabular text-[34px] font-semibold tracking-[-0.03em] text-[#1D1D1F]">
              {overview.tables.length}
            </div>
            <div className="mt-1 text-[13px] text-[#6E6E73]">
              Postgres Tables · {distractorCount} distractors
            </div>
          </button>

          <button
            type="button"
            onClick={() => onNavigate("tables")}
            className="text-left transition-opacity hover:opacity-75 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[#0071E3]"
          >
            <div className="font-mono-tabular text-[34px] font-semibold tracking-[-0.03em] text-[#1D1D1F]">
              {operationalRows}
            </div>
            <div className="mt-1 text-[13px] text-[#6E6E73]">
              Seeded Operational Rows
            </div>
          </button>

          <button
            type="button"
            onClick={() => onNavigate("handbooks")}
            className="text-left transition-opacity hover:opacity-75 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[#0071E3]"
          >
            <div className="font-mono-tabular text-[34px] font-semibold tracking-[-0.03em] text-[#1D1D1F]">
              {overview.pdfs.length}
            </div>
            <div className="mt-1 text-[13px] text-[#6E6E73]">
              Generated Handbook PDFs
            </div>
          </button>

          <button
            type="button"
            onClick={() => onNavigate("gold")}
            className="text-left transition-opacity hover:opacity-75 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[#0071E3]"
          >
            <div className="font-mono-tabular text-[34px] font-semibold tracking-[-0.03em] text-[#1D1D1F]">
              {overview.gold_stats.total}
            </div>
            <div className="mt-1 text-[13px] text-[#6E6E73]">
              Gold Set Queries · 4 routes
            </div>
          </button>
        </div>
      </section>

      {/* Live verification output if user ran tests */}
      {verifyResult && (
        <section
          aria-live="polite"
          className="rounded-2xl bg-[#F5F5F7] p-6 sm:p-8"
        >
          <div className="flex flex-wrap items-baseline justify-between gap-4">
            <h2 className="text-[19px] font-semibold tracking-[-0.02em] text-[#1D1D1F]">
              Automated Test Suite (Phases 1–7) — {verifyResult.passed ? "Passed" : "Failed"}
            </h2>
            <span className="font-mono-tabular text-[13px] text-[#6E6E73]">
              python3 -m unittest discover -s tests -p "test_*.py" -v
            </span>
          </div>
          <pre className="font-mono-tabular mt-4 overflow-x-auto whitespace-pre-wrap text-[12px] leading-[1.6] text-[#1D1D1F]">
            {verifyResult.output}
          </pre>
        </section>
      )}

      {/* Planted Test Conditions */}
      <section>
        <div className="flex flex-wrap items-end justify-between gap-4 border-b border-black/[0.08] pb-5">
          <div>
            <h2 className="text-[26px] font-semibold tracking-[-0.02em] text-[#1D1D1F]">
              Planted Evaluation Scenarios
            </h2>
            <p className="mt-1 text-[15px] text-[#6E6E73]">
              Deliberate ambiguities and conflicts engineered into Phase 1 data for downstream routing and verification.
            </p>
          </div>
          <button
            type="button"
            onClick={() => onNavigate("handbooks")}
            className="text-[14px] font-medium text-[#0071E3] hover:underline whitespace-nowrap shrink-0"
          >
            Inspect Handbooks
          </button>
        </div>

        <div className="mt-8 grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
          {plantedCases.map((item) => (
            <div
              key={item.title}
              className="rounded-2xl bg-[#F5F5F7] p-6"
            >
              <h3 className="text-[16px] font-semibold tracking-[-0.01em] text-[#1D1D1F]">
                {item.title}
              </h3>
              <p className="mt-2.5 text-[14px] leading-[1.55] text-[#6E6E73]">
                {item.detail}
              </p>
              <p className="font-mono-tabular mt-4 text-[12px] text-[#86868B]">
                {item.location}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* Gold Set & Feature Flags summary */}
      <section className="grid grid-cols-1 gap-10 border-t border-black/[0.08] pt-12 lg:grid-cols-2">
        <div>
          <h2 className="text-[22px] font-semibold tracking-[-0.02em] text-[#1D1D1F]">
            Gold Set Breakdown
          </h2>
          <p className="mt-1 text-[14px] text-[#6E6E73]">
            eval/gold.jsonl · {overview.gold_stats.total} curated queries
          </p>
          <dl className="mt-6 divide-y divide-black/[0.06] border-y border-black/[0.06]">
            {[
              ["SQL Route", overview.gold_stats.routes.sql ?? 0],
              ["Vector Route", overview.gold_stats.routes.vector ?? 0],
              ["Hybrid Route", overview.gold_stats.routes.hybrid ?? 0],
              ["Out of Scope", overview.gold_stats.routes.out_of_scope ?? 0],
              ["Multi-Turn Follow-ups", overview.gold_stats.follow_ups],
              ["Adversarial & Prompt Injection", overview.gold_stats.adversarial],
              ["Paraphrased Query Variants", overview.gold_stats.paraphrased],
            ].map(([label, val]) => (
              <div key={String(label)} className="flex items-center justify-between py-3 text-[14px]">
                <dt className="text-[#6E6E73]">{label}</dt>
                <dd className="font-mono-tabular font-medium text-[#1D1D1F]">{val}</dd>
              </div>
            ))}
          </dl>
        </div>

        <div>
          <h2 className="text-[22px] font-semibold tracking-[-0.02em] text-[#1D1D1F]">
            Configured Feature Flags
          </h2>
          <p className="mt-1 text-[14px] text-[#6E6E73]">
            config.yaml · Reference date {overview.current_date}
          </p>
          <dl className="mt-6 divide-y divide-black/[0.06] border-y border-black/[0.06]">
            {Object.entries(overview.feature_flags).map(([flag, enabled]) => (
              <div key={flag} className="flex items-center justify-between py-3 text-[14px]">
                <dt className="font-mono-tabular text-[#1D1D1F]">{flag}</dt>
                <dd className="font-mono-tabular text-[#6E6E73]">
                  {enabled ? "Enabled" : "Disabled"}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      </section>
        </div>
      )}
    </div>
  );
}
