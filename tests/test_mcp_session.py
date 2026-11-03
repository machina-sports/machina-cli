"""Protocol tests for mcp_session against real local MCP servers.

No network beyond 127.0.0.1, no Machina credentials: the servers are the
official SDK's FastMCP, shaped like the deployments the CLI must handle.
"""

from __future__ import annotations

import json

import pytest

from machina_cli import mcp_session
from machina_cli.mcp_session import MCPConnectError
from tests.mcp_server_fixture import (
    GOOD_TOKEN,
    Recorder,
    legacy_app,
    modern_app,
    serve,
)

AUTH = ("X-Api-Token", GOOD_TOKEN)


def _error(base, auth=AUTH, timeout=5.0) -> MCPConnectError:
    with pytest.raises(MCPConnectError) as info:
        mcp_session.probe(base, auth, timeout=timeout)
    return info.value


def test_probe_streamable_http_ready():
    with serve(modern_app()) as base:
        result = mcp_session.probe(base, AUTH, timeout=5)
    assert result["transport"] == "streamable-http"
    assert result["url"] == f"{base}/mcp"
    assert result["protocol_version"]
    assert result["server"]["name"] == "machina-test"
    assert result["health_check"] == "ok"
    assert result["tool_count"] == 2  # health_check + search_agents


def test_probe_legacy_sse_fallback_on_404():
    app = Recorder(legacy_app())
    with serve(app) as base:
        result = mcp_session.probe(base, AUTH, timeout=5)
    assert result["transport"] == "sse"
    assert result["url"] == f"{base}/mcp/sse"
    assert result["health_check"] == "ok"
    # streamable was tried first, then SSE — on the same host only.
    assert app.paths[0] == ("POST", "/mcp")
    assert ("GET", "/mcp/sse") in app.paths


@pytest.mark.parametrize(("status", "code"), [(401, "expired_credentials"), (403, "access_denied")])
def test_no_sse_downgrade_after_auth_denial(status, code):
    app = Recorder(legacy_app(), deny=status)
    with serve(app) as base:
        error = _error(base)
    assert error.code == code
    assert error.http_status == status
    assert error.transport == "streamable-http"
    # The denial on /mcp stops resolution: SSE is never attempted.
    assert all(path != "/mcp/sse" for _, path in app.paths)


def test_wrong_token_is_rejected_not_downgraded():
    app = Recorder(modern_app(), require_token=True)
    with serve(app) as base:
        error = _error(base, auth=("X-Api-Token", "sk-wrong"))
    assert error.code == "expired_credentials"


def test_missing_credentials_never_connects():
    with pytest.raises(MCPConnectError) as info:
        mcp_session.probe("http://127.0.0.1:9", ("", ""), timeout=1)
    assert info.value.code == "missing_credentials"


def test_endpoint_unavailable_on_connection_refused():
    error = _error("http://127.0.0.1:9", timeout=2)
    assert error.code == "endpoint_unavailable"


def test_endpoint_unavailable_on_5xx_without_fallback():
    app = Recorder(legacy_app(), deny=503)
    with serve(app) as base:
        error = _error(base)
    assert error.code == "endpoint_unavailable"
    assert error.http_status == 503
    assert all(path != "/mcp/sse" for _, path in app.paths)


@pytest.mark.parametrize(
    ("health", "code"),
    [
        ("denied", "access_denied"),
        ("expired", "expired_credentials"),
        ("error", "health_check_failed"),
    ],
)
def test_health_check_failure_is_not_ready(health, code):
    # Handshake + tools/list succeed but the harmless read fails: never "ready".
    with serve(modern_app(health=health)) as base:
        error = _error(base)
    assert error.code == code


def test_tools_list_pagination_is_walked():
    with serve(modern_app(tools=25, page_size=4)) as base:
        result = mcp_session.probe(base, AUTH, timeout=5)
    assert result["tool_count"] == 27


def test_incompatible_server_without_health_check():
    from mcp.server.fastmcp import FastMCP

    bare = FastMCP("other", streamable_http_path="/mcp")

    @bare.tool()
    def ping() -> str:
        return "pong"

    from mcp.server.transport_security import TransportSecuritySettings

    bare.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=False
    )
    with serve(bare.streamable_http_app()) as base:
        error = _error(base)
    assert error.code == "incompatible_protocol"


def test_candidates_stay_on_resolved_host():
    urls = [url for _, url in mcp_session.candidates("https://acme-proj.org.machina.gg/")]
    assert urls == [
        "https://acme-proj.org.machina.gg/mcp",
        "https://acme-proj.org.machina.gg/mcp/sse",
    ]


def test_error_payload_never_contains_token():
    app = Recorder(modern_app(), require_token=True)
    with serve(app) as base:
        error = _error(base, auth=("X-Api-Token", "sk-wrong-secret-value"))
    dumped = json.dumps(error.to_payload())
    assert "sk-wrong-secret-value" not in dumped
    assert error.to_payload()["schema"] == mcp_session.SCHEMA


@pytest.mark.parametrize(
    ("read", "code"), [("expired", "expired_credentials"), ("denied", "access_denied")]
)
def test_health_check_alone_does_not_prove_the_credential(read, code):
    # health_check succeeds without checking the token; the authenticated
    # read is what rejects a wrong credential.
    with serve(modern_app(read=read)) as base:
        error = _error(base)
    assert error.code == code


def test_probe_reports_the_authenticated_read():
    with serve(modern_app()) as base:
        result = mcp_session.probe(base, AUTH, timeout=5)
    assert result["authenticated_read"] == "search_agents"


def test_profile_without_project_reads_is_not_claimed_authenticated():
    with serve(modern_app(read=None)) as base:
        result = mcp_session.probe(base, AUTH, timeout=5)
    assert result["authenticated_read"] is None
