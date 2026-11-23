"""Pure-Python valid PDF 1.4 writer with optional PyMuPDF acceleration.

Produces real, multi-page binary PDF files with embedded Helvetica / Helvetica-Bold
resources, page trees, and clean text extraction (readable by PyMuPDF, pypdf, pdfplumber,
and standard PDF viewers) without requiring third-party packages at build time.
"""
from __future__ import annotations

import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


def _pdf_escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
        .encode("latin-1", "replace")
        .decode("latin-1")
    )


@dataclass(frozen=True)
class PdfSection:
    heading: str
    paragraphs: tuple[str, ...]
    table: tuple[tuple[str, ...], ...] | None = None


def _render_page_stream(lines: Sequence[tuple[str, int, int, str]]) -> bytes:
    """Render list of (font_key, font_size, y_pos, text) into PDF content stream."""
    ops: list[str] = ["BT"]
    for font_key, size, y_pos, line in lines:
        ops.append(f"/{font_key} {size} Tf")
        ops.append(f"1 0 0 1 54 {y_pos} Tm")
        ops.append(f"({_pdf_escape(line)}) Tj")
    ops.append("ET")
    return "\n".join(ops).encode("latin-1", "replace")


def write_handbook_pdf(
    output_path: Path,
    *,
    title: str,
    doc_id: str,
    version: str,
    effective_date: str,
    sections: Sequence[PdfSection],
) -> int:
    """Write a multi-page valid PDF 1.4 handbook and return page count."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Prefer PyMuPDF if installed, otherwise use our built-in deterministic PDF 1.4 writer.
    try:
        import fitz  # type: ignore

        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        y = 56
        page.insert_text((54, y), title, fontsize=16, fontname="helv")
        y += 20
        page.insert_text(
            (54, y),
            f"Document ID: {doc_id} | Version: {version} | Effective Date: {effective_date}",
            fontsize=9,
            fontname="helv",
        )
        y += 24
        for sec in sections:
            if y > 710:
                page = doc.new_page(width=612, height=792)
                y = 56
            page.insert_text((54, y), sec.heading, fontsize=12, fontname="helv")
            y += 18
            for para in sec.paragraphs:
                for wrapped in textwrap.wrap(para, width=86):
                    if y > 735:
                        page = doc.new_page(width=612, height=792)
                        y = 56
                    page.insert_text((54, y), wrapped, fontsize=10, fontname="helv")
                    y += 14
                y += 6
            if sec.table:
                for r_idx, row in enumerate(sec.table):
                    if y > 735:
                        page = doc.new_page(width=612, height=792)
                        y = 56
                    line = " | ".join(str(cell) for cell in row)
                    page.insert_text((54, y), line, fontsize=9 if r_idx > 0 else 9, fontname="cour")
                    y += 14
                y += 8
        page_count = len(doc)
        doc.save(str(output_path))
        doc.close()
        return page_count
    except ImportError:
        pass

    # Pure Python PDF 1.4 writer
    pages_ops: list[list[tuple[str, int, int, str]]] = [[]]
    y = 738

    def add_line(font_key: str, size: int, line: str, step: int) -> None:
        nonlocal y
        if y < 60:
            pages_ops.append([])
            y = 738
        pages_ops[-1].append((font_key, size, y, line))
        y -= step

    add_line("F2", 16, title, 22)
    add_line("F1", 9, f"Document ID: {doc_id} | Version: {version} | Effective Date: {effective_date}", 22)

    for sec in sections:
        if y < 120:
            pages_ops.append([])
            y = 738
        add_line("F2", 12, sec.heading, 18)
        for para in sec.paragraphs:
            for wrapped in textwrap.wrap(para, width=86):
                add_line("F1", 10, wrapped, 14)
            y -= 6
        if sec.table:
            col_widths = [max(len(str(row[i])) for row in sec.table) for i in range(len(sec.table[0]))]
            for r_idx, row in enumerate(sec.table):
                formatted = " | ".join(str(cell).ljust(col_widths[i]) for i, cell in enumerate(row))
                add_line("F3" if r_idx > 0 else "F2", 8, formatted, 13)
                if r_idx == 0:
                    sep = "-+-".join("-" * w for w in col_widths)
                    add_line("F3", 8, sep, 13)
            y -= 8

    # Assemble PDF objects:
    # 1: Catalog, 2: Pages, 3: F1 Helvetica, 4: F2 Helvetica-Bold, 5: F3 Courier
    # For each page p_i: page_obj = 6 + 2*i, content_obj = 7 + 2*i
    objects: list[bytes] = []
    num_pages = len(pages_ops)
    page_obj_ids = [6 + 2 * i for i in range(num_pages)]

    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids_str = " ".join(f"{pid} 0 R" for pid in page_obj_ids)
    objects.append(f"<< /Type /Pages /Kids [{kids_str}] /Count {num_pages} >>".encode("ascii"))
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>")

    for i, lines in enumerate(pages_ops):
        page_id = 6 + 2 * i
        content_id = page_id + 1
        stream_bytes = _render_page_stream(lines)
        page_dict = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R /F3 5 0 R >> >> "
            f"/Contents {content_id} 0 R >>"
        ).encode("ascii")
        content_obj = (
            f"<< /Length {len(stream_bytes)} >>\nstream\n".encode("ascii")
            + stream_bytes
            + b"\nendstream"
        )
        objects.append(page_dict)
        objects.append(content_obj)

    chunks: list[bytes] = [b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"]
    offsets: list[int] = [0]
    for obj_num, body in enumerate(objects, start=1):
        offsets.append(sum(len(c) for c in chunks))
        chunks.append(f"{obj_num} 0 obj\n".encode("ascii") + body + b"\nendobj\n")

    xref_offset = sum(len(c) for c in chunks)
    xref_lines = [f"xref\n0 {len(objects) + 1}\n", "0000000000 65535 f \n"]
    for off in offsets[1:]:
        xref_lines.append(f"{off:010d} 00000 n \n")
    trailer = (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    )
    chunks.append("".join(xref_lines).encode("ascii") + trailer.encode("ascii"))
    output_path.write_bytes(b"".join(chunks))
    return num_pages


def extract_pdf_text_simple(pdf_path: Path) -> list[str]:
    """Extract per-page text using PyMuPDF if available, else parse PDF Tj streams."""
    try:
        import fitz  # type: ignore

        doc = fitz.open(str(pdf_path))
        pages = [page.get_text("text") for page in doc]
        doc.close()
        return pages
    except ImportError:
        pass

    import re

    raw = pdf_path.read_bytes().decode("latin-1", "replace")
    streams = re.findall(r"stream\n(.*?)\nendstream", raw, flags=re.DOTALL)
    pages: list[str] = []
    for st in streams:
        parts = re.findall(r"\((.*?)\)\s*Tj", st, flags=re.DOTALL)
        cleaned = [
            p.replace("\\(", "(").replace("\\)", ")").replace("\\\\", "\\")
            for p in parts
        ]
        pages.append("\n".join(cleaned))
    return pages
