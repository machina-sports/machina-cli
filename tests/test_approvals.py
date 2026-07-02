"""Tests for `machina approvals` — the human side of workflow approval checkpoints.

The CLI is deliberately thin: list reads `approval-request` documents; approve/
reject execute the in-pod `machina-approval-resolve` workflow so every surface
shares the same resolution logic. These pin that contract.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from machina_cli.main import app

runner = CliRunner()


def _doc(request_id, title, status="pending", workflow="publish-article"):
    return {"created": "Thu, 02 Jul 2026 12:00:00 GMT",
            "value": {"request_id": request_id, "title": title, "status": status,
                      "action": {"workflow": workflow}, "requested_at": "2026-07-02T12:00:00+00:00"}}


def test_list_renders_pending_requests():
    client = MagicMock()
    client.post.return_value = {"data": {"data": [_doc("abc123", "Publish: Flamengo preview")]}}
    with patch("machina_cli.commands.approvals.ProjectClient", return_value=client):
        result = runner.invoke(app, ["approvals", "list"])
    assert result.exit_code == 0
    assert "abc123" in result.output and "Flamengo" in result.output
    body = client.post.call_args[0][1]
    assert body["filters"] == {"name": "approval-request", "value.status": "pending"}


def test_list_all_drops_the_status_filter():
    client = MagicMock()
    client.post.return_value = {"data": {"data": []}}
    with patch("machina_cli.commands.approvals.ProjectClient", return_value=client):
        result = runner.invoke(app, ["approvals", "list", "--all"])
    assert result.exit_code == 0
    assert client.post.call_args[0][1]["filters"] == {"name": "approval-request"}


def test_list_json_is_parseable():
    client = MagicMock()
    client.post.return_value = {"data": {"data": [_doc("abc123", "T")]}}
    with patch("machina_cli.commands.approvals.ProjectClient", return_value=client):
        result = runner.invoke(app, ["approvals", "list", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload[0]["request_id"] == "abc123"
    assert payload[0]["action_workflow"] == "publish-article"


def test_approve_executes_the_resolve_workflow():
    client = MagicMock()
    client.post.return_value = {"status": True, "data": {"resolved": True,
                                                          "dispatch": {"dispatched": True, "workflow": "publish-article"}}}
    with patch("machina_cli.commands.approvals.ProjectClient", return_value=client):
        result = runner.invoke(app, ["approvals", "approve", "abc123"])
    assert result.exit_code == 0
    path, body = client.post.call_args[0]
    assert path == "workflow/execute/machina-approval-resolve"
    assert body["request_id"] == "abc123" and body["decision"] == "approve"
    assert "approved" in result.output and "publish-article" in result.output


def test_reject_sends_reject_decision():
    client = MagicMock()
    client.post.return_value = {"status": True, "data": {"resolved": True, "dispatch": {"dispatched": False}}}
    with patch("machina_cli.commands.approvals.ProjectClient", return_value=client):
        result = runner.invoke(app, ["approvals", "reject", "abc123"])
    assert result.exit_code == 0
    assert client.post.call_args[0][1]["decision"] == "reject"
    assert "rejected" in result.output


def test_resolve_failure_exits_nonzero_with_reason():
    client = MagicMock()
    client.post.return_value = {"status": True, "data": {"resolved": False, "error": "request zz not found"}}
    with patch("machina_cli.commands.approvals.ProjectClient", return_value=client):
        result = runner.invoke(app, ["approvals", "approve", "zz"])
    assert result.exit_code == 1
    assert "not found" in result.output


def test_approve_reports_dispatch_failure():
    client = MagicMock()
    client.post.return_value = {"status": True, "data": {"resolved": True,
                                                          "dispatch": {"dispatched": False, "workflow": "w", "error": "boom"}}}
    with patch("machina_cli.commands.approvals.ProjectClient", return_value=client):
        result = runner.invoke(app, ["approvals", "approve", "abc123"])
    assert result.exit_code == 0
    assert "dispatch failed" in result.output and "boom" in result.output
