"""Build all Phase 1 artifacts: Postgres seed.sql, SQLite mirror, 9 handbook PDFs, and 86-query gold.jsonl."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import AppConfig
from src.data_gen.generate_pdfs import generate_all_pdfs
from src.data_gen.gold_generator import write_gold_jsonl
from src.data_gen.seed_data import build_dataset, write_postgres_seed_sql, write_sqlite_mirror


def main() -> None:
    cfg = AppConfig.load(ROOT / "config.yaml")
    dataset = build_dataset()
    write_postgres_seed_sql(dataset, ROOT / "db" / "seed.sql")
    write_sqlite_mirror(dataset, ROOT / cfg.sqlite_mirror_path)
    pdf_manifest = generate_all_pdfs(ROOT / cfg.pdf_dir)
    gold_items = write_gold_jsonl(ROOT / cfg.gold_path)

    summary = {
        "tables_seeded": {k: len(v) for k, v in dataset.items()},
        "pdf_count": len(pdf_manifest),
        "gold_count": len(gold_items),
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
