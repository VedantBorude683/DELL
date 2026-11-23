"""Phase 7 MCP Server (FastMCP) exposing safe read-only SQL & schema tools.

Uses `fastmcp.FastMCP` when installed, and ships a compatible JSON-RPC 2.0 MCP
stdio implementation (`_CompatFastMCP`) so standard MCP Inspector / stdio clients
can discover and invoke tools in minimal Python 3.11 environments too.

Run standalone stdio server:
    python3 -m mcp_server.server
Inspect with official MCP Inspector:
    npx @modelcontextprotocol/inspector python3 -m mcp_server.server
"""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dataclasses import asdict
from src.config import AppConfig
from src.ingestion.schema_indexer import retrieve_tables
from src.sql_branch.executor import execute_readonly_sql
from src.sql_branch.models import SQLValidationError
from src.sql_branch.validator import validate_select_sql


def safe_sql_query_impl(sql: str, *, root_dir: Path | None = None) -> dict[str, Any]:
    """Validate ONE read-only SELECT via sqlglot/allow-list and execute with timeouts + row cap."""
    root = root_dir or ROOT
    cfg = AppConfig.load(root / "config.yaml")
    statement = (sql or "").strip()
    if not statement:
        return {
            "ok": False,
            "blocked": True,
            "stage": "validation",
            "error": "SQL statement must not be empty.",
            "columns": [],
            "rows": [],
            "row_count": 0,
            "tables": [],
        }

    max_rows = int(cfg.raw.get("database", {}).get("max_rows", 100))
    try:
        validated = validate_select_sql(
            statement,
            cfg.allowlisted_tables,
            max_rows=max_rows,
        )
    except SQLValidationError as exc:
        return {
            "ok": False,
            "blocked": True,
            "stage": "sqlglot_guard",
            "error": str(exc),
            "columns": [],
            "rows": [],
            "row_count": 0,
            "tables": [],
        }

    try:
        result = execute_readonly_sql(
            validated.sql,
            cfg=cfg,
            root_dir=root,
            provenance_extra={"mcp_tool": "safe_sql_query"},
        )
        return {
            "ok": True,
            "blocked": False,
            "stage": "executed",
            "sql": result.sql,
            "tables": list(result.tables),
            "columns": list(result.columns),
            "rows": result.rows,
            "row_count": len(result.rows),
            "provenance": result.provenance,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "blocked": True,
            "stage": "readonly_executor",
            "error": str(exc),
            "sql": validated.sql,
            "columns": [],
            "rows": [],
            "row_count": 0,
            "tables": list(validated.tables),
        }


def list_allowlisted_tables_impl(*, root_dir: Path | None = None) -> dict[str, Any]:
    """List the 18 allow-listed operational tables permitted by safe_sql_query."""
    root = root_dir or ROOT
    cfg = AppConfig.load(root / "config.yaml")
    return {
        "allowlisted_tables": list(cfg.allowlisted_tables),
        "count": len(cfg.allowlisted_tables),
        "max_rows": int(cfg.raw.get("database", {}).get("max_rows", 100)),
        "statement_timeout_ms": int(cfg.raw.get("database", {}).get("statement_timeout_ms", 5000)),
        "lock_timeout_ms": int(cfg.raw.get("database", {}).get("lock_timeout_ms", 2000)),
    }


def search_schema_index_impl(
    query: str,
    top_k: int = 3,
    *,
    root_dir: Path | None = None,
) -> dict[str, Any]:
    """Search Phase 2 semantic schema index for relevant operational tables and metric views."""
    root = root_dir or ROOT
    k = max(1, min(int(top_k or 3), 10))
    hits = [asdict(h) for h in retrieve_tables(query, top_k=k, root_dir=root)]
    return {
        "query": query,
        "top_k": k,
        "hits": hits,
    }


# ---------------------------------------------------------------------------
# FastMCP / Spec-Compliant MCP JSON-RPC 2.0 Stdio Server Wrapper
# ---------------------------------------------------------------------------


def _python_type_to_json_schema(ann: Any) -> str:
    if ann is int:
        return "integer"
    if ann is float:
        return "number"
    if ann is bool:
        return "boolean"
    return "string"


def _build_tool_input_schema(fn: Callable[..., Any]) -> dict[str, Any]:
    sig = inspect.signature(fn)
    props: dict[str, Any] = {}
    required: list[str] = []
    for name, param in sig.parameters.items():
        props[name] = {"type": _python_type_to_json_schema(param.annotation)}
        if param.default is inspect.Parameter.empty:
            required.append(name)
    return {
        "type": "object",
        "properties": props,
        "required": required,
    }


class _CompatFastMCP:
    """Minimal spec-compliant MCP stdio JSON-RPC 2.0 server matching FastMCP API."""

    def __init__(self, name: str, instructions: str = "") -> None:
        self.name = name
        self.instructions = instructions
        self._tools: dict[str, dict[str, Any]] = {}

    def tool(self, name: str | None = None, description: str | None = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def _decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            tname = name or fn.__name__
            self._tools[tname] = {
                "name": tname,
                "description": (description or (fn.__doc__ or "")).strip(),
                "inputSchema": _build_tool_input_schema(fn),
                "fn": fn,
            }
            return fn

        return _decorator

    def handle_jsonrpc_message(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        method = msg.get("method")
        req_id = msg.get("id")
        params = msg.get("params") or {}

        # Notifications have no id and expect no JSON-RPC response
        if req_id is None and str(method or "").startswith("notifications/"):
            return None

        if method == "initialize":
            proto = str(params.get("protocolVersion") or "2024-11-05")
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": proto,
                    "capabilities": {
                        "tools": {"listChanged": False},
                    },
                    "serverInfo": {
                        "name": self.name,
                        "version": "1.0.0",
                    },
                    "instructions": self.instructions,
                },
            }

        if method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}

        if method == "tools/list":
            tools_payload = [
                {
                    "name": t["name"],
                    "description": t["description"],
                    "inputSchema": t["inputSchema"],
                }
                for t in self._tools.values()
            ]
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools_payload}}

        if method == "tools/call":
            tname = str(params.get("name") or "")
            args = params.get("arguments") or {}
            tool_entry = self._tools.get(tname)
            if not tool_entry:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32602, "message": f"Unknown tool: {tname}"},
                }
            try:
                out = tool_entry["fn"](**args)
                is_err = isinstance(out, dict) and bool(out.get("blocked") and not out.get("ok", True))
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(out, ensure_ascii=False, indent=2),
                            }
                        ],
                        "structuredContent": out if isinstance(out, dict) else {"value": out},
                        "isError": is_err,
                    },
                }
            except Exception as exc:  # noqa: BLE001
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": f"Tool error: {exc}"}],
                        "isError": True,
                    },
                }

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }

    def run(self, transport: str = "stdio") -> None:
        if transport != "stdio":
            raise ValueError("Compat MCP server supports stdio transport.")
        # Read line-delimited JSON-RPC 2.0 requests (MCP Python SDK / Inspector stdio style)
        while True:
            line = sys.stdin.readline()
            if not line:
                break
            stripped = line.strip()
            if not stripped:
                continue
            # Also support Content-Length LSP/MCP framing if sent by an inspector
            if stripped.lower().startswith("content-length:"):
                length = int(stripped.split(":", 1)[1].strip())
                while True:
                    hdr = sys.stdin.readline()
                    if not hdr or hdr.strip() == "":
                        break
                body = sys.stdin.read(length)
                msg = json.loads(body)
                resp = self.handle_jsonrpc_message(msg)
                if resp is not None:
                    encoded = json.dumps(resp, ensure_ascii=False).encode("utf-8")
                    sys.stdout.write(f"Content-Length: {len(encoded)}\r\n\r\n")
                    sys.stdout.write(encoded.decode("utf-8"))
                    sys.stdout.flush()
                continue

            try:
                msg = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            resp = self.handle_jsonrpc_message(msg)
            if resp is not None:
                sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
                sys.stdout.flush()


def create_mcp_server() -> tuple[Any, str]:
    """Instantiate FastMCP server (or spec-compliant compat FastMCP when wheel is absent)."""
    instructions = (
        "Alderwood University Hybrid RAG safe SQL server. All SQL queries pass through "
        "sqlglot single-SELECT allow-list validation, read-only database execution, "
        "statement/lock timeouts, and strict row caps."
    )
    try:
        from fastmcp import FastMCP  # type: ignore

        mcp_app: Any = FastMCP("alderwood-hybrid-rag", instructions=instructions)
        backend = "fastmcp"
    except ImportError:
        try:
            from mcp.server.fastmcp import FastMCP  # type: ignore

            mcp_app = FastMCP("alderwood-hybrid-rag", instructions=instructions)
            backend = "mcp.server.fastmcp"
        except ImportError:
            mcp_app = _CompatFastMCP("alderwood-hybrid-rag", instructions=instructions)
            backend = "compat_fastmcp_stdio"

    @mcp_app.tool(
        name="safe_sql_query",
        description=(
            "Execute ONE validated read-only SELECT query against Alderwood University's "
            "allow-listed operational tables (enforces sqlglot AST guard, statement_timeout, "
            "lock_timeout, and row cap)."
        ),
    )
    def safe_sql_query(sql: str) -> dict[str, Any]:
        return safe_sql_query_impl(sql)

    @mcp_app.tool(
        name="list_allowlisted_tables",
        description="List the 18 allow-listed operational tables and safety limits for safe_sql_query.",
    )
    def list_allowlisted_tables() -> dict[str, Any]:
        return list_allowlisted_tables_impl()

    @mcp_app.tool(
        name="search_schema_index",
        description="Search the semantic schema index for relevant operational tables and metric views.",
    )
    def search_schema_index(query: str, top_k: int = 3) -> dict[str, Any]:
        return search_schema_index_impl(query, top_k=top_k)

    return mcp_app, backend


mcp, MCP_BACKEND = create_mcp_server()


if __name__ == "__main__":
    mcp.run()
