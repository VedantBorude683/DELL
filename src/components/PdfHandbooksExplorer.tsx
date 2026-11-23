import { useEffect, useState } from "react";
import type { PdfManifestItem, PdfTextResponse } from "../types/phase1";
import { formatPlantedCaseLabel } from "../utils/phase1Filters";
import { DocBranchExplorer } from "./DocBranchExplorer";

interface PdfHandbooksExplorerProps {
  pdfs: PdfManifestItem[];
}

export function PdfHandbooksExplorer({ pdfs }: PdfHandbooksExplorerProps) {
  const [subTab, setSubTab] = useState<"doc_branch" | "pdfs">("doc_branch");
  const [selectedFile, setSelectedFile] = useState<string>(
    pdfs[1]?.filename ?? pdfs[0]?.filename ?? ""
  );
  const [extracted, setExtracted] = useState<PdfTextResponse | null>(null);
  const [loading, setLoading] = useState(false);

  const selectedMeta = pdfs.find((p) => p.filename === selectedFile) ?? pdfs[0];

  useEffect(() => {
    if (!selectedFile) return;
    let cancelled = false;
    setLoading(true);
    fetch(`/api/phase1/pdf/${encodeURIComponent(selectedFile)}`)
      .then((res) => res.json())
      .then((data: PdfTextResponse) => {
        if (!cancelled) setExtracted(data);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedFile]);

  return (
    <div className="space-y-8">
      <div className="border-b border-black/[0.08] pb-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-[32px] font-semibold tracking-[-0.025em] text-[#1D1D1F]">
              {subTab === "doc_branch" ? "Document Branch & Hybrid Retrieval" : "Generated Handbook PDFs"}
            </h1>
            <p className="mt-1.5 text-[15px] text-[#6E6E73]">
              {subTab === "doc_branch"
                ? "Phase 4 hybrid vector + FTS5 RRF search, metadata pre-filtering, reranker, 1-retry HyDE, and CRAG grading."
                : `${pdfs.length} binary PDF 1.4 documents stored in data/pdfs/ with versioned policies, embedded tables, soft conditions, and planted DB conflicts.`}
            </p>
          </div>
          <div
            role="tablist"
            aria-label="Document branch and PDFs"
            className="flex items-center gap-1 rounded-lg bg-[#F5F5F7] p-1"
          >
            <button
              type="button"
              role="tab"
              aria-selected={subTab === "doc_branch"}
              onClick={() => setSubTab("doc_branch")}
              className={`rounded-md px-3.5 py-1.5 text-[12px] font-medium transition-colors whitespace-nowrap shrink-0 ${
                subTab === "doc_branch"
                  ? "bg-white text-[#1D1D1F] shadow-xs"
                  : "text-[#6E6E73] hover:text-[#1D1D1F]"
              }`}
            >
              Document Search (Phase 4)
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={subTab === "pdfs"}
              onClick={() => setSubTab("pdfs")}
              className={`rounded-md px-3.5 py-1.5 text-[12px] font-medium transition-colors whitespace-nowrap shrink-0 ${
                subTab === "pdfs"
                  ? "bg-white text-[#1D1D1F] shadow-xs"
                  : "text-[#6E6E73] hover:text-[#1D1D1F]"
              }`}
            >
              Handbook PDFs
            </button>
          </div>
        </div>
      </div>

      {subTab === "doc_branch" ? (
        <DocBranchExplorer />
      ) : (
        <div className="grid grid-cols-1 gap-8 lg:grid-cols-12">
          <div className="lg:col-span-5">
            <ul className="divide-y divide-black/[0.06] border-y border-black/[0.06]">
              {pdfs.map((pdf) => {
                const active = pdf.filename === selectedFile;
                return (
                  <li key={pdf.filename}>
                    <button
                      type="button"
                      onClick={() => setSelectedFile(pdf.filename)}
                      className={`w-full px-3 py-4 text-left transition-colors ${
                        active ? "bg-[#F5F5F7]" : "hover:bg-[#F5F5F7]/60"
                      }`}
                    >
                      <div className="text-[14px] font-medium text-[#1D1D1F]">
                        {pdf.title}
                      </div>
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-[12px] text-[#6E6E73]">
                        <span className="font-mono-tabular">{pdf.version}</span>
                        <span aria-hidden="true">·</span>
                        <span className="font-mono-tabular">Effective {pdf.effective_date}</span>
                        <span aria-hidden="true">·</span>
                        <span className="font-mono-tabular">{pdf.page_count}p</span>
                      </div>
                      <div className="mt-1.5 text-[12px] text-[#86868B]">
                        {pdf.planted_cases.map(formatPlantedCaseLabel).join(" · ")}
                      </div>
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>

          <div className="min-w-0 lg:col-span-7">
            {selectedMeta && (
              <div className="space-y-6">
                <div className="rounded-2xl bg-[#F5F5F7] p-6">
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0 flex-1">
                      <h2 className="text-[20px] font-semibold tracking-[-0.015em] text-[#1D1D1F]">
                        {selectedMeta.title}
                      </h2>
                      <p className="mt-1.5 text-[13px] text-[#6E6E73]">
                        <span className="font-mono-tabular">{selectedMeta.doc_id}</span> ·{" "}
                        <span className="font-mono-tabular">{selectedMeta.version}</span> ·{" "}
                        Effective <span className="font-mono-tabular">{selectedMeta.effective_date}</span> ·{" "}
                        <span className="font-mono-tabular">
                          {(selectedMeta.size_bytes / 1024).toFixed(1)} KB
                        </span>
                      </p>
                    </div>
                    <a
                      href={`/api/phase1/pdf-raw/${encodeURIComponent(selectedMeta.filename)}`}
                      target="_blank"
                      rel="noreferrer"
                      className="rounded-full bg-[#1D1D1F] px-4 py-2 text-[12px] font-medium text-white transition-colors hover:bg-[#333336] whitespace-nowrap shrink-0"
                    >
                      Open PDF
                    </a>
                  </div>

                  {selectedMeta.grant_ids.length > 0 && (
                    <p className="mt-4 border-t border-black/[0.06] pt-3 text-[12px] text-[#6E6E73]">
                      Linked Grant IDs:{" "}
                      <span className="font-mono-tabular text-[#1D1D1F]">
                        {selectedMeta.grant_ids.join(", ")}
                      </span>
                    </p>
                  )}
                </div>

                <div className="rounded-2xl border border-black/[0.08] p-6">
                  <h3 className="text-[13px] font-medium text-[#6E6E73]">
                    Extracted PDF Text Stream
                  </h3>
                  {loading ? (
                    <p className="mt-4 text-[14px] text-[#6E6E73]">Extracting PDF pages...</p>
                  ) : (
                    <div className="mt-4 space-y-6">
                      {(extracted?.pages ?? []).map((pageText, idx) => (
                        <div key={idx} className="space-y-2">
                          <div className="font-mono-tabular text-[11px] text-[#86868B]">
                            Page {idx + 1}
                          </div>
                          <pre className="font-mono-tabular whitespace-pre-wrap text-[12px] leading-[1.65] text-[#1D1D1F]">
                            {pageText}
                          </pre>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
