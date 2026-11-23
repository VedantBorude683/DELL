"""Phase 4 evaluation harness: Recall@k across HyDE/reranker flag combinations and metadata filters."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Any

from src.config import AppConfig
from src.doc_branch.reranker import Reranker
from src.doc_branch.retriever import search_documents
from src.rag.embeddings import Embedder


def _load_cached_chunks(root: Path, cfg: AppConfig) -> list[dict[str, Any]]:
    db_path = (root / cfg.sqlite_mirror_path).resolve()
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT chunk_id, doc_id, version, effective_date, grant_id, dept_code, year_scope,
               page_num, chunk_type, content, structured_table_json, injection_flagged, embedding_json
        FROM document_chunks
        """
    ).fetchall()
    conn.close()
    return [
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


def evaluate_doc_recall_ablation(
    root_dir: Path | None = None,
    *,
    cfg: AppConfig | None = None,
    k_values: tuple[int, ...] = (3, 5),
) -> dict[str, Any]:
    """Measure Document Recall@k and MRR on gold queries with HyDE and reranker flags ON vs OFF."""
    root = root_dir or Path(".")
    base_cfg = cfg or AppConfig.load(root / "config.yaml")
    embedder = Embedder(
        model_name=str(base_cfg.raw.get("models", {}).get("embedding_model", "BAAI/bge-m3"))
    )
    reranker = Reranker(
        model_name=str(base_cfg.raw.get("models", {}).get("reranker_model", "BAAI/bge-reranker-v2-m3"))
    )
    cached_chunks = _load_cached_chunks(root, base_cfg)

    gold_rows = [
        json.loads(line)
        for line in (root / base_cfg.gold_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    eval_rows = [r for r in gold_rows if r.get("expected_doc_ids")]
    max_k = max(k_values)

    matrix_configs = [
        ("rrf_only", False, False, False),
        ("rrf_rerank", False, True, False),
        ("rrf_hyde", True, False, False),
        ("full_phase4", True, True, True),
    ]

    ablation_results: list[dict[str, Any]] = []
    full_query_details: list[dict[str, Any]] = []

    for mode_name, use_hyde, use_reranker, use_crag in matrix_configs:
        mode_cfg = replace(
            base_cfg,
            flags=replace(
                base_cfg.flags,
                use_hyde=use_hyde,
                use_reranker=use_reranker,
                use_crag_grader=use_crag,
            ),
        )
        recall_sums = {k: 0.0 for k in k_values}
        any_hit_sums = {k: 0 for k in k_values}
        mrr_sum = 0.0
        hyde_triggers = 0

        for row in eval_rows:
            res = search_documents(
                row["query"],
                top_k=max_k,
                cfg=mode_cfg,
                root_dir=root,
                embedder=embedder,
                reranker=reranker,
                cached_chunks=cached_chunks,
            )
            if res.trace.get("hyde_triggered"):
                hyde_triggers += 1

            expected = set(row["expected_doc_ids"])
            retrieved_docs_ordered: list[str] = []
            for p in res.passages:
                if p.doc_id not in retrieved_docs_ordered:
                    retrieved_docs_ordered.append(p.doc_id)

            # All chunks' doc_ids at rank position (standard document-level Recall@k over top-k passages)
            passage_doc_ids = [p.doc_id for p in res.passages]
            for k in k_values:
                top_docs = set(passage_doc_ids[:k])
                overlap = expected & top_docs
                recall_sums[k] += len(overlap) / len(expected)
                if overlap:
                    any_hit_sums[k] += 1

            # MRR of first expected doc_id in passage list
            rr = 0.0
            for idx, did in enumerate(passage_doc_ids, start=1):
                if did in expected:
                    rr = 1.0 / idx
                    break
            mrr_sum += rr

            if mode_name == "full_phase4":
                top5 = set(passage_doc_ids[:5])
                full_query_details.append(
                    {
                        "query_id": row["query_id"],
                        "route": row["route"],
                        "query": row["query"],
                        "expected_doc_ids": sorted(expected),
                        "retrieved_doc_ids_top5": retrieved_docs_ordered[:5],
                        "recall_at_5": round(len(expected & top5) / len(expected), 4),
                        "top_rerank_score": res.trace["top_score_initial"],
                        "hyde_triggered": res.trace["hyde_triggered"],
                        "top_citation": res.passages[0].citation if res.passages else "",
                    }
                )

        n = len(eval_rows)
        ablation_results.append(
            {
                "mode": mode_name,
                "use_hyde": use_hyde,
                "use_reranker": use_reranker,
                "use_crag_grader": use_crag,
                "evaluated_queries": n,
                "recall_at_3": round(recall_sums[3] / n, 4) if 3 in recall_sums and n else 0.0,
                "recall_at_5": round(recall_sums[5] / n, 4) if 5 in recall_sums and n else 0.0,
                "any_hit_at_5": round(any_hit_sums[5] / n, 4) if 5 in any_hit_sums and n else 0.0,
                "mrr": round(mrr_sum / n, 4) if n else 0.0,
                "hyde_triggers": hyde_triggers,
            }
        )

    return {
        "evaluated_queries": len(eval_rows),
        "ablation": ablation_results,
        "embedder_backend": embedder.backend_name,
        "reranker_backend": reranker.backend_name,
        "query_details": full_query_details,
    }
