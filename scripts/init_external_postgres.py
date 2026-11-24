from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")

    psycopg_url = database_url.replace("postgresql://", "postgresql+psycopg://")
    psycopg_url = psycopg_url.replace("postgresql+psycopg://", "postgresql+psycopg://", 1)
    os.environ["DATABASE_URL"] = psycopg_url

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    from src.config import AppConfig
    from src.ingestion.pdf_ingestor import ingest_pdfs
    from src.ingestion.schema_indexer import build_schema_index

    import sqlalchemy

    engine = sqlalchemy.create_engine(psycopg_url, pool_pre_ping=True)
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")

    schema_path = ROOT / "db" / "schema.sql"
    seed_path = ROOT / "db" / "seed.sql"
    for sql_path in (schema_path, seed_path):
        subprocess.run(
            [
                "psql",
                psycopg_url,
                "-v",
                "ON_ERROR_STOP=1",
                "-f",
                str(sql_path),
            ],
            check=True,
        )

    cfg = AppConfig.load(ROOT / "config.yaml")
    ingestion = ingest_pdfs(ROOT, cfg=cfg, use_llm_fallback=False)
    schema = build_schema_index(ROOT, cfg=cfg)
    print({
        "document_chunks": ingestion["total_chunks"],
        "schema_entries": schema["total_entries"],
        "status": "initialized",
    })


if __name__ == "__main__":
    main()
