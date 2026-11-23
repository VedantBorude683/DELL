import { useEffect, useState } from "react";
import type { TableCategory, TableRowsResponse, TableSummary } from "../types/phase1";
import { filterTables, formatCategoryLabel } from "../utils/phase1Filters";
import { SqlBranchExplorer } from "./SqlBranchExplorer";

interface TablesExplorerProps {
  tables: TableSummary[];
}

const CATEGORIES: { id: TableCategory; label: string }[] = [
  { id: "all", label: "All Tables" },
  { id: "core", label: "Core" },
  { id: "distractor", label: "Distractors" },
  { id: "related", label: "Support" },
  { id: "rag_infra", label: "RAG Index" },
];

export function TablesExplorer({ tables }: TablesExplorerProps) {
  const [subTab, setSubTab] = useState<"schema" | "sql_branch">("sql_branch");
  const [category, setCategory] = useState<TableCategory>("all");
  const [search, setSearch] = useState("");
  const [selectedTable, setSelectedTable] = useState<string>(
    tables[0]?.table_name ?? "students"
  );
  const [tableData, setTableData] = useState<TableRowsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const filtered = filterTables(tables, category, search);
  const activeMeta = tables.find((t) => t.table_name === selectedTable) ?? filtered[0];

  useEffect(() => {
    if (!selectedTable) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetch(`/api/phase1/table/${encodeURIComponent(selectedTable)}`)
      .then((res) => res.json())
      .then((data: TableRowsResponse) => {
        if (cancelled) return;
        if (data.error) {
          setError(data.error);
          setTableData(null);
        } else {
          setTableData(data);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load rows");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedTable]);

  return (
    <div className="space-y-8">
      <div className="border-b border-black/[0.08] pb-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-[32px] font-semibold tracking-[-0.025em] text-[#1D1D1F]">
              {subTab === "sql_branch" ? "SQL Branch & Safety Guardrails" : "Relational Schema & Sample Rows"}
            </h1>
            <p className="mt-1.5 text-[15px] text-[#6E6E73]">
              {subTab === "sql_branch"
                ? "Phase 3 trimmed schema prompting, sqlglot single-SELECT validation, read-only execution, and 3-retry self-heal."
                : `${tables.length} PostgreSQL tables including deliberate distractors and GPA disambiguation columns.`}
            </p>
          </div>
          <div
            role="tablist"
            aria-label="SQL and schema views"
            className="flex items-center gap-1 rounded-lg bg-[#F5F5F7] p-1"
          >
            <button
              type="button"
              role="tab"
              aria-selected={subTab === "sql_branch"}
              onClick={() => setSubTab("sql_branch")}
              className={`rounded-md px-3.5 py-1.5 text-[12px] font-medium transition-colors whitespace-nowrap shrink-0 ${
                subTab === "sql_branch"
                  ? "bg-white text-[#1D1D1F] shadow-xs"
                  : "text-[#6E6E73] hover:text-[#1D1D1F]"
              }`}
            >
              SQL Branch (Phase 3)
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={subTab === "schema"}
              onClick={() => setSubTab("schema")}
              className={`rounded-md px-3.5 py-1.5 text-[12px] font-medium transition-colors whitespace-nowrap shrink-0 ${
                subTab === "schema"
                  ? "bg-white text-[#1D1D1F] shadow-xs"
                  : "text-[#6E6E73] hover:text-[#1D1D1F]"
              }`}
            >
              Schema & Sample Rows
            </button>
          </div>
        </div>

        {subTab === "schema" && (
          <div className="mt-6 flex flex-wrap items-center gap-3">
            <div
              role="group"
              aria-label="Filter tables by category"
              className="flex items-center gap-1 rounded-lg bg-[#F5F5F7] p-1"
            >
              {CATEGORIES.map((cat) => {
                const active = category === cat.id;
                return (
                  <button
                    key={cat.id}
                    type="button"
                    onClick={() => setCategory(cat.id)}
                    className={`rounded-md px-3 py-1.5 text-[12px] font-medium transition-colors whitespace-nowrap shrink-0 ${
                      active
                        ? "bg-white text-[#1D1D1F] shadow-xs"
                        : "text-[#6E6E73] hover:text-[#1D1D1F]"
                    }`}
                  >
                    {cat.label}
                  </button>
                );
              })}
            </div>

            <label className="sr-only" htmlFor="table-search">
              Search tables or columns
            </label>
            <input
              id="table-search"
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Filter table or column..."
              className="w-60 rounded-lg border border-black/[0.1] bg-white px-3.5 py-2 text-[13px] text-[#1D1D1F] placeholder:text-[#86868B] focus:border-[#0071E3] focus:outline-none"
            />
          </div>
        )}
      </div>

      {subTab === "sql_branch" ? (
        <SqlBranchExplorer />
      ) : (
        <div className="grid grid-cols-1 gap-8 lg:grid-cols-12">
        {/* Left table list */}
        <div className="lg:col-span-4">
          {filtered.length === 0 ? (
            <div className="rounded-2xl bg-[#F5F5F7] p-6 text-[14px] text-[#6E6E73]">
              No tables match that filter.
            </div>
          ) : (
            <ul className="divide-y divide-black/[0.06] border-y border-black/[0.06]">
              {filtered.map((tbl) => {
                const isSelected = tbl.table_name === selectedTable;
                return (
                  <li key={tbl.table_name}>
                    <button
                      type="button"
                      onClick={() => setSelectedTable(tbl.table_name)}
                      className={`flex w-full items-start justify-between gap-3 px-3 py-3.5 text-left transition-colors ${
                        isSelected ? "bg-[#F5F5F7]" : "hover:bg-[#F5F5F7]/60"
                      }`}
                    >
                      <div className="min-w-0">
                        <div className="font-mono-tabular truncate text-[14px] font-medium text-[#1D1D1F]">
                          {tbl.table_name}
                        </div>
                        <div className="mt-0.5 text-[12px] text-[#6E6E73]">
                          {formatCategoryLabel(tbl.category)} · {tbl.columns.length} cols
                        </div>
                      </div>
                      <span className="font-mono-tabular shrink-0 text-[12px] text-[#6E6E73]">
                        {tbl.row_count} rows
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        {/* Right table detail + real sample rows */}
        <div className="min-w-0 lg:col-span-8">
          {activeMeta && (
            <div className="space-y-6">
              <div className="rounded-2xl bg-[#F5F5F7] p-6">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <h2 className="font-mono-tabular text-[20px] font-semibold text-[#1D1D1F]">
                    {activeMeta.table_name}
                  </h2>
                  <span className="text-[13px] text-[#6E6E73]">
                    {formatCategoryLabel(activeMeta.category)} ·{" "}
                    <span className="font-mono-tabular">{activeMeta.row_count} rows</span>
                  </span>
                </div>
                <p className="mt-2 text-[14px] leading-[1.55] text-[#6E6E73]">
                  {activeMeta.purpose}
                </p>
                <div className="mt-4 flex flex-wrap gap-x-4 gap-y-1.5 border-t border-black/[0.06] pt-3 text-[12px] text-[#6E6E73]">
                  {activeMeta.columns.map((col) => (
                    <span key={col.name} className="font-mono-tabular">
                      <span className={col.pk ? "font-semibold text-[#1D1D1F]" : "text-[#1D1D1F]"}>
                        {col.name}
                      </span>
                      {col.pk ? " (PK)" : ""} · {col.type}
                    </span>
                  ))}
                </div>
              </div>

              {loading && (
                <div className="rounded-2xl border border-black/[0.08] p-8 text-[14px] text-[#6E6E73]">
                  Loading rows from database...
                </div>
              )}

              {error && (
                <div className="rounded-2xl border border-[#DC2626]/30 bg-[#DC2626]/5 p-6 text-[14px] text-[#DC2626]">
                  {error}
                </div>
              )}

              {!loading && !error && tableData && (
                <div className="overflow-x-auto rounded-2xl border border-black/[0.08]">
                  {tableData.rows.length === 0 ? (
                    <div className="p-8 text-[14px] text-[#6E6E73]">
                      Table <span className="font-mono-tabular">{tableData.table_name}</span> is reserved for Phase 2 ingestion (0 rows in Phase 1).
                    </div>
                  ) : (
                    <table className="w-full border-collapse text-left text-[12px]">
                      <thead>
                        <tr className="border-b border-black/[0.08] bg-[#F5F5F7]/70">
                          {tableData.columns.map((col) => (
                            <th
                              key={col}
                              className="font-mono-tabular px-3 py-2.5 font-medium text-[#6E6E73] whitespace-nowrap"
                            >
                              {col}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-black/[0.06]">
                        {tableData.rows.map((row, idx) => (
                          <tr key={idx} className="hover:bg-[#F5F5F7]/40">
                            {tableData.columns.map((col) => {
                              const rawVal = row[col];
                              const display =
                                rawVal === null || rawVal === undefined ? "—" : String(rawVal);
                              const isNum = typeof rawVal === "number";
                              return (
                                <td
                                  key={col}
                                  className={`px-3 py-2.5 text-[#1D1D1F] whitespace-nowrap ${
                                    isNum ? "font-mono-tabular" : ""
                                  }`}
                                >
                                  {display}
                                </td>
                              );
                            })}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
      )}
    </div>
  );
}
