import { useEffect, useState } from "react";
import { GoldSetExplorer } from "./components/GoldSetExplorer";
import { IngestionExplorer } from "./components/IngestionExplorer";
import { OverviewSection } from "./components/OverviewSection";
import { PdfHandbooksExplorer } from "./components/PdfHandbooksExplorer";
import { TablesExplorer } from "./components/TablesExplorer";
import { TopBar } from "./components/TopBar";
import type { ActiveSection, Phase1Overview, Phase1VerifyResult } from "./types/phase1";

export default function App() {
  const [activeSection, setActiveSection] = useState<ActiveSection>("overview");
  const [overview, setOverview] = useState<Phase1Overview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [verifyResult, setVerifyResult] = useState<Phase1VerifyResult | null>(null);
  const [isVerifying, setIsVerifying] = useState(false);

  useEffect(() => {
    fetch("/api/phase1/overview")
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data: Phase1Overview) => setOverview(data))
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load corpus"))
      .finally(() => setLoading(false));
  }, []);

  async function handleRunVerify() {
    setIsVerifying(true);
    try {
      const res = await fetch("/api/phase1/verify", { method: "POST" });
      const data: Phase1VerifyResult = await res.json();
      setVerifyResult(data);
      setActiveSection("overview");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Test execution failed");
    } finally {
      setIsVerifying(false);
    }
  }

  return (
    <div className="min-h-screen bg-white text-[#1D1D1F]">
      <TopBar
        activeSection={activeSection}
        onSelectSection={setActiveSection}
        onRunVerify={handleRunVerify}
        isVerifying={isVerifying}
      />

      <main className="mx-auto max-w-[1200px] px-6 py-12 lg:px-10 lg:py-16">
        {loading && (
          <div className="py-20 text-[15px] text-[#6E6E73]">
            Loading schema, handbooks, ingestion index, and evaluation set...
          </div>
        )}

        {error && (
          <div className="rounded-2xl border border-[#DC2626]/30 bg-[#DC2626]/5 p-6 text-[14px] text-[#DC2626]">
            {error}
          </div>
        )}

        {!loading && !error && overview && (
          <>
            {activeSection === "overview" && (
              <OverviewSection
                overview={overview}
                verifyResult={verifyResult}
                onNavigate={setActiveSection}
              />
            )}
            {activeSection === "tables" && <TablesExplorer tables={overview.tables} />}
            {activeSection === "handbooks" && <PdfHandbooksExplorer pdfs={overview.pdfs} />}
            {activeSection === "ingestion" && <IngestionExplorer />}
            {activeSection === "gold" && (
              <GoldSetExplorer
                queries={overview.gold_queries}
                stats={overview.gold_stats}
              />
            )}
          </>
        )}
      </main>

      <footer className="border-t border-black/[0.06] py-8">
        <div className="mx-auto flex max-w-[1200px] flex-wrap items-center justify-between gap-4 px-6 text-[12px] text-[#86868B] lg:px-10">
          <span>Alderwood University Hybrid RAG · Phase 7 Assistant, MCP & Evals</span>
          <span>PostgreSQL 16 + pgvector + FTS · BGE-M3 · sqlglot · LangGraph</span>
        </div>
      </footer>
    </div>
  );
}
