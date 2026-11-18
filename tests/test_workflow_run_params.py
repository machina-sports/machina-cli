"""`machina workflow run <name> key=value` must deliver the params as the workflow's inputs.

client-api's /workflow/execute/<name> and /workflow/schedule/<name> take the JSON body and use it
as the run's "context-workflow" (core/workflow/routes.py), so the CLI must send the inputs at the
top level. Sending {"context-workflow": {...}} nested them and every input arrived as None.
"""

from __future__ import annotations

import json

from machina_cli.main import app
from tests.test_execution_truth import WF_RUN, api, runner  # noqa: F401  (fixture)


def _run(*args):
    return runner.invoke(app, ["workflow", "run", "wf", "--project", "p", "--json", *args])


def _post_body(fake, path):
    reqs = [r for r in fake.posts() if r.url.path == path]
    assert reqs, f"no POST to {path}"
    return json.loads(reqs[-1].content or b"{}")


def test_sync_sends_params_as_top_level_inputs(api):  # noqa: F811
    api.submit = (200, {"status": True, "data": {"workflow_run_id": WF_RUN}})
    api.workflow_runs = [{"status": "executed"}]
    _run("team=50", "last=2", "live=true", "season=sr:season:1")
    body = _post_body(api, "/workflow/execute/wf")
    assert body == {"team": 50, "last": 2, "live": True, "season": "sr:season:1"}
    assert "context-workflow" not in body


def test_async_sends_params_as_top_level_inputs(api):  # noqa: F811
    api.submit = (200, {"status": True, "data": {"workflow_run_id": WF_RUN}})
    _run("--async", "search=Haaland")
    assert _post_body(api, "/workflow/schedule/wf") == {"search": "Haaland"}


def test_no_params_sends_an_empty_object(api):  # noqa: F811
    api.submit = (200, {"status": True, "data": {"workflow_run_id": WF_RUN}})
    api.workflow_runs = [{"status": "executed"}]
    _run()
    assert _post_body(api, "/workflow/execute/wf") == {}
