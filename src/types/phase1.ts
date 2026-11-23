export type ActiveSection = "overview" | "tables" | "handbooks" | "ingestion" | "gold";

export type TableCategory = "all" | "core" | "distractor" | "related" | "rag_infra";

export type GoldRoute = "all" | "sql" | "vector" | "hybrid" | "out_of_scope";

export type GoldTagFilter = "all" | "follow_up" | "adversarial" | "paraphrase";

export interface TableColumnInfo {
  name: string;
  type: string;
  pk: boolean;
}

export interface TableSummary {
  table_name: string;
  category: Exclude<TableCategory, "all">;
  purpose: string;
  row_count: number;
  columns: TableColumnInfo[];
}

export interface TableRowsResponse {
  table_name: string;
  columns: string[];
  rows: Record<string, unknown>[];
  error?: string;
}

export interface PdfManifestItem {
  filename: string;
  title: string;
  doc_id: string;
  version: string;
  effective_date: string;
  page_count: number;
  size_bytes: number;
  grant_ids: string[];
  planted_cases: string[];
}

export interface PdfTextResponse {
  filename: string;
  pages: string[];
  error?: string;
}

export interface GoldQueryItem {
  query_id: string;
  query: string;
  route: Exclude<GoldRoute, "all">;
  persona_student_id: string;
  expected_answer_facts: string[];
  expected_tables: string[];
  expected_doc_ids: string[];
  is_follow_up: boolean;
  conversation_id: string | null;
  turn_index: number;
  is_adversarial: boolean;
  adversarial_type: string | null;
  paraphrase_group: string | null;
  notes: string;
}

export interface GoldStats {
  total: number;
  routes: Record<string, number>;
  follow_ups: number;
  adversarial: number;
  paraphrased: number;
}

export interface Phase1Overview {
  app_name: string;
  current_date: string;
  feature_flags: Record<string, boolean>;
  tables: TableSummary[];
  pdfs: PdfManifestItem[];
  gold_stats: GoldStats;
  gold_queries: GoldQueryItem[];
}

export interface Phase1VerifyResult {
  passed: boolean;
  returncode: number;
  output: string;
}

export interface DocumentChunkItem {
  chunk_id: string;
  doc_id: string;
  version: string;
  effective_date: string;
  grant_id: string | null;
  dept_code: string | null;
  year_scope: string | null;
  page_num: number;
  chunk_type: "prose" | "table";
  content: string;
  structured_table_json: {
    headers: string[];
    rows: Record<string, string>[];
  } | null;
  injection_flagged: boolean;
  entity_link_method: string;
}

export interface SchemaIndexEntryItem {
  entry_id: string;
  table_name: string;
  column_name: string | null;
  description: string;
  sample_values: string;
  metric_view_sql: string | null;
}

export interface Phase2Report {
  ingestion: {
    total_chunks: number;
    prose_chunks: number;
    table_chunks: number;
    flagged_injection_chunks: number;
    grant_bearing_chunks: number;
    linked_grant_chunks: number;
    entity_link_match_rate: number;
    linked_grant_ids: string[];
    embedder_backend: string;
  };
  schema_index: {
    total_entries: number;
    tables_indexed: number;
    metric_views_indexed: number;
    embedder_backend: string;
  };
  table_retrieval_eval: {
    k: number;
    evaluated_queries: number;
    mean_recall_at_k: number;
    any_expected_hit_rate: number;
    perfect_recall_queries: number;
  };
}

export interface Phase2Overview {
  report: Phase2Report;
  chunks: DocumentChunkItem[];
  schema_entries: SchemaIndexEntryItem[];
}

export interface SchemaHitItem {
  table_name: string;
  score: number;
  matched_entry_id: string;
  description: string;
  sample_values: string;
  metric_view_sql: string | null;
}

export interface TabularResultItem {
  columns: string[];
  rows: Record<string, unknown>[];
  sql: string;
  tables: string[];
  provenance: {
    engine?: string;
    validator_backend?: string;
    limit_applied?: number;
    statement_timeout_ms?: number;
    lock_timeout_ms?: number;
    latency_ms?: number;
    query?: string;
    persona_student_id?: string;
    current_date?: string;
    retrieved_tables?: string[];
    attempts?: number;
    retries_used?: number;
    max_retries?: number;
    heal_errors?: Array<{
      attempt: string;
      stage: string;
      bad_sql: string;
      error: string;
    }>;
  };
}

export interface Phase3GoldQueryResult {
  query_id: string;
  query: string;
  sql: string;
  tables: string[];
  row_count: number;
  expected_facts: string[];
  missing_facts: string[];
  passed: boolean;
  latency_ms?: number;
  engine?: string;
  validator_backend?: string;
  error?: string;
}

export interface Phase3SafetyProbeResult {
  id: string;
  label: string;
  sql: string;
  blocked: boolean;
  reason: string;
}

export interface Phase3Report {
  evaluated_sql_queries: number;
  execution_ok_count: number;
  fact_accurate_count: number;
  execution_accuracy: number;
  safety_probes_total: number;
  safety_probes_blocked: number;
  results: Phase3GoldQueryResult[];
  safety_results: Phase3SafetyProbeResult[];
}

export interface Phase3Overview {
  report: Phase3Report;
  demo_self_heal: TabularResultItem;
  trimmed_schema_preview: string;
  live_llm_available: boolean;
  allowlisted_tables: string[];
  max_rows: number;
  statement_timeout_ms: number;
  lock_timeout_ms: number;
}

export interface Phase3ExecuteResponse {
  ok: boolean;
  blocked: boolean;
  stage?: string;
  error?: string;
  result?: TabularResultItem;
}

export interface PassageItem {
  text: string;
  doc_id: string;
  version: string;
  page: number;
  citation: string;
  chunk_id: string;
  chunk_type: string;
  grant_id: string | null;
  dept_code: string | null;
  effective_date: string;
  structured_table_json: {
    headers: string[];
    rows: Record<string, string>[];
  } | null;
  injection_flagged: boolean;
  vector_rank: number | null;
  fts_rank: number | null;
  rrf_score: number;
  rerank_score: number;
  crag_grade: string;
}

export interface Phase4AblationRow {
  mode: string;
  use_hyde: boolean;
  use_reranker: boolean;
  use_crag_grader: boolean;
  evaluated_queries: number;
  recall_at_3: number;
  recall_at_5: number;
  any_hit_at_5: number;
  mrr: number;
  hyde_triggers: number;
}

export interface Phase4Overview {
  report: {
    evaluated_queries: number;
    ablation: Phase4AblationRow[];
    embedder_backend: string;
    reranker_backend: string;
  };
  defaults: {
    vector_top_k: number;
    fts_top_k: number;
    rrf_k: number;
    rerank_top_k: number;
    rerank_score_threshold: number;
    use_hyde: boolean;
    use_reranker: boolean;
    use_crag_grader: boolean;
  };
}

export interface Phase4SearchResponse {
  passages: PassageItem[];
  trace: {
    query: string;
    filters: {
      grant_ids: string[];
      doc_ids: string[];
      version: string | null;
      dept_code: string | null;
      year_scope: string | null;
    };
    search_backend: string;
    embedder_backend: string;
    reranker_enabled: boolean;
    reranker_backend: string;
    rerank_score_threshold: number;
    top_score_initial: number;
    hyde_enabled: boolean;
    hyde_triggered: boolean;
    hyde_retry_count: number;
    hyde_backend: string;
    hyde_text: string | null;
    top_score_after_hyde: number;
    crag_enabled: boolean;
    crag_backend: string;
    crag_grades: Array<{
      chunk_id: string;
      doc_id: string;
      grade: string;
      reason: string;
    }>;
    returned_count: number;
    latency_ms: number;
  };
}

export interface StudentPersonaItem {
  student_id: string;
  full_name: string;
  dept_code: string;
  year_of_study: number;
  cumulative_gpa: number;
  semester_gpa: number;
  enrollment_status: string;
}

export interface IdentityCheckItem {
  persona_student_id: string;
  profile: StudentPersonaItem | null;
  self_reported: Record<string, unknown>;
  mismatches: Array<{
    field: string;
    self_reported: unknown;
    db_value: unknown;
  }>;
  flagged: boolean;
  warning_message: string | null;
}

export interface ExecutionPlanItem {
  route: Exclude<GoldRoute, "all">;
  execution_mode: "single" | "parallel" | "sequential" | "refuse";
  sql_subquery: string | null;
  doc_subquery: string | null;
  resolved_query: string;
  target_grant_ids: string[];
  target_faculty_names: string[];
  decision_path: string;
  exemplar_similarity: number;
  reasoning: string;
}

export interface ConversationMemoryItem {
  last_plan?: ExecutionPlanItem | null;
  last_entities?: {
    grant_ids?: string[];
    focused_grant_id?: string | null;
    faculty_names?: string[];
    student_id?: string;
  };
  turns?: Array<{
    query: string;
    resolved_query: string;
    route: string;
    execution_mode: string;
    decision_path: string;
    status_notice: string | null;
  }>;
}

export interface Phase5CaseRecord {
  query_id: string;
  query: string;
  persona_student_id: string;
  expected_route: string;
  predicted_route: string;
  correct: boolean;
  execution_mode: string;
  decision_path: string;
  exemplar_similarity: number;
  resolved_query: string;
  target_grant_ids: string[];
  target_faculty_names: string[];
  identity_flagged: boolean;
}

export interface Phase5Overview {
  report: {
    total_queries: number;
    total_correct: number;
    overall_route_accuracy: number;
    per_class_accuracy: Record<string, { total: number; correct: number; accuracy: number }>;
    confusing_middle_cases: {
      total: number;
      correct: number;
      accuracy: number;
      cases: Phase5CaseRecord[];
    };
    follow_up_eval: {
      total: number;
      correct: number;
      accuracy: number;
      cases: Phase5CaseRecord[];
    };
    identity_mismatch_detections: Array<{
      query_id: string;
      persona_student_id: string;
      mismatches: Array<{ field: string; self_reported: unknown; db_value: unknown }>;
      predicted_route: string;
    }>;
    decision_path_breakdown: Record<string, number>;
    execution_mode_breakdown: Record<string, number>;
    sample_zero_row_trace?: {
      query: string;
      status_notice: string;
      doc_result_is_none: boolean;
    };
  };
  personas: StudentPersonaItem[];
  router_threshold: number;
  sequential_max_grant_ids: number;
}

export interface Phase5RouteResponse {
  query: string;
  persona_student_id: string;
  identity_check: IdentityCheckItem;
  plan: ExecutionPlanItem;
  sql_result: TabularResultItem | null;
  doc_result: Phase4SearchResponse | null;
  status_notice: string | null;
  trace: {
    decision_path?: string;
    executed_branch?: string;
    identity_latency_ms?: number;
    planner_latency_ms?: number;
    sequential_filter?: {
      sql_row_count: number;
      max_grant_ids: number;
      extracted_grant_ids: string[];
      doc_search_skipped: boolean;
      reason?: string;
    };
  };
  memory: ConversationMemoryItem;
}

export interface ClaimItem {
  entity: string;
  field: string;
  value: unknown;
  source_id: string;
  claim_type: "sql" | "policy";
  section: "meets_hard_criteria" | "still_verify" | "conflict" | "expired";
  citation: string | null;
}

export interface ConflictNoticeItem {
  entity: string;
  field: string;
  sql_value: string;
  doc_value: string;
  sql_source_id: string;
  doc_source_id: string;
  doc_citation: string;
  summary: string;
}

export interface DeadlineNoticeItem {
  entity: string;
  grant_name: string;
  deadline: string;
  current_date: string;
  source_id: string;
  status: "expired" | "active";
  summary: string;
}

export interface VerificationIssueItem {
  claim_index: number;
  entity: string;
  field: string;
  source_id: string;
  check_type: string;
  message: string;
}

export interface VerificationResultItem {
  passed: boolean;
  issues: VerificationIssueItem[];
  llm_check_ran: boolean;
  llm_check_backend: string;
  checked_claims_count: number;
  policy_claims_count: number;
}

export interface SynthesisResultItem {
  answer_markdown: string;
  claims: ClaimItem[];
  meets_hard_criteria: ClaimItem[];
  still_verify: ClaimItem[];
  conflicts: ConflictNoticeItem[];
  deadline_notices: DeadlineNoticeItem[];
  missing_evidence_notices: string[];
  verification: VerificationResultItem;
  regeneration_count: number;
  warnings: string[];
  writer_backend: string;
  latency_ms: number;
}

export interface Phase6Overview {
  report: {
    evaluated_queries: number;
    verification_pass_count: number;
    verification_pass_rate: number;
    format_compliant_count: number;
    format_compliant_rate: number;
    total_claims_generated: number;
    total_policy_claims_checked: number;
    conflict_detected_qids: string[];
    expired_detected_qids: string[];
    missing_evidence_qids: string[];
  };
  use_llm_claim_check: boolean;
  max_regeneration_attempts: number;
  current_date: string;
}

export interface Phase6SynthesizeResponse extends Phase5RouteResponse {
  synthesis: SynthesisResultItem;
}

export interface StepTraceItem {
  step: string;
  status: string;
  latency_ms: number;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
  detail: string;
}

export interface TokenSummaryItem {
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_tokens: number;
  total_cost_usd: number;
  total_latency_ms: number;
  llm_calls: Array<{
    timestamp: string;
    step: string;
    tier: string;
    model: string;
    prompt_tokens: number;
    completion_tokens: number;
    latency_ms: number;
    cost_usd: number;
  }>;
}

export interface Phase7ChatResponse extends Phase6SynthesizeResponse {
  feature_flags: Record<string, boolean>;
  step_trace: StepTraceItem[];
  token_summary: TokenSummaryItem;
}

export interface McpToolItem {
  name: string;
  description: string;
  inputSchema: {
    type: string;
    properties: Record<string, { type: string }>;
    required: string[];
  };
}

export interface McpInspectResponse {
  returncode: number;
  stderr: string;
  server_info: { name: string; version: string } | null;
  protocol_version: string | null;
  instructions: string | null;
  tools: McpToolItem[];
  call_results: Array<{
    tool: string;
    arguments: Record<string, unknown>;
    isError: boolean;
    output: unknown;
    raw_response: unknown;
  }>;
  transcript: {
    requests: unknown[];
    responses: unknown[];
  };
}

export interface EvalSummaryItem {
  total_queries: number;
  route_accuracy: number;
  route_correct_count: number;
  per_class_route_accuracy: Record<string, { total: number; correct: number; accuracy: number }>;
  confusing_middle_accuracy: number;
  follow_up_accuracy: number;
  table_recall_at_3: number;
  doc_recall_at_5: number;
  answer_fact_coverage: number;
  verification_pass_rate: number;
  format_compliant_rate: number;
  adversarial_defense_rate: number;
  adversarial_total: number;
  adversarial_handled: number;
  latency_ms: {
    mean_total_ms: number;
    p50_total_ms: number;
    p95_total_ms: number;
    per_step_mean_ms: Record<string, number>;
  };
  tokens_and_cost: {
    total_prompt_tokens: number;
    total_completion_tokens: number;
    total_tokens: number;
    total_cost_usd: number;
  };
}

export interface EvalRecordItem {
  query_id: string;
  query: string;
  persona_student_id: string;
  expected_route: string;
  predicted_route: string;
  route_correct: boolean;
  execution_mode: string;
  decision_path: string;
  table_recall: number | null;
  doc_recall: number | null;
  fact_coverage: number;
  verification_passed: boolean;
  format_compliant: boolean;
  claims_count: number;
  conflicts_count: number;
  expired_count: number;
  identity_flagged: boolean;
  total_latency_ms: number;
}

export interface Phase7Overview {
  eval_summary: EvalSummaryItem | null;
  eval_records: EvalRecordItem[];
  personas: StudentPersonaItem[];
  feature_flags: Record<string, boolean>;
  current_date: string;
  mcp_server_info: { name: string; version: string } | null;
  mcp_protocol_version: string | null;
  mcp_tools: McpToolItem[];
}
