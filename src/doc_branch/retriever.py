"""Phase 4 Document Branch: pgvector/cosine + FTS hybrid search fused with RRF, metadata filters, reranker, 1-retry HyDE, and optional CRAG."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from src.config import AppConfig
from src.doc_branch.hyde_and_crag import (
    CragGraderFn,
    HydeGeneratorFn,
    generate_hyde_passage,
    grade_passages_crag,
)
from src.doc_branch.models import DocumentSearchResult, MetadataFilter, Passage
from src.doc_branch.reranker import Reranker
from src.rag.embeddings import Embedder, cosine_similarity


def _format_citation(chunk: dict[str, Any]) -> str:
    parts = [f"{chunk['doc_id']} {chunk['version']}", f"p.{chunk['page_num']}"]
    if chunk.get("grant_id"):
        parts.append(str(chunk["grant_id"]))
    if chunk.get("chunk_type") == "table":
        parts.append("Table")
    return "[" + ", ".join(parts) + "]"


def _build_sqlite_where(filters: MetadataFilter | None) -> tuple[str, list[Any]]:
    if filters is None:
        return "", []
    clauses: list[str] = []
    params: list[Any] = []
    if filters.grant_ids:
        placeholders = ",".join("?" for _ in filters.grant_ids)
        clauses.append(f"grant_id IN ({placeholders})")
        params.extend(filters.grant_ids)
    if filters.doc_ids:
        placeholders = ",".join("?" for _ in filters.doc_ids)
        clauses.append(f"doc_id IN ({placeholders})")
        params.extend(filters.doc_ids)
    if filters.version:
        clauses.append("version = ?")
        params.append(filters.version)
    if filters.dept_code:
        clauses.append("(dept_code = ? OR dept_code = 'ALL' OR dept_code IS NULL)")
        params.append(filters.dept_code)
    if filters.year_scope:
        clauses.append("(year_scope = ? OR year_scope IS NULL)")
        params.append(filters.year_scope)
    if filters.exclude_title_banners:
        clauses.append("chunk_id NOT LIKE '%_c01'")
    if not clauses:
        return "", []
    return "WHERE " + " AND ".join(clauses), params


def _sqlite_fts5_ranks(query: str, chunks: list[dict[str, Any]], fts_top_k: int) -> dict[str, tuple[int, float]]:
    """Run SQLite FTS5 BM25 ranking over the filtered chunk set."""
    if not chunks:
        return {}
    terms = re.findall(r"[a-zA-Z0-9_]{2,}", query.lower())
    if not terms:
        return {}
    # Deduplicate preserving order; quote each term safely for FTS5 MATCH
    unique_terms = list(dict.fromkeys(terms))[:24]
    fts_expr = " OR ".join(f'"{t}"' for t in unique_terms)

    mem = sqlite3.connect(":memory:")
    try:
        mem.execute("CREATE VIRTUAL TABLE chunks_fts USING fts5(chunk_id UNINDEXED, content)")
        mem.executemany(
            "INSERT INTO chunks_fts (chunk_id, content) VALUES (?, ?)",
            [(c["chunk_id"], c["content"]) for c in chunks],
        )
        rows = mem.execute(
            "SELECT chunk_id, bm25(chunks_fts) AS score FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY score ASC LIMIT ?",
            (fts_expr, fts_top_k),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        mem.close()

    return {
        row[0]: (rank, round(-float(row[1]), 6))
        for rank, row in enumerate(rows, start=1)
    }


def _hybrid_search_postgres(
    query: str,
    *,
    filters: MetadataFilter | None,
    vector_top_k: int,
    fts_top_k: int,
    rrf_k: int,
    active_cfg: AppConfig,
    active_embedder: Embedder,
) -> tuple[list[dict[str, Any]], str]:
    from sqlalchemy import create_engine, text  # type: ignore

    db_url = os.environ["DATABASE_URL"]
    q_vec = active_embedder.embed_one(query)
    vec_literal = "[" + ",".join(f"{x:.6f}" for x in q_vec) + "]"

    clauses: list[str] = []
    params: dict[str, Any] = {
        "qvec": vec_literal,
        "qtext": query,
        "v_k": vector_top_k,
        "f_k": fts_top_k,
    }
    if filters:
        if filters.grant_ids:
            clauses.append("grant_id = ANY(:grant_ids)")
            params["grant_ids"] = list(filters.grant_ids)
        if filters.doc_ids:
            clauses.append("doc_id = ANY(:doc_ids)")
            params["doc_ids"] = list(filters.doc_ids)
        if filters.version:
            clauses.append("version = :version")
            params["version"] = filters.version
        if filters.dept_code:
            clauses.append("(dept_code = :dept_code OR dept_code = 'ALL' OR dept_code IS NULL)")
            params["dept_code"] = filters.dept_code
        if filters.year_scope:
            clauses.append("(year_scope = :year_scope OR year_scope IS NULL)")
            params["year_scope"] = filters.year_scope
        if filters.exclude_title_banners:
            clauses.append("chunk_id NOT LIKE '%_c01'")

    where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    engine = create_engine(db_url, pool_pre_ping=True)
    with engine.connect() as conn:
        vec_rows = conn.execute(
            text(
                f"""
                SELECT chunk_id, doc_id, version, effective_date::text, grant_id, dept_code,
                       year_scope, page_num, chunk_type, content, structured_table_json,
                       injection_flagged, (1.0 - (embedding <=> CAST(:qvec AS vector))) AS vec_sim
                FROM document_chunks
                {where_sql}
                ORDER BY embedding <=> CAST(:qvec AS vector) ASC
                LIMIT :v_k
                """
            ),
            params,
        ).mappings().all()

        fts_where = (
            f"{where_sql} AND tsv @@ websearch_to_tsquery('english', :qtext)"
            if where_sql
            else "WHERE tsv @@ websearch_to_tsquery('english', :qtext)"
        )
        fts_rows = conn.execute(
            text(
                f"""
                SELECT chunk_id, doc_id, version, effective_date::text, grant_id, dept_code,
                       year_scope, page_num, chunk_type, content, structured_table_json,
                       injection_flagged, ts_rank_cd(tsv, websearch_to_tsquery('english', :qtext)) AS fts_score
                FROM document_chunks
                {fts_where}
                ORDER BY fts_score DESC
                LIMIT :f_k
                """
            ),
            params,
        ).mappings().all()

    by_id: dict[str, dict[str, Any]] = {}
    for rank, row in enumerate(vec_rows, start=1):
        cid = row["chunk_id"]
        d = dict(row)
        d["vector_rank"] = rank
        d["fts_rank"] = None
        d["vec_sim"] = float(row["vec_sim"] or 0.0)
        d["fts_score"] = 0.0
        by_id[cid] = d

    for rank, row in enumerate(fts_rows, start=1):
        cid = row["chunk_id"]
        if cid not in by_id:
            d = dict(row)
            d["vector_rank"] = None
            d["vec_sim"] = 0.0
            by_id[cid] = d
        by_id[cid]["fts_rank"] = rank
        by_id[cid]["fts_score"] = float(row["fts_score"] or 0.0)

    fused: list[dict[str, Any]] = []
    for item in by_id.values():
        rrf = 0.0
        if item["vector_rank"] is not None:
            rrf += 1.0 / (rrf_k + item["vector_rank"])
        if item["fts_rank"] is not None:
            rrf += 1.0 / (rrf_k + item["fts_rank"])
        item["rrf_score"] = round(rrf, 6)
        if isinstance(item.get("structured_table_json"), str):
            item["structured_table_json"] = json.loads(item["structured_table_json"])
        fused.append(item)

    fused.sort(key=lambda x: x["rrf_score"], reverse=True)
    return fused, "postgres_pgvector_tsvector_rrf"


def hybrid_search_chunks(
    query: str,
    *,
    filters: MetadataFilter | None = None,
    vector_top_k: int = 12,
    fts_top_k: int = 12,
    rrf_k: int = 60,
    cfg: AppConfig | None = None,
    root_dir: Path | None = None,
    embedder: Embedder | None = None,
    cached_chunks: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Run vector + FTS hybrid search over metadata-filtered chunks and fuse with RRF."""
    root = root_dir or Path(".")
    active_cfg = cfg or AppConfig.load(root / "config.yaml")
    active_embedder = embedder or Embedder(
        model_name=str(active_cfg.raw.get("models", {}).get("embedding_model", "BAAI/bge-m3"))
    )

    pg_url = os.environ.get("DATABASE_URL", "").strip()
    use_postgres = os.environ.get("USE_POSTGRES", "").lower() == "true"
    if pg_url and ("alderwood_password" not in pg_url or use_postgres) and cached_chunks is None:
        return _hybrid_search_postgres(
            query,
            filters=filters,
            vector_top_k=vector_top_k,
            fts_top_k=fts_top_k,
            rrf_k=rrf_k,
            active_cfg=active_cfg,
            active_embedder=active_embedder,
        )

    # Load and metadata-filter SQLite mirror chunks (or filter cached_chunks in-memory)
    if cached_chunks is None:
        db_path = (root / active_cfg.sqlite_mirror_path).resolve()
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        where_sql, params = _build_sqlite_where(filters)
        rows = conn.execute(
            f"""
            SELECT chunk_id, doc_id, version, effective_date, grant_id, dept_code, year_scope,
                   page_num, chunk_type, content, structured_table_json, injection_flagged, embedding_json
            FROM document_chunks
            {where_sql}
            """,
            params,
        ).fetchall()
        conn.close()
        chunks = [
            {
                "chunk_id": r["chunk_id"],
                "doc_id": r["doc_id"],
                "version": r["version"],
                "effective_date": r["effective_date"],
                "grant_id": r["grant_id"],
                "dept_code": r["dept_code"],
                "year_scope": r["year_scope"],
                "page_num": int(r["page_num"]),
                "chunk_type": r["chunk_type"],
                "content": r["content"],
                "structured_table_json": json.loads(r["structured_table_json"])
                if r["structured_table_json"]
                else None,
                "injection_flagged": bool(r["injection_flagged"]),
                "embedding": json.loads(r["embedding_json"]) if r["embedding_json"] else [],
            }
            for r in rows
        ]
    else:
        chunks = []
        for c in cached_chunks:
            if filters:
                if filters.grant_ids and c.get("grant_id") not in filters.grant_ids:
                    continue
                if filters.doc_ids and c.get("doc_id") not in filters.doc_ids:
                    continue
                if filters.version and c.get("version") != filters.version:
                    continue
                if filters.dept_code and c.get("dept_code") not in (filters.dept_code, "ALL", None):
                    continue
                if filters.year_scope and c.get("year_scope") not in (filters.year_scope, None):
                    continue
                if filters.exclude_title_banners and str(c.get("chunk_id", "")).endswith("_c01"):
                    continue
            chunks.append(dict(c))

    if not chunks:
        return [], "sqlite_vector_fts5_rrf"

    q_vec = active_embedder.embed_one(query)
    vec_scored: list[tuple[str, float]] = []
    for c in chunks:
        sim = cosine_similarity(q_vec, c["embedding"])
        c["vec_sim"] = round(sim, 6)
        vec_scored.append((c["chunk_id"], sim))
    vec_scored.sort(key=lambda item: item[1], reverse=True)
    vec_ranks = {cid: rank for rank, (cid, _) in enumerate(vec_scored[:vector_top_k], start=1)}

    fts_ranks = _sqlite_fts5_ranks(query, chunks, fts_top_k)

    fused: list[dict[str, Any]] = []
    for c in chunks:
        cid = c["chunk_id"]
        v_rank = vec_ranks.get(cid)
        f_rank = fts_ranks.get(cid, (None, 0.0))[0]
        f_score = fts_ranks.get(cid, (None, 0.0))[1]
        if v_rank is None and f_rank is None:
            continue
        rrf = (1.0 / (rrf_k + v_rank) if v_rank is not None else 0.0) + (
            1.0 / (rrf_k + f_rank) if f_rank is not None else 0.0
        )
        merged = dict(c)
        merged["vector_rank"] = v_rank
        merged["fts_rank"] = f_rank
        merged["fts_score"] = f_score
        merged["rrf_score"] = round(rrf, 6)
        fused.append(merged)

    fused.sort(key=lambda x: (x["rrf_score"], x["vec_sim"]), reverse=True)
    return fused, "sqlite_vector_fts5_rrf"


def search_documents(
    query: str,
    *,
    filters: MetadataFilter | None = None,
    top_k: int | None = None,
    cfg: AppConfig | None = None,
    root_dir: Path | None = None,
    embedder: Embedder | None = None,
    reranker: Reranker | None = None,
    hyde_generator: HydeGeneratorFn | None = None,
    crag_grader: CragGraderFn | None = None,
    cached_chunks: list[dict[str, Any]] | None = None,
) -> DocumentSearchResult:
    """Execute full Phase 4 document branch: hybrid RRF -> rerank -> optional 1x HyDE retry -> optional CRAG -> Passage[]."""
    root = root_dir or Path(".")
    active_cfg = cfg or AppConfig.load(root / "config.yaml")
    ret_cfg = active_cfg.raw.get("retrieval", {})

    vector_top_k = int(ret_cfg.get("vector_top_k", 12))
    fts_top_k = int(ret_cfg.get("fts_top_k", 12))
    rrf_k = int(ret_cfg.get("rrf_k", 60))
    rerank_top_k = int(top_k if top_k is not None else ret_cfg.get("rerank_top_k", 5))
    rerank_threshold = float(ret_cfg.get("rerank_score_threshold", 0.42))

    active_embedder = embedder or Embedder(
        model_name=str(active_cfg.raw.get("models", {}).get("embedding_model", "BAAI/bge-m3"))
    )
    active_reranker = reranker or Reranker(
        model_name=str(active_cfg.raw.get("models", {}).get("reranker_model", "BAAI/bge-reranker-v2-m3"))
    )

    started = time.perf_counter()

    def _run_pass(search_query: str, original_query: str) -> tuple[list[dict[str, Any]], float, str]:
        fused, search_backend = hybrid_search_chunks(
            search_query,
            filters=filters,
            vector_top_k=vector_top_k,
            fts_top_k=fts_top_k,
            rrf_k=rrf_k,
            cfg=active_cfg,
            root_dir=root,
            embedder=active_embedder,
            cached_chunks=cached_chunks,
        )
        if not fused:
            return [], 0.0, search_backend

        if active_cfg.flags.use_reranker:
            scores = active_reranker.score_pairs(original_query, fused)
            for item, sc in zip(fused, scores):
                item["rerank_score"] = sc
            fused.sort(key=lambda x: (x["rerank_score"], x["rrf_score"]), reverse=True)
            top_sc = float(fused[0]["rerank_score"])
        else:
            # When reranker is OFF, derive confidence strictly from RRF + cosine to gate HyDE
            # while preserving pure RRF rank ordering.
            for item in fused:
                item["rerank_score"] = round(min(0.99, item["rrf_score"] * 9.0 + item.get("vec_sim", 0.0) * 0.35), 4)
            top_sc = float(fused[0]["rerank_score"])
        return fused, top_sc, search_backend

    # Pass 1: Hybrid search (+ optional rerank)
    candidates, top_score_initial, search_backend = _run_pass(query, query)

    hyde_triggered = False
    hyde_backend = "not_run"
    hyde_text: str | None = None
    top_score_after_hyde = top_score_initial

    # Pass 2 (max 1 HyDE retry) if use_hyde enabled and top score < threshold
    if active_cfg.flags.use_hyde and (not candidates or top_score_initial < rerank_threshold):
        hyde_triggered = True
        hyde_text, hyde_backend = generate_hyde_passage(
            query, cfg=active_cfg, hyde_generator=hyde_generator
        )
        hyde_query = f"{query}\n{hyde_text}"
        # Expand retrieval query via HyDE while reranking strictly against original user query
        hyde_candidates, top_score_after_hyde, _ = _run_pass(hyde_query, query)

        # Merge initial and HyDE candidates keeping highest score per chunk_id
        merged_map: dict[str, dict[str, Any]] = {c["chunk_id"]: c for c in candidates}
        for hc in hyde_candidates:
            cid = hc["chunk_id"]
            if cid not in merged_map or (hc["rerank_score"], hc["rrf_score"]) > (
                merged_map[cid]["rerank_score"],
                merged_map[cid]["rrf_score"],
            ):
                merged_map[cid] = hc
        candidates = list(merged_map.values())
        if active_cfg.flags.use_reranker:
            candidates.sort(key=lambda x: (x["rerank_score"], x["rrf_score"]), reverse=True)
        else:
            candidates.sort(key=lambda x: (x["rrf_score"], x["rerank_score"]), reverse=True)

    # Diversity-aware selection: max 3 chunks per doc_id when reranker is active so multi-handbook queries aren't crowded out
    if active_cfg.flags.use_reranker:
        selected: list[dict[str, Any]] = []
        overflow: list[dict[str, Any]] = []
        per_doc_counts: dict[str, int] = {}
        for c in candidates:
            cnt = per_doc_counts.get(c["doc_id"], 0)
            if cnt < 3:
                selected.append(c)
                per_doc_counts[c["doc_id"]] = cnt + 1
            else:
                overflow.append(c)
            if len(selected) >= rerank_top_k:
                break
        if len(selected) < rerank_top_k:
            selected.extend(overflow[: rerank_top_k - len(selected)])
    else:
        selected = candidates[:rerank_top_k]
    passages = [
        Passage(
            text=c["content"],
            doc_id=c["doc_id"],
            version=c["version"],
            page=int(c["page_num"]),
            citation=_format_citation(c),
            chunk_id=c["chunk_id"],
            chunk_type=c["chunk_type"],
            grant_id=c.get("grant_id"),
            dept_code=c.get("dept_code"),
            effective_date=str(c.get("effective_date", "")),
            structured_table_json=c.get("structured_table_json"),
            injection_flagged=bool(c.get("injection_flagged", False)),
            vector_rank=c.get("vector_rank"),
            fts_rank=c.get("fts_rank"),
            rrf_score=float(c.get("rrf_score", 0.0)),
            rerank_score=float(c.get("rerank_score", 0.0)),
        )
        for c in selected
    ]

    crag_backend = "disabled"
    crag_grades: list[dict[str, str]] = []
    if active_cfg.flags.use_crag_grader and passages:
        passages, crag_grades, crag_backend = grade_passages_crag(
            query, passages, cfg=active_cfg, crag_grader=crag_grader
        )

    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    trace = {
        "query": query,
        "filters": {
            "grant_ids": list(filters.grant_ids) if filters else [],
            "doc_ids": list(filters.doc_ids) if filters else [],
            "version": filters.version if filters else None,
            "dept_code": filters.dept_code if filters else None,
            "year_scope": filters.year_scope if filters else None,
        },
        "search_backend": search_backend,
        "embedder_backend": active_embedder.backend_name,
        "reranker_enabled": active_cfg.flags.use_reranker,
        "reranker_backend": active_reranker.backend_name if active_cfg.flags.use_reranker else "disabled",
        "rerank_score_threshold": rerank_threshold,
        "top_score_initial": round(top_score_initial, 4),
        "hyde_enabled": active_cfg.flags.use_hyde,
        "hyde_triggered": hyde_triggered,
        "hyde_retry_count": 1 if hyde_triggered else 0,
        "hyde_backend": hyde_backend,
        "hyde_text": hyde_text,
        "top_score_after_hyde": round(top_score_after_hyde, 4),
        "crag_enabled": active_cfg.flags.use_crag_grader,
        "crag_backend": crag_backend,
        "crag_grades": crag_grades,
        "returned_count": len(passages),
        "latency_ms": latency_ms,
    }
    return DocumentSearchResult(passages=passages, trace=trace)


def retrieve_passages(
    query: str,
    *,
    filters: MetadataFilter | None = None,
    top_k: int | None = None,
    cfg: AppConfig | None = None,
    root_dir: Path | None = None,
) -> list[Passage]:
    """Convenience wrapper returning Passage[] directly."""
    return search_documents(
        query,
        filters=filters,
        top_k=top_k,
        cfg=cfg,
        root_dir=root_dir,
    ).passages
