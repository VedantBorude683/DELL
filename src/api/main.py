"""Phase 7 FastAPI Backend for Alderwood University Hybrid RAG.

Run with uvicorn (when FastAPI + Uvicorn are installed):
    uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload

Or run directly with built-in stdlib HTTP fallback if uvicorn isn't installed:
    python3 -m src.api.main
"""
from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from fastapi import UploadFile, File

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.run import run_gold_evaluation
from mcp_server.inspector_client import run_mcp_stdio_session
from src.assistant import run_assistant_query
from src.config import AppConfig
from src.orchestrator.identity import list_student_personas


def handle_health() -> dict[str, Any]:
    cfg = AppConfig.load(ROOT / "config.yaml")
    database_status = "unconfigured"
    try:
        ro_url = os.environ.get("READONLY_DATABASE_URL", "").strip()
        if ro_url:
            from sqlalchemy import create_engine, text
            engine = create_engine(ro_url, pool_pre_ping=True)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            database_status = "connected_readonly"
    except Exception as exc:
        database_status = f"error: {type(exc).__name__}"
    return {
        "status": "ok",
        "app_name": cfg.raw.get("app", {}).get("name", "Alderwood University Hybrid RAG"),
        "current_date": cfg.current_date,
        "database": database_status,
    }


def handle_personas() -> dict[str, Any]:
    return {"personas": list_student_personas(root_dir=ROOT)}


def handle_chat(payload: dict[str, Any]) -> dict[str, Any]:
    query = str(payload.get("query") or "").strip()
    if not query:
        raise ValueError("query is required")
    persona = str(payload.get("persona_student_id") or "STU-1001").strip() or "STU-1001"
    memory = payload.get("memory") or None
    ff_override = payload.get("feature_flags") or None
    return run_assistant_query(
        query,
        persona_student_id=persona,
        memory=memory,
        feature_flags_override=ff_override,
        root_dir=ROOT,
    )


def handle_latest_eval() -> dict[str, Any]:
    cfg = AppConfig.load(ROOT / "config.yaml")
    out_path = ROOT / cfg.raw.get("eval", {}).get("report_output_path", "eval/latest_report.json")
    if out_path.exists():
        return json.loads(out_path.read_text(encoding="utf-8"))
    return run_gold_evaluation(root_dir=ROOT, cfg=cfg)


def handle_mcp_inspect(payload: dict[str, Any]) -> dict[str, Any]:
    tool_calls = payload.get("tool_calls")
    if not isinstance(tool_calls, list):
        tool_calls = [{"name": "list_allowlisted_tables", "arguments": {}}]
    return run_mcp_stdio_session(tool_calls=tool_calls, root_dir=ROOT)


def create_fastapi_app() -> Any:
    """Build real FastAPI application when `fastapi` is installed, else return handler registry."""
    try:
        from fastapi import FastAPI, HTTPException  # type: ignore
        from pydantic import BaseModel  # type: ignore

        api = FastAPI(title="Alderwood University Hybrid RAG API", version="1.0.0")

        class ChatRequest(BaseModel):
            query: str
            persona_student_id: str = "STU-1001"
            memory: dict[str, Any] | None = None
            feature_flags: dict[str, Any] | None = None

        class MCPInspectRequest(BaseModel):
            tool_calls: list[dict[str, Any]] = []

        @api.get("/health")
        def get_health() -> dict[str, Any]:
            return handle_health()

        @api.get("/personas")
        def get_personas() -> dict[str, Any]:
            return handle_personas()

        @api.post("/chat")
        def post_chat(payload: dict[str, Any]) -> dict[str, Any]:
            try:
                return handle_chat(payload)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        @api.get("/eval/latest")
        def get_eval_latest() -> dict[str, Any]:
            return handle_latest_eval()

        @api.post("/mcp/inspect")
        def post_mcp_inspect(req: MCPInspectRequest) -> dict[str, Any]:
            return handle_mcp_inspect(req.model_dump())

        @api.post("/sources/pdf")
        async def upload_pdf(file: UploadFile = File(...)) -> dict[str, Any]:
            if not file.filename or not file.filename.lower().endswith(".pdf"):
                raise HTTPException(status_code=400, detail="Only PDF files are accepted")
            cfg = AppConfig.load(ROOT / "config.yaml")
            pdf_dir = ROOT / cfg.pdf_dir
            pdf_dir.mkdir(parents=True, exist_ok=True)
            target = pdf_dir / Path(file.filename).name
            target.write_bytes(await file.read())

            manifest_path = pdf_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else []
            if not any(str(item.get("filename")) == target.name for item in manifest):
                from datetime import date
                doc_id = "HANDBOOK-UPLOADED-" + target.stem.upper().replace("-", "_").replace(" ", "_")
                manifest.append({
                    "filename": target.name,
                    "title": target.stem,
                    "doc_id": doc_id,
                    "version": "uploaded",
                    "effective_date": date.today().isoformat(),
                    "page_count": 0,
                    "size_bytes": target.stat().st_size,
                    "grant_ids": [],
                    "planted_cases": ["user_uploaded_pdf"],
                })
                manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

            if not os.environ.get("DATABASE_URL", "").strip():
                raise HTTPException(status_code=503, detail="DATABASE_URL is not configured")
            from src.ingestion.pdf_ingestor import ingest_pdfs
            stats = ingest_pdfs(ROOT, cfg=cfg, use_llm_fallback=False)
            return {
                "filename": target.name,
                "doc_id": next((item["doc_id"] for item in manifest if item["filename"] == target.name), ""),
                "ingestion": stats,
            }

        return api
    except ImportError:
        return {
            "backend": "stdlib_compat",
            "routes": {
                "GET /health": handle_health,
                "GET /personas": handle_personas,
                "POST /chat": handle_chat,
                "GET /eval/latest": handle_latest_eval,
                "POST /mcp/inspect": handle_mcp_inspect,
            },
        }


app = create_fastapi_app()


def serve_stdlib_http(host: str = "0.0.0.0", port: int = 8000) -> None:
    """Fallback stdlib HTTP server when uvicorn/fastapi wheels are not installed."""

    class _Handler(BaseHTTPRequestHandler):
        def _send_json(self, status: int, body: dict[str, Any]) -> None:
            raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health":
                self._send_json(200, handle_health())
            elif self.path == "/personas":
                self._send_json(200, handle_personas())
            elif self.path == "/eval/latest":
                self._send_json(200, handle_latest_eval())
            else:
                self._send_json(404, {"error": "Not found"})

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            payload = json.loads(raw or "{}")
            try:
                if self.path == "/chat":
                    self._send_json(200, handle_chat(payload))
                elif self.path == "/mcp/inspect":
                    self._send_json(200, handle_mcp_inspect(payload))
                else:
                    self._send_json(404, {"error": "Not found"})
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})

    server = HTTPServer((host, port), _Handler)
    print(f"Stdlib fallback API listening on http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    try:
        import uvicorn  # type: ignore

        uvicorn.run(app, host="0.0.0.0", port=8000)
    except ImportError:
        serve_stdlib_http()
