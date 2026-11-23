"""Run Phase 2 ingestion and schema-index build, and output real metrics."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import AppConfig
from src.ingestion.pdf_ingestor import ingest_pdfs
from src.ingestion.schema_indexer import build_schema_index, evaluate_table_recall_at_k


def main() -> None:
    cfg = AppConfig.load(ROOT / "config.yaml")
    ingestion_stats = ingest_pdfs(ROOT, cfg=cfg, use_llm_fallback=True)
    schema_stats = build_schema_index(ROOT, cfg=cfg)
    recall_eval = evaluate_table_recall_at_k(ROOT, k=3, cfg=cfg)

    report = {
        "ingestion": ingestion_stats,
        "schema_index": schema_stats,
        "table_retrieval_eval": recall_eval,
    }
    out_path = ROOT / "data" / "phase2_report.json"
    out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
