"""Read-only JSON bridge for Express API to inspect and query Phase 4 Document Branch."""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import AppConfig
from src.doc_branch.evaluator import evaluate_doc_recall_ablation
from src.doc_branch.models import MetadataFilter
from src.doc_branch.retriever import search_documents


def get_phase4_overview() -> dict:
    cfg = AppConfig.load(ROOT / "config.yaml")
    report_path = ROOT / "data" / "phase4_report.json"
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
    else:
        report = evaluate_doc_recall_ablation(ROOT, cfg=cfg, k_values=(3, 5))

    return {
        "report": report,
        "defaults": {
            "vector_top_k": int(cfg.raw.get("retrieval", {}).get("vector_top_k", 12)),
            "fts_top_k": int(cfg.raw.get("retrieval", {}).get("fts_top_k", 12)),
            "rrf_k": int(cfg.raw.get("retrieval", {}).get("rrf_k", 60)),
            "rerank_top_k": int(cfg.raw.get("retrieval", {}).get("rerank_top_k", 5)),
            "rerank_score_threshold": float(cfg.raw.get("retrieval", {}).get("rerank_score_threshold", 0.42)),
            "use_hyde": cfg.flags.use_hyde,
            "use_reranker": cfg.flags.use_reranker,
            "use_crag_grader": cfg.flags.use_crag_grader,
        },
    }


def query_documents(payload: dict) -> dict:
    cfg = AppConfig.load(ROOT / "config.yaml")
    query = str(payload.get("query", "")).strip()
    use_hyde = bool(payload.get("use_hyde", cfg.flags.use_hyde))
    use_reranker = bool(payload.get("use_reranker", cfg.flags.use_reranker))
    use_crag = bool(payload.get("use_crag_grader", cfg.flags.use_crag_grader))

    grant_id = str(payload.get("grant_id") or "").strip()
    version = str(payload.get("version") or "").strip()
    dept_code = str(payload.get("dept_code") or "").strip()

    flt = MetadataFilter(
        grant_ids=(grant_id,) if grant_id else (),
        version=version or None,
        dept_code=dept_code or None,
    )
    run_cfg = replace(
        cfg,
        flags=replace(
            cfg.flags,
            use_hyde=use_hyde,
            use_reranker=use_reranker,
            use_crag_grader=use_crag,
        ),
    )
    res = search_documents(query, filters=flt, cfg=run_cfg, root_dir=ROOT)
    return res.to_dict()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "overview"
    if cmd == "overview":
        print(json.dumps(get_phase4_overview()))
    elif cmd == "search":
        raw = sys.argv[2] if len(sys.argv) > 2 else "{}"
        print(json.dumps(query_documents(json.loads(raw))))
