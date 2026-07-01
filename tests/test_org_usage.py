"""Tests for `machina org usage` — token-consumption rollup from the usage ledger.

Token usage is read from the permanent `organization_ledger` via core-api (the same
source the Studio usage view uses): the headline + by-day come from the paginated
`{scope}/{id}/usage` endpoint (server computes `totals` + `chart_data` over the full
window), and the by-project / by-agent breakdown is best-effort from the unpaginated
`{scope}/{id}/usage/export`. These tests mock MachinaClient.post for those endpoints
(no network) and pin the aggregation, the JSON contract, and graceful degradation.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx
from typer.testing import CliRunner

from machina_cli.main import app

runner = CliRunner()

# Paginated /usage response: server-computed totals + per-bucket chart_data.
_USAGE = {
    "data": {
        "totals": {"input": 7200, "output": 240, "duration": 12.0},
        "chart_data": [
            {"timestamp": "2026-06-29T22:00:00", "input_tokens": 3000, "output_tokens": 150, "count": 2},
            {"timestamp": "2026-06-28T09:00:00", "input_tokens": 4200, "output_tokens": 90, "count": 3},
        ],
    },
    "pagination": {"total_documents": 5},
}
_TOTAL = 7440  # 7200 + 240

# Org export rows use keys input/output/pid.
_EXPORT_ORG = {
    "data": {
        "documents": [
            {"date": "2026-06-29 23:00:00", "input": 1000, "output": 100, "name": "sportingbot-assistant", "pid": "p1"},
            {"date": "2026-06-29 22:00:00", "input": 2000, "output": 50, "name": "sportingbot-assistant", "pid": "p1"},
            {"date": "2026-06-28 10:00:00", "input": 3000, "output": 60, "name": "sportingbot-assistant", "pid": "p1"},
            {"date": "2026-06-28 09:00:00", "input": 500, "output": 20, "name": "coverage-enrich", "pid": "p1"},
            {"date": "2026-06-28 08:00:00", "input": 700, "output": 10, "name": "coverage-enrich", "pid": "p1"},
        ]
    }
}

# Project export rows use DIFFERENT keys: input_tokens/output_tokens/project_id.
_EXPORT_PROJECT = {
    "data": {
        "documents": [
            {"date": "2026-06-29 23:00:00", "input_tokens": 1000, "output_tokens": 100, "name": "sportingbot-assistant", "project_id": "p1"},
            {"date": "2026-06-28 09:00:00", "input_tokens": 500, "output_tokens": 20, "name": "coverage-enrich", "project_id": "p1"},
        ]
    }
}


def _client(usage=_USAGE, export=_EXPORT_ORG, projects=None):
    """MachinaClient mock routing by path: /usage, /usage/export, user/projects/search.

    `usage`/`export` may be a dict (returned) or an Exception instance (raised), to
    exercise the headline-timeout and breakdown-degradation paths.
    """
    client = MagicMock()

    def _post(path, json_data=None, quiet=False, **kwargs):
        if path.endswith("/usage/export"):
            if isinstance(export, Exception):
                raise export
            return export
        if path.endswith("/usage"):
            if isinstance(usage, Exception):
                raise usage
            return usage
        if path == "user/projects/search":
            rows = projects or []
            return {"data": rows, "pagination": {"total_documents": len(rows)}}
        return {"data": []}

    client.return_value.post.side_effect = _post
    return client


_PROJECTS = [
    {"project_id": "p1", "project_name": "SBOT", "organization_id": "org_1", "status": "active"},
    {"project_id": "p2", "project_name": "Other", "organization_id": "org_2", "status": "active"},
]


def test_usage_reads_ledger_totals_and_breakdown_for_org():
    with (
        patch("machina_cli.commands.org.get_config", return_value=None),
        patch("machina_cli.commands.org.MachinaClient", _client(projects=_PROJECTS)),
    ):
        result = runner.invoke(app, ["org", "usage", "--org", "org_1", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)

    assert payload["source"] == "organization_ledger"
    assert payload["totals"] == {"prompt": 7200, "completion": 240, "total": _TOTAL, "count": 5}
    # by-day is rolled up from chart_data (not from paginated documents)
    assert payload["by_day"]["2026-06-29"] == {"total": 3150, "count": 2}
    assert payload["by_day"]["2026-06-28"] == {"total": 4290, "count": 3}
    # by-agent from the export, ordered by total desc; pid mapped to a readable name
    agents = payload["by_agent"]
    assert agents["sportingbot-assistant"]["total"] == 1100 + 2050 + 3060
    assert agents["coverage-enrich"]["total"] == 520 + 710
    assert list(agents.keys())[0] == "sportingbot-assistant"
    assert "SBOT" in payload["by_project"]
    assert payload["breakdown_available"] is True
    # legacy scan flags retained but inert
    assert payload["incomplete"] is False
    assert payload["projects_errored"] == []
    assert payload["projects_skipped"] == []


def test_project_scope_reads_project_export_field_names():
    # Regression guard: the project export uses input_tokens/output_tokens/project_id,
    # NOT input/output/pid. The breakdown MUST show non-zero tokens.
    with (
        patch("machina_cli.commands.org.get_config", return_value=None),
        patch("machina_cli.commands.org.MachinaClient", _client(export=_EXPORT_PROJECT)),
    ):
        result = runner.invoke(app, ["org", "usage", "--project", "p1", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    agents = payload["by_agent"]
    assert agents["sportingbot-assistant"]["total"] == 1100
    assert agents["coverage-enrich"]["total"] == 520
    assert all(a["total"] > 0 for a in agents.values())  # not silently zero


def test_headline_timeout_is_actionable_not_traceback():
    # The /usage headline call is essential; a timeout must produce a clean error
    # and exit 1, never an unhandled traceback.
    with (
        patch("machina_cli.commands.org.get_config", return_value=None),
        patch("machina_cli.commands.org.MachinaClient", _client(usage=httpx.ReadTimeout("slow"))),
    ):
        result = runner.invoke(app, ["org", "usage", "--org", "org_1", "--json"])
    assert result.exit_code == 1
    assert "timed out" in result.output.lower()


def test_breakdown_failure_degrades_gracefully():
    # If the export (breakdown) call fails, the headline + by-day stay exact and the
    # command still succeeds; breakdown is flagged unavailable.
    with (
        patch("machina_cli.commands.org.get_config", return_value=None),
        patch(
            "machina_cli.commands.org.MachinaClient",
            _client(export=httpx.ReadTimeout("slow"), projects=_PROJECTS),
        ),
    ):
        result = runner.invoke(app, ["org", "usage", "--org", "org_1", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["totals"]["total"] == _TOTAL  # headline still exact
    assert payload["by_day"]["2026-06-29"]["total"] == 3150
    assert payload["breakdown_available"] is False
    assert payload["by_agent"] == {}


def test_resolve_org_projects_maps_names_and_labels_unnamed_stub():
    from machina_cli.commands import org as org_mod

    projects = [
        {"project_id": "p1", "project_name": "Real One", "organization_id": "org_1"},
        {"project_id": "69ffa178815a5305f540dcac", "organization_id": "org_1"},  # bare stub
        {"project_id": "p3", "project_name": "Other Org", "organization_id": "org_2"},
    ]
    with patch("machina_cli.commands.org.MachinaClient", _client(projects=projects)):
        names = org_mod._resolve_org_projects("org_1")
    assert names["p1"] == "Real One"
    assert names["69ffa178815a5305f540dcac"] == "(unnamed:69ffa178)"
    assert "p3" not in names  # other org excluded


def test_usage_no_org_no_project_errors():
    with patch("machina_cli.commands.org.get_config", return_value=None):
        result = runner.invoke(app, ["org", "usage"])
    assert result.exit_code == 1
    assert "No organization specified" in result.output


def test_usage_console_reports_headline_and_source():
    with (
        patch("machina_cli.commands.org.get_config", return_value=None),
        patch("machina_cli.commands.org.MachinaClient", _client(projects=_PROJECTS)),
    ):
        result = runner.invoke(app, ["org", "usage", "--org", "org_1"])
    assert result.exit_code == 0, result.output
    assert "Token consumption" in result.output
    assert "organization_ledger" in result.output


def test_month_flag_sets_full_calendar_window():
    # Invoicing: --month YYYY-MM must cover the whole calendar month, inclusive.
    from datetime import datetime as _dt

    with (
        patch("machina_cli.commands.org.get_config", return_value=None),
        patch("machina_cli.commands.org.MachinaClient", _client(projects=_PROJECTS)),
    ):
        result = runner.invoke(app, ["org", "usage", "--org", "org_1", "--month", "2026-02", "--json"])
    assert result.exit_code == 0, result.output
    window = json.loads(result.output)["window"]
    assert window["from"] == "2026-02-01"
    assert window["to"] == "2026-02-28"  # non-leap year: last day is the 28th
    assert window["label"] == _dt(2026, 2, 1).strftime("%B %Y")


def test_month_flag_handles_leap_year():
    with (
        patch("machina_cli.commands.org.get_config", return_value=None),
        patch("machina_cli.commands.org.MachinaClient", _client(projects=_PROJECTS)),
    ):
        result = runner.invoke(app, ["org", "usage", "--org", "org_1", "--month", "2024-02", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["window"]["to"] == "2024-02-29"  # leap day included


def test_month_flag_rejects_bad_format():
    with (
        patch("machina_cli.commands.org.get_config", return_value=None),
        patch("machina_cli.commands.org.MachinaClient", _client(projects=_PROJECTS)),
    ):
        result = runner.invoke(app, ["org", "usage", "--org", "org_1", "--month", "2026-13", "--json"])
    assert result.exit_code == 1
    assert "YYYY-MM" in result.output


def test_last_month_flag_is_a_full_prior_calendar_month():
    with (
        patch("machina_cli.commands.org.get_config", return_value=None),
        patch("machina_cli.commands.org.MachinaClient", _client(projects=_PROJECTS)),
    ):
        result = runner.invoke(app, ["org", "usage", "--org", "org_1", "--last-month", "--json"])
    assert result.exit_code == 0, result.output
    window = json.loads(result.output)["window"]
    assert window["from"].endswith("-01")  # starts on the 1st
    assert window["from"][:7] == window["to"][:7]  # same calendar month
    assert window["label"] != "last 30d"  # not the rolling window
