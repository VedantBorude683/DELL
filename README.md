# Alderwood University — Unified Hybrid RAG Assistant

A phased prototype of a Unified Hybrid RAG system that answers student questions requiring **both** exact relational data (PostgreSQL 16) and university policy handbooks (PDFs + pgvector + full-text search), orchestrated with LangGraph and verified against source rows and passages before rendering.

---

## Architecture Overview

```
                    +-----------------------+
                    |   Streamlit / Web UI  |
                    +-----------+-----------+
                                |
                                v
                    +-----------------------+
                    |    FastAPI Backend    |
                    +-----------+-----------+
                                |
                                v
               +----------------+----------------+
               |   LangGraph Router & Planner    |
               | (Exemplar Cosine -> LLM JSON)   |
               +----+-----------+-----------+----+
                    |           |           |
       +------------+           |           +------------+
       v (sql / seq)            v (vector)               v (out_of_scope)
+------+--------+       +-------+-------+        +-------+-------+
|  SQL Branch   |       |  Doc Branch   |        | Polite Refusal|
| Schema Index  |       | pgvector + FTS|        +---------------+
| sqlglot guard |       | RRF + Rerank  |
| RO SQLAlchemy |       | HyDE / CRAG   |
+------+--------+       +-------+-------+
       |                        |
       +------------+-----------+
                    |
                    v
         +----------+-----------+
         | Synthesis & Verifier |
         | Claim JSON -> Ground |
         | Conflict / Expiry    |
         +----------------------+
```

---

## Assumptions (Phase 1)

1. **Academic Reference Date**: For Phase 1 synthetic data and deadline/expiry checks, "today" is anchored to `2026-11-23` (Fall 2026 term), configurable via `config.yaml` (`app.current_date_override`).
2. **Primary GPA Definition**: `students.cumulative_gpa` is the canonical GPA used for grant and honors eligibility unless a query explicitly asks for `semester_gpa` or term-level performance (`student_semester_gpas`).
3. **Database Dual-Target in Phase 1**: `db/schema.sql` and `db/seed.sql` target PostgreSQL 16 + `pgvector` + `tsvector` FTS via `docker-compose.yml`. Because Docker/Postgres is not running inside this browser preview sandbox, Phase 1 also materializes a deterministic SQLite mirror (`data/university.db`) from the exact same Python generator so all Phase 1 tables, row counts, and sample queries execute and pass automated tests immediately.
4. **PDF Generation**: `scripts/generate_pdfs.py` prefers PyMuPDF (`fitz`) when available and automatically falls back to our deterministic pure-Python PDF 1.4 writer (`src/data_gen/pdf_writer.py`) so valid, parseable binary `.pdf` handbooks are generated cleanly in both minimal and full Python 3.11 environments.
5. **External LLM & Privacy Scope**: The `llm(model_tier, messages, schema)` wrapper uses `FAST_MODEL` and `STRONG_MODEL` from environment variables.

---

## Known Limitations

- **External LLM Visibility**: Student records (GPA, academic year, department, fee ledger) retrieved during hybrid synthesis are sent to the configured external LLM provider.
- **Static Policy Handbooks**: PDFs represent point-in-time snapshots (`effective_date`); live registrar policy amendments require re-running ingestion.
- **Approximate Entity Linking**: Matching handbook passages to `grant_id` combines deterministic alias/regex matching with an LLM fallback, which may mislink ambiguous grant titles when multiple departments share similar program names.

---

## Phase 1 Deliverables

- **PostgreSQL 16 Schema (`db/schema.sql`)**: 20 tables (18 operational + `document_chunks` + `schema_index`), including deliberate distractors (`grants` vs `grant_applications` vs `grant_history` vs `scholarships_archive`; `fee_ledger` vs `fees` vs `fee_waivers`) and real GPA ambiguity (`cumulative_gpa` vs `semester_gpa`).
- **Synthetic Seed (`db/seed.sql` + `data/university.db`)**: 18 populated operational tables with deterministic records.
- **9 University Policy PDFs (`data/pdfs/`)**: Real `.pdf` documents with planted edge cases:
  - Vocabulary mismatch (`"submission window"` vs `"deadline"`)
  - Structured multi-row table embedded inside `05_tuition_fees_and_waiver_handbook.pdf`
  - Soft eligibility conditions invisible to SQL (`"needs faculty mentor"`, `"not stackable"`)
  - Intentional DB-vs-PDF deadline conflict on `GR-CS-01` (`2026-12-15` in DB vs `"December 1, 2026"` in handbook v2.0)
  - Expired grant (`GR-GEN-04`, deadline `2026-06-30`)
  - Two document versions (`v1.0` effective `2025-09-01` vs `v2.0` effective `2026-09-01`)
- **Gold Evaluation Set (`eval/gold.jsonl`)**: 86 curated queries across `sql`, `vector`, `hybrid`, and `out_of_scope` routes, including 10 multi-turn follow-ups, 10 adversarial/prompt-injection cases, and paraphrased query groups.

---

## Phase 2 Deliverables (Ingestion + Schema Layer)

- **PDF Ingestion (`src/ingestion/pdf_ingestor.py`)**: Parses all 9 handbook PDFs (PyMuPDF / Docling for table-heavy docs when installed, or built-in PDF stream extractor), tags metadata (`doc_id`, `version`, `effective_date`, `grant_id`, `dept_code`, `year_scope`), and stores 33 chunks (32 prose + 1 structured PDF table).
- **PDF Table Handling**: `05_tuition_fees_and_waiver_handbook.pdf` matrix is stored with a summary embedding plus `structured_table_json` containing all 5 rows.
- **Prompt-Injection Guard (`src/ingestion/injection_guard.py`)**: Scans every chunk for instruction-like spans; flags and strips the untrusted appendix instruction in `09_campus_code_and_library_access.pdf`.
- **Entity Linking (`src/ingestion/entity_linker.py`)**: Matches chunks to canonical `grant_id` via ID/alias matching first, then `llm("fast", ...)` fallback when `GEMINI_API_KEY` is configured (`100%` match rate across all 13 grant-bearing chunks).
- **Schema Index (`src/ingestion/schema_indexer.py`)**: Indexes all 18 operational tables, key column distinct sample values, and 6 metric views (`cumulative_gpa`, `semester_gpa_deans_list`, `active_grant_window`, `outstanding_fee_balance`, `student_course_timetable`, `available_faculty_mentors`). Gold-set table retrieval **Recall@3 = 87.76%** (`any_expected_hit_rate = 97.96%`).
- **Embedder Note**: Uses `BAAI/bge-m3` via `sentence-transformers` when installed; falls back cleanly to a deterministic 1024-dim semantic-hash + domain-synonym encoder (`src/rag/embeddings.py`) in minimal environments.

## Phase 3 Deliverables (SQL Branch)

- **Schema-Trimmed SQL Generation (`src/sql_branch/agent.py`)**: Retrieves top 2–3 relevant tables from `schema_index` (respecting `feature_flags.use_schema_index`), builds a trimmed DDL + distinct sample values + metric views prompt, injects reference date `2026-11-23`, and invokes `llm("strong", ...)` with structured JSON output (`{"sql": ...}`).
- **Multi-Layer SQL Safety (`src/sql_branch/validator.py`, `src/sql_branch/executor.py`)**:
  - **Layer 1 (AST / Guardrail)**: Uses `sqlglot` AST parsing (or strict tokenizer fallback when `sqlglot` is absent in minimal containers) to permit **one single `SELECT`** (or `WITH ... SELECT`) over the 18 allow-listed operational tables, rejecting `DROP`/`UPDATE`/`DELETE`/`INSERT`/`UNION`/multi-statement/system-catalog/RAG-table access and enforcing `LIMIT <= 100`.
  - **Layer 2 (Read-Only Role & Timeouts)**: Executes against PostgreSQL `alderwood_readonly` via SQLAlchemy `BEGIN READ ONLY` + `SET LOCAL statement_timeout = 5000` / `lock_timeout = 2000` when configured (`USE_POSTGRES=true` or non-default `READONLY_DATABASE_URL`), or strict SQLite `?mode=ro` + `PRAGMA query_only = ON` + progress-handler timeout in sandbox mode.
- **Self-Heal Loop & Structured Output**: Feeds validation or database errors back to the generator for up to `max_retries = 3`, returning `TabularResult(columns, rows, sql, tables, provenance)`.
- **Gold SQL Accuracy**: Evaluates all 24 standalone SQL queries (`G-001`–`G-024`) with **100% execution and expected-fact accuracy (24/24)** and **8/8 adversarial SQL injection probes blocked**.

---

## Phase 4 Deliverables (Document Branch)

- **Hybrid Vector + FTS Search (`src/doc_branch/retriever.py`)**: Fuses dense similarity (`pgvector` `<=>` or 1024-dim cosine over `document_chunks`) and native full-text search (`ts_rank_cd` / SQLite FTS5 `bm25`) using Reciprocal Rank Fusion (`rrf_k = 60`), pre-filtered by `MetadataFilter(grant_ids, doc_ids, version, dept_code, year_scope)`.
- **Cross-Encoder Reranker (`src/doc_branch/reranker.py`)**: Wraps `BAAI/bge-reranker-v2-m3` (`sentence_transformers.CrossEncoder` when installed) with a calibrated local cross-term fallback (`feature_flags.use_reranker`), plus diversity-aware selection across multi-chunk handbooks.
- **Single-Retry HyDE & Optional CRAG Grader (`src/doc_branch/hyde_and_crag.py`)**: Triggers at most **1 HyDE retry** when `use_hyde=true` and initial top score `< 0.42` (`rerank_score_threshold`), and optionally runs CRAG (`use_crag_grader=true`) to prune `"irrelevant"` chunks. Returns `Passage[](text, doc_id, version, page, citation)`.
- **Recall@k Ablations (`scripts/build_phase4.py`, 48 doc-bearing gold queries)**:
  - RRF Baseline (HyDE Off, Reranker Off): `Recall@3 = 92.36%`, `Recall@5 = 94.44%`, `MRR = 94.10%`
  - RRF + Reranker (HyDE Off): `Recall@3 = 93.40%`, `Recall@5 = 97.22%`, `MRR = 100.00%`
  - Full Phase 4 (RRF + Reranker + HyDE + CRAG): `Recall@3 = 93.40%`, `Recall@5 = 96.18%`, `Any-Hit@5 = 100.0%`, `MRR = 100.00%`

---

## Phase 5 Deliverables (Router + Planner + LangGraph Multi-Turn State)

- **Calibrated Fast Path & Safety Guard (`src/orchestrator/exemplars.py`)**: Embeds canonical held-out route prototypes (`sql`, `vector`, `hybrid`, `out_of_scope`) and takes the embedding fast path when cosine similarity `>= 0.78` with sufficient margin, while blocking unsafe SQL mutation/exfiltration queries via `safety_guard` and escalating follow-ups/confusing boundary queries to the planner.
- **STRONG_MODEL JSON Planner & Follow-up Resolver (`src/orchestrator/planner.py`)**: Calls `llm("strong", ..., schema=PLANNER_JSON_SCHEMA)` (or deterministic multi-signal fallback when `GEMINI_API_KEY` is unset) to emit structured `route`, `execution_mode` (`single | parallel | sequential | refuse`), `sql_subquery`, `doc_subquery`, and entity targets, resolving anaphora from LangGraph conversation memory (`CONV-01`, `CONV-02`, `CONV-03`).
- **LangGraph Orchestrator & Sequential 0-Row Guard (`src/orchestrator/graph.py`)**: Compiles a `langgraph.graph.StateGraph(OrchestratorState)` (with compatible pure-Python fallback runner in minimal sandboxes). In `sequential` mode, SQL executes first and its distinct `grant_id`s (capped at `sequential_max_grant_ids = 5`) constrain Document branch `MetadataFilter(grant_ids=...)`. When SQL returns `0` rows, the orchestrator emits `"no matching records"` and **skips Document retrieval with zero fallback**.
- **Student Identity Verification (`src/orchestrator/identity.py`)**: Loads the logged-in student persona (`cumulative_gpa`, `semester_gpa`, `year_of_study`, `dept_code`) from DB and flags mismatched self-reported query claims (`G-057`, `G-080`) while forcing SQL filters to use authoritative DB values.
- **Routing Accuracy (`scripts/build_phase5.py`)**: **86/86 (100.0%)** overall (`sql`: 28/28, `vector`: 27/27, `hybrid`: 21/21, `out_of_scope`: 10/10), **11/11 (100.0%)** confusing middle boundary cases, **10/10 (100.0%)** multi-turn follow-ups (`fast_path_exemplar`: 17, `strong_planner`: 63, `safety_guard`: 6).

---

## Phase 6 Deliverables (Synthesis + Verification)

- **Structured Claim Writer & Deterministic Renderer (`src/synthesis/writer.py`)**: Calls `llm("strong", ..., schema=WRITER_CLAIMS_SCHEMA)` (or deterministic grounded claim builder when `GEMINI_API_KEY` is unset) to produce structured JSON claims `{entity, field, value, source_id, claim_type, section, citation}` and deterministically renders `## Meets hard criteria` and `## Still verify` sections without ever emitting a flat `"you're eligible"` verdict.
- **Strict Own-Source Code Verifier & LLM Policy Check (`src/synthesis/verifier.py`)**:
  - Verifies every claim value strictly against its **own** `source_id` (`sql:row:i` / `sql:identity:<sid>` row fields and entity key, or `doc:<chunk_id>` passage text), rejecting values that appear only in other rows or chunks.
  - Requires a valid handbook citation on every policy claim and runs `use_llm_claim_check` (`llm("fast", ..., schema=LLM_CLAIM_CHECK_SCHEMA)` or deterministic entailment fallback) when enabled.
  - Scans rendered markdown to forbid flat eligibility verdicts.
- **Conflict, Expiry & Missing-Evidence Checks (`src/synthesis/checks.py`)**:
  - **SQL vs. PDF Conflict**: Flags `GR-CS-01` DB deadline `2026-12-15` vs. `HANDBOOK-RESEARCH-GRANTS v2.0` `"December 1, 2026"` (`2026-12-01`) across 12 gold queries.
  - **Deadline Passed**: Flags grants whose deadline precedes `2026-11-23` (e.g., `GR-GEN-04` expired `2026-06-30` on `G-055`).
  - **Missing Evidence & Soft Conditions**: Preserves sequential 0-row `"no matching records"` and flags SQL-untracked prerequisites (`faculty mentor`, `not stackable`, `IRB/cleanroom`, `paper acceptance notice`).
- **Single-Retry Self-Correction (`src/synthesis/synthesizer.py`)**: Re-runs claim generation at most once (`max_regeneration_attempts = 1`) with verifier error feedback if verification fails, then returns the rendered answer with an explicit `Verification Warning` if issues persist.
- **Gold Evaluation (`scripts/build_phase6.py`, 86 queries)**: **86/86 (100.0%)** verified pass rate, **86/86 (100.0%)** structured format compliance (`0` flat eligibility verdicts), **906** grounded JSON claims generated, **267** policy claims checked, **12** DB-vs-PDF conflict detections, **1** expired grant flag (`G-055`), **40** missing-evidence/soft-condition notices.

---

## Phase 7 Deliverables (UI, FastMCP, FastAPI & Evals)

- **Streamlit UI (`app_streamlit.py`)**: Full two-column Streamlit interface (`streamlit run app_streamlit.py`) with sidebar student persona selector (`STU-1001..STU-1012`), live `config.yaml` feature flag overrides, multi-turn chat (`ConversationMemory`), and an execution trace panel showing route, plan, SQL + provenance, retrieved chunks + scores, verification result + JSON claims, and per-step latency + token/USD cost. Also mirrored natively in the React workbench (`Assistant & Trace (Phase 7)`).
- **FastAPI Backend (`src/api/main.py`)**: Exposes `/health`, `/personas`, `/chat`, `/eval/latest`, and `/mcp/inspect` (using FastAPI + Uvicorn when installed, with a built-in Python stdlib HTTP fallback).
- **FastMCP Server & Stdio Inspector (`mcp_server/server.py`, `mcp_server/inspector_client.py`)**: Exposes `safe_sql_query`, `list_allowlisted_tables`, and `search_schema_index` over MCP JSON-RPC 2.0 stdio (`fastmcp.FastMCP` or spec-compliant `_CompatFastMCP`), enforcing Phase 3 `sqlglot` AST allow-list + read-only execution + timeouts + row cap. Verified via real stdio handshake (`initialize` -> `tools/list` -> `tools/call`), compatible with `npx @modelcontextprotocol/inspector python3 -m mcp_server.server`.
- **End-to-End Gold Benchmark (`python -m eval.run` -> `eval/latest_report.json`)**:
  - **Overall Route Accuracy**: **86/86 (100.0%)** (`sql` 28/28, `vector` 27/27, `hybrid` 21/21, `out_of_scope` 10/10)
  - **Confusing Middle & Follow-ups**: **100.0%** / **100.0%**
  - **Table Recall@3 / Doc Recall@5**: **94.56%** / **91.32%**
  - **Answer Fact Coverage**: **88.10%**
  - **Verification Pass & Format Compliance**: **100.0%** / **100.0%**
  - **Adversarial Cases Defended**: **10/10 (100.0%)**
  - **Latency (offline deterministic path)**: mean `35.12ms` (`p50 = 43.61ms`, `p95 = 53.98ms`)

---

## Running Phases 1–7

```bash
# 1–6. Build & evaluate individual phase artifacts
python3 scripts/build_phase1.py
python3 scripts/build_phase2.py
python3 scripts/build_phase3.py
python3 scripts/build_phase4.py
python3 scripts/build_phase5.py
python3 scripts/build_phase6.py

# 7. Run complete end-to-end gold set benchmark -> eval/latest_report.json
python3 -m eval.run

# 8. Start FastMCP server (or inspect via MCP Inspector)
python3 -m mcp_server.server
# npx @modelcontextprotocol/inspector python3 -m mcp_server.server

# 9. Launch Streamlit UI (with requirements.txt installed)
streamlit run app_streamlit.py

# 10. Run all Phase 1–7 tests (36 tests)
python3 -m unittest discover -s tests -p "test_*.py" -v
```

