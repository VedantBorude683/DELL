"""Read-only JSON bridge for Express API to inspect Phase 2 ingestion & schema index."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import AppConfig
from src.ingestion.schema_indexer import retrieve_tables


def get_phase2_overview() -> dict:
    cfg = AppConfig.load(ROOT / "config.yaml")
    report = json.loads((ROOT / "data" / "phase2_report.json").read_text(encoding="utf-8"))

    conn = sqlite3.connect(str(ROOT / cfg.sqlite_mirror_path))
    conn.row_factory = sqlite3.Row
    chunks = [
        {
            "chunk_id": r["chunk_id"],
            "doc_id": r["doc_id"],
            "version": r["version"],
            "effective_date": r["effective_date"],
            "grant_id": r["grant_id"],
            "dept_code": r["dept_code"],
            "year_scope": r["year_scope"],
            "page_num": r["page_num"],
            "chunk_type": r["chunk_type"],
            "content": r["content"],
            "structured_table_json": json.loads(r["structured_table_json"])
            if r["structured_table_json"]
            else None,
            "injection_flagged": bool(r["injection_flagged"]),
            "entity_link_method": r["entity_link_method"],
        }
        for r in conn.execute(
            "SELECT chunk_id, doc_id, version, effective_date, grant_id, dept_code, year_scope, page_num, chunk_type, content, structured_table_json, injection_flagged, entity_link_method FROM document_chunks ORDER BY doc_id, version, page_num, chunk_id"
        ).fetchall()
    ]
    schema_entries = [
        dict(r)
        for r in conn.execute(
            "SELECT entry_id, table_name, column_name, description, sample_values, metric_view_sql FROM schema_index ORDER BY entry_id"
        ).fetchall()
    ]
    conn.close()

    return {
        "report": report,
        "chunks": chunks,
        "schema_entries": schema_entries,
    }


def query_schema_tables(query: str, top_k: int = 3) -> dict:
    cfg = AppConfig.load(ROOT / "config.yaml")
    hits = retrieve_tables(query, top_k=top_k, root_dir=ROOT, cfg=cfg)
    return {
        "query": query,
        "hits": [
            {
                "table_name": h.table_name,
                "score": h.score,
                "matched_entry_id": h.matched_entry_id,
                "description": h.description,
                "sample_values": h.sample_values,
                "metric_view_sql": h.metric_view_sql,
            }
            for h in hits
        ],
    }


def run_all_tests() -> dict:
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=45,
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    return {"passed": proc.returncode == 0, "returncode": proc.returncode, "output": output.strip()}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "overview"
    if cmd == "overview":
        print(json.dumps(get_phase2_overview()))
    elif cmd == "retrieve":
        q = sys.argv[2] if len(sys.argv) > 2 else "Which CS research grants can I apply for?"
        print(json.dumps(query_schema_tables(q)))
    elif cmd == "test":
        print(json.dumps(run_all_tests()))
