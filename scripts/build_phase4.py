"""Build and evaluate Phase 4 Document Branch Recall@k ablation report."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import AppConfig
from src.doc_branch.evaluator import evaluate_doc_recall_ablation


def main() -> None:
    cfg = AppConfig.load(ROOT / "config.yaml")
    report = evaluate_doc_recall_ablation(ROOT, cfg=cfg, k_values=(3, 5))
    out_path = ROOT / "data" / "phase4_report.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    summary = {k: v for k, v in report.items() if k != "query_details"}
    print(json.dumps({"report_path": str(out_path.relative_to(ROOT)), **summary}, indent=2))


if __name__ == "__main__":
    main()
