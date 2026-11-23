import { useEffect, useState } from "react";
import type { Phase3ExecuteResponse, Phase3Overview } from "../types/phase1";

const SAMPLE_SQL_PROBES = [
  {
    label: "Eligible CS Grants",
    sql: "SELECT grant_id, grant_name, min_gpa, award_amount, deadline FROM grants WHERE status = 'open' AND (dept_code = 'CS' OR dept_code = 'ALL') AND min_gpa <= 3.74 ORDER BY grant_id",
  },
  {
    label: "Block: DROP TABLE",
    sql: "SELECT * FROM students; DROP TABLE fee_ledger;--",
  },
  {
    label: "Block: UPDATE grants",
    sql: "UPDATE grants SET min_gpa = 0.0 WHERE grant_id = 'GR-CS-01'",
  },
  {
    label: "Block: document_chunks",
    sql: "SELECT chunk_id, doc_id, content FROM document_chunks LIMIT 5",
  },
];

export function SqlBranchExplorer() {
  const [data, setData] = useState<Phase3Overview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [sqlInput, setSqlInput] = useState(SAMPLE_SQL_PROBES[0].sql);
  const [execLoading, setExecLoading] = useState(false);
  const [execResult, setExecResult] = useState<Phase3ExecuteResponse | null>(null);
  const [showSchemaPreview, setShowSchemaPreview] = useState(false);

  useEffect(() => {
    fetch("/api/phase3/overview")
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((payload: Phase3Overview) => setData(payload))
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load Phase 3 data"))
      .finally(() => setLoading(false));
  }, []);

  async function handleRunSql(e?: React.FormEvent, overrideSql?: string) {
    if (e) e.preventDefault();
    const targetSql = (overrideSql ?? sqlInput).trim();
    if (!targetSql) return;
    if (overrideSql !== undefined) setSqlInput(overrideSql);
    setExecLoading(true);
    try {
      const res = await fetch("/api/phase3/execute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sql: targetSql }),
      });
      const payload: Phase3ExecuteResponse = await res.json();
      setExecResult(payload);
    } catch (err) {
      setExecResult({
        ok: false,
        blocked: false,
        stage: "network",
        error: err instanceof Error ? err.message : "Execution failed",
      });
    } finally {
      setExecLoading(false);
    }
  }

  if (loading) {
    return (
      <div className="py-12 text-[15px] text-[#6E6E73]">
        Loading Phase 3 SQL Branch metrics, safety checks, and execution trace...
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="rounded-2xl border border-[#DC2626]/30 bg-[#DC2626]/5 p-6 text-[14px] text-[#DC2626]">
        {error || "Phase 3 overview unavailable."}
      </div>
    );
  }

  const { report, demo_self_heal } = data;
  const accuracyPct = (report.execution_accuracy * 100).toFixed(1);

  return (
    <div className="space-y-12">
      {/* KPI summary row */}
      <div className="grid grid-cols-2 gap-6 border-b border-black/[0.08] pb-8 sm:grid-cols-4">
        <div>
          <div className="font-mono-tabular text-[32px] font-semibold tracking-[-0.03em] text-[#1D1D1F]">
            {accuracyPct}%
          </div>
          <div className="mt-1 text-[13px] text-[#6E6E73]">
            Gold SQL Accuracy ({report.fact_accurate_count}/{report.evaluated_sql_queries})
          </div>
        </div>
        <div>
          <div className="font-mono-tabular text-[32px] font-semibold tracking-[-0.03em] text-[#1D1D1F]">
            {report.safety_probes_blocked}/{report.safety_probes_total}
          </div>
          <div className="mt-1 text-[13px] text-[#6E6E73]">
            Safety Probes Blocked
          </div>
        </div>
        <div>
          <div className="font-mono-tabular text-[32px] font-semibold tracking-[-0.03em] text-[#1D1D1F]">
            {data.allowlisted_tables.length} / {data.max_rows}
          </div>
          <div className="mt-1 text-[13px] text-[#6E6E73]">
            Allow-Listed Tables · Row Cap
          </div>
        </div>
        <div>
          <div className="font-mono-tabular text-[32px] font-semibold tracking-[-0.03em] text-[#1D1D1F]">
            {data.statement_timeout_ms}ms
          </div>
          <div className="mt-1 text-[13px] text-[#6E6E73]">
            Stmt Timeout · Lock {data.lock_timeout_ms}ms
          </div>
        </div>
      </div>

      {/* Live Read-Only SQL & Guardrail Tester */}
      <section className="rounded-2xl bg-[#F5F5F7] p-6 sm:p-8">
        <div className="flex flex-wrap items-baseline justify-between gap-4">
          <div>
            <h2 className="text-[20px] font-semibold tracking-[-0.02em] text-[#1D1D1F]">
              Interactive SQL Safety Validator & Read-Only Executor
            </h2>
            <p className="mt-1 text-[14px] text-[#6E6E73]">
              Tests multi-layer validation (single SELECT, allow-listed tables, LIMIT &le; {data.max_rows}) and read-only execution.
            </p>
          </div>
          <span className="font-mono-tabular text-[12px] text-[#6E6E73]">
            STRONG_MODEL live key: {data.live_llm_available ? "Configured" : "Not set (using offline sandbox)"}
          </span>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          {SAMPLE_SQL_PROBES.map((probe) => (
            <button
              key={probe.label}
              type="button"
              onClick={() => handleRunSql(undefined, probe.sql)}
              className="rounded-lg bg-white px-3 py-1.5 text-[12px] font-medium text-[#1D1D1F] transition-colors hover:bg-black/[0.04]"
            >
              {probe.label}
            </button>
          ))}
        </div>

        <form onSubmit={(e) => handleRunSql(e)} className="mt-4 space-y-3">
          <label htmlFor="sql-branch-input" className="sr-only">
            SQL query to validate and execute
          </label>
          <textarea
            id="sql-branch-input"
            rows={3}
            value={sqlInput}
            onChange={(e) => setSqlInput(e.target.value)}
            className="font-mono-tabular w-full rounded-xl border border-black/[0.1] bg-white p-3.5 text-[13px] text-[#1D1D1F] focus:border-[#0071E3] focus:outline-none"
          />
          <div className="flex items-center justify-between gap-4">
            <span className="text-[12px] text-[#6E6E73]">
              Only single SELECT statements targeting {data.allowlisted_tables.length} allow-listed tables are permitted.
            </span>
            <button
              type="submit"
              disabled={execLoading}
              className="rounded-xl bg-[#0071E3] px-5 py-2.5 text-[13px] font-medium text-white hover:bg-[#0077ED] disabled:opacity-60 whitespace-nowrap shrink-0"
            >
              {execLoading ? "Validating..." : "Validate & Execute"}
            </button>
          </div>
        </form>

        {execResult && (
          <div className="mt-6 rounded-xl border border-black/[0.08] bg-white p-5">
            {!execResult.ok ? (
              <div>
                <div className="text-[13px] font-semibold text-[#DC2626]">
                  {execResult.blocked ? "Blocked by SQL Safety Layer" : `Failed at ${execResult.stage}`}
                </div>
                <p className="font-mono-tabular mt-1.5 text-[13px] text-[#1D1D1F]">
                  {execResult.error}
                </p>
              </div>
            ) : (
              execResult.result && (
                <div className="space-y-4">
                  <div className="flex flex-wrap items-baseline justify-between gap-3">
                    <span className="text-[13px] font-semibold text-[#15803D]">
                      Executed safely · {execResult.result.rows.length} rows
                    </span>
                    <span className="font-mono-tabular text-[12px] text-[#6E6E73]">
                      {execResult.result.provenance.engine} · validator={execResult.result.provenance.validator_backend} · limit={execResult.result.provenance.limit_applied} · {execResult.result.provenance.latency_ms}ms
                    </span>
                  </div>
                  <div className="font-mono-tabular rounded-lg bg-[#F5F5F7] p-3 text-[12px] text-[#1D1D1F]">
                    {execResult.result.sql}
                  </div>
                  {execResult.result.rows.length > 0 && (
                    <div className="overflow-x-auto rounded-xl border border-black/[0.06]">
                      <table className="w-full border-collapse text-left text-[12px]">
                        <thead>
                          <tr className="border-b border-black/[0.08] bg-[#F5F5F7]/70">
                            {execResult.result.columns.map((col) => (
                              <th key={col} className="font-mono-tabular px-3 py-2 font-medium text-[#6E6E73] whitespace-nowrap">
                                {col}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-black/[0.06]">
                          {execResult.result.rows.map((row, idx) => (
                            <tr key={idx}>
                              {execResult.result!.columns.map((col) => (
                                <td key={col} className="font-mono-tabular px-3 py-2 text-[#1D1D1F] whitespace-nowrap">
                                  {row[col] === null || row[col] === undefined ? "—" : String(row[col])}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )
            )}
          </div>
        )}
      </section>

      {/* Self-Heal Loop & Trimmed Schema Provenance */}
      <section className="space-y-4">
        <div className="flex flex-wrap items-baseline justify-between gap-4 border-b border-black/[0.08] pb-4">
          <div>
            <h2 className="text-[22px] font-semibold tracking-[-0.02em] text-[#1D1D1F]">
              Self-Heal Trace & Trimmed Schema Provenance
            </h2>
            <p className="mt-1 text-[14px] text-[#6E6E73]">
              Example execution of G-008 recovering automatically from a bad-column SQL error within max_retries={demo_self_heal.provenance.max_retries}.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setShowSchemaPreview((v) => !v)}
            className="text-[13px] font-medium text-[#0071E3] hover:underline"
          >
            {showSchemaPreview ? "Hide Trimmed Schema Prompt" : "Inspect Trimmed Schema Prompt"}
          </button>
        </div>

        {showSchemaPreview && (
          <pre className="font-mono-tabular overflow-x-auto whitespace-pre-wrap rounded-2xl bg-[#F5F5F7] p-5 text-[12px] leading-[1.6] text-[#1D1D1F]">
            {data.trimmed_schema_preview}
          </pre>
        )}

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <div className="rounded-2xl bg-[#F5F5F7] p-6">
            <h3 className="text-[15px] font-semibold text-[#1D1D1F]">
              TabularResult Provenance
            </h3>
            <dl className="mt-4 divide-y divide-black/[0.06] border-y border-black/[0.06] text-[13px]">
              <div className="flex justify-between py-2.5">
                <dt className="text-[#6E6E73]">Injected Reference Date</dt>
                <dd className="font-mono-tabular text-[#1D1D1F]">{demo_self_heal.provenance.current_date}</dd>
              </div>
              <div className="flex justify-between py-2.5">
                <dt className="text-[#6E6E73]">Retrieved Schema Tables</dt>
                <dd className="font-mono-tabular text-[#1D1D1F]">
                  {demo_self_heal.provenance.retrieved_tables?.join(", ")}
                </dd>
              </div>
              <div className="flex justify-between py-2.5">
                <dt className="text-[#6E6E73]">Attempts / Heal Retries</dt>
                <dd className="font-mono-tabular text-[#1D1D1F]">
                  {demo_self_heal.provenance.attempts} attempts ({demo_self_heal.provenance.retries_used} retry)
                </dd>
              </div>
              <div className="flex justify-between py-2.5">
                <dt className="text-[#6E6E73]">Returned Rows</dt>
                <dd className="font-mono-tabular text-[#1D1D1F]">
                  {demo_self_heal.rows.length} rows · tables={demo_self_heal.tables.join(", ")}
                </dd>
              </div>
            </dl>
          </div>

          <div className="rounded-2xl bg-[#F5F5F7] p-6">
            <h3 className="text-[15px] font-semibold text-[#1D1D1F]">
              Error Feedback & Recovery
            </h3>
            <div className="mt-4 space-y-3">
              {demo_self_heal.provenance.heal_errors?.map((errItem) => (
                <div key={errItem.attempt} className="rounded-xl bg-white p-4 text-[12px]">
                  <div className="font-semibold text-[#DC2626]">
                    Attempt {errItem.attempt} ({errItem.stage} failure fed back)
                  </div>
                  <div className="font-mono-tabular mt-1 text-[#6E6E73]">{errItem.bad_sql}</div>
                  <div className="font-mono-tabular mt-1 text-[#1D1D1F]">{errItem.error}</div>
                </div>
              ))}
              <div className="rounded-xl bg-white p-4 text-[12px]">
                <div className="font-semibold text-[#15803D]">
                  Attempt {demo_self_heal.provenance.attempts} Succeeded
                </div>
                <div className="font-mono-tabular mt-1 text-[#1D1D1F]">{demo_self_heal.sql}</div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Gold SQL Benchmark & Safety Probe Tables */}
      <section className="space-y-4">
        <div className="border-b border-black/[0.08] pb-4">
          <h2 className="text-[22px] font-semibold tracking-[-0.02em] text-[#1D1D1F]">
            Gold SQL Execution Accuracy ({report.evaluated_sql_queries} Queries)
          </h2>
          <p className="mt-1 text-[14px] text-[#6E6E73]">
            Every standalone SQL query (G-001 to G-024) validated, executed read-only, and checked against expected answer facts.
          </p>
        </div>

        <div className="overflow-x-auto rounded-2xl border border-black/[0.08]">
          <table className="w-full border-collapse text-left text-[12px]">
            <thead>
              <tr className="border-b border-black/[0.08] bg-[#F5F5F7]/70">
                <th className="font-mono-tabular px-3 py-2.5 font-medium text-[#6E6E73]">ID</th>
                <th className="px-3 py-2.5 font-medium text-[#6E6E73]">Question</th>
                <th className="font-mono-tabular px-3 py-2.5 font-medium text-[#6E6E73]">Tables</th>
                <th className="font-mono-tabular px-3 py-2.5 font-medium text-[#6E6E73]">Rows</th>
                <th className="font-mono-tabular px-3 py-2.5 font-medium text-[#6E6E73]">Latency</th>
                <th className="px-3 py-2.5 font-medium text-[#6E6E73]">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-black/[0.06]">
              {report.results.map((item) => (
                <tr key={item.query_id} className="hover:bg-[#F5F5F7]/40">
                  <td className="font-mono-tabular px-3 py-2.5 font-medium text-[#1D1D1F] whitespace-nowrap">
                    {item.query_id}
                  </td>
                  <td className="px-3 py-2.5 text-[#1D1D1F]">{item.query}</td>
                  <td className="font-mono-tabular px-3 py-2.5 text-[#6E6E73] whitespace-nowrap">
                    {item.tables.join(", ")}
                  </td>
                  <td className="font-mono-tabular px-3 py-2.5 text-[#1D1D1F] whitespace-nowrap">
                    {item.row_count}
                  </td>
                  <td className="font-mono-tabular px-3 py-2.5 text-[#6E6E73] whitespace-nowrap">
                    {item.latency_ms ?? 0}ms
                  </td>
                  <td className="px-3 py-2.5 font-medium whitespace-nowrap">
                    <span className={item.passed ? "text-[#15803D]" : "text-[#DC2626]"}>
                      {item.passed ? "Pass" : "Fail"}
                    </span>
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
