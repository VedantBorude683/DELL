"""Real MCP stdio JSON-RPC 2.0 Inspector client for verifying mcp_server.server."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def run_mcp_stdio_session(
    tool_calls: list[dict[str, Any]] | None = None,
    *,
    root_dir: Path | None = None,
) -> dict[str, Any]:
    """Spawn `python3 -m mcp_server.server`, execute MCP initialize + tools/list + tools/call."""
    root = root_dir or Path(__file__).resolve().parent.parent
    calls = tool_calls or []

    requests_to_send: list[dict[str, Any]] = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "alderwood-mcp-inspector", "version": "1.0.0"},
            },
        },
        {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        },
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        },
    ]

    for idx, call in enumerate(calls, start=3):
        requests_to_send.append(
            {
                "jsonrpc": "2.0",
                "id": idx,
                "method": "tools/call",
                "params": {
                    "name": call["name"],
                    "arguments": call.get("arguments") or {},
                },
            }
        )

    stdin_payload = "\n".join(json.dumps(r) for r in requests_to_send) + "\n"
    proc = subprocess.run(
        [sys.executable, "-m", "mcp_server.server"],
        input=stdin_payload,
        capture_output=True,
        text=True,
        cwd=str(root),
        timeout=20,
        check=False,
    )

    responses: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            responses.append(json.loads(s))
        except json.JSONDecodeError:
            continue

    by_id = {r.get("id"): r for r in responses if "id" in r}
    init_resp = by_id.get(1, {})
    list_resp = by_id.get(2, {})
    tools = (list_resp.get("result") or {}).get("tools") or []

    call_results: list[dict[str, Any]] = []
    for idx, call in enumerate(calls, start=3):
        raw_resp = by_id.get(idx, {})
        res = raw_resp.get("result") or {}
        text_blocks = [c.get("text", "") for c in (res.get("content") or []) if c.get("type") == "text"]
        parsed_output: Any = res.get("structuredContent")
        if parsed_output is None and text_blocks:
            try:
                parsed_output = json.loads(text_blocks[0])
            except json.JSONDecodeError:
                parsed_output = text_blocks[0]
        call_results.append(
            {
                "tool": call["name"],
                "arguments": call.get("arguments") or {},
                "isError": bool(res.get("isError", False)),
                "output": parsed_output,
                "raw_response": raw_resp,
            }
        )

    return {
        "returncode": proc.returncode,
        "stderr": proc.stderr.strip(),
        "server_info": (init_resp.get("result") or {}).get("serverInfo"),
        "protocol_version": (init_resp.get("result") or {}).get("protocolVersion"),
        "instructions": (init_resp.get("result") or {}).get("instructions"),
        "tools": tools,
        "call_results": call_results,
        "transcript": {
            "requests": requests_to_send,
            "responses": responses,
        },
    }
