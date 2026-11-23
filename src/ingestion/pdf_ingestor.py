"""PDF ingestion pipeline: chunking, table extraction, prompt-injection guard, entity linking, and embedding."""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.config import AppConfig
from src.data_gen.pdf_writer import extract_pdf_text_simple
from src.ingestion.entity_linker import link_chunk_entities
from src.ingestion.injection_guard import sanitize_chunk_text
from src.rag.embeddings import Embedder

_HEADING_RE = re.compile(r"^\d+\.\s+[A-Z].+")
_GRANT_START_RE = re.compile(
    r"^(?:Turing Undergraduate Research Fellowship|Alderwood AI Systems Innovation Stipend|"
    r"First-Year Computing Discovery Award|Provost Cross-Disciplinary Research Grant|"
    r"Summer 2026 Heritage Innovation Grant|The Maxwell Hardware Prototyping Grant|"
    r"The Alderwood Student Conference Travel Fund|Biological Sciences students applying)"
)


@dataclass(frozen=True)
class IngestedChunk:
    chunk_id: str
    doc_id: str
    version: str
    effective_date: str
    grant_id: str | None
    dept_code: str | None
    year_scope: str | None
    page_num: int
    chunk_type: str  # "prose" | "table"
    content: str
    structured_table_json: dict[str, Any] | None
    injection_flagged: bool
    entity_link_method: str
    embedding: list[float]


def _extract_pages_for_pdf(pdf_path: Path, is_table_heavy: bool) -> tuple[list[str], str]:
    """Use Docling (table-heavy) or PyMuPDF when installed, else built-in PDF stream extractor."""
    if is_table_heavy:
        try:
            from docling.document_converter import DocumentConverter  # type: ignore

            converter = DocumentConverter()
            res = converter.convert(str(pdf_path))
            md = res.document.export_to_markdown()
            return [md], "docling"
        except Exception:
            pass

    try:
        import fitz  # type: ignore

        doc = fitz.open(str(pdf_path))
        pages = [page.get_text("text") for page in doc]
        doc.close()
        return pages, "pymupdf"
    except ImportError:
        pass

    return extract_pdf_text_simple(pdf_path), "stdlib_pdf_stream"


def _parse_pipe_table(table_lines: list[str]) -> dict[str, Any] | None:
    cleaned = [ln.strip() for ln in table_lines if ln.strip() and "-+-" not in ln]
    if len(cleaned) < 2:
        return None
    headers = [h.strip() for h in cleaned[0].split("|")]
    rows: list[dict[str, str]] = []
    for ln in cleaned[1:]:
        cells = [c.strip() for c in ln.split("|")]
        if len(cells) != len(headers):
            continue
        rows.append({headers[i]: cells[i] for i in range(len(headers))})
    if not rows:
        return None
    return {"headers": headers, "rows": rows}


def _reconstruct_blocks(page_text: str) -> tuple[list[str], list[dict[str, Any]]]:
    """Split page text into coherent prose blocks and structured pipe tables."""
    lines = [ln.rstrip() for ln in page_text.splitlines()]
    prose_blocks: list[str] = []
    tables: list[dict[str, Any]] = []

    current_heading = ""
    current_buf: list[str] = []
    table_buf: list[str] = []

    def flush_prose() -> None:
        nonlocal current_buf
        if current_buf:
            joined = " ".join(part.strip() for part in current_buf if part.strip())
            if joined:
                prefix = f"{current_heading} — " if current_heading and not joined.startswith(current_heading) else ""
                prose_blocks.append(f"{prefix}{joined}")
            current_buf = []

    def flush_table() -> None:
        nonlocal table_buf
        if table_buf:
            parsed = _parse_pipe_table(table_buf)
            if parsed:
                tables.append(parsed)
            table_buf = []

    for ln in lines:
        stripped = ln.strip()
        if not stripped:
            flush_table()
            flush_prose()
            continue

        # Skip redundant header metadata banner line
        if stripped.startswith("Document ID: "):
            continue

        if "|" in stripped or "-+-" in stripped:
            flush_prose()
            table_buf.append(stripped)
            continue

        flush_table()

        if _HEADING_RE.match(stripped):
            flush_prose()
            current_heading = stripped
            continue

        if _GRANT_START_RE.match(stripped) and current_buf:
            flush_prose()

        current_buf.append(stripped)

    flush_table()
    flush_prose()
    return prose_blocks, tables


def _split_tokens_with_overlap(text: str, max_words: int = 160, overlap_words: int = 25) -> list[str]:
    words = text.split()
    if len(words) <= max_words:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = min(len(words), start + max_words)
        chunks.append(" ".join(words[start:end]))
        if end >= len(words):
            break
        start = max(0, end - overlap_words)
    return chunks


def _ensure_sqlite_vector_columns(conn: sqlite3.Connection) -> None:
    for table in ("document_chunks", "schema_index"):
        cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if "embedding_json" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN embedding_json TEXT")
        if table == "document_chunks" and "entity_link_method" not in cols:
            conn.execute("ALTER TABLE document_chunks ADD COLUMN entity_link_method TEXT DEFAULT 'none'")


def ingest_pdfs(
    root_dir: Path | None = None,
    *,
    cfg: AppConfig | None = None,
    embedder: Embedder | None = None,
    use_llm_fallback: bool = True,
) -> dict[str, Any]:
    """Ingest all handbook PDFs into document_chunks and return Phase 2 ingestion metrics."""
    root = root_dir or Path(".")
    active_cfg = cfg or AppConfig.load(root / "config.yaml")
    active_embedder = embedder or Embedder(
        model_name=str(active_cfg.raw.get("models", {}).get("embedding_model", "BAAI/bge-m3"))
    )

    pdf_dir = root / active_cfg.pdf_dir
    manifest = json.loads((pdf_dir / "manifest.json").read_text(encoding="utf-8"))
    table_heavy_set = set(active_cfg.raw.get("ingestion", {}).get("table_heavy_docs", []))

    raw_chunks: list[dict[str, Any]] = []
    extractors_used: dict[str, str] = {}

    for doc_meta in manifest:
        filename = doc_meta["filename"]
        pdf_path = pdf_dir / filename
        pages, extractor_name = _extract_pages_for_pdf(pdf_path, filename in table_heavy_set)
        extractors_used[filename] = extractor_name

        doc_slug = re.sub(r"[^a-zA-Z0-9]+", "_", filename.replace(".pdf", "")).strip("_")
        chunk_seq = 0

        for page_idx, page_text in enumerate(pages, start=1):
            prose_blocks, tables = _reconstruct_blocks(page_text)

            for block in prose_blocks:
                for sub_text in _split_tokens_with_overlap(block):
                    chunk_seq += 1
                    guard = sanitize_chunk_text(sub_text)
                    entity = link_chunk_entities(
                        guard.sanitized_text,
                        doc_grant_ids=doc_meta.get("grant_ids", []),
                        use_llm_fallback=use_llm_fallback,
                    )
                    raw_chunks.append(
                        {
                            "chunk_id": f"{doc_slug}_p{page_idx}_c{chunk_seq:02d}",
                            "doc_id": doc_meta["doc_id"],
                            "version": doc_meta["version"],
                            "effective_date": doc_meta["effective_date"],
                            "grant_id": entity.primary_grant_id,
                            "dept_code": entity.dept_code,
                            "year_scope": entity.year_scope,
                            "page_num": page_idx,
                            "chunk_type": "prose",
                            "content": guard.sanitized_text,
                            "structured_table_json": None,
                            "injection_flagged": guard.flagged,
                            "entity_link_method": entity.method,
                            "doc_has_grants": bool(doc_meta.get("grant_ids")),
                        }
                    )

            for tbl_idx, tbl in enumerate(tables, start=1):
                chunk_seq += 1
                row_summaries = [
                    ", ".join(f"{k}: {v}" for k, v in row.items())
                    for row in tbl["rows"]
                ]
                summary_text = (
                    f"Structured Table ({doc_meta['title']}, {doc_meta['version']}, "
                    f"effective {doc_meta['effective_date']}): Columns {', '.join(tbl['headers'])}. "
                    + " | ".join(row_summaries)
                )
                guard = sanitize_chunk_text(summary_text)
                entity = link_chunk_entities(
                    guard.sanitized_text,
                    doc_grant_ids=doc_meta.get("grant_ids", []),
                    use_llm_fallback=use_llm_fallback,
                )
                raw_chunks.append(
                    {
                        "chunk_id": f"{doc_slug}_p{page_idx}_tbl{tbl_idx:02d}",
                        "doc_id": doc_meta["doc_id"],
                        "version": doc_meta["version"],
                        "effective_date": doc_meta["effective_date"],
                        "grant_id": entity.primary_grant_id,
                        "dept_code": entity.dept_code or "ALL",
                        "year_scope": entity.year_scope,
                        "page_num": page_idx,
                        "chunk_type": "table",
                        "content": guard.sanitized_text,
                        "structured_table_json": tbl,
                        "injection_flagged": guard.flagged,
                        "entity_link_method": entity.method,
                        "doc_has_grants": bool(doc_meta.get("grant_ids")),
                    }
                )

    embeddings = active_embedder.embed_batch([c["content"] for c in raw_chunks])
    for c, emb in zip(raw_chunks, embeddings):
        c["embedding"] = emb

    # Persist into SQLite mirror
    db_path = root / active_cfg.sqlite_mirror_path
    conn = sqlite3.connect(str(db_path))
    _ensure_sqlite_vector_columns(conn)
    conn.execute("DELETE FROM document_chunks")
    for c in raw_chunks:
        conn.execute(
            """
            INSERT INTO document_chunks (
                chunk_id, doc_id, version, effective_date, grant_id, dept_code,
                year_scope, page_num, chunk_type, content, structured_table_json,
                injection_flagged, embedding_json, entity_link_method
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                c["chunk_id"],
                c["doc_id"],
                c["version"],
                c["effective_date"],
                c["grant_id"],
                c["dept_code"],
                c["year_scope"],
                c["page_num"],
                c["chunk_type"],
                c["content"],
                json.dumps(c["structured_table_json"]) if c["structured_table_json"] else None,
                1 if c["injection_flagged"] else 0,
                json.dumps(c["embedding"]),
                c["entity_link_method"],
            ),
        )
    conn.commit()
    conn.close()

    # Entity linking match rate: among chunks mentioning specific grant IDs or grant program names
    grant_mention_re = re.compile(
        r"(?:\bGR-[A-Z]+-\d{2}\b|turing\s+(?:undergraduate\s+research\s+)?fellowship|"
        r"ai\s+systems\s+innovation|computing\s+discovery|"
        r"maxwell\s+hardware|watt\s+sustainable|heritage\s+innovation|"
        r"provost\s+cross-disciplinary|conference\s+travel\s+fund|franklin\s+genomics)",
        re.IGNORECASE,
    )
    grant_bearing = [c for c in raw_chunks if grant_mention_re.search(c["content"])]
    linked_grant_bearing = [c for c in grant_bearing if c["grant_id"] is not None]
    match_rate = (
        round(len(linked_grant_bearing) / len(grant_bearing), 4)
        if grant_bearing
        else 1.0
    )

    return {
        "total_chunks": len(raw_chunks),
        "prose_chunks": sum(1 for c in raw_chunks if c["chunk_type"] == "prose"),
        "table_chunks": sum(1 for c in raw_chunks if c["chunk_type"] == "table"),
        "flagged_injection_chunks": sum(1 for c in raw_chunks if c["injection_flagged"]),
        "grant_bearing_chunks": len(grant_bearing),
        "linked_grant_chunks": len(linked_grant_bearing),
        "entity_link_match_rate": match_rate,
        "linked_grant_ids": sorted({c["grant_id"] for c in raw_chunks if c["grant_id"]}),
        "embedder_backend": active_embedder.backend_name,
        "extractors_used": extractors_used,
    }
