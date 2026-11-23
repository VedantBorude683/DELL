"""Phase 7 Streamlit UI: Persona Selector, Chat, and Full Execution Trace Panel.

Launch:
    streamlit run app_streamlit.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.assistant import run_assistant_query
from src.config import AppConfig
from src.orchestrator.identity import list_student_personas


def build_trace_panel_payload(turn: dict[str, Any]) -> dict[str, Any]:
    """Pure-Python view-model builder for the Streamlit trace panel (unit-testable cleanly)."""
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


def render_streamlit_app() -> None:
    """Render full Streamlit UI (requires `streamlit` installed)."""
    import streamlit as st  # type: ignore

    st.set_page_config(
        page_title="Alderwood Hybrid RAG — University Assistant",
        layout="wide",
    )
    st.title("Alderwood University Hybrid RAG")
    st.caption("PostgreSQL 16 + pgvector + FTS · LangGraph · Verified Claim Synthesis · FastMCP")

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
        st.header("Student Persona & Flags")
        selected_sid = st.selectbox(
            "Logged-in Persona",
            options=[p["student_id"] for p in personas],
            format_func=lambda sid: persona_labels.get(sid, sid),
        )
        selected_profile = next((p for p in personas if p["student_id"] == selected_sid), None)
        if selected_profile:
            st.markdown(
                f"**Dept:** `{selected_profile['dept_code']}` · **Year:** `{selected_profile['year_of_study']}`  \n"
                f"**Cumulative GPA:** `{selected_profile['cumulative_gpa']:.2f}` · **Semester:** `{selected_profile['semester_gpa']:.2f}`"
            )

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

    col_chat, col_trace = st.columns([1.05, 1.0], gap="large")

    with col_chat:
        st.subheader("Assistant Chat")
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        prompt = st.chat_input("Ask about research grants, deadlines, GPA rules, fees, or campus policies...")
        if prompt:
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            with st.spinner("Routing, querying Postgres + PDFs, and verifying claims..."):
                api_url = os.environ.get("API_BASE_URL", "").strip()
                if api_url:
                    import urllib.request
                    import json

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
                    with urllib.request.urlopen(req, timeout=30) as resp:
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

            st.session_state.memory = turn.get("memory")
            st.session_state.last_turn = turn
            answer_md = (turn.get("synthesis") or {}).get("answer_markdown") or ""
            st.session_state.messages.append({"role": "assistant", "content": answer_md})
            with st.chat_message("assistant"):
                st.markdown(answer_md)

    with col_trace:
        st.subheader("Execution Trace & Verification Panel")
        if not st.session_state.last_turn:
            st.info("Submit a question in the chat panel to inspect route, plan, SQL, retrieved chunks, verification, per-step latency, and token cost.")
        else:
            trace_vm = build_trace_panel_payload(st.session_state.last_turn)
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Route", f"{trace_vm['route']} ({trace_vm['execution_mode']})")
            m2.metric("Verification", "PASS" if trace_vm["verification_result"]["passed"] else "WARN")
            m3.metric("Total Latency", f"{trace_vm['token_cost']['total_latency_ms']:.1f} ms")
            m4.metric("Tokens / Cost", f"{trace_vm['token_cost']['total_tokens']} · ${trace_vm['token_cost']['cost_usd']:.5f}")

            tab_plan, tab_sql, tab_chunks, tab_ver, tab_lat = st.tabs(
                ["Route & Plan", "SQL", "Retrieved Chunks", "Verification", "Latency & Cost"]
            )

            with tab_plan:
                st.json(
                    {
                        "route": trace_vm["route"],
                        "execution_mode": trace_vm["execution_mode"],
                        "decision_path": trace_vm["decision_path"],
                        **trace_vm["plan"],
                    }
                )

            with tab_sql:
                if trace_vm["sql"]["sql"]:
                    st.code(trace_vm["sql"]["sql"], language="sql")
                    st.caption(f"Tables: {', '.join(trace_vm['sql']['tables'])} · Rows: {trace_vm['sql']['row_count']}")
                    if trace_vm["sql"]["rows"]:
                        st.dataframe(trace_vm["sql"]["rows"], use_container_width=True)
                    st.json(trace_vm["sql"]["provenance"])
                else:
                    st.write("SQL branch was not executed for this route.")

            with tab_chunks:
                chunks = trace_vm["retrieved_chunks"]
                if not chunks:
                    st.write("No document passages retrieved (vector branch skipped or 0-row SQL stop).")
                for ch in chunks:
                    with st.expander(f"{ch['citation']} · rrf={ch['rrf_score']} rerank={ch['rerank_score']} ({ch['crag_grade']})"):
                        st.write(ch["text"])

            with tab_ver:
                ver_v = trace_vm["verification_result"]
                st.write(
                    f"**Passed:** `{ver_v['passed']}` · **LLM Claim Check:** `{ver_v['llm_check_backend']}` · "
                    f"**Claims:** `{ver_v['checked_claims_count']}` · **Regenerations:** `{ver_v['regeneration_count']}`"
                )
                if ver_v["conflicts"]:
                    st.warning("DB vs. PDF Conflicts: " + "; ".join(c["summary"] for c in ver_v["conflicts"]))
                if ver_v["deadline_notices"]:
                    st.warning("Expired Deadlines: " + "; ".join(d["summary"] for d in ver_v["deadline_notices"]))
                if ver_v["warnings"]:
                    st.error(" · ".join(ver_v["warnings"]))
                if ver_v["claims"]:
                    st.dataframe(ver_v["claims"], use_container_width=True)

            with tab_lat:
                st.dataframe(trace_vm["step_latency"], use_container_width=True)
                st.json(trace_vm["token_cost"])


if __name__ == "__main__":
    try:
        render_streamlit_app()
    except ImportError:
        print("Streamlit is not installed in this minimal container. Install requirements.txt and run: streamlit run app_streamlit.py")
