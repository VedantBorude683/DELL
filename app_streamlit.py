"""Phase 7 Streamlit UI: Persona Selector, Chat, and Full Execution Trace Panel.

Launch:
    streamlit run app_streamlit.py
"""
from __future__ import annotations

import os
import sys
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.assistant import run_assistant_query
from src.config import AppConfig
from src.orchestrator.identity import list_student_personas


def build_trace_panel_payload(turn: dict[str, Any]) -> dict[str, Any]:
    """Build the Streamlit execution-trace view model."""
    plan = turn.get("plan") or {}
    sql_res = turn.get("sql_result") or {}
    doc_res = turn.get("doc_result") or {}
    syn = turn.get("synthesis") or {}
    ver = syn.get("verification") or {}
    tok = turn.get("token_summary") or {}
    return {
        "route": plan.get("route", "unknown"),
        "execution_mode": plan.get("execution_mode", "single"),
        "decision_path": plan.get("decision_path", "unknown"),
        "plan": {
            "resolved_query": plan.get("resolved_query"),
            "sql_subquery": plan.get("sql_subquery"),
            "doc_subquery": plan.get("doc_subquery"),
            "exemplar_similarity": plan.get("exemplar_similarity"),
            "target_grant_ids": plan.get("target_grant_ids") or [],
            "target_faculty_names": plan.get("target_faculty_names") or [],
            "identity_flagged": bool((turn.get("identity_check") or {}).get("flagged", False)),
            "identity_warning": (turn.get("identity_check") or {}).get("warning_message"),
        },
        "sql": {
            "sql": sql_res.get("sql"),
            "tables": sql_res.get("tables") or [],
            "row_count": len(sql_res.get("rows") or []),
            "rows": sql_res.get("rows") or [],
            "provenance": sql_res.get("provenance") or {},
        },
        "retrieved_chunks": [
            {
                "chunk_id": p.get("chunk_id"),
                "doc_id": p.get("doc_id"),
                "version": p.get("version"),
                "page": p.get("page"),
                "citation": p.get("citation"),
                "rrf_score": p.get("rrf_score"),
                "rerank_score": p.get("rerank_score"),
                "crag_grade": p.get("crag_grade"),
                "text": p.get("text"),
            }
            for p in (doc_res.get("passages") or [])
        ],
        "verification_result": {
            "passed": bool(ver.get("passed", False)),
            "llm_check_ran": bool(ver.get("llm_check_ran", False)),
            "llm_check_backend": ver.get("llm_check_backend"),
            "checked_claims_count": int(ver.get("checked_claims_count") or 0),
            "policy_claims_count": int(ver.get("policy_claims_count") or 0),
            "regeneration_count": int(syn.get("regeneration_count") or 0),
            "issues": ver.get("issues") or [],
            "conflicts": syn.get("conflicts") or [],
            "deadline_notices": syn.get("deadline_notices") or [],
            "missing_evidence_notices": syn.get("missing_evidence_notices") or [],
            "warnings": syn.get("warnings") or [],
            "claims": syn.get("claims") or [],
        },
        "step_latency": turn.get("step_trace") or [],
        "token_cost": {
            "prompt_tokens": int(tok.get("total_prompt_tokens") or 0),
            "completion_tokens": int(tok.get("total_completion_tokens") or 0),
            "total_tokens": int(tok.get("total_tokens") or 0),
            "cost_usd": float(tok.get("total_cost_usd") or 0.0),
            "total_latency_ms": float(tok.get("total_latency_ms") or 0.0),
        },
    }


def format_judge_answer(turn: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Reduce raw synthesis output into judge-readable result and verification sections."""
    synthesis = turn.get("synthesis") or {}
    meets = [claim for claim in (synthesis.get("meets_hard_criteria") or []) if isinstance(claim, dict)]
    verify = [claim for claim in (synthesis.get("still_verify") or []) if isinstance(claim, dict)]
    conflicts = [
        str(item.get("summary"))
        for item in (synthesis.get("conflicts") or [])
        if isinstance(item, dict) and item.get("summary")
    ]
    deadlines = [
        str(item.get("summary"))
        for item in (synthesis.get("deadline_notices") or [])
        if isinstance(item, dict) and item.get("summary")
    ]
    missing = [str(item) for item in (synthesis.get("missing_evidence_notices") or [])]
    notices = list(dict.fromkeys([*conflicts, *deadlines, *missing]))
    return meets[:8], verify[:8], notices[:8]


def render_streamlit_app() -> None:
    """Render full Streamlit UI (requires `streamlit` installed)."""
    import streamlit as st  # type: ignore

    try:
        if hasattr(st, "secrets"):
            secret_values = st.secrets.to_dict()
            for key in (
                "GEMINI_API_KEY",
                "FAST_MODEL",
                "STRONG_MODEL",
                "DATABASE_URL",
                "READONLY_DATABASE_URL",
            ):
                value = secret_values.get(key)
                if value:
                    os.environ[key] = str(value)
    except Exception:
        pass

    st.set_page_config(
        page_title="Alderwood University Assistant",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(
        """
        <style>
        :html, body, [class*="css"] { font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
        [data-testid="stAppViewContainer"] { background: #0b1220; color: #e5e7eb; }
        [data-testid="stMain"], [data-testid="stMainBlockContainer"] { background: #0b1220; }
        [data-testid="stAppViewBlockContainer"] { background: #0b1220; }
        [data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"] { display: none; }
        footer { visibility: hidden; }
        [data-testid="stSidebar"] { background: #172033; border-right: 1px solid #263247; width: 292px !important; }
        [data-testid="stSidebar"] * { color: #f8fafc; }
        [data-testid="stSidebar"] [data-baseweb="checkbox"] { margin-right: 4px; }
        .block-container { max-width: 1360px; padding-top: 1.25rem; padding-bottom: 1.5rem; }
        .app-header {
            background: linear-gradient(120deg, #172554 0%, #1e3a8a 55%, #155e75 100%);
            border: 1px solid #243b64;
            border-radius: 16px; padding: 18px 22px; margin: 0 0 14px 0; color: #f8fafc;
            box-shadow: 0 10px 24px rgba(0, 0, 0, 0.22);
        }
        .app-header h1 { font-size: 26px; margin: 0 0 3px 0; color: white; letter-spacing: -0.02em; }
        .app-header p { margin: 0; color: #dbeafe; font-size: 13px; }
        .panel {
            background: #111827; border: 1px solid #263247; border-radius: 16px;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.18); padding: 16px;
        }
        .panel-title { color: #f8fafc; font-size: 18px; font-weight: 780; margin: 0 0 12px 0; }
        .source-pill {
            display:inline-block; border-radius:999px; padding:5px 9px; margin:2px 5px 2px 0;
            font-size:12px; font-weight:700;
        }
        .pill-db { background:#e0ecff; color:#1d4ed8; }
        .pill-pdf { background:#dff7ef; color:#08785d; }
        .pill-llm { background:#ede9fe; color:#6d28d9; }
        .pill-pass { background:#dcfce7; color:#166534; }
        .pill-warn { background:#fef3c7; color:#92400e; }
        [data-testid="stChatMessage"] {
            border: 1px solid #263247; border-radius: 14px; background: #111827;
            margin: 0 0 10px 0; box-shadow: 0 4px 14px rgba(0, 0, 0, 0.16); color: #e5e7eb;
        }
        [data-testid="stChatMessage"] p, [data-testid="stChatMessage"] li,
        [data-testid="stChatMessage"] span, [data-testid="stChatMessage"] strong { color: #e5e7eb; }
        [data-testid="stMetric"] {
            background: #111827; border: 1px solid #263247; border-radius: 12px; padding: 12px;
        }
        [data-testid="stMetricLabel"] { color: #94a3b8; }
        [data-testid="stMetricValue"] { color: #f8fafc; }
        .sidebar-card { background:#1d2939; border:1px solid #344054; border-radius:12px; padding:12px; margin:8px 0; }
        .sidebar-card b { color:#dbeafe; }
        .trace-section { background:#111827; border:1px solid #263247; border-radius:12px; padding:12px; margin-bottom:10px; }
        .trace-section h4 { margin:0 0 8px 0; color:#f8fafc; }
        [data-baseweb="tab-list"] { gap: 4px; }
        [data-baseweb="tab"] { border-radius: 8px 8px 0 0; }
        [data-baseweb="tab"] * { color: #cbd5e1; }
        [data-baseweb="tab"][aria-selected="true"] * { color: #60a5fa; }
        [data-testid="stFileUploader"] { background:#1d2939; border:1px dashed #667085; border-radius:12px; padding:8px; }
        [data-testid="stChatInput"] { border-radius: 14px; background:#111827; }
        [data-testid="stChatInput"] textarea { color:#f8fafc; }
        [data-testid="stExpander"] { background:#111827; border:1px solid #263247; color:#e5e7eb; }
        [data-testid="stExpander"] summary, [data-testid="stExpander"] summary * { color:#e5e7eb; }
        [data-testid="stDataFrame"] { background:#111827; }
        [data-testid="stCodeBlock"], code { background:#0f172a !important; color:#e2e8f0 !important; }
        .stTabs [data-baseweb="tab-highlight"] { background:#60a5fa; }
        h1, h2, h3, h4, h5, h6, p, li, label, .stMarkdown { color:#e5e7eb; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <div class="app-header">
          <h1>Alderwood University Assistant</h1>
          <p>PostgreSQL + pgvector handbook search + live LLM routing and verification</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    cfg = AppConfig.load(ROOT / "config.yaml")
    personas = list_student_personas(root_dir=ROOT)
    persona_labels = {
        p["student_id"]: f"{p['student_id']} · {p['full_name']} ({p['dept_code']} Y{p['year_of_study']}, {p['cumulative_gpa']:.2f} GPA)"
        for p in personas
    }

    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "memory" not in st.session_state:
        st.session_state.memory = None
    if "last_turn" not in st.session_state:
        st.session_state.last_turn = None

    with st.sidebar:
        st.markdown("## University Workspace")
        st.caption("1 persona · 2 evidence sources · 1 verified answer")
        st.markdown("### Student")
        selected_sid = st.selectbox(
            "Logged-in persona",
            options=[p["student_id"] for p in personas],
            format_func=lambda sid: persona_labels.get(sid, sid),
        )
        selected_profile = next((p for p in personas if p["student_id"] == selected_sid), None)
        if selected_profile:
            st.markdown(
                f"""
                <div class="sidebar-card">
                  <b>{selected_profile['full_name']}</b><br>
                  Department: {selected_profile['dept_code']} · Year {selected_profile['year_of_study']}<br>
                  Cumulative GPA: {selected_profile['cumulative_gpa']:.2f}<br>
                  Semester GPA: {selected_profile['semester_gpa']:.2f}
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.markdown("### Evidence sources")
        api_url = os.environ.get("API_BASE_URL", "").strip()
        db_status = "Configured by server"
        if api_url:
            try:
                import urllib.request
                with urllib.request.urlopen(f"{api_url.rstrip('/')}/health", timeout=5) as resp:
                    health = json.loads(resp.read().decode("utf-8"))
                db_status = str(health.get("database", "unknown"))
            except Exception:
                db_status = "API unavailable"
        db_ok = "connected_readonly" in db_status
        st.markdown(
            f"""
            <div class="sidebar-card">
              <b>PostgreSQL</b><br>
              {'Read-only connection active' if db_ok else db_status}
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("### Judge Demo Sample")
        sample_pdf = ROOT / "data" / "pdfs" / "Alderwood_Database_Matched_Handbook.pdf"
        if sample_pdf.exists():
            st.caption(
                "Judge sample: this PDF is designed to cover the seeded Alderwood database—"
                " student profiles, grants, courses, timetable, fees, departments, mentor rules,"
                " stacking limits, and DB/PDF conflicts."
            )
            st.download_button(
                "Download sample PDF",
                data=sample_pdf.read_bytes(),
                file_name=sample_pdf.name,
                mime="application/pdf",
                use_container_width=True,
            )
            if api_url and st.button("Ingest sample PDF", use_container_width=True):
                import requests
                with st.spinner("Ingesting database-matched sample PDF..."):
                    response = requests.post(
                        f"{api_url.rstrip('/')}/sources/pdf",
                        files={"file": (sample_pdf.name, sample_pdf.read_bytes(), "application/pdf")},
                        timeout=300,
                    )
                if response.ok:
                    result = response.json()
                    st.success(f"Sample PDF ingested: `{result['doc_id']}`")
                else:
                    st.error(response.text)

        uploaded_pdf = st.file_uploader("Add a handbook PDF", type=["pdf"], help="The PDF is ingested into pgvector and searched with the live question.")
        if uploaded_pdf is not None and api_url:
            if st.button("Ingest PDF"):
                import requests
                with st.spinner("Ingesting PDF into pgvector..."):
                    response = requests.post(
                        f"{api_url.rstrip('/')}/sources/pdf",
                        files={"file": (uploaded_pdf.name, uploaded_pdf.getvalue(), "application/pdf")},
                        timeout=300,
                    )
                if response.ok:
                    result = response.json()
                    st.success(f"Ingested `{result['filename']}` as `{result['doc_id']}`")
                else:
                    st.error(response.text)

        st.divider()
        st.subheader("Feature Flags")
        flag_overrides = {
            "use_hyde": st.checkbox("use_hyde", value=cfg.flags.use_hyde),
            "use_reranker": st.checkbox("use_reranker", value=cfg.flags.use_reranker),
            "use_crag_grader": st.checkbox("use_crag_grader", value=cfg.flags.use_crag_grader),
            "use_llm_claim_check": st.checkbox("use_llm_claim_check", value=cfg.flags.use_llm_claim_check),
            "use_schema_index": st.checkbox("use_schema_index", value=cfg.flags.use_schema_index),
        }

        st.divider()
        if st.button("Reset Conversation"):
            st.session_state.messages = []
            st.session_state.memory = None
            st.session_state.last_turn = None
            st.rerun()

    col_chat, col_trace = st.columns([1.15, 0.85], gap="large")

    with col_chat:
        st.markdown('<p class="panel-title">Assistant Chat</p>', unsafe_allow_html=True)
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        prompt = st.chat_input("Ask a database or handbook question")
        if prompt:
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            with st.status("Analyzing sources...", expanded=False) as status:
                status.update(label="Routing through the live LLM")
                turn = None
                error_text = None
                api_url = os.environ.get("API_BASE_URL", "").strip()
                try:
                    if api_url:
                        req = urllib.request.Request(
                            f"{api_url.rstrip('/')}/chat",
                            data=json.dumps(
                                {
                                    "query": prompt,
                                    "persona_student_id": selected_sid,
                                    "memory": st.session_state.memory,
                                    "feature_flags": flag_overrides,
                                }
                            ).encode("utf-8"),
                            headers={"Content-Type": "application/json"},
                            method="POST",
                        )
                        with urllib.request.urlopen(req, timeout=600) as resp:
                            turn = json.loads(resp.read().decode("utf-8"))
                    else:
                        turn = run_assistant_query(
                            prompt,
                            persona_student_id=selected_sid,
                            memory=st.session_state.memory,
                            feature_flags_override=flag_overrides,
                            cfg=cfg,
                            root_dir=ROOT,
                        )
                except urllib.error.HTTPError as exc:
                    error_text = f"API returned HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')}"
                except urllib.error.URLError as exc:
                    error_text = f"Could not reach the API: {exc.reason}"
                except Exception as exc:
                    error_text = f"{type(exc).__name__}: {exc}"

            if error_text:
                st.error(error_text)
                st.session_state.messages.append({"role": "assistant", "content": f"**Request failed:** {error_text}"})
            else:
                st.session_state.memory = turn.get("memory")
                st.session_state.last_turn = turn
                answer_md = (turn.get("synthesis") or {}).get("answer_markdown") or ""
                plan = turn.get("plan") or {}
                route = str(plan.get("route", "unknown"))
                sql_rows = len((turn.get("sql_result") or {}).get("rows") or [])
                passages = len((turn.get("doc_result") or {}).get("passages") or [])
                badges = (
                    '<span class="source-pill pill-llm">LLM route</span>'
                    + (f'<span class="source-pill pill-db">Database · {sql_rows} rows</span>' if sql_rows else "")
                    + (f'<span class="source-pill pill-pdf">PDF · {passages} passages</span>' if passages else "")
                )
                st.session_state.messages.append({"role": "assistant", "content": answer_md})
                with st.chat_message("assistant"):
                    st.markdown(badges, unsafe_allow_html=True)
                    meets, verify, notices = format_judge_answer(turn)
                    if route == "out_of_scope":
                        st.error("Out of scope")
                        st.write(answer_md.split("## Meets hard criteria")[0].replace("## Out of Scope", "").strip())
                    else:
                        sql_rows = (turn.get("sql_result") or {}).get("rows") or []
                        grant_rows = [row for row in sql_rows if isinstance(row, dict) and row.get("grant_id")]
                        profile = ((turn.get("identity_check") or {}).get("profile") or {})
                        if grant_rows and profile:
                            filtered_grants = []
                            student_gpa = float(profile.get("cumulative_gpa") or 0)
                            student_year = int(profile.get("year_of_study") or 0)
                            student_dept = str(profile.get("dept_code") or "")
                            for row in grant_rows:
                                if str(row.get("status") or "").lower() != "open":
                                    continue
                                dept = str(row.get("dept_code") or "")
                                if dept not in ("ALL", student_dept):
                                    continue
                                try:
                                    if student_gpa < float(row.get("min_gpa") or 0):
                                        continue
                                    if not int(row.get("min_year") or 0) <= student_year <= int(row.get("max_year") or 99):
                                        continue
                                except (TypeError, ValueError):
                                    continue
                                filtered_grants.append(row)
                            grant_rows = filtered_grants
                        if grant_rows:
                            if profile:
                                st.write(
                                    f"Based on the university database, **{profile.get('full_name')}** "
                                    f"(Year {profile.get('year_of_study')}, {profile.get('dept_code')}, "
                                    f"cumulative GPA {profile.get('cumulative_gpa'):.2f}) is a numerical match for:"
                                )
                            names = []
                            for row in grant_rows:
                                name = row.get("grant_name") or row.get("grant_id")
                                amount = row.get("award_amount")
                                deadline = row.get("deadline")
                                text = f"**{name}**"
                                if amount is not None:
                                    text += f" (${float(amount):,.2f})"
                                if deadline is not None:
                                    text += f", database deadline {deadline}"
                                names.append(text)
                            st.markdown(" • " + "<br>• ".join(names), unsafe_allow_html=True)
                            st.caption(
                                "Policy conditions and any handbook deadline differences still need verification."
                            )
                        else:
                            if profile and "grant" in prompt.lower():
                                st.write(
                                    f"Based on the available university database, **{profile.get('full_name')}** "
                                    f"does not currently match any open research grant. "
                                    f"{profile.get('full_name')} is in Year {profile.get('year_of_study')}, "
                                    f"{profile.get('dept_code')}, with a cumulative GPA of "
                                    f"{profile.get('cumulative_gpa'):.2f}; no listed open grant satisfies the "
                                    "department, GPA, year, and deadline requirements."
                                )
                            elif meets:
                                st.markdown("**Key results**")
                                for claim in meets:
                                    entity = claim.get("entity") or "Result"
                                    field = claim.get("field") or "value"
                                    value = claim.get("value")
                                    source = claim.get("source_id") or ""
                                    citation = f" · {claim['citation']}" if claim.get("citation") else ""
                                    st.markdown(f"- **{entity}:** {value}")
                                    st.caption(f"{field.replace('_', ' ').title()} · Source: {source}{citation}")
                            else:
                                st.markdown("**Key results**")
                                st.info("No directly grounded numeric/database result was returned.")
                        if verify:
                            st.markdown("**Needs verification**")
                            for claim in verify[:5]:
                                entity = claim.get("entity") or "Policy"
                                field = claim.get("field") or "condition"
                                value = claim.get("value")
                                source = claim.get("source_id") or ""
                                citation = f" · {claim['citation']}" if claim.get("citation") else ""
                                st.markdown(
                                    f"- **{entity}** — **{field}:** {value}"
                                    f'<br><span style="color:#64748b;font-size:12px;">Source: `{source}`{citation}</span>',
                                    unsafe_allow_html=True,
                                )
                        if notices:
                            st.markdown("**Important notice**")
                            for notice in notices[:3]:
                                st.warning(notice)

    with col_trace:
        st.markdown('<p class="panel-title">How It Answered</p>', unsafe_allow_html=True)
        if not st.session_state.last_turn:
            st.markdown(
                """
                <div class="panel">
                  <b>Waiting for a question</b>
                  <p style="color:#64748b;margin-bottom:0;">The trace will separate route, SQL, PDF passages, verification, and latency.</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            trace_vm = build_trace_panel_payload(st.session_state.last_turn)
            ver = trace_vm["verification_result"]
            m1, m2, m3 = st.columns(3)
            m1.metric("Route", trace_vm["route"].replace("_", " ").title())
            m2.metric("SQL rows", trace_vm["sql"]["row_count"])
            m3.metric("PDF passages", len(trace_vm["retrieved_chunks"]))

            verification_label = "Verified" if ver["passed"] else "Needs review"
            verification_class = "pill-pass" if ver["passed"] else "pill-warn"
            st.markdown(
                f'<span class="source-pill pill-llm">{trace_vm["decision_path"]}</span>'
                f'<span class="source-pill {verification_class}">{verification_label}</span>'
                f'<span class="source-pill pill-db">{trace_vm["token_cost"]["total_latency_ms"]:.0f} ms total</span>',
                unsafe_allow_html=True,
            )

            tab_route, tab_sql, tab_pdf, tab_check, tab_perf = st.tabs(
                ["Route", "Database", "PDF evidence", "Verification", "Latency"]
            )

            with tab_route:
                st.markdown("#### Routing decision")
                st.write(trace_vm["plan"]["resolved_query"] or "No resolved query returned.")
                st.write(f"**Mode:** `{trace_vm['execution_mode']}`")
                st.write(f"**Decision:** `{trace_vm['decision_path']}`")
                if trace_vm["plan"]["target_grant_ids"]:
                    st.write("**Grant IDs:** " + ", ".join(f"`{g}`" for g in trace_vm["plan"]["target_grant_ids"]))
                if trace_vm["plan"]["identity_warning"]:
                    st.warning(trace_vm["plan"]["identity_warning"])

            with tab_sql:
                st.markdown("#### SQL evidence")
                if trace_vm["sql"]["sql"]:
                    st.code(trace_vm["sql"]["sql"], language="sql")
                    if trace_vm["sql"]["tables"]:
                        st.caption("Tables: " + ", ".join(trace_vm["sql"]["tables"]))
                    if trace_vm["sql"]["rows"]:
                        st.dataframe(trace_vm["sql"]["rows"], use_container_width=True)
                    else:
                        st.info("The query ran successfully and returned no rows.")
                else:
                    st.info("Database branch was not executed.")

            with tab_pdf:
                st.markdown("#### Handbook evidence")
                chunks = trace_vm["retrieved_chunks"]
                if not chunks:
                    st.info("No PDF passages were used.")
                for index, ch in enumerate(chunks, start=1):
                    with st.expander(f"{index}. {ch['citation']}", expanded=index == 1):
                        st.caption(
                            f"RRF: {ch['rrf_score'] or 0:.4f} · Rerank: {ch['rerank_score'] or 0:.4f} · {ch['crag_grade']}"
                        )
                        st.write(ch["text"])

            with tab_check:
                st.markdown("#### Verification")
                st.metric("Claims checked", ver["checked_claims_count"])
                st.metric("Policy claims", ver["policy_claims_count"])
                if ver["conflicts"]:
                    st.warning("DB vs PDF conflict detected")
                    for conflict in ver["conflicts"]:
                        st.write(conflict["summary"])
                if ver["deadline_notices"]:
                    for notice in ver["deadline_notices"]:
                        st.warning(notice["summary"])
                if ver["missing_evidence_notices"]:
                    for notice in ver["missing_evidence_notices"]:
                        st.info(notice)
                if ver["issues"]:
                    for issue in ver["issues"]:
                        st.error(f"{issue['entity']} · {issue['message']}")
                if ver["warnings"]:
                    for warning in ver["warnings"]:
                        st.warning(warning)

            with tab_perf:
                st.markdown("#### Real latency")
                if trace_vm["step_latency"]:
                    st.dataframe(trace_vm["step_latency"], use_container_width=True, hide_index=True)
                st.caption(
                    f"{trace_vm['token_cost']['total_tokens']} LLM tokens · "
                    f"${trace_vm['token_cost']['cost_usd']:.5f} estimated cost"
                )


if __name__ == "__main__":
    try:
        render_streamlit_app()
    except ImportError:
        print("Streamlit is not installed in this minimal container. Install requirements.txt and run: streamlit run app_streamlit.py")
