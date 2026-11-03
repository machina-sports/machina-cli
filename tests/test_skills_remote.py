"""Tests for remote project Skills (`skills show|docs|run --remote|result`).

A real local MCP server stands in for the pod. Its tools return the client-api
proxy envelopes verbatim: `process_response` → {"status": "success", "data":
<REST body>}, REST body → {"status": true, "data": <record>}; failures are
{"status": "error", "message": "API call failed with status 404", ...}.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from typer.testing import CliRunner

from machina_cli.main import app
from tests.mcp_server_fixture import GOOD_TOKEN, serve

runner = CliRunner()

SKILL_ID = "65f0c0ffee0000000000aa01"
DOC_1 = "65f0c0ffee0000000000dd01"
DOC_2 = "65f0c0ffee0000000000dd02"
RUN_ID = "65f0c0ffee0000000000ee01"

SKILL = {
    "_id": SKILL_ID,
    "name": "match-stats-formatter",
    "title": "Match Stats Formatter",
    "description": "Formats raw match stats.",
    "status": "available",
    "domain": "https://github.com/machina-sports/machina-templates",
    "workflows": [{"name": "format-match-stats"}],
    "documents": [
        {"_id": DOC_1, "name": "skill-guide", "title": "Guide"},
        {"_id": DOC_2, "name": "examples", "title": "Examples"},
    ],
}
INSTRUCTION_ONLY = {"_id": "65f0c0ffee0000000000aa02", "name": "style-guide", "documents": []}
DOCS = {
    DOC_1: {"_id": DOC_1, "name": "skill-guide", "filetype": "markdown", "value": "# Guide"},
    DOC_2: {"_id": DOC_2, "name": "examples", "filetype": "json", "value": {"ok": True}},
}


def _ok(record):
    return {"status": "success", "message": "ok", "data": {"status": True, "data": record}}


def _missing():
    return {"status": "error", "message": "API call failed with status 404", "details": "nf"}


def build_pod(runs: dict | None = None, executed: list | None = None, missing_doc=None):
    pod = FastMCP(
        "machina-pod",
        streamable_http_path="/mcp",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    skills = {SKILL["name"]: SKILL, INSTRUCTION_ONLY["name"]: INSTRUCTION_ONLY}

    @pod.tool()
    async def get_skill_by_name(name: str, fields: list[str] | None = None) -> dict[str, Any]:
        return _ok(skills[name]) if name in skills else _missing()

    @pod.tool()
    async def get_skill(item_id: str, fields: list[str] | None = None) -> dict[str, Any]:
        match = [s for s in skills.values() if s["_id"] == item_id]
        return _ok(match[0]) if match else _missing()

    @pod.tool()
    async def get_document(item_id: str) -> dict[str, Any]:
        if item_id == missing_doc or item_id not in DOCS:
            return _missing()
        return _ok(DOCS[item_id])

    @pod.tool()
    async def execute_skill(
        messages: list[dict[str, Any]],
        skill_id: str | None = None,
        name: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if executed is not None:
            executed.append({"skill_id": skill_id, "messages": messages, "context": context})
        return {
            **_ok({"skill_run_id": RUN_ID, "task_id": "celery-1"}),
            "skill_run_id": RUN_ID,
        }

    @pod.tool()
    async def get_skill_execution(skill_run_id: str, compact: bool = True) -> dict[str, Any]:
        assert compact is False
        run = (runs or {}).get(skill_run_id)
        return _ok(run) if run else _missing()

    return pod


def _invoke(base, *args, cwd: Path | None = None):
    client = MagicMock()
    client.return_value.api_url = base
    with (
        patch("machina_cli.commands.mcp.get_config", return_value="proj_1"),
        patch("machina_cli.commands.mcp.ProjectClient", client),
        patch("machina_cli.config.resolve_auth_token", return_value=("X-Api-Token", GOOD_TOKEN)),
    ):
        return runner.invoke(app, ["skills", *args])


def test_show_returns_supplied_metadata_and_ordered_documents():
    with serve(build_pod().streamable_http_app()) as base:
        result = _invoke(base, "show", "match-stats-formatter", "--json")
    assert result.exit_code == 0, result.output
    skill = json.loads(result.output)["skill"]
    assert skill["id"] == SKILL_ID
    assert [d["id"] for d in skill["documents"]] == [DOC_1, DOC_2]
    assert skill["instruction_only"] is False
    # version/category weren't supplied: reported missing, never synthesised
    assert skill["version"] is None
    assert set(skill["missing"]) == {"version", "category"}
    assert GOOD_TOKEN not in result.output


def test_show_by_object_id_uses_get_skill():
    with serve(build_pod().streamable_http_app()) as base:
        result = _invoke(base, "show", SKILL_ID, "--json")
    assert json.loads(result.output)["skill"]["name"] == "match-stats-formatter"


def test_show_unknown_skill_is_typed_not_found():
    with serve(build_pod().streamable_http_app()) as base:
        result = _invoke(base, "show", "nope", "--json")
    assert result.exit_code == 1
    assert json.loads(result.output)["error_code"] == "not_found"


def test_docs_reads_documents_in_order():
    with serve(build_pod().streamable_http_app()) as base:
        result = _invoke(base, "docs", "match-stats-formatter", "--json")
    assert result.exit_code == 0, result.output
    docs = json.loads(result.output)["documents"]
    assert [d["name"] for d in docs] == ["skill-guide", "examples"]
    assert docs[0]["value"] == "# Guide"
    assert docs[1]["value"] == {"ok": True}


def test_docs_missing_reference_is_non_success():
    with serve(build_pod(missing_doc=DOC_2).streamable_http_app()) as base:
        result = _invoke(base, "docs", "match-stats-formatter", "--json")
    assert result.exit_code == 1
    docs = json.loads(result.output)["documents"]
    assert "error" in docs[1] and "value" not in docs[1]


def test_docs_instruction_skill_without_documents_is_non_success():
    with serve(build_pod().streamable_http_app()) as base:
        result = _invoke(base, "docs", "style-guide")
    assert result.exit_code == 1
    assert "supplies none" in result.output


def test_run_remote_is_submit_only_and_returns_run_id():
    executed: list = []
    with serve(build_pod(executed=executed).streamable_http_app()) as base:
        result = _invoke(
            base, "run", "match-stats-formatter", "team=PSG", "--remote", "-m", "go", "--json"
        )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["outcome"] == "accepted"  # never "completed" on submission
    assert payload["skill_run_id"] == RUN_ID
    assert payload["result_command"] == f"machina skills result {RUN_ID}"
    assert executed == [
        {
            "skill_id": SKILL_ID,
            "messages": [{"role": "user", "content": "go"}],
            "context": {
                "context-agent": {"team": "PSG", "messages": [{"role": "user", "content": "go"}]}
            },
        }
    ]


def test_run_remote_refuses_instruction_only_skill_without_executing():
    executed: list = []
    with serve(build_pod(executed=executed).streamable_http_app()) as base:
        result = _invoke(base, "run", "style-guide", "--remote", "--json")
    assert result.exit_code == 1
    assert json.loads(result.output)["error_code"] == "instruction_only"
    assert executed == []


def _result(runs, *extra):
    with serve(build_pod(runs=runs).streamable_http_app()) as base:
        return _invoke(base, "result", RUN_ID, "--json", *extra)


def test_result_completed_exits_zero_with_persisted_output():
    result = _result({RUN_ID: {"_id": RUN_ID, "status": "executed", "response": {"x": 1}}})
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["outcome"] == "completed"
    assert payload["execution"]["response"] == {"x": 1}


def test_result_failed_exits_one_with_error():
    result = _result({RUN_ID: {"_id": RUN_ID, "status": "failed", "error": "boom"}})
    assert result.exit_code == 1
    assert json.loads(result.output)["error"] == "boom"


def test_result_partial_exits_two():
    run = {"status": "executed", "completed_workflows": 1, "total_workflows": 3}
    result = _result({RUN_ID: run})
    assert result.exit_code == 2
    assert json.loads(result.output)["outcome"] == "partial"


def test_result_not_finished_exits_three():
    result = _result({RUN_ID: {"_id": RUN_ID, "status": "scheduled"}})
    assert result.exit_code == 3
    assert json.loads(result.output)["outcome"] == "accepted"


def test_result_server_outcome_field_wins():
    result = _result({RUN_ID: {"status": "executed", "outcome": "failed"}})
    assert result.exit_code == 1


def test_result_unknown_run_is_not_found():
    result = _result({})
    assert result.exit_code == 1
    assert json.loads(result.output)["error_code"] == "not_found"


# --- discovery never installs ------------------------------------------------


def test_read_paths_never_download_the_constructor(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with (
        patch("machina_cli.commands.skills._download_template_files") as download,
        patch("machina_cli.commands.skills.template.list_templates", return_value=None),
    ):
        runner.invoke(app, ["skills", "list"])
        runner.invoke(app, ["skills", "info", "skills/whatever"])
        runner.invoke(app, ["skills", "run", "whatever"])
    download.assert_not_called()
    assert not (tmp_path / "mkn-constructor").exists()
