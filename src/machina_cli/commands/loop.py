"""`machina loop` — drive the durable agentic turn loop (harness).

The loop runs server-side (the `loop-runner` agent + `harness_session` documents,
re-dispatched by the beat). These commands start sessions, stream their turns,
inject follow-up messages, and stop them. They mirror the `machina factory`
watch/logs ergonomics.

See docs/agentic-harness-loop.md for the architecture.
"""

import time

import typer
from rich.console import Console

from machina_cli.loop_client import DEFAULT_PERSONA, LoopClient

app = typer.Typer(help="Durable agentic turn loop (harness)")
console = Console()

# `idle` = the turn was answered and the session is awaiting the next user message
# (continue it with `machina loop say`). The others are end-of-life states.
TERMINAL_STATUSES = {"idle", "completed", "failed", "paused"}

_ROLE_STYLE = {
    "user": "bold cyan",
    "assistant": "bold green",
    "tool": "yellow",
}


def _render_entry(entry: dict) -> None:
    role = entry.get("role", "?")
    turn = entry.get("turn", "?")
    etype = entry.get("type", "message")
    style = _ROLE_STYLE.get(role, "white")

    if etype == "tool_call":
        args = entry.get("content", entry.get("args", ""))
        body = f"→ {entry.get('tool', '?')}({args})"
    elif etype == "tool_result":
        body = f"← {entry.get('content', '')}"
    else:
        body = entry.get("content", "")

    console.print(f"[dim]turn {turn}[/] [{style}]{role}[/] {body}")


def _watch(
    session_id: str,
    interval: int = 3,
    timeout: int = 1800,
    min_turn: int = 1,
    since_entries: int = 0,
) -> None:
    """Poll the session document, rendering new entries until the turn completes.

    `min_turn` guards against the async race where the session still shows the
    *previous* turn's terminal status: we only stop once `turn >= min_turn`.
    `since_entries` skips entries already shown (so a follow-up only prints the new turn).
    """
    client = LoopClient()
    elapsed = 0
    seen = since_entries
    last_status = None

    with console.status("running turns…", spinner="dots"):
        while elapsed < timeout:
            session = client.get_session(session_id) or {}
            entries = session.get("entries", [])
            for entry in entries[seen:]:
                _render_entry(entry)
            seen = len(entries)

            status = session.get("status")
            last_status = status or last_status
            if status in TERMINAL_STATUSES and session.get("turn", 0) >= min_turn:
                console.print(
                    f"\n[bold]{status}[/] · {session.get('turn', seen)} turns · {session_id}"
                )
                if status == "idle":
                    console.print(
                        f'[dim]Continue with[/] machina loop say {session_id} "<message>"'
                    )
                return

            time.sleep(interval)
            elapsed += interval

    console.print(
        f"\n[yellow]watch timed out[/] after {timeout}s "
        f"(last status: {last_status or 'unknown'}). Re-run `machina loop watch {session_id}`."
    )


@app.command()
def run(
    prompt: str = typer.Argument(..., help="The task / first user message for the loop"),
    persona: str = typer.Option(DEFAULT_PERSONA, "--persona", "-p", help="Reasoning persona (prompt) the runner uses"),
    watch: bool = typer.Option(False, "--watch", "-w", help="Stream turns until the session finishes"),
):
    """Start a new loop session."""
    session_id = LoopClient().start(prompt, persona_agent=persona)
    console.print(f"[green]session started[/] {session_id}")
    if watch:
        _watch(session_id, min_turn=1)
    else:
        console.print(f"[dim]Stream it with[/] machina loop watch {session_id}")


@app.command()
def watch(
    session_id: str = typer.Argument(..., help="Session id to stream"),
):
    """Stream a session's turns until it finishes."""
    _watch(session_id)


@app.command()
def say(
    session_id: str = typer.Argument(..., help="Session id to continue"),
    message: str = typer.Argument(..., help="The follow-up message to inject"),
    watch: bool = typer.Option(False, "--watch", "-w", help="Stream turns after injecting"),
):
    """Inject a follow-up user turn and re-activate the session."""
    client = LoopClient()
    prior = client.get_session(session_id) or {}
    prior_turn = prior.get("turn", 0)
    prior_entries = len(prior.get("entries", []))
    client.say(session_id, message)
    console.print("[green]queued[/]")
    if watch:
        _watch(session_id, min_turn=prior_turn + 1, since_entries=prior_entries)


@app.command()
def stop(
    session_id: str = typer.Argument(..., help="Session id to pause"),
):
    """Pause a running session."""
    LoopClient().stop(session_id)
    console.print(f"[yellow]stopped[/] {session_id}")


@app.command()
def sessions(
    limit: int = typer.Option(30, "--limit", "-n", help="Max sessions to list"),
):
    """List recent loop sessions."""
    rows = LoopClient().list_sessions(limit=limit)
    if not rows:
        console.print("[dim]No sessions yet.[/]")
        return
    for s in rows:
        status = s.get("status", "?")
        console.print(
            f"{s.get('session_id', '?'):32} "
            f"[bold]{status:10}[/] turn={s.get('turn', 0):<3} "
            f"[dim]{s.get('persona_agent', '')}[/]"
        )
