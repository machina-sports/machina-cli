"""Execution truth for agent and workflow runs (DX-04).

Maps each run record onto one outcome — accepted / running / completed /
failed / partial / unknown (plus `timeout` for a bounded wait that ran out) —
and gives every waiting command the same exit codes:

    0 completed   1 failed   2 partial   3 timeout / unknown / not finished

A server-supplied `outcome` field (client-api is adding it) always wins; the
mapping below is the fallback for today's server. Waiting is bounded and
polls only the one run id it was given. Nothing here ever resubmits.
"""

from __future__ import annotations

import time

import httpx

from machina_cli.project_client import ProjectClient

EXIT_CODES = {"completed": 0, "failed": 1, "partial": 2}
EXIT_UNKNOWN = 3
TERMINAL = {"completed", "failed", "partial"}

# Server cap for GET /execution/agent-run/<id>?wait= (core/execution/routes.py).
LONG_POLL_SECONDS = 25
WORKFLOW_POLL_SECONDS = 3

_AGENT_STATUS = {
    "agent-scheduled": "accepted",
    "agent-executing": "running",
    "agent-executed": "completed",
    "agent-streamed": "completed",
    "failed": "failed",
}
_WORKFLOW_STATUS = {
    "scheduled": "accepted",
    "executing": "running",
    "executed": "completed",
    "completed": "completed",
    # A workflow that declares `workflow-status: skipped` finished by its own decision.
    "skipped": "completed",
    "failed": "failed",
}


def exit_code(outcome: str) -> int:
    return EXIT_CODES.get(outcome, EXIT_UNKNOWN)


def agent_outcome(run: dict | None) -> str:
    if not isinstance(run, dict) or not run:
        return "unknown"
    if run.get("outcome"):
        return str(run["outcome"])
    outcome = _AGENT_STATUS.get(str(run.get("status") or ""), "unknown")
    if outcome == "completed":
        done, total = run.get("completed_workflows"), run.get("total_workflows")
        # A failed workflow does not fail the agent run; it makes it partial.
        if isinstance(done, int) and isinstance(total, int) and done < total:
            return "partial"
    return outcome


def workflow_outcome(run: dict | None) -> str:
    if not isinstance(run, dict) or not run:
        return "unknown"
    if run.get("outcome"):
        return str(run["outcome"])
    return _WORKFLOW_STATUS.get(str(run.get("status") or ""), "unknown")


class SubmissionUncertain(Exception):
    """The submit request timed out: the run may or may not exist."""


class PollFailed(Exception):
    """A status poll could not be completed (transport error)."""


def get_agent_run(client: ProjectClient, run_id: str, wait: float = 0) -> dict:
    path = f"execution/agent-run/{run_id}?compact=true"
    if wait > 0:
        path += f"&wait={wait:g}"
    try:
        # The server holds a long-poll up to `wait`s; give the read headroom.
        return client.get(path, timeout=wait + 15).get("data") or {}
    except httpx.TransportError as exc:
        raise PollFailed(f"polling agent run {run_id} failed ({type(exc).__name__})") from None


def get_workflow_run(client: ProjectClient, run_id: str) -> dict:
    try:
        return client.get(f"workflow/schedule/{run_id}").get("data") or {}
    except httpx.TransportError as exc:
        raise PollFailed(f"polling workflow run {run_id} failed ({type(exc).__name__})") from None


def wait_for(kind: str, client: ProjectClient, run_id: str, timeout: float) -> tuple[str, dict]:
    """Wait (bounded by `timeout`) for one run to reach a terminal outcome.

    Agent runs use the server long-poll; workflow runs poll every few seconds.
    Returns ("timeout", last_record) when the deadline passes first. Polling
    errors propagate — PollFailed for transport errors, ProjectAPIError for a
    rejected poll — they are never swallowed into "still running".
    """
    deadline = time.monotonic() + timeout
    run: dict = {}
    while True:
        remaining = deadline - time.monotonic()
        if kind == "agent":
            run = get_agent_run(client, run_id, wait=max(0.0, min(LONG_POLL_SECONDS, remaining)))
            outcome = agent_outcome(run)
        else:
            run = get_workflow_run(client, run_id)
            outcome = workflow_outcome(run)
        if outcome in TERMINAL:
            return outcome, run
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return "timeout", run
        if kind != "agent":
            time.sleep(min(WORKFLOW_POLL_SECONDS, remaining))


def submit(client: ProjectClient, path: str, body: dict, timeout: float | None = None) -> dict:
    """POST a run submission. A timeout here means the outcome is UNKNOWN —
    the server may have accepted it — so raise SubmissionUncertain and let the
    caller tell the user how to reconcile; never resubmit."""
    try:
        return client.post(path, body, timeout=timeout)
    except httpx.TimeoutException:
        raise SubmissionUncertain() from None


SCHEMA = "machina.execution/v1"


def uncertain(kind: str, json_output: bool):
    """Report an unknown submission outcome and exit 3 — never resubmit."""
    import json

    import typer

    from machina_cli.ui import console

    hint = f"machina {kind} executions" if kind == "agent" else "machina execution list"
    message = (
        f"submission may have run — check `{hint}` (or Studio) for a run started just now "
        "before retrying; it was not resubmitted"
    )
    if json_output:
        print(json.dumps({"schema": SCHEMA, "kind": kind, "outcome": "unknown", "error": message}))
    else:
        console.print(f"  [yellow]Outcome unknown:[/yellow] {message}")
    raise typer.Exit(EXIT_UNKNOWN)


def poll_failed(kind: str, run_id: str, exc: Exception, json_output: bool):
    """A status read failed after a successful submit: exit 3, never resubmit."""
    import json

    import typer

    from machina_cli.ui import console

    detail = getattr(exc, "message", None) or str(exc)
    message = f"status poll failed ({detail}); the run was submitted and not resubmitted"
    if json_output:
        print(
            json.dumps(
                {
                    "schema": SCHEMA,
                    "kind": kind,
                    "run_id": run_id,
                    "outcome": "unknown",
                    "error": message,
                    "result_command": _result_command(kind, run_id),
                }
            )
        )
    else:
        console.print(f"  [red]{message}[/red]")
        console.print(f"  [dim]Check with:[/dim] [bold]{_result_command(kind, run_id)}[/bold]")
    raise typer.Exit(EXIT_UNKNOWN)


def report(
    kind: str,
    mode: str,
    outcome: str,
    run_id: str,
    data: dict,
    run: dict | None,
    json_output: bool,
) -> int:
    """Print the outcome (JSON or console) and return the exit code.

    `mode` is submit / sync / wait. Submit-only is a successful exit with
    outcome "accepted" — the run is NOT complete; wait/sync exit by outcome.
    """
    import json

    from rich.panel import Panel

    from machina_cli.ui import console

    code = 0 if mode == "submit" else exit_code(outcome)
    status = (run or {}).get("status") or data.get("status")
    if json_output:
        payload = {
            **data,
            "schema": SCHEMA,
            "kind": kind,
            "mode": mode,
            "run_id": run_id,
            "outcome": outcome,
            "status": status,
            "result_command": _result_command(kind, run_id),
        }
        if run is not None:
            payload["run"] = run
        print(json.dumps(payload, default=str))
        return code

    color = {"completed": "green", "failed": "red", "partial": "yellow"}.get(outcome, "cyan")
    lines = [
        f"[bold]Outcome:[/bold] [{color}]{outcome}[/{color}]"
        + (f"  [dim]({status})[/dim]" if status else ""),
        f"[bold]{kind.capitalize()} Run ID:[/bold] {run_id}",
    ]
    record = run or {}
    if record.get("total_workflows") is not None:
        lines.append(
            f"[bold]Workflows:[/bold] {record.get('completed_workflows', 0)}/"
            f"{record.get('total_workflows')}"
        )
    if record.get("error"):
        lines.append(f"[bold]Error:[/bold] [red]{record['error']}[/red]")
    titles = {
        "submit": "Submitted — not completed",
        "timeout": "Still running — wait timed out",
    }
    title = titles.get(mode if mode == "submit" else outcome, f"{kind.capitalize()} run")
    console.print(Panel("\n".join(lines), title=title, border_style="#FF5C1F"))

    response = record.get("response") if kind == "agent" else None
    if response:
        from rich.syntax import Syntax

        formatted = json.dumps(response, indent=2, default=str, ensure_ascii=False)
        console.print(Panel(Syntax(formatted, "json", theme="monokai"), title="Response"))
    if mode == "submit" or outcome not in TERMINAL:
        console.print(f"  [dim]Track with:[/dim] [bold]{_result_command(kind, run_id)}[/bold]")
    return code


def _result_command(kind: str, run_id: str) -> str:
    flag = " --workflow" if kind == "workflow" else ""
    return f"machina execution get{flag} {run_id}"
