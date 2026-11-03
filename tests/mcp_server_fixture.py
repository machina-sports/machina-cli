"""Real in-process MCP servers (official SDK + uvicorn) for protocol tests.

Each scenario mirrors a deployment shape the CLI must handle:
- "modern":  streamable HTTP at /mcp
- "legacy":  SSE at /mcp/sse (+ /mcp/messages/), nothing at /mcp (404) — today's
             released client-api MCP server behind the tenant ingress
- auth gate: an ASGI wrapper answering 401/403 for every request, to prove the
             client never falls back to SSE after an auth denial
"""

from __future__ import annotations

import contextlib
import socket
import threading
import time
from typing import Any

import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

GOOD_TOKEN = "sk-test-supersecret-0123456789"


def build_server(
    health: str = "ok",
    tools: int = 0,
    page_size: int | None = None,
    calls: list | None = None,
) -> FastMCP:
    server = FastMCP(
        "machina-test",
        streamable_http_path="/mcp",
        sse_path="/mcp/sse",
        message_path="/mcp/messages/",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @server.tool(structured_output=True)
    async def health_check() -> dict[str, Any]:
        """Return stable status, message and data health fields."""
        if calls is not None:
            calls.append("health_check")
        if health == "denied":
            raise ValueError("Upstream API rejected authentication (HTTP 403)")
        if health == "expired":
            raise ValueError("Upstream API rejected authentication (HTTP 401)")
        if health == "error":
            return {"status": "error", "error_code": "upstream_error", "message": "down"}
        return {"status": "success", "operation": "health", "message": "ok", "data": {}}

    for i in range(tools):

        def make(i=i):
            async def extra(query: str, limit: int = 10) -> dict:
                return {"i": i}

            extra.__name__ = f"extra_tool_{i:03d}"
            extra.__doc__ = f"Extra tool {i}"
            return extra

        server.tool()(make())

    if page_size:
        _paginate_tools(server, page_size)
    return server


def _paginate_tools(server: FastMCP, page_size: int) -> None:
    """Replace the tools/list handler with a cursor-paginated one."""
    from mcp import types

    low = server._mcp_server

    async def handler(request: types.ListToolsRequest):
        tools = await server.list_tools()
        # call_tool validates against the low-level cache, which the default
        # handler fills with the full list; keep that behaviour.
        low._tool_cache.update({tool.name: tool for tool in tools})
        cursor = request.params.cursor if request.params else None
        start = int(cursor or 0)
        page = tools[start : start + page_size]
        nxt = str(start + page_size) if start + page_size < len(tools) else None
        return types.ServerResult(types.ListToolsResult(tools=page, nextCursor=nxt))

    low.request_handlers[types.ListToolsRequest] = handler


class Recorder:
    """ASGI wrapper that records every request path and can deny with a status."""

    def __init__(self, app, deny: int | None = None, require_token: bool = False):
        self.app = app
        self.deny = deny
        self.require_token = require_token
        self.paths: list[tuple[str, str]] = []

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            self.paths.append((scope["method"], scope["path"]))
            headers = dict(scope.get("headers") or [])
            token = headers.get(b"x-api-token", b"").decode()
            status = self.deny
            if status is None and self.require_token and token != GOOD_TOKEN:
                status = 401
            if status is not None:
                await send({"type": "http.response.start", "status": status, "headers": []})
                await send({"type": "http.response.body", "body": b"denied"})
                return
        await self.app(scope, receive, send)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextlib.contextmanager
def serve(app):
    """Run an ASGI app on a free localhost port; yields its base URL."""
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", lifespan="on")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started:
        if time.time() > deadline:
            raise RuntimeError("test MCP server did not start")
        time.sleep(0.02)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def modern_app(**kwargs):
    return build_server(**kwargs).streamable_http_app()


def legacy_app(**kwargs):
    return build_server(**kwargs).sse_app()
