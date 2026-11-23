import { useEffect, useState } from "react";
import type { Phase4Overview, Phase4SearchResponse } from "../types/phase1";

const PRESET_DOC_QUERIES = [
  "When does the submission window close for GR-CS-01 under the latest policy?",
  "Can I stack the Turing Fellowship with a Dean Entrance Waiver or another research stipend?",
  "According to the Tuition & Waiver matrix table, what is the maximum merit waiver for CS Out-of-State students?",
  "What are the rules for F-1/J-1 international students receiving research stipends above $2,000?",
];

const MODE_LABELS: Record<string, string> = {
  rrf_only: "RRF Baseline (HyDE Off · Reranker Off)",
  rrf_rerank: "RRF + Reranker (HyDE Off)",
  rrf_hyde: "RRF + HyDE (Reranker Off)",
  full_phase4: "Full Phase 4 (RRF + Reranker + HyDE + CRAG)",
};

export function DocBranchExplorer() {
  const [overview, setOverview] = useState<Phase4Overview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [query, setQuery] = useState(PRESET_DOC_QUERIES[0]);
  const [grantFilter, setGrantFilter] = useState("");
  const [versionFilter, setVersionFilter] = useState("");
  const [useHyde, setUseHyde] = useState(true);
  const [useReranker, setUseReranker] = useState(true);
  const [useCrag, setUseCrag] = useState(true);
  const [searching, setSearching] = useState(false);
  const [searchResult, setSearchResult] = useState<Phase4SearchResponse | null>(null);

  useEffect(() => {
    fetch("/api/phase4/overview")
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((payload: Phase4Overview) => setOverview(payload))
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load Phase 4 overview"))
      .finally(() => setLoading(false));
  }, []);

  async function runSearch(e?: React.FormEvent, overrideQuery?: string) {
    if (e) e.preventDefault();
    const q = (overrideQuery ?? query).trim();
    if (!q) return;
    if (overrideQuery !== undefined) setQuery(overrideQuery);
    setSearching(true);
    try {
      const res = await fetch("/api/phase4/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: q,
          grant_id: grantFilter,
          version: versionFilter,
          use_hyde: useHyde,
          use_reranker: useReranker,
          use_crag_grader: useCrag,
        }),
      });
      const data: Phase4SearchResponse = await res.json();
      setSearchResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Document search failed");
    } finally {
      setSearching(false);
    }
  }

  if (loading) {
    return (
      <div className="py-12 text-[15px] text-[#6E6E73]">
        Loading Phase 4 hybrid search ablations and passage retriever...
      </div>
    );
  }

  if (error || !overview) {
    return (
      <div className="rounded-2xl border border-[#DC2626]/30 bg-[#DC2626]/5 p-6 text-[14px] text-[#DC2626]">
        {error || "Phase 4 overview unavailable."}
      </div>
    );
  }

  const fullStats =
    overview.report.ablation.find((a) => a.mode === "full_phase4") ??
    overview.report.ablation[overview.report.ablation.length - 1];

  return (
    <div className="space-y-12">
      {/* KPI summary */}
      <div className="grid grid-cols-2 gap-6 border-b border-black/[0.08] pb-8 sm:grid-cols-4">
        <div>
          <div className="font-mono-tabular text-[32px] font-semibold tracking-[-0.03em] text-[#1D1D1F]">
            {(fullStats.recall_at_3 * 100).toFixed(1)}%
          </div>
          <div className="mt-1 text-[13px] text-[#6E6E73]">
            Recall@3 · {overview.report.evaluated_queries} Gold Queries
          </div>
        </div>
        <div>
          <div className="font-mono-tabular text-[32px] font-semibold tracking-[-0.03em] text-[#1D1D1F]">
            {(fullStats.recall_at_5 * 100).toFixed(1)}%
          </div>
          <div className="mt-1 text-[13px] text-[#6E6E73]">
            Recall@5 · Hit@5 {(fullStats.any_hit_at_5 * 100).toFixed(0)}%
          </div>
        </div>
        <div>
          <div className="font-mono-tabular text-[32px] font-semibold tracking-[-0.03em] text-[#1D1D1F]">
            {(fullStats.mrr * 100).toFixed(1)}%
          </div>
          <div className="mt-1 text-[13px] text-[#6E6E73]">
            Mean Reciprocal Rank
          </div>
        </div>
        <div>
          <div className="font-mono-tabular text-[32px] font-semibold tracking-[-0.03em] text-[#1D1D1F]">
            {fullStats.hyde_triggers}
          </div>
          <div className="mt-1 text-[13px] text-[#6E6E73]">
            HyDE Retries (&lt; {overview.defaults.rerank_score_threshold})
          </div>
        </div>
      </div>

      {/* Interactive Hybrid Search Tester */}
      <section className="rounded-2xl bg-[#F5F5F7] p-6 sm:p-8">
        <div className="flex flex-wrap items-baseline justify-between gap-4">
          <div>
            <h2 className="text-[20px] font-semibold tracking-[-0.02em] text-[#1D1D1F]">
              Interactive Hybrid Document Search (Vector + FTS5 + RRF)
            </h2>
            <p className="mt-1 text-[14px] text-[#6E6E73]">
              Tests metadata pre-filtering, RRF (k={overview.defaults.rrf_k}), reranking, single HyDE retry, and CRAG passage grading.
            </p>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          {PRESET_DOC_QUERIES.map((preset) => (
            <button
              key={preset}
              type="button"
              onClick={() => runSearch(undefined, preset)}
              className="rounded-lg bg-white px-3 py-1.5 text-left text-[12px] font-medium text-[#1D1D1F] transition-colors hover:bg-black/[0.04]"
            >
              {preset.length > 58 ? preset.slice(0, 58) + "…" : preset}
            </button>
          ))}
        </div>

        <form onSubmit={(e) => runSearch(e)} className="mt-4 space-y-4">
          <div className="flex flex-wrap gap-3">
            <label className="sr-only" htmlFor="doc-search-query">
              Policy question
            </label>
            <input
              id="doc-search-query"
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Ask a policy handbook question..."
              className="min-w-[260px] flex-1 rounded-xl border border-black/[0.1] bg-white px-4 py-2.5 text-[14px] text-[#1D1D1F] focus:border-[#0071E3] focus:outline-none"
            />
            <button
              type="submit"
              disabled={searching}
              className="rounded-xl bg-[#0071E3] px-5 py-2.5 text-[13px] font-medium text-white hover:bg-[#0077ED] disabled:opacity-60 whitespace-nowrap shrink-0"
            >
              {searching ? "Searching..." : "Retrieve Passages"}
            </button>
          </div>

          <div className="flex flex-wrap items-center gap-4 text-[13px] text-[#1D1D1F]">
            <label className="flex items-center gap-2">
              <span className="text-[#6E6E73]">grant_id:</span>
              <select
                value={grantFilter}
                onChange={(e) => setGrantFilter(e.target.value)}
                className="rounded-lg border border-black/[0.1] bg-white px-2.5 py-1.5 text-[12px]"
              >
                <option value="">All grants</option>
                {["GR-CS-01", "GR-CS-02", "GR-CS-03", "GR-ECE-01", "GR-BIO-01", "GR-ME-01", "GR-GEN-01", "GR-GEN-02", "GR-GEN-04"].map((g) => (
                  <option key={g} value={g}>{g}</option>
                ))}
              </select>
            </label>

            <label className="flex items-center gap-2">
              <span className="text-[#6E6E73]">version:</span>
              <select
                value={versionFilter}
                onChange={(e) => setVersionFilter(e.target.value)}
                className="rounded-lg border border-black/[0.1] bg-white px-2.5 py-1.5 text-[12px]"
              >
                <option value="">All versions</option>
                {["v2.0", "v1.4", "v1.3", "v1.2", "v1.1", "v1.0"].map((v) => (
                  <option key={v} value={v}>{v}</option>
                ))}
              </select>
            </label>

            <label className="flex items-center gap-1.5">
              <input
                type="checkbox"
                checked={useReranker}
                onChange={(e) => setUseReranker(e.target.checked)}
              />
              <span>use_reranker</span>
            </label>

            <label className="flex items-center gap-1.5">
              <input
                type="checkbox"
                checked={useHyde}
                onChange={(e) => setUseHyde(e.target.checked)}
              />
              <span>use_hyde</span>
            </label>

            <label className="flex items-center gap-1.5">
              <input
                type="checkbox"
                checked={useCrag}
                onChange={(e) => setUseCrag(e.target.checked)}
              />
              <span>use_crag_grader</span>
            </label>
          </div>
        </form>

        {searchResult && (
          <div className="mt-6 space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-white px-4 py-3 text-[12px] text-[#6E6E73]">
              <span className="font-mono-tabular">
                {searchResult.trace.search_backend} · initial_top={searchResult.trace.top_score_initial} · hyde_triggered={String(searchResult.trace.hyde_triggered)} · crag={searchResult.trace.crag_backend}
              </span>
              <span className="font-mono-tabular text-[#1D1D1F]">
                {searchResult.passages.length} passages · {searchResult.trace.latency_ms}ms
              </span>
            </div>

            {searchResult.trace.hyde_text && (
              <div className="rounded-xl bg-white p-4 text-[12px]">
                <div className="font-semibold text-[#1D1D1F]">
                  HyDE Single-Retry Expansion ({searchResult.trace.hyde_backend})
                </div>
                <p className="mt-1 text-[#6E6E73]">{searchResult.trace.hyde_text}</p>
              </div>
            )}

            <div className="space-y-3">
              {searchResult.passages.map((p, idx) => (
                <div key={p.chunk_id} className="rounded-xl border border-black/[0.06] bg-white p-4">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="font-mono-tabular text-[12px] font-semibold text-[#1D1D1F]">
                      #{idx + 1} · {p.citation}
                    </span>
                    <span className="font-mono-tabular text-[12px] text-[#6E6E73]">
                      rerank={p.rerank_score} · rrf={p.rrf_score} · vec=#{p.vector_rank ?? "—"} · fts=#{p.fts_rank ?? "—"} · crag={p.crag_grade}
                    </span>
                  </div>
                  <p className="mt-2 text-[13px] leading-[1.55] text-[#1D1D1F]">{p.text}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </section>

      {/* Ablation Matrix Table */}
      <section className="space-y-4">
        <div className="border-b border-black/[0.08] pb-4">
          <h2 className="text-[22px] font-semibold tracking-[-0.02em] text-[#1D1D1F]">
            Recall@k Ablation (HyDE & Reranker Flags ON vs. OFF)
          </h2>
          <p className="mt-1 text-[14px] text-[#6E6E73]">
            Evaluated over {overview.report.evaluated_queries} document-bearing gold queries · embedder={overview.report.embedder_backend} · reranker={overview.report.reranker_backend}
          </p>
        </div>

        <div className="overflow-x-auto rounded-2xl border border-black/[0.08]">
          <table className="w-full border-collapse text-left text-[13px]">
            <thead>
              <tr className="border-b border-black/[0.08] bg-[#F5F5F7]/70">
                <th className="px-4 py-3 font-medium text-[#6E6E73]">Configuration</th>
                <th className="font-mono-tabular px-4 py-3 font-medium text-[#6E6E73]">Recall@3</th>
                <th className="font-mono-tabular px-4 py-3 font-medium text-[#6E6E73]">Recall@5</th>
                <th className="font-mono-tabular px-4 py-3 font-medium text-[#6E6E73]">Any Hit@5</th>
                <th className="font-mono-tabular px-4 py-3 font-medium text-[#6E6E73]">MRR</th>
                <th className="font-mono-tabular px-4 py-3 font-medium text-[#6E6E73]">HyDE Triggers</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-black/[0.06]">
              {overview.report.ablation.map((row) => (
                <tr key={row.mode} className="hover:bg-[#F5F5F7]/40">
                  <td className="px-4 py-3 font-medium text-[#1D1D1F]">
                    {MODE_LABELS[row.mode] ?? row.mode}
                  </td>
                  <td className="font-mono-tabular px-4 py-3 text-[#1D1D1F]">
                    {(row.recall_at_3 * 100).toFixed(2)}%
                  </td>
                  <td className="font-mono-tabular px-4 py-3 text-[#1D1D1F]">
                    {(row.recall_at_5 * 100).toFixed(2)}%
                  </td>
                  <td className="font-mono-tabular px-4 py-3 text-[#1D1D1F]">
                    {(row.any_hit_at_5 * 100).toFixed(1)}%
                  </td>
                  <td className="font-mono-tabular px-4 py-3 text-[#1D1D1F]">
                    {(row.mrr * 100).toFixed(2)}%
                  </td>
                  <td className="font-mono-tabular px-4 py-3 text-[#6E6E73]">
                    {row.hyde_triggers}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
