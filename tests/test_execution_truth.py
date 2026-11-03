"""DX-04 execution truth: submit-only vs wait, outcome exit codes, no blind
resubmission, polling errors surfaced, `execution get --workflow`.

The fake Client API returns the shapes today's server returns
(core/agent/executor.py, core/workflow/executor.py, core/execution/routes.py).
"""

from __future__ import annotations

import json
from unittest.mock import patch

import httpx
import pytest
from typer.testing import CliRunner

from machina_cli import execution_outcome
from machina_cli.main import app

runner = CliRunner()
REAL_CLIENT = httpx.Client
RUN = "65f0c0ffee0000000000ee01"
WF_RUN = "65f0c0ffee0000000000ff01"


class FakeAPI:
    def __init__(self):
        self.agent_runs: list[dict] = []  # successive GET agent-run answers
        self.workflow_runs: list[dict] = []
        self.submit: tuple[int, dict] | Exception = (
            200,
            {"status": True, "data": {"agent_run_id": RUN, "task_id": "t1"}},
        )
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.method == "GET" and path.startswith("/agent/"):
            return httpx.Response(200, json={"status": True, "data": {"name": "scout"}})
        if request.method == "GET" and path.startswith("/workflow/") and "schedule" not in path:
            return httpx.Response(200, json={"status": True, "data": {"name": "wf"}})
        if request.method == "POST":
            if isinstance(self.submit, Exception):
                raise self.submit
            status, body = self.submit
            return httpx.Response(status, json=body)
        if path == f"/execution/agent-run/{RUN}":
            run = self.agent_runs.pop(0) if len(self.agent_runs) > 1 else self.agent_runs[0]
            if isinstance(run, tuple):
                return httpx.Response(run[0], json=run[1])
            return httpx.Response(200, json={"status": True, "data": run})
        if path == f"/workflow/schedule/{WF_RUN}":
            run = (
                self.workflow_runs.pop(0) if len(self.workflow_runs) > 1 else self.workflow_runs[0]
            )
            return httpx.Response(200, json={"status": True, "data": run})
        return httpx.Response(404, json={"error": {"message": "nope"}})

    def posts(self):
        return [r for r in self.requests if r.method == "POST"]


@pytest.fixture
def api():
    fake = FakeAPI()
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
        patch("machina_cli.execution_outcome.time.sleep"),
    ):
        yield fake


def _agent(*args):
    return runner.invoke(app, ["agent", "run", "scout", "--project", "p", "--json", *args])


def _payload(result):
    return json.loads(result.stdout)


# --- outcome mapping -----------------------------------------------------------


@pytest.mark.parametrize(
    ("run", "outcome"),
    [
        ({"status": "agent-scheduled"}, "accepted"),
        ({"status": "agent-executing"}, "running"),
        ({"status": "agent-executed", "completed_workflows": 2, "total_workflows": 2}, "completed"),
        ({"status": "agent-executed", "completed_workflows": 1, "total_workflows": 3}, "partial"),
        ({"status": "failed"}, "failed"),
        ({"status": "weird"}, "unknown"),
        ({}, "unknown"),
        ({"status": "agent-executed", "outcome": "failed"}, "failed"),  # server field wins
    ],
)
def test_agent_outcome_mapping(run, outcome):
    assert execution_outcome.agent_outcome(run) == outcome


@pytest.mark.parametrize(
    ("run", "outcome"),
    [
        ({"status": "scheduled"}, "accepted"),
        ({"status": "executing"}, "running"),
        ({"status": "executed"}, "completed"),
        ({"status": "skipped"}, "completed"),
        ({"status": "failed"}, "failed"),
        ({"status": "something-custom"}, "unknown"),
    ],
)
def test_workflow_outcome_mapping(run, outcome):
    assert execution_outcome.workflow_outcome(run) == outcome


# --- agent run -------------------------------------------------------------------


def test_submit_only_is_accepted_not_completed(api):
    result = _agent()
    assert result.exit_code == 0, result.output
    payload = _payload(result)
    assert payload["outcome"] == "accepted"
    assert payload["mode"] == "submit"
    assert payload["run_id"] == RUN
    assert payload["result_command"] == f"machina execution get {RUN}"
    assert not [r for r in api.requests if "/execution/" in r.url.path]  # no polling


def test_wait_long_polls_until_completed(api):
    api.agent_runs = [
        {"status": "agent-executing"},
        {"status": "agent-executed", "completed_workflows": 2, "total_workflows": 2},
    ]
    result = _agent("--wait")
    assert result.exit_code == 0, result.output
    assert _payload(result)["outcome"] == "completed"
    polls = [r for r in api.requests if "/execution/agent-run/" in r.url.path]
    assert len(polls) == 2
    assert all(r.url.params["wait"] == "25" for r in polls)
    assert all(r.url.params["compact"] == "true" for r in polls)


@pytest.mark.parametrize(
    ("run", "code", "outcome"),
    [
        ({"status": "failed", "error": "boom"}, 1, "failed"),
        (
            {"status": "agent-executed", "completed_workflows": 1, "total_workflows": 3},
            2,
            "partial",
        ),
    ],
)
def test_wait_exit_codes(api, run, code, outcome):
    api.agent_runs = [run]
    result = _agent("--watch")
    assert result.exit_code == code
    assert _payload(result)["outcome"] == outcome


def test_wait_timeout_exits_three(api):
    api.agent_runs = [{"status": "agent-executing"}]
    result = _agent("--wait", "--timeout", "0.01")
    assert result.exit_code == 3
    assert _payload(result)["outcome"] == "timeout"


def test_sync_reports_the_persisted_outcome_not_a_hardcoded_completed(api):
    api.submit = (
        200,
        {"status": True, "data": {"agent_run_id": RUN, "status": "agent-executed"}},
    )
    api.agent_runs = [{"status": "failed", "error": "workflow crashed"}]
    result = _agent("--sync")
    assert result.exit_code == 1
    payload = _payload(result)
    assert payload["outcome"] == "failed"
    assert payload["run"]["error"] == "workflow crashed"


def test_sync_console_never_says_complete_on_failure(api):
    api.agent_runs = [{"status": "failed"}]
    result = runner.invoke(app, ["agent", "run", "scout", "--project", "p", "--sync"])
    assert result.exit_code == 1
    assert "completed" not in result.output.lower()


def test_submit_timeout_is_unknown_and_never_resubmitted(api):
    api.submit = httpx.ReadTimeout("slow")
    result = _agent()
    assert result.exit_code == 3
    payload = _payload(result)
    assert payload["outcome"] == "unknown"
    assert "submission may have run" in payload["error"]
    assert len(api.posts()) == 1


def test_status_false_on_submission_fails(api):
    api.submit = (200, {"status": False, "error": {"message": "agent is inactive"}})
    result = _agent()
    assert result.exit_code == 1


def test_polling_error_is_surfaced_not_swallowed(api):
    api.agent_runs = [(500, {"error": {"message": "db down"}})]
    result = _agent("--watch")
    assert result.exit_code == 3
    payload = _payload(result)
    assert payload["outcome"] == "unknown"
    assert "db down" in payload["error"]
    assert len(api.posts()) == 1  # never resubmitted


def test_json_stdout_is_one_document(api):
    result = runner.invoke(app, ["agent", "run", "scout", "k=v", "--project", "p", "--json"])
    json.loads(result.stdout)  # no "Running agent" banner mixed in


# --- workflow run ------------------------------------------------------------------


def _workflow(*args):
    return runner.invoke(app, ["workflow", "run", "wf", "--project", "p", "--json", *args])


def test_workflow_sync_failure_masked_by_execute_response_is_reported_failed(api):
    # workflow_executor answers status True + {workflow_run_id} even when the run failed.
    api.submit = (200, {"status": True, "data": {"workflow_run_id": WF_RUN}})
    api.workflow_runs = [{"_id": WF_RUN, "status": "failed"}]
    result = _workflow()
    assert result.exit_code == 1
    assert _payload(result)["outcome"] == "failed"


def test_workflow_async_is_submit_only(api):
    api.submit = (200, {"status": True, "data": {"workflow_run_id": WF_RUN}})
    result = _workflow("--async")
    assert result.exit_code == 0
    payload = _payload(result)
    assert payload["outcome"] == "accepted"
    assert payload["result_command"] == f"machina execution get --workflow {WF_RUN}"


def test_workflow_async_wait_polls_until_done(api):
    api.submit = (200, {"status": True, "data": {"workflow_run_id": WF_RUN}})
    api.workflow_runs = [{"status": "scheduled"}, {"status": "executing"}, {"status": "executed"}]
    result = _workflow("--async", "--wait")
    assert result.exit_code == 0, result.output
    assert _payload(result)["outcome"] == "completed"


def test_workflow_wait_timeout_exits_three(api):
    api.submit = (200, {"status": True, "data": {"workflow_run_id": WF_RUN}})
    api.workflow_runs = [{"status": "executing"}]
    result = _workflow("--async", "--watch", "--timeout", "0.01")
    assert result.exit_code == 3


# --- execution get ------------------------------------------------------------------


def test_execution_get_workflow_reads_the_workflow_run(api):
    api.workflow_runs = [{"_id": WF_RUN, "status": "executed", "outputs": {"x": 1}}]
    result = runner.invoke(
        app, ["execution", "get", "--workflow", WF_RUN, "--project", "p", "--json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["outcome"] == "completed"
    assert any(r.url.path == f"/workflow/schedule/{WF_RUN}" for r in api.requests)
    assert not any("/execution/agent-run/" in r.url.path for r in api.requests)


def test_execution_get_agent_includes_outcome(api):
    api.agent_runs = [{"_id": RUN, "status": "agent-executed"}]
    result = runner.invoke(app, ["execution", "get", RUN, "--project", "p", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["outcome"] == "completed"
