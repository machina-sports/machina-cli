"""Tests for `machina org usage` — token-consumption rollup over agent executions.

Token usage is recorded on agent executions (`execution_tokens`); the Client-API
`execution/agent-search` totals are page-level only, so the command paginates and
sums client-side. These tests pin the aggregation, pagination termination, and the
by-agent / by-day breakdown without touching the network.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx
from typer.testing import CliRunner

from machina_cli.main import app

runner = CliRunner()

# Five token-bearing agent executions across two agents and two days.
_ROWS = [
    {
        "name": "sportingbot-assistant",
        "date": "Mon, 29 Jun 2026 23:00:00 GMT",
        "execution_tokens": {"prompt_tokens": 1000, "completion_tokens": 100, "total_tokens": 1100},
    },
    {
        "name": "sportingbot-assistant",
        "date": "Mon, 29 Jun 2026 22:00:00 GMT",
        "execution_tokens": {"prompt_tokens": 2000, "completion_tokens": 50, "total_tokens": 2050},
    },
    {
        "name": "sportingbot-assistant",
        "date": "Sun, 28 Jun 2026 10:00:00 GMT",
        "execution_tokens": {"prompt_tokens": 3000, "completion_tokens": 60, "total_tokens": 3060},
    },
    {
        "name": "coverage-enrich",
        "date": "Sun, 28 Jun 2026 09:00:00 GMT",
        "execution_tokens": {"prompt_tokens": 500, "completion_tokens": 20, "total_tokens": 520},
    },
    {
        "name": "coverage-enrich",
        "date": "Sun, 28 Jun 2026 08:00:00 GMT",
        "execution_tokens": {"prompt_tokens": 700, "completion_tokens": 10, "total_tokens": 710},
    },
]
_TOTAL = sum(r["execution_tokens"]["total_tokens"] for r in _ROWS)  # 7440
_PROMPT = sum(r["execution_tokens"]["prompt_tokens"] for r in _ROWS)  # 7200
_COMPLETION = sum(r["execution_tokens"]["completion_tokens"] for r in _ROWS)  # 240


def _paged_client(rows=_ROWS):
    """ProjectClient mock whose `execution/agent-search` paginates `rows`.

    Response shape mirrors the live Client-API: a top-level `total_documents` and
    NO `pagination` object — the contract the command's loop terminates against.
    """
    client = MagicMock()

    def _post(path, payload=None):
        assert path == "execution/agent-search"
        pg = payload["page"]
        ps = payload["page_size"]
        start = (pg - 1) * ps
        return {"data": rows[start : start + ps], "total_documents": len(rows), "status": True}

    client.return_value.post.side_effect = _post
    return client


def _projects_client(projects):
    """MachinaClient mock for `user/projects/search`."""
    client = MagicMock()

    def _post(path, payload=None):
        if path == "user/projects/search":
            return {"data": projects, "total_documents": len(projects)}
        return {"data": []}

    client.return_value.post.side_effect = _post
    return client


def test_usage_aggregates_tokens_for_single_project():
    # --project skips org resolution; --limit 2 forces 3 pages (2+2+1) to exercise the loop
    with (
        patch("machina_cli.commands.org.get_config", return_value=None),
        patch("machina_cli.commands.org.ProjectClient", _paged_client()),
    ):
        result = runner.invoke(app, ["org", "usage", "--project", "p1", "--limit", "2", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["totals"] == {
        "prompt": _PROMPT,
        "completion": _COMPLETION,
        "total": _TOTAL,
        "count": len(_ROWS),
    }
    # by-agent breakdown is correct and ordered by total tokens desc
    agents = payload["by_agent"]
    assert agents["sportingbot-assistant"]["count"] == 3
    assert agents["sportingbot-assistant"]["total"] == 1100 + 2050 + 3060
    assert agents["coverage-enrich"]["total"] == 520 + 710
    assert list(agents.keys())[0] == "sportingbot-assistant"
    # by-day groups the RFC-1123 `date` field
    assert payload["by_day"]["2026-06-29"]["count"] == 2
    assert payload["by_day"]["2026-06-28"]["total"] == 3060 + 520 + 710


def test_usage_pagination_visits_every_page_once():
    # page cap proves termination keys off total_documents, not an empty trailing page
    client = _paged_client()
    with (
        patch("machina_cli.commands.org.get_config", return_value=None),
        patch("machina_cli.commands.org.ProjectClient", client),
    ):
        result = runner.invoke(app, ["org", "usage", "--project", "p1", "--limit", "2", "--json"])
    assert result.exit_code == 0, result.output
    # 5 rows / page_size 2 -> pages 1,2,3 (no wasted 4th request)
    pages = [
        c.kwargs.get("json", c.args[1])["page"] for c in client.return_value.post.call_args_list
    ]
    assert pages == [1, 2, 3]


def test_usage_resolves_projects_for_org():
    projects = [
        {
            "project_id": "p1",
            "project_name": "SBOT",
            "organization_id": "org_1",
            "status": "active",
        },
        {
            "project_id": "p2",
            "project_name": "Other",
            "organization_id": "org_2",
            "status": "active",
        },
    ]
    with (
        patch("machina_cli.commands.org.get_config", return_value=None),
        patch("machina_cli.commands.org.MachinaClient", _projects_client(projects)),
        patch("machina_cli.commands.org.ProjectClient", _paged_client()),
    ):
        result = runner.invoke(app, ["org", "usage", "--org", "org_1", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    # only org_1's project is scanned and attributed
    assert payload["organization_id"] == "org_1"
    assert "SBOT" in payload["by_project"]
    assert "Other" not in payload["by_project"]
    assert payload["totals"]["total"] == _TOTAL


def test_resolve_org_projects_labels_unnamed_stub():
    # a bare membership stub (project_id only, no name) gets a readable label, not a
    # raw ObjectId — and is still returned as a target (never silently excluded)
    from machina_cli.commands import org as org_mod

    projects = [
        {"project_id": "p1", "project_name": "Real One", "organization_id": "org_1"},
        {"project_id": "69ffa178815a5305f540dcac", "organization_id": "org_1"},  # bare stub
        {"project_id": "p3", "project_name": "Other Org", "organization_id": "org_2"},
    ]
    with patch("machina_cli.commands.org.MachinaClient", _projects_client(projects)):
        targets = dict(org_mod._resolve_org_projects("org_1"))
    assert targets["p1"] == "Real One"
    assert targets["69ffa178815a5305f540dcac"] == "(unnamed:69ffa178)"
    assert "p3" not in targets  # other org excluded


def test_usage_skips_undeployed_project_as_benign():
    # ProjectClient() (session login) fails persistently -> undeployed/no access ->
    # benign skip, NOT marked incomplete.
    bad = MagicMock(side_effect=SystemExit(1))
    with (
        patch("machina_cli.commands.org.get_config", return_value=None),
        patch("time.sleep", lambda *a: None),  # don't wait on retry backoff
        patch("machina_cli.commands.org.ProjectClient", bad),
    ):
        result = runner.invoke(app, ["org", "usage", "--project", "p1", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["totals"]["count"] == 0
    assert payload["projects_skipped"] == ["p1"]
    assert payload["projects_errored"] == []
    assert payload["incomplete"] is False


def test_usage_flags_incomplete_when_reachable_project_scan_fails():
    # session opens fine (reachable) but the search keeps 500ing/timing out -> the
    # project is ERRORED and the total must be flagged PARTIAL, never silently dropped.
    client = MagicMock()
    client.return_value.post.side_effect = httpx.ReadTimeout("slow")
    with (
        patch("machina_cli.commands.org.get_config", return_value=None),
        patch("time.sleep", lambda *a: None),
        patch("machina_cli.commands.org.ProjectClient", client),
    ):
        result = runner.invoke(app, ["org", "usage", "--project", "p1", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["totals"]["count"] == 0
    assert payload["projects_errored"] == ["p1"]
    assert payload["projects_skipped"] == []
    assert payload["incomplete"] is True


def test_usage_retries_then_succeeds():
    # transient failures (sbot-prd-style 500s) recover on retry -> project IS counted
    client = MagicMock()
    calls = {"n": 0}

    def _post(path, payload=None):
        calls["n"] += 1
        if calls["n"] <= 2:  # fail the first two attempts, succeed on the third
            raise httpx.ReadTimeout("transient 500")
        return {"data": _ROWS, "total_documents": len(_ROWS), "status": True}

    client.return_value.post.side_effect = _post
    with (
        patch("machina_cli.commands.org.get_config", return_value=None),
        patch("time.sleep", lambda *a: None),
        patch("machina_cli.commands.org.ProjectClient", client),
    ):
        result = runner.invoke(app, ["org", "usage", "--project", "p1", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["totals"]["total"] == _TOTAL  # recovered, fully counted
    assert payload["incomplete"] is False
    assert payload["projects_errored"] == []


def test_usage_no_org_no_project_errors():
    with patch("machina_cli.commands.org.get_config", return_value=None):
        result = runner.invoke(app, ["org", "usage"])
    assert result.exit_code == 1
    assert "No organization specified" in result.output


def test_usage_console_reports_prompt_completion_split():
    with (
        patch("machina_cli.commands.org.get_config", return_value=None),
        patch("machina_cli.commands.org.ProjectClient", _paged_client()),
    ):
        result = runner.invoke(app, ["org", "usage", "--project", "p1"])
    assert result.exit_code == 0, result.output
    # the prompt-dominated profile is the headline insight — it must surface
    assert "Token consumption" in result.output
    assert "prompt" in result.output.lower()
