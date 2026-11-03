"""Protocol-level access to a project's MCP server (official `mcp` Python SDK).

One bounded resolution rule, shared by `machina mcp` and `machina connect`:

1. Streamable HTTP at ``{client-api base}/mcp``.
2. Legacy SSE at ``{client-api base}/mcp/sse`` — ONLY when (1) answered 404/405,
   i.e. the deployment has no streamable endpoint. Never after a 401/403 (no
   silent downgrade after an auth denial), never on a connection error, and
   never on any host other than the project's resolved Client-API base.

"Ready" means the protocol handshake completed, `tools/list` was walked and the
harmless `health_check` tool answered success — an HTTP 200 or an open stream
alone never counts. Every failure is a typed `MCPConnectError` whose code/hint
callers print verbatim; credentials never appear in messages or payloads.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

SCHEMA = "machina.mcp.connection/v1"

STREAMABLE_PATH = "/mcp"
SSE_PATH = "/mcp/sse"
TRANSPORT_STREAMABLE = "streamable-http"
TRANSPORT_SSE = "sse"

DEFAULT_TIMEOUT = 15.0
# Upper bound on tools/list pages, so a server echoing the same cursor can't spin us.
MAX_PAGES = 100

HINTS = {
    "missing_credentials": "Run `machina login`, or set MACHINA_API_KEY to a project API key.",
    "expired_credentials": (
        "The credential was rejected. Run `machina login` again, or rotate the "
        "project API key (`machina credentials`)."
    ),
    "wrong_project": (
        "Check the project id (`machina project list`) and that your login can access it."
    ),
    "access_denied": "The credential is valid but has no access to this project's MCP server.",
    "endpoint_unavailable": (
        "The project's MCP server did not answer. Check the project is deployed and "
        "running, then retry."
    ),
    "incompatible_protocol": (
        "The server does not speak a compatible MCP protocol. Update machina-cli "
        "(`machina update`) or report the server version."
    ),
    "health_check_failed": (
        "The MCP server is up but its health_check read failed; the project API may be degraded."
    ),
    "tool_failed": "The MCP tool returned an error; see the message for the server's reason.",
    "not_found": "Nothing with that name or id exists in this project.",
}


class MCPConnectError(Exception):
    """A typed, user-actionable MCP connection failure (never carries a secret)."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status: int | None = None,
        url: str | None = None,
        transport: str | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = HINTS.get(code, "")
        self.http_status = http_status
        self.url = url
        self.transport = transport

    def to_payload(self) -> dict:
        payload = {
            "schema": SCHEMA,
            "error": self.message,
            "error_code": self.code,
            "hint": self.hint,
        }
        if self.http_status is not None:
            payload["http_status"] = self.http_status
        if self.url:
            payload["url"] = self.url
        if self.transport:
            payload["transport"] = self.transport
        return payload


class _HTTPFailure(Exception):
    def __init__(self, status: int):
        super().__init__(f"HTTP {status}")
        self.status = status


def _leaves(exc: BaseException):
    """Flatten (possibly nested) exception groups raised by anyio task groups."""
    children = getattr(exc, "exceptions", None)
    if children:
        for child in children:
            yield from _leaves(child)
    else:
        yield exc


def _status_error(status: int, url: str, transport: str) -> MCPConnectError:
    if status == 401:
        return MCPConnectError(
            "expired_credentials",
            "MCP server rejected the credential (HTTP 401)",
            http_status=status,
            url=url,
            transport=transport,
        )
    if status == 403:
        return MCPConnectError(
            "access_denied",
            "MCP server denied access (HTTP 403)",
            http_status=status,
            url=url,
            transport=transport,
        )
    return MCPConnectError(
        "endpoint_unavailable",
        f"MCP endpoint answered HTTP {status}",
        http_status=status,
        url=url,
        transport=transport,
    )


def _classify(exc: BaseException, url: str, transport: str) -> MCPConnectError:
    import httpx
    from pydantic import ValidationError

    for leaf in _leaves(exc):
        if isinstance(leaf, MCPConnectError):
            return leaf
        if isinstance(leaf, httpx.HTTPStatusError):
            return _status_error(leaf.response.status_code, url, transport)
        if isinstance(leaf, (httpx.TimeoutException, TimeoutError)):
            return MCPConnectError(
                "endpoint_unavailable", "MCP endpoint timed out", url=url, transport=transport
            )
        if isinstance(leaf, (httpx.TransportError, OSError)):
            return MCPConnectError(
                "endpoint_unavailable",
                f"cannot reach MCP endpoint ({type(leaf).__name__})",
                url=url,
                transport=transport,
            )
        if isinstance(leaf, ValidationError) or "protocol" in str(leaf).lower():
            return MCPConnectError(
                "incompatible_protocol",
                "MCP handshake failed: server reply is not a compatible MCP protocol",
                url=url,
                transport=transport,
            )
    from mcp.shared.exceptions import McpError

    for leaf in _leaves(exc):
        if isinstance(leaf, McpError):
            return MCPConnectError(
                "incompatible_protocol",
                f"MCP request failed: {leaf.error.message}",
                url=url,
                transport=transport,
            )
    return MCPConnectError(
        "endpoint_unavailable",
        f"MCP session failed ({type(exc).__name__})",
        url=url,
        transport=transport,
    )


# Read-only project searches the probe may use to prove the credential, in
# order of preference. Product profiles that expose none of them are reported
# with authenticated_read=None (credential not proven by the probe).
_AUTH_READ_TOOLS = ("search_agents", "search_workflows", "search_documents")

_DENIAL_PATTERNS = (
    (re.compile(r"HTTP 401"), "expired_credentials"),
    (re.compile(r"HTTP 403"), "access_denied"),
    (re.compile(r"Authentication required", re.IGNORECASE), "missing_credentials"),
)


def tool_payload(result: Any) -> tuple[bool, Any, str]:
    """Return (is_error, data, text) for a CallToolResult.

    `data` is the structured content when the server supplies it (unwrapping the
    SDK's {"result": ...} envelope for non-object returns), else the JSON-decoded
    text content, else None. `text` is the joined text content, for messages.
    """
    import json

    text = "".join(
        getattr(block, "text", "") for block in (result.content or []) if block.type == "text"
    )
    data = result.structuredContent
    if isinstance(data, dict) and set(data) == {"result"}:
        data = data["result"]
    if data is None and text:
        try:
            data = json.loads(text)
        except ValueError:
            data = None
    return bool(result.isError), data, text


def tool_error(
    name: str, text: str, url: str | None = None, code: str = "tool_failed"
) -> MCPConnectError:
    """Map an isError tool result onto the typed error map (auth denials first)."""
    for pattern, denial in _DENIAL_PATTERNS:
        if pattern.search(text or ""):
            return MCPConnectError(
                denial, f"{name} was denied: {denial.replace('_', ' ')}", url=url
            )
    return MCPConnectError(code, f"{name} returned an error", url=url)


def unwrap(name: str, data: Any) -> Any:
    """Peel the proxy envelopes ({"status", "data"}) a client-api MCP tool returns.

    The MCP layer wraps the REST body ({"status": true, "data": ...}); either
    layer may report failure (`status` "error"/false, or `error_code`). A failure
    raises a typed error — an envelope that *says* error is never success data.
    """
    # Only envelope statuses are peeled: a resource's own `status` (a skill's
    # "available", a run's "executed") ends the walk and is returned as data.
    while isinstance(data, dict) and (
        data.get("status") in ("success", True, "error", False) or data.get("error_code")
    ):
        if data.get("status") in ("error", False) or data.get("error_code"):
            error = data.get("error")
            message = (
                (error.get("message") if isinstance(error, dict) else error)
                or data.get("message")
                or data.get("error_code")
                or "error"
            )
            detail = f"{message} {data.get('details') or ''}"
            code = (
                "not_found" if re.search(r"404|not found", detail, re.IGNORECASE) else "tool_failed"
            )
            raise MCPConnectError(code, f"{name}: {message}")
        if "data" not in data:
            return data
        data = data["data"]
    return data


async def call(session: Any, name: str, arguments: dict) -> Any:
    """Call one MCP tool and return its unwrapped payload, or raise typed."""
    is_error, data, text = tool_payload(await session.call_tool(name, arguments))
    if is_error:
        raise tool_error(name, text)
    return unwrap(name, data)


async def list_all_tools(session: Any) -> list:
    """Walk `tools/list` cursor pagination to the end (bounded by MAX_PAGES)."""
    tools: list = []
    cursor: str | None = None
    seen: set[str] = set()
    for _ in range(MAX_PAGES):
        page = await session.list_tools(cursor=cursor) if cursor else await session.list_tools()
        tools.extend(page.tools)
        cursor = page.nextCursor
        if not cursor or cursor in seen:
            return tools
        seen.add(cursor)
    raise MCPConnectError(
        "incompatible_protocol", f"tools/list did not finish within {MAX_PAGES} pages"
    )


async def _attempt(
    transport: str,
    url: str,
    headers: dict,
    timeout: float,
    work: Callable[[Any], Awaitable[Any]],
) -> tuple[dict, Any]:
    """One transport attempt. Raises _HTTPFailure(status) on an HTTP error status
    (so the caller decides about fallback), MCPConnectError otherwise."""
    import anyio
    import httpx
    from mcp import ClientSession, types
    from mcp.client.sse import sse_client
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared._httpx_utils import create_mcp_http_client

    from machina_cli import __version__

    state: dict[str, Any] = {"status": None, "exc": None}
    scope = anyio.CancelScope()

    # The SDK reports HTTP failures asynchronously through the read stream, which
    # leaves the pending request waiting for its read timeout. Record the first
    # error status here and cancel at once so a 401/404 is a fast, typed answer.
    async def on_response(response: httpx.Response):
        if response.status_code >= 400 and state["status"] is None:
            state["status"] = response.status_code
            scope.cancel()

    def client_factory(headers=None, timeout=None, auth=None) -> httpx.AsyncClient:
        client = create_mcp_http_client(headers=headers, timeout=timeout, auth=auth)
        client.event_hooks["response"].append(on_response)
        return client

    async def on_message(message: Any):
        if isinstance(message, Exception) and state["exc"] is None:
            state["exc"] = message
            scope.cancel()

    client_info = types.Implementation(name="machina-cli", version=__version__)
    meta: dict | None = None
    result: Any = None
    try:
        with scope:
            scope.deadline = anyio.current_time() + timeout
            if transport == TRANSPORT_STREAMABLE:
                http_client = client_factory(
                    headers=headers, timeout=httpx.Timeout(timeout, read=timeout)
                )
                async with (
                    http_client,
                    streamable_http_client(url, http_client=http_client) as (
                        read,
                        write,
                        _,
                    ),
                ):
                    meta, result = await _run_session(
                        ClientSession, read, write, timeout, on_message, client_info, work
                    )
            else:
                async with sse_client(
                    url,
                    headers=headers,
                    timeout=timeout,
                    sse_read_timeout=timeout,
                    httpx_client_factory=client_factory,
                ) as (read, write):
                    meta, result = await _run_session(
                        ClientSession, read, write, timeout, on_message, client_info, work
                    )
    except Exception as exc:
        for leaf in _leaves(exc):
            if isinstance(leaf, MCPConnectError):
                leaf.url = leaf.url or url
                leaf.transport = leaf.transport or transport
                raise leaf from None
        if state["exc"] is None:
            state["exc"] = exc

    if meta is not None and state["status"] is None and state["exc"] is None:
        meta.update({"transport": transport, "url": url})
        return meta, result
    if state["status"] is not None:
        raise _HTTPFailure(state["status"])
    if state["exc"] is not None:
        raise _classify(state["exc"], url, transport)
    raise MCPConnectError(
        "endpoint_unavailable",
        f"MCP endpoint timed out after {timeout:g}s",
        url=url,
        transport=transport,
    )


async def _run_session(ClientSession, read, write, timeout, on_message, client_info, work):
    async with ClientSession(
        read,
        write,
        read_timeout_seconds=timedelta(seconds=timeout),
        message_handler=on_message,
        client_info=client_info,
    ) as session:
        init = await session.initialize()
        server = getattr(init, "serverInfo", None)
        meta = {
            "protocol_version": str(init.protocolVersion),
            "server": {
                "name": getattr(server, "name", None),
                "version": getattr(server, "version", None),
            },
        }
        return meta, await work(session)


def candidates(base_url: str) -> list[tuple[str, str]]:
    """The only endpoints ever tried, in order — both on the resolved base host."""
    base = base_url.rstrip("/")
    return [
        (TRANSPORT_STREAMABLE, f"{base}{STREAMABLE_PATH}"),
        (TRANSPORT_SSE, f"{base}{SSE_PATH}"),
    ]


async def _resolve_and_run(base_url, headers, timeout, work):
    (modern, modern_url), (legacy, legacy_url) = candidates(base_url)
    try:
        return await _attempt(modern, modern_url, headers, timeout, work)
    except _HTTPFailure as failure:
        if failure.status not in (404, 405):
            # 401/403/5xx: report it — falling back after an auth denial would
            # silently downgrade, and a 5xx is not "no streamable endpoint".
            raise _status_error(failure.status, modern_url, modern) from None
    try:
        return await _attempt(legacy, legacy_url, headers, timeout, work)
    except _HTTPFailure as failure:
        raise _status_error(failure.status, legacy_url, legacy) from None


def run(
    base_url: str,
    auth: tuple[str, str],
    work: Callable[[Any], Awaitable[Any]],
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[dict, Any]:
    """Open a session on the project's MCP server and run `work(session)`.

    Returns (connection_meta, work_result); meta carries transport, url,
    protocol_version and server info. Raises MCPConnectError.
    """
    import anyio

    header_name, token = auth
    if not header_name or not token:
        # Never connect anonymously: a legacy server may lend its own token.
        raise MCPConnectError("missing_credentials", "not authenticated")
    if not base_url:
        raise MCPConnectError("wrong_project", "project has no client-api address")
    headers = {header_name: token}
    return anyio.run(_resolve_and_run, base_url, headers, timeout, work)


async def _probe_work(session: Any) -> dict:
    tools = await list_all_tools(session)
    if "health_check" not in {tool.name for tool in tools}:
        raise MCPConnectError(
            "incompatible_protocol", "server does not expose the health_check tool"
        )
    is_error, data, text = tool_payload(await session.call_tool("health_check", {}))
    if is_error:
        raise tool_error("health_check", text, code="health_check_failed")
    if not isinstance(data, dict) or data.get("status") != "success":
        detail = data.get("error_code") or data.get("message") if isinstance(data, dict) else None
        raise MCPConnectError(
            "health_check_failed",
            f"health_check did not report success{f' ({detail})' if detail else ''}",
        )
    # health_check answers without touching project data (the client-api health
    # route is unauthenticated, and the stateless /mcp only checks that a token
    # is present), so it cannot tell a valid credential from a wrong one. One
    # authenticated, read-only, single-item search proves the credential.
    names = {tool.name for tool in tools}
    read_tool = next((name for name in _AUTH_READ_TOOLS if name in names), None)
    if read_tool:
        result = await session.call_tool(read_tool, {"page_size": 1, "fields": ["_id"]})
        is_error, data, text = tool_payload(result)
        if is_error:
            raise tool_error(read_tool, text)
        if isinstance(data, dict) and (
            data.get("status") in ("error", False) or data.get("error_code")
        ):
            raise tool_error(read_tool, f"{data.get('message') or ''} {data.get('details') or ''}")
    return {"tool_count": len(tools), "health_check": "ok", "authenticated_read": read_tool}


def probe(base_url: str, auth: tuple[str, str], timeout: float = DEFAULT_TIMEOUT) -> dict:
    """Full readiness probe: handshake → tools/list → health_check.

    Returns {transport, url, protocol_version, server, tool_count, health_check}.
    """
    meta, result = run(base_url, auth, _probe_work, timeout)
    return {**meta, **result}
