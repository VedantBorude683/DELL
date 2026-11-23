import { useEffect, useState } from "react";
import type { DocumentChunkItem, Phase2Overview, SchemaHitItem } from "../types/phase1";

type ChunkFilter = "all" | "linked" | "table" | "flagged";

export function IngestionExplorer() {
  const [data, setData] = useState<Phase2Overview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [chunkFilter, setChunkFilter] = useState<ChunkFilter>("all");
  const [queryInput, setQueryInput] = useState(
    "I'm a 3rd-year CS student. Which research grants can I apply for and what are the deadlines?"
  );
  const [schemaHits, setSchemaHits] = useState<SchemaHitItem[]>([]);
  const [retrieving, setRetrieving] = useState(false);

  useEffect(() => {
    fetch("/api/phase2/overview")
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((payload: Phase2Overview) => setData(payload))
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load Phase 2 data"))
      .finally(() => setLoading(false));
  }, []);

  async function handleRetrieveTables(e: React.FormEvent) {
    e.preventDefault();
    if (!queryInput.trim()) return;
    setRetrieving(true);
    try {
      const res = await fetch("/api/phase2/retrieve-tables", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: queryInput }),
      });
      const json = await res.json();
      setSchemaHits(json.hits ?? []);
    } finally {
      setRetrieving(false);
    }
  }

  if (loading) {
    return (
      <div className="py-16 text-[15px] text-[#6E6E73]">
        Loading Phase 2 chunks, entity links, and schema index...
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="rounded-2xl border border-[#DC2626]/30 bg-[#DC2626]/5 p-6 text-[14px] text-[#DC2626]">
        {error ?? "Phase 2 data unavailable"}
      </div>
    );
  }

  const { report, chunks } = data;
  const filteredChunks: DocumentChunkItem[] = chunks.filter((c) => {
    if (chunkFilter === "linked") return Boolean(c.grant_id);
    if (chunkFilter === "table") return c.chunk_type === "table";
    if (chunkFilter === "flagged") return c.injection_flagged;
    return true;
  });

  return (
    <div className="space-y-16">
      <div className="border-b border-black/[0.08] pb-8">
        <p className="text-[13px] font-medium text-[#0071E3]">
          Phase 2 · Ingestion & Schema Retrieval Layer
        </p>
        <h1 className="mt-2 text-[32px] font-semibold tracking-[-0.025em] text-[#1D1D1F]">
          Chunked Handbooks & Embedded Schema Index
        </h1>
        <p className="mt-2 max-w-2xl text-[15px] leading-[1.6] text-[#6E6E73]">
          Every handbook page is parsed into metadata-tagged chunks, guarded against prompt injections, linked to canonical grant IDs, and paired with an embedded table/metric-view schema index.
        </p>

        <div className="mt-8 grid grid-cols-2 gap-6 border-t border-black/[0.08] pt-6 sm:grid-cols-4">
          <div>
            <div className="font-mono-tabular text-[30px] font-semibold tracking-[-0.03em] text-[#1D1D1F]">
              {report.ingestion.total_chunks}
            </div>
            <div className="mt-1 text-[13px] text-[#6E6E73]">
              Chunks · {report.ingestion.table_chunks} table · {report.ingestion.flagged_injection_chunks} flagged
            </div>
          </div>
          <div>
            <div className="font-mono-tabular text-[30px] font-semibold tracking-[-0.03em] text-[#1D1D1F]">
              {Math.round(report.ingestion.entity_link_match_rate * 100)}%
            </div>
            <div className="mt-1 text-[13px] text-[#6E6E73]">
              Grant Entity Link Rate ({report.ingestion.linked_grant_chunks}/{report.ingestion.grant_bearing_chunks})
            </div>
          </div>
          <div>
            <div className="font-mono-tabular text-[30px] font-semibold tracking-[-0.03em] text-[#1D1D1F]">
              {(report.table_retrieval_eval.mean_recall_at_k * 100).toFixed(1)}%
            </div>
            <div className="mt-1 text-[13px] text-[#6E6E73]">
              Schema Recall@3 ({report.table_retrieval_eval.evaluated_queries} gold queries)
            </div>
          </div>
          <div>
            <div className="font-mono-tabular text-[30px] font-semibold tracking-[-0.03em] text-[#1D1D1F]">
              {report.schema_index.total_entries}
            </div>
            <div className="mt-1 text-[13px] text-[#6E6E73]">
              Schema Index Vectors · {report.schema_index.metric_views_indexed} metric views
            </div>
          </div>
        </div>
      </div>

      {/* Interactive Schema Table Retrieval Tester */}
      <section className="space-y-5">
        <div>
          <h2 className="text-[22px] font-semibold tracking-[-0.02em] text-[#1D1D1F]">
            Test Schema Table Retrieval (Top-3)
          </h2>
          <p className="mt-1 text-[14px] text-[#6E6E73]">
            Query the embedded schema_index across all 18 operational tables, sample distinct values, and metric views.
          </p>
        </div>

        <form onSubmit={handleRetrieveTables} className="flex flex-col gap-3 sm:flex-row">
          <label className="sr-only" htmlFor="schema-query-input">
            Natural language query for table retrieval
          </label>
          <input
            id="schema-query-input"
            type="text"
            value={queryInput}
            onChange={(e) => setQueryInput(e.target.value)}
            placeholder="Ask a student question to retrieve top-3 tables..."
            className="min-w-0 flex-1 rounded-xl border border-black/[0.12] bg-white px-4 py-2.5 text-[14px] text-[#1D1D1F] focus:border-[#0071E3] focus:outline-none"
          />
          <button
            type="submit"
            disabled={retrieving}
            className="rounded-full bg-[#1D1D1F] px-6 py-2.5 text-[13px] font-medium text-white transition-colors hover:bg-[#333336] disabled:opacity-60 whitespace-nowrap shrink-0"
          >
            {retrieving ? "Retrieving..." : "Retrieve Tables"}
          </button>
        </form>

        {schemaHits.length > 0 && (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            {schemaHits.map((hit, idx) => (
              <div key={hit.table_name} className="rounded-2xl bg-[#F5F5F7] p-5">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="font-mono-tabular text-[15px] font-semibold text-[#1D1D1F]">
                    {idx + 1}. {hit.table_name}
                  </span>
                  <span className="font-mono-tabular text-[12px] text-[#0071E3]">
                    {hit.score.toFixed(4)}
                  </span>
                </div>
                <p className="mt-2 text-[13px] leading-[1.5] text-[#6E6E73]">
                  {hit.description}
                </p>
                <p className="font-mono-tabular mt-3 text-[11px] text-[#86868B]">
                  {hit.matched_entry_id}
                </p>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Document Chunks Explorer */}
      <section className="space-y-6 border-t border-black/[0.08] pt-12">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h2 className="text-[22px] font-semibold tracking-[-0.02em] text-[#1D1D1F]">
              Ingested Handbook Chunks
            </h2>
            <p className="mt-1 text-[14px] text-[#6E6E73]">
              Showing {filteredChunks.length} of {chunks.length} embedded chunks stored in document_chunks
            </p>
          </div>

          <div
            role="group"
            aria-label="Filter ingested chunks"
            className="flex items-center gap-1 rounded-lg bg-[#F5F5F7] p-1"
          >
            {(
              [
                ["all", "All Chunks"],
                ["linked", "Grant-Linked"],
                ["table", "PDF Tables"],
                ["flagged", "Injection Guard"],
              ] as const
            ).map(([id, label]) => (
              <button
                key={id}
                type="button"
                onClick={() => setChunkFilter(id)}
                className={`rounded-md px-3 py-1.5 text-[12px] font-medium transition-colors whitespace-nowrap shrink-0 ${
                  chunkFilter === id
                    ? "bg-white text-[#1D1D1F] shadow-xs"
                    : "text-[#6E6E73] hover:text-[#1D1D1F]"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        <div className="divide-y divide-black/[0.06] border-y border-black/[0.06]">
          {filteredChunks.map((chunk) => (
            <article key={chunk.chunk_id} className="py-5">
              <div className="flex flex-wrap items-center gap-2 text-[12px] text-[#6E6E73]">
                <span className="font-mono-tabular font-medium text-[#1D1D1F]">
                  {chunk.doc_id}
                </span>
                <span aria-hidden="true">·</span>
                <span className="font-mono-tabular">{chunk.version}</span>
                <span aria-hidden="true">·</span>
                <span className="font-mono-tabular">Eff. {chunk.effective_date}</span>
                <span aria-hidden="true">·</span>
                <span className="font-mono-tabular">p.{chunk.page_num}</span>
                {chunk.grant_id && (
                  <>
                    <span aria-hidden="true">·</span>
                    <span className="font-mono-tabular font-medium text-[#0071E3]">
                      {chunk.grant_id}
                    </span>
                  </>
                )}
                {chunk.dept_code && (
                  <>
                    <span aria-hidden="true">·</span>
                    <span className="font-mono-tabular">Dept {chunk.dept_code}</span>
                  </>
                )}
                {chunk.chunk_type === "table" && (
                  <>
                    <span aria-hidden="true">·</span>
                    <span className="font-medium text-[#1D1D1F]">Structured PDF Table</span>
                  </>
                )}
                {chunk.injection_flagged && (
                  <>
                    <span aria-hidden="true">·</span>
                    <span className="font-medium text-[#DC2626]">
                      Prompt Injection Stripped
                    </span>
                  </>
                )}
              </div>

              <p className="mt-2.5 text-[14px] leading-[1.6] text-[#1D1D1F]">
                {chunk.content}
              </p>

              {chunk.structured_table_json && (
                <div className="mt-4 overflow-x-auto rounded-xl border border-black/[0.08]">
                  <table className="w-full border-collapse text-left text-[12px]">
                    <thead>
                      <tr className="border-b border-black/[0.08] bg-[#F5F5F7]">
                        {chunk.structured_table_json.headers.map((h) => (
                          <th key={h} className="px-3 py-2 font-medium text-[#6E6E73] whitespace-nowrap">
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-black/[0.06]">
                      {chunk.structured_table_json.rows.map((row, idx) => (
                        <tr key={idx}>
                          {chunk.structured_table_json!.headers.map((h) => (
                            <td key={h} className="font-mono-tabular px-3 py-2 text-[#1D1D1F] whitespace-nowrap">
                              {row[h]}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}
