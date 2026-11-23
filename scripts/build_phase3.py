"""Build and evaluate Phase 3 SQL Branch benchmark report."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import AppConfig
from src.sql_branch.gold_reference_queries import evaluate_sql_branch_gold


def main() -> None:
    cfg = AppConfig.load(ROOT / "config.yaml")
    report = evaluate_sql_branch_gold(ROOT, cfg=cfg)
    out_path = ROOT / "data" / "phase3_report.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    summary = {k: v for k, v in report.items() if k not in ("results", "safety_results")}
    print(json.dumps({"report_path": str(out_path.relative_to(ROOT)), **summary}, indent=2))


if __name__ == "__main__":
    main()
