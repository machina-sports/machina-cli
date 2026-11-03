"""Tests for `machina agent|workflow create|update|delete --file` and the
ProjectClient error contract they depend on.

The fake Client API below reproduces the legacy controllers literally: failures
come back as HTTP 200 with {"status": false, "error": {...}} (agent/workflow
update/delete use `jsonify(result)`), updates are Mongo `$set`.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import httpx
import pytest
from typer.testing import CliRunner

from machina_cli.main import app
from machina_cli.project_client import ProjectAPIError, ProjectClient

runner = CliRunner()
REAL_CLIENT = httpx.Client
AGENT_ID = "65f0c0ffee0000000000ab01"


class FakeClientAPI:
    def __init__(self):
        self.store = {
            "agent": {
                AGENT_ID: {
                    "_id": AGENT_ID,
                    "name": "scout",
                    "title": "Scout",
                    "status": "inactive",
                    "context": {"config-frequency": 5},
                    "workflows": [{"name": "wf-a"}],
                }
            },
            # The workflow the agent above calls, so round trips stay valid.
            "workflow": {
                "65f0c0ffee0000000000ef00": {"_id": "65f0c0ffee0000000000ef00", "name": "wf-a"}
            },
        }
        self.requests: list[tuple[str, str, dict | None]] = []
        self.force: tuple[int, dict] | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        path = request.url.path.strip("/").split("/")
        self.requests.append((request.method, request.url.path, body))
        if self.force:
            status, payload = self.force
            return httpx.Response(status, json=payload)
        kind, rest = path[0], path[1:]
        items = self.store[kind]
        fail = {"status": False, "data": {}, "error": {"code": 400, "message": "Item not found"}}

        if request.method == "POST" and not rest:
            if any(i["name"] == body.get("name") for i in items.values()):
                return httpx.Response(
                    200,
                    json={"status": False, "error": {"message": f"{kind} already exists"}},
                )
            new_id = f"65f0c0ffee0000000000cd{len(items):02d}"
            items[new_id] = {"_id": new_id, **body}
            return httpx.Response(200, json={"status": True, "data": {"id": new_id}})
        if request.method == "GET":
            if rest[0] == "id":
                item = items.get(rest[1])
            else:
                item = next((i for i in items.values() if i["name"] == rest[0]), None)
            if not item:
                return httpx.Response(200, json=fail)
            return httpx.Response(200, json={"status": True, "data": item})
        if request.method == "PUT":
            if rest[0] not in items:
                return httpx.Response(200, json=fail)
            items[rest[0]].update(body)  # $set
            return httpx.Response(200, json={"status": True, "message": f"{kind} updated"})
        if request.method == "DELETE":
            if not items.pop(rest[0], None):
                return httpx.Response(200, json=fail)
            return httpx.Response(200, json={"status": True, "data": {"id": rest[0]}})
        return httpx.Response(405)


@pytest.fixture
def api():
    fake = FakeClientAPI()
    transport = httpx.MockTransport(fake.handler)
    with (
        patch(
            "machina_cli.project_client._get_project_session",
            return_value={"token": "t", "api_url": "https://acme.test", "direct_api_key": True},
        ),
        patch(
            "machina_cli.project_client.httpx.Client",
            side_effect=lambda **kw: REAL_CLIENT(transport=transport, **kw),
        ),
    ):
        yield fake


def _run(*args):
    return runner.invoke(app, [*args, "--project", "proj_1"])


def _file(tmp_path, data, name="body.json"):
    path = tmp_path / name
    path.write_text(json.dumps(data))
    return str(path)


# --- ProjectClient error contract --------------------------------------------


def test_status_false_in_http_200_is_a_failure(api):
    api.force = (200, {"status": False, "error": {"message": "Agent already exists"}})
    with pytest.raises(ProjectAPIError) as info:
        ProjectClient("proj_1").post("agent", {"name": "x"})
    assert info.value.code == "rejected"
    assert info.value.message == "Agent already exists"
    assert info.value.code != 0


def test_numeric_error_status_in_http_200_is_a_failure(api):
    # agent/executor/<name> answers {"status": 404, "message": "Item not found"} with HTTP 200
    api.force = (200, {"status": 404, "message": "Item not found"})
    with pytest.raises(ProjectAPIError) as info:
        ProjectClient("proj_1").post("agent/executor/ghost", {})
    assert info.value.message == "Item not found"


@pytest.mark.parametrize(
    ("status", "code"),
    [(400, "invalid_request"), (409, "conflict"), (422, "invalid_request"), (500, "server_error")],
)
def test_any_4xx_5xx_is_a_failure(api, status, code):
    api.force = (status, {"error": {"message": "nope", "details": ["name is required"]}})
    with pytest.raises(ProjectAPIError) as info:
        ProjectClient("proj_1").put("agent/x", {})
    assert info.value.code == code
    assert info.value.http_status == status
    assert isinstance(info.value, SystemExit) and info.value.code != 0


# --- create -------------------------------------------------------------------


def test_create_posts_file_and_prints_persisted_record(api, tmp_path):
    body = {"name": "new-agent", "title": "New", "workflows": []}
    result = _run("agent", "create", "--file", _file(tmp_path, body), "--json")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["operation"] == "created"
    assert payload["record"]["name"] == "new-agent"
    assert payload["record"]["_id"] == payload["id"]
    assert ("POST", "/agent", body) in api.requests
    assert api.requests[-1][0] == "GET"  # read back


def test_create_duplicate_exits_nonzero_with_structured_error(api, tmp_path):
    result = _run("agent", "create", "--file", _file(tmp_path, {"name": "scout"}), "--json")
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error_code"] == "rejected"
    assert "already exists" in payload["error"]


def test_create_requires_name(api, tmp_path):
    result = _run("workflow", "create", "--file", _file(tmp_path, {"title": "x"}), "--json")
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_code"] == "invalid_file"
    assert api.requests == []


def test_create_rejects_invalid_json(api, tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{nope")
    result = _run("agent", "create", "--file", str(path), "--json")
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_code"] == "invalid_file"


# --- update -------------------------------------------------------------------


def test_update_by_name_preserves_omitted_fields(api, tmp_path):
    result = _run(
        "agent", "update", "scout", "--file", _file(tmp_path, {"title": "Scout v2"}), "--json"
    )
    assert result.exit_code == 0, result.output
    record = json.loads(result.stdout)["record"]
    assert record["title"] == "Scout v2"
    assert record["context"] == {"config-frequency": 5}  # omitted → kept
    assert record["status"] == "inactive"
    put = [r for r in api.requests if r[0] == "PUT"]
    assert put == [("PUT", f"/agent/{AGENT_ID}", {"title": "Scout v2"})]


def test_update_round_trip_of_get_output_never_writes_lifecycle(api, tmp_path):
    current = dict(api.store["agent"][AGENT_ID])
    current.update({"title": "Edited", "created": "2026-01-01", "updated": "2026-01-02"})
    result = _run("agent", "update", AGENT_ID, "--file", _file(tmp_path, current), "--json")
    assert result.exit_code == 0, result.output
    _, _, sent = next(r for r in api.requests if r[0] == "PUT")
    assert not {"status", "_id", "created", "updated"} & set(sent)
    assert sent["title"] == "Edited"


def test_update_refuses_activation(api, tmp_path):
    result = _run(
        "agent", "update", "scout", "--file", _file(tmp_path, {"status": "active"}), "--json"
    )
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_code"] == "lifecycle_change_refused"
    assert not [r for r in api.requests if r[0] == "PUT"]
    assert api.store["agent"][AGENT_ID]["status"] == "inactive"


def test_update_refuses_mismatched_id(api, tmp_path):
    body = {"_id": "65f0c0ffee0000000000ffff", "title": "x"}
    result = _run("agent", "update", "scout", "--file", _file(tmp_path, body), "--json")
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_code"] == "id_mismatch"


def test_update_absent_record_exits_nonzero(api, tmp_path):
    result = _run("agent", "update", "ghost", "--file", _file(tmp_path, {"title": "x"}), "--json")
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"] == "Item not found"


def test_update_server_rejection_is_not_optimistic_success(api, tmp_path):
    original = api.handler

    def reject_put(request):
        if request.method == "PUT":
            return httpx.Response(
                200, json={"status": False, "error": {"message": "Exception when updating item"}}
            )
        return original(request)

    api.handler = reject_put  # type: ignore[method-assign]
    transport = httpx.MockTransport(reject_put)
    with patch(
        "machina_cli.project_client.httpx.Client",
        side_effect=lambda **kw: REAL_CLIENT(transport=transport, **kw),
    ):
        result = _run("agent", "update", "scout", "--file", _file(tmp_path, {"title": "x"}))
    assert result.exit_code == 1
    assert "updated:" not in result.output


# --- delete -------------------------------------------------------------------


def test_delete_requires_confirmation_in_json_mode(api):
    result = _run("agent", "delete", "scout", "--json")
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_code"] == "confirmation_required"
    assert AGENT_ID in api.store["agent"]


def test_delete_with_yes(api):
    result = _run("agent", "delete", "scout", "--yes", "--json")
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {
        "schema": "machina.config/v1",
        "resource": "agent",
        "operation": "deleted",
        "id": AGENT_ID,
        "record": None,
    }
    assert AGENT_ID not in api.store["agent"]


def test_delete_absent_record_exits_nonzero(api):
    result = _run("workflow", "delete", "ghost", "--yes", "--json")
    assert result.exit_code == 1


def test_delete_interactive_abort_keeps_record(api):
    result = runner.invoke(app, ["agent", "delete", "scout", "--project", "proj_1"], input="n\n")
    assert result.exit_code != 0
    assert AGENT_ID in api.store["agent"]


# --- references (DX-02: no dangling workflow/skill calls) ---------------------


def test_create_refuses_unknown_workflow_reference_without_writing(api, tmp_path):
    body = {
        "name": "fresh",
        "workflows": [{"name": "ghost-workflow"}, {"name": "ghost-skill", "type": "skill"}],
    }
    api.store["skill"] = {}
    result = _run("agent", "create", "--file", _file(tmp_path, body), "--json")
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error_code"] == "invalid_reference"
    assert "ghost-workflow" in payload["error"] and "ghost-skill" in payload["error"]
    assert not [r for r in api.requests if r[0] == "POST"]


def test_create_accepts_existing_references(api, tmp_path):
    body = {"name": "fresh", "workflows": [{"name": "wf-a"}]}
    result = _run("agent", "create", "--file", _file(tmp_path, body), "--json")
    assert result.exit_code == 0, result.output


def test_update_checks_new_references(api, tmp_path):
    body = {"workflows": [{"name": "not-there"}]}
    result = _run("agent", "update", "scout", "--file", _file(tmp_path, body), "--json")
    assert result.exit_code == 1
    assert json.loads(result.output)["error_code"] == "invalid_reference"
    assert not [r for r in api.requests if r[0] == "PUT"]
