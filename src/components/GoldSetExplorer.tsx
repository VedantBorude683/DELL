import { useState } from "react";
import type { GoldQueryItem, GoldRoute, GoldStats, GoldTagFilter } from "../types/phase1";
import { filterGoldQueries, formatRouteLabel } from "../utils/phase1Filters";
import { RouterPlannerExplorer } from "./RouterPlannerExplorer";

interface GoldSetExplorerProps {
  queries: GoldQueryItem[];
  stats: GoldStats;
}

const ROUTES: { id: GoldRoute; label: string }[] = [
  { id: "all", label: "All Routes" },
  { id: "sql", label: "SQL" },
  { id: "vector", label: "Vector" },
  { id: "hybrid", label: "Hybrid" },
  { id: "out_of_scope", label: "Out of Scope" },
];

const TAGS: { id: GoldTagFilter; label: string }[] = [
  { id: "all", label: "All Types" },
  { id: "follow_up", label: "Follow-ups" },
  { id: "adversarial", label: "Adversarial" },
  { id: "paraphrase", label: "Paraphrased" },
];

export function GoldSetExplorer({ queries, stats }: GoldSetExplorerProps) {
  const [subTab, setSubTab] = useState<"router_planner" | "gold_corpus">("router_planner");
  const [route, setRoute] = useState<GoldRoute>("all");
  const [tag, setTag] = useState<GoldTagFilter>("all");
  const [search, setSearch] = useState("");

  const filtered = filterGoldQueries(queries, route, tag, search);

  return (
    <div className="space-y-8">
      <div className="border-b border-black/[0.08] pb-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-[32px] font-semibold tracking-[-0.025em] text-[#1D1D1F]">
              {subTab === "router_planner" ? "Router, Planner & LangGraph State" : "Gold Evaluation Set"}
            </h1>
            <p className="mt-1.5 text-[15px] text-[#6E6E73]">
              {subTab === "router_planner"
                ? "Phase 5 fast-path exemplar routing, STRONG_MODEL JSON planning, sequential top-k filtering, follow-up memory, and DB identity checks."
                : `eval/gold.jsonl · ${stats.total} queries · ${stats.follow_ups} follow-ups · ${stats.adversarial} adversarial · ${stats.paraphrased} paraphrased`}
            </p>
          </div>
          <div
            role="tablist"
            aria-label="Router and Gold Set views"
            className="flex items-center gap-1 rounded-lg bg-[#F5F5F7] p-1"
          >
            <button
              type="button"
              role="tab"
              aria-selected={subTab === "router_planner"}
              onClick={() => setSubTab("router_planner")}
              className={`rounded-md px-3.5 py-1.5 text-[12px] font-medium transition-colors whitespace-nowrap shrink-0 ${
                subTab === "router_planner"
                  ? "bg-white text-[#1D1D1F] shadow-xs"
                  : "text-[#6E6E73] hover:text-[#1D1D1F]"
              }`}
            >
              Router & Planner (Phase 5)
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={subTab === "gold_corpus"}
              onClick={() => setSubTab("gold_corpus")}
              className={`rounded-md px-3.5 py-1.5 text-[12px] font-medium transition-colors whitespace-nowrap shrink-0 ${
                subTab === "gold_corpus"
                  ? "bg-white text-[#1D1D1F] shadow-xs"
                  : "text-[#6E6E73] hover:text-[#1D1D1F]"
              }`}
            >
              Gold Set ({stats.total})
            </button>
          </div>
        </div>

        {subTab === "gold_corpus" && (
          <div className="mt-6 flex flex-wrap items-center gap-3">
            <div
              role="group"
              aria-label="Filter gold queries by route"
              className="flex items-center gap-1 rounded-lg bg-[#F5F5F7] p-1"
            >
              {ROUTES.map((r) => (
                <button
                  key={r.id}
                  type="button"
                  onClick={() => setRoute(r.id)}
                  className={`rounded-md px-3 py-1.5 text-[12px] font-medium transition-colors whitespace-nowrap shrink-0 ${
                    route === r.id
                      ? "bg-white text-[#1D1D1F] shadow-xs"
                      : "text-[#6E6E73] hover:text-[#1D1D1F]"
                  }`}
                >
                  {r.label}
                </button>
              ))}
            </div>

            <div
              role="group"
              aria-label="Filter gold queries by category tag"
              className="flex items-center gap-1 rounded-lg bg-[#F5F5F7] p-1"
            >
              {TAGS.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => setTag(t.id)}
                  className={`rounded-md px-3 py-1.5 text-[12px] font-medium transition-colors whitespace-nowrap shrink-0 ${
                    tag === t.id
                      ? "bg-white text-[#1D1D1F] shadow-xs"
                      : "text-[#6E6E73] hover:text-[#1D1D1F]"
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>

            <label className="sr-only" htmlFor="gold-search">
              Search gold queries
            </label>
            <input
              id="gold-search"
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search query, ID, table, or fact..."
              className="w-64 rounded-lg border border-black/[0.1] bg-white px-3.5 py-2 text-[13px] text-[#1D1D1F] placeholder:text-[#86868B] focus:border-[#0071E3] focus:outline-none"
            />
            <span className="font-mono-tabular ml-auto text-[13px] text-[#6E6E73]">
              Showing {filtered.length} of {queries.length}
            </span>
          </div>
        )}
      </div>

      {subTab === "router_planner" ? (
        <RouterPlannerExplorer />
      ) : filtered.length === 0 ? (
        <div className="rounded-2xl bg-[#F5F5F7] p-8 text-[14px] text-[#6E6E73]">
          No evaluation queries match your current filters.
        </div>
      ) : (
        <div className="divide-y divide-black/[0.06] border-y border-black/[0.06]">
          {filtered.map((item) => (
            <article key={item.query_id} className="py-5">
              <div className="flex flex-wrap items-center gap-2 text-[12px] text-[#6E6E73]">
                <span className="font-mono-tabular font-medium text-[#1D1D1F]">
                  {item.query_id}
                </span>
                <span aria-hidden="true">·</span>
                <span className="font-medium text-[#0071E3]">
                  {formatRouteLabel(item.route)}
                </span>
                <span aria-hidden="true">·</span>
                <span className="font-mono-tabular">Persona {item.persona_student_id}</span>
                {item.is_follow_up && (
                  <>
                    <span aria-hidden="true">·</span>
                    <span>
                      Follow-up ({item.conversation_id} Turn {item.turn_index})
                    </span>
                  </>
                )}
                {item.is_adversarial && (
                  <>
                    <span aria-hidden="true">·</span>
                    <span className="text-[#DC2626]">
                      Adversarial ({item.adversarial_type})
                    </span>
                  </>
                )}
                {item.paraphrase_group && (
                  <>
                    <span aria-hidden="true">·</span>
                    <span className="font-mono-tabular">
                      Paraphrase {item.paraphrase_group}
                    </span>
                  </>
                )}
              </div>

              <h2 className="mt-2 text-[16px] font-medium leading-[1.45] text-[#1D1D1F]">
                {item.query}
              </h2>

              <div className="mt-3 flex flex-col gap-1.5 text-[13px] text-[#6E6E73]">
                <div>
                  <span className="text-[#86868B]">Expected facts:</span>{" "}
                  {item.expected_answer_facts.join(" · ")}
                </div>
                {item.expected_tables.length > 0 && (
                  <div>
                    <span className="text-[#86868B]">Expected tables:</span>{" "}
                    <span className="font-mono-tabular text-[#1D1D1F]">
                      {item.expected_tables.join(", ")}
                    </span>
                  </div>
                )}
                {item.expected_doc_ids.length > 0 && (
                  <div>
                    <span className="text-[#86868B]">Expected docs:</span>{" "}
                    <span className="font-mono-tabular text-[#1D1D1F]">
                      {item.expected_doc_ids.join(", ")}
                    </span>
                  </div>
                )}
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
