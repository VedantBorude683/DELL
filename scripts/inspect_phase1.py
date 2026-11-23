"""Read-only JSON bridge for Express API to inspect real Phase 1 artifacts."""
from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import AppConfig
from src.data_gen.pdf_writer import extract_pdf_text_simple
from src.data_gen.seed_data import TABLE_CATALOG_METADATA


def get_overview() -> dict:
    cfg = AppConfig.load(ROOT / "config.yaml")
    schema_sql = (ROOT / "db" / "schema.sql").read_text(encoding="utf-8")
    schema_tables = re.findall(r"CREATE TABLE IF NOT EXISTS\s+([a-zA-Z0-9_]+)", schema_sql)
    conn = sqlite3.connect(str(ROOT / cfg.sqlite_mirror_path))
    cur = conn.cursor()

    meta_map = {m["table_name"]: m for m in TABLE_CATALOG_METADATA}
    tables_info = []
    for tbl in schema_tables:
        cols_raw = cur.execute(f"PRAGMA table_info({tbl})").fetchall()
        columns = [{"name": c[1], "type": c[2], "pk": bool(c[5])} for c in cols_raw]
        row_count = cur.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        meta = meta_map.get(tbl, {"category": "related", "purpose": ""})
        tables_info.append(
            {
                "table_name": tbl,
                "category": meta["category"],
                "purpose": meta["purpose"],
                "row_count": row_count,
                "columns": columns,
            }
        )
    conn.close()

    manifest = json.loads((ROOT / cfg.pdf_dir / "manifest.json").read_text(encoding="utf-8"))
    gold_rows = [
        json.loads(line)
        for line in (ROOT / cfg.gold_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    routes = dict(Counter(r["route"] for r in gold_rows))
    gold_stats = {
        "total": len(gold_rows),
        "routes": routes,
        "follow_ups": sum(1 for r in gold_rows if r["is_follow_up"]),
        "adversarial": sum(1 for r in gold_rows if r["is_adversarial"]),
        "paraphrased": sum(1 for r in gold_rows if r.get("paraphrase_group")),
    }
    return {
        "app_name": cfg.raw.get("app", {}).get("name", "Alderwood University Hybrid RAG"),
        "current_date": cfg.current_date,
        "feature_flags": cfg.raw.get("feature_flags", {}),
        "tables": tables_info,
        "pdfs": manifest,
        "gold_stats": gold_stats,
        "gold_queries": gold_rows,
    }


def get_table_rows(table_name: str, limit: int = 25) -> dict:
    cfg = AppConfig.load(ROOT / "config.yaml")
    schema_sql = (ROOT / "db" / "schema.sql").read_text(encoding="utf-8")
    schema_tables = set(re.findall(r"CREATE TABLE IF NOT EXISTS\s+([a-zA-Z0-9_]+)", schema_sql))
    if table_name not in schema_tables:
        return {"error": f"Unknown table: {table_name}"}

    conn = sqlite3.connect(str(ROOT / cfg.sqlite_mirror_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    rows = [dict(r) for r in cur.execute(f"SELECT * FROM {table_name} LIMIT ?", (limit,)).fetchall()]
    cols = [c[1] for c in cur.execute(f"PRAGMA table_info({table_name})").fetchall()]
    conn.close()
    return {"table_name": table_name, "columns": cols, "rows": rows}


def get_pdf_text(filename: str) -> dict:
    cfg = AppConfig.load(ROOT / "config.yaml")
    safe_name = Path(filename).name
    pdf_path = ROOT / cfg.pdf_dir / safe_name
    if not pdf_path.exists():
        return {"error": f"PDF not found: {safe_name}"}
    pages = extract_pdf_text_simple(pdf_path)
    return {"filename": safe_name, "pages": pages}


def run_phase1_tests() -> dict:
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "tests/test_phase1.py", "-v"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    return {"passed": proc.returncode == 0, "returncode": proc.returncode, "output": output.strip()}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "overview"
    if cmd == "overview":
        print(json.dumps(get_overview()))
    elif cmd == "table":
        tbl = sys.argv[2] if len(sys.argv) > 2 else "students"
        print(json.dumps(get_table_rows(tbl)))
    elif cmd == "pdf":
        fname = sys.argv[2] if len(sys.argv) > 2 else ""
        print(json.dumps(get_pdf_text(fname)))
    elif cmd == "test":
        print(json.dumps(run_phase1_tests()))
