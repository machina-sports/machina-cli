"""Factory commands — trigger Machina Factory coding-agent jobs.

Factory takes a prompt, builds an app in a sandbox, and opens a PR. These
commands drive the customer surface (`customers.machina.gg/c/api/*`) using your
studio session — exactly like the web UI. Authenticate with `machina login`.

Examples:
    machina factory run "build a tactical match widget" --repo machina-sports/sports-skills
    machina factory run "workflow that posts goal alerts" --mode workflow --watch
    machina factory status <job-id>
    machina factory logs <job-id> --follow
    machina factory list
"""

import json as json_lib
import time

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from machina_cli.factory_client import FactoryClient

app = typer.Typer(help="Trigger Factory coding-agent jobs")
console = Console()

# Job lifecycle states (machina-factory-customers jobStatusEnum).
ACTIVE_STATUSES = {
    "queued",
    "paused",
    "provisioning",
    "running",
    "verifying",
    "committing",
    "deploying",
}
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}

VALID_MODES = ["skill", "connector", "workflow", "agent", "template"]


def _status_color(status: str) -> str:
    if status == "completed":
        return "green"
    if status in ("failed", "cancelled"):
        return "red"
    if status in ACTIVE_STATUSES:
        return "yellow"
    return "dim"


def _parse_repo(repo: str | None) -> dict | None:
    """`owner/name` → {owner, repo}. Errors clearly on a malformed value."""
    if not repo:
        return None
    if "/" not in repo:
        console.print(
            f"[red]Invalid --repo '{repo}'. Use owner/name (e.g. machina-sports/sports-skills).[/red]"
        )
        raise SystemExit(1)
    owner, name = repo.split("/", 1)
    return {"owner": owner.strip(), "repo": name.strip()}


@app.command("run")
def run(
    prompt: str = typer.Argument(..., help="What to build (natural language)"),
    repo: str | None = typer.Option(None, "--repo", "-r", help="Target repo as owner/name"),
    mode: str | None = typer.Option(
        None, "--mode", "-m", help=f"Category chip: {', '.join(VALID_MODES)}"
    ),
    project_id: str | None = typer.Option(None, "--project", "-p", help="Studio project ID"),
    watch_progress: bool = typer.Option(
        False, "--watch", "-w", help="Follow progress until the build finishes"
    ),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Kick off a new Factory build from a prompt."""
    if mode and mode not in VALID_MODES:
        console.print(
            f"[red]Invalid --mode '{mode}'. Choose one of: {', '.join(VALID_MODES)}.[/red]"
        )
        raise SystemExit(1)

    client = FactoryClient(project_id)

    body = {"prompt": prompt}
    if mode:
        body["mode"] = mode
    target = _parse_repo(repo)
    if target:
        body["target"] = target
    # Headless (api-key) mode: hand the server the client-api URL so it can
    # build pod credentials from the key. Ignored by the session path.
    if client.mode == "apikey" and client.client_api_url:
        body["clientApiUrl"] = client.client_api_url

    console.print()
    console.print(f"  [bold]Factory build:[/bold] [#FF5C1F]{prompt}[/#FF5C1F]")
    if target:
        console.print(f"  [dim]repo:[/dim] {target['owner']}/{target['repo']}")
    if mode:
        console.print(f"  [dim]mode:[/dim] {mode}")
    console.print()

    with console.status("  Submitting build..."):
        result = client.post("/c/api/projects", body)

    job_id = result.get("projectId") or result.get("jobId") or result.get("id", "")

    if json_output:
        console.print_json(json_lib.dumps(result, default=str))
        return

    console.print(
        Panel(
            f"[bold]Job ID:[/bold] {job_id}\n"
            f"[bold]Track:[/bold] machina factory status {job_id}\n"
            f"[bold]Logs:[/bold]  machina factory logs {job_id} --follow",
            title="Build Started",
            border_style="#FF5C1F",
        )
    )

    if watch_progress and job_id:
        _watch(client, job_id)


@app.command("status")
def status(
    job_id: str = typer.Argument(..., help="Job ID"),
    project_id: str | None = typer.Option(None, "--project", "-p", help="Studio project ID"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Show a job's status and its build chain (continuations, deploys)."""
    client = FactoryClient(project_id)
    chain = client.get(f"/c/api/jobs/{job_id}/chain")

    if json_output:
        console.print_json(json_lib.dumps(chain, default=str))
        return

    _render_chain(chain)


@app.command("watch")
def watch(
    job_id: str = typer.Argument(..., help="Job ID"),
    project_id: str | None = typer.Option(None, "--project", "-p", help="Studio project ID"),
):
    """Poll a job until it reaches a terminal status."""
    client = FactoryClient(project_id)
    _watch(client, job_id)


@app.command("logs")
def logs(
    job_id: str = typer.Argument(..., help="Job ID"),
    follow: bool = typer.Option(False, "--follow", "-f", help="Stream live progress (SSE)"),
    project_id: str | None = typer.Option(None, "--project", "-p", help="Studio project ID"),
):
    """Stream the live build timeline for a job."""
    client = FactoryClient(project_id)
    if not follow:
        # One-shot: show current chain status; the live timeline needs --follow.
        _render_chain(client.get(f"/c/api/jobs/{job_id}/chain"))
        console.print("\n  [dim]Use --follow to stream the live timeline.[/dim]")
        return

    icons = {"code": "✎", "shell": "$", "db": "▤", "image": "▦", "alert": "!"}
    for ev in client.stream(f"/c/api/stream/{job_id}"):
        kind = ev.get("kind")
        if kind == "agent":
            tone = "red" if ev.get("tone") == "error" else "white"
            console.print(f"  [{tone}]{ev.get('text', '').strip()}[/{tone}]")
        elif kind == "action":
            icon = icons.get(ev.get("icon", ""), "•")
            tone = "red" if ev.get("tone") == "error" else "cyan"
            console.print(f"  [{tone}]{icon}[/{tone}] [dim]{ev.get('label', '')}[/dim]")
        elif kind == "user":
            console.print(f"  [#FF5C1F]»[/#FF5C1F] {ev.get('text', '').strip()}")
        elif kind == "turn-divider":
            console.print(f"  [dim]── {ev.get('label', 'continuation')} ──[/dim]")
        elif kind == "status":
            preview = ev.get("preview", "")
            if preview == "error":
                console.print("  [red]Build reported an error.[/red]")
        elif kind == "done":
            console.print("  [dim]— stream closed —[/dim]")
            break


@app.command("follow-up")
def follow_up(
    job_id: str = typer.Argument(..., help="Parent job ID"),
    prompt: str = typer.Argument(..., help="What to change next"),
    project_id: str | None = typer.Option(None, "--project", "-p", help="Studio project ID"),
    watch_progress: bool = typer.Option(
        False, "--watch", "-w", help="Follow progress until finished"
    ),
):
    """Iterate on a finished build with a follow-up instruction."""
    client = FactoryClient(project_id)
    with console.status("  Submitting follow-up..."):
        result = client.post(f"/c/api/projects/{job_id}/follow-up", {"prompt": prompt})

    new_id = result.get("projectId") or result.get("jobId") or result.get("id", job_id)
    console.print(
        Panel(
            f"[bold]Continuation job:[/bold] {new_id}",
            title="Follow-up Started",
            border_style="#FF5C1F",
        )
    )
    if watch_progress and new_id:
        _watch(client, new_id)


@app.command("cancel")
def cancel(
    job_id: str = typer.Argument(..., help="Job ID"),
    project_id: str | None = typer.Option(None, "--project", "-p", help="Studio project ID"),
):
    """Cancel a running build."""
    client = FactoryClient(project_id)
    result = client.post(f"/c/api/projects/{job_id}/cancel")
    status_val = result.get("status", "cancelled")
    console.print(f"  [yellow]Job {job_id} → {status_val}[/yellow]")


@app.command("open-pr")
def open_pr(
    job_id: str = typer.Argument(..., help="Job ID"),
    project_id: str | None = typer.Option(None, "--project", "-p", help="Studio project ID"),
):
    """Open (or reveal) the pull request for a completed build."""
    client = FactoryClient(project_id)
    result = client.post(f"/c/api/jobs/{job_id}/open-pr")
    pr_url = result.get("prUrl", "")
    pr_number = result.get("prNumber", "")
    if pr_url:
        already = " [dim](already open)[/dim]" if result.get("alreadyOpen") else ""
        console.print(
            Panel(
                f"[bold]PR #{pr_number}:[/bold] {pr_url}{already}",
                title="Pull Request",
                border_style="#FF5C1F",
            )
        )
    else:
        console.print(f"  [yellow]No PR available yet for {job_id}.[/yellow]")


@app.command("list")
def list_jobs(
    project_id: str | None = typer.Option(None, "--project", "-p", help="Studio project ID"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """List your active and recent Factory builds."""
    client = FactoryClient(project_id)
    active = client.get("/c/api/projects/active").get("active", [])
    recent = client.get("/c/api/projects/recent").get("projects", [])

    if json_output:
        console.print_json(json_lib.dumps({"active": active, "recent": recent}, default=str))
        return

    if not active and not recent:
        console.print("[yellow]No Factory builds yet.[/yellow]")
        return

    if active:
        table = Table(title="Active builds")
        table.add_column("ID", style="dim")
        table.add_column("Repo")
        table.add_column("Task")
        table.add_column("Status")
        for j in active:
            st = j.get("status", "")
            table.add_row(
                j.get("id", ""),
                j.get("repo", ""),
                j.get("task", ""),
                f"[{_status_color(st)}]{st}[/{_status_color(st)}]",
            )
        console.print(table)

    if recent:
        table = Table(title="Recent builds")
        table.add_column("ID", style="dim")
        table.add_column("Repo")
        table.add_column("Task")
        table.add_column("Completed", style="dim")
        for j in recent:
            table.add_row(
                j.get("id", ""),
                j.get("repo", ""),
                j.get("task", ""),
                str(j.get("completedAt", "") or ""),
            )
        console.print(table)


@app.command("whoami")
def whoami(
    project_id: str | None = typer.Option(None, "--project", "-p", help="Studio project ID"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Show the studio identity Factory sees for you."""
    client = FactoryClient(project_id)
    me = client.get("/c/api/me")

    if json_output:
        console.print_json(json_lib.dumps(me, default=str))
        return

    # Recognized if Factory returned a uid (session) or an org (api-key).
    if not me.get("uid") and not me.get("organization"):
        console.print(
            "[yellow]Factory does not recognize you.[/yellow] Run [bold]machina login[/bold] (or set a valid project API key)."
        )
        return

    console.print(
        Panel.fit(
            f"[bold]Auth mode:[/bold] {me.get('authKind') or client.mode}\n"
            f"[bold]User ID:[/bold] {me.get('uid') or 'N/A (api-key)'}\n"
            f"[bold]Organization:[/bold] {me.get('organization', 'N/A')}\n"
            f"[bold]Project:[/bold] {me.get('projectNamespace', 'N/A')} ({me.get('projectId', 'N/A')})",
            title="Factory Identity",
            border_style="#FF5C1F",
        )
    )


# -- helpers ------------------------------------------------------------------


def _render_chain(chain: dict):
    """Render a chain payload (root/current/ancestors/descendants) as a table."""
    root = chain.get("root", {})
    current = chain.get("current", {})
    descendants = chain.get("descendants", [])

    nodes = []
    seen = set()
    for node in [root, *chain.get("ancestors", []), current, *descendants]:
        nid = node.get("id")
        if nid and nid not in seen:
            seen.add(nid)
            nodes.append(node)

    table = Table(title=f"Job chain · root {root.get('id', '')}")
    table.add_column("ID", style="dim")
    table.add_column("Origin")
    table.add_column("Task")
    table.add_column("Status")
    for node in nodes:
        st = node.get("status", "")
        marker = " [#FF5C1F]●[/#FF5C1F]" if node.get("id") == current.get("id") else ""
        table.add_row(
            (node.get("id", "") or "")[:18] + marker,
            node.get("origin", ""),
            (node.get("task", "") or "")[:60],
            f"[{_status_color(st)}]{st}[/{_status_color(st)}]",
        )
    console.print(table)


def _is_chain_active(chain: dict) -> bool:
    nodes = [chain.get("root", {}), chain.get("current", {}), *chain.get("descendants", [])]
    return any(n.get("status") in ACTIVE_STATUSES for n in nodes)


def _watch(client: FactoryClient, job_id: str, timeout: int = 1800):
    """Poll the job chain every few seconds until nothing is active."""
    console.print()
    last_line = ""
    elapsed = 0
    interval = 3
    with console.status("  Watching build...") as live:
        while elapsed < timeout:
            try:
                chain = client.get(f"/c/api/jobs/{job_id}/chain")
            except SystemExit:
                break
            current = chain.get("current", {})
            st = current.get("status", "")
            line = f"  {current.get('task', '')[:50]} → [{_status_color(st)}]{st}[/{_status_color(st)}]"
            if line != last_line:
                live.update(line)
                last_line = line
            if not _is_chain_active(chain):
                break
            time.sleep(interval)
            elapsed += interval

    console.print()
    final = client.get(f"/c/api/jobs/{job_id}/chain")
    _render_chain(final)

    # Surface the PR for a completed build (open-pr is idempotent).
    current = final.get("current", {})
    if current.get("status") == "completed":
        try:
            pr = client.post(f"/c/api/jobs/{job_id}/open-pr")
            if pr.get("prUrl"):
                console.print(
                    f"\n  [bold green]PR #{pr.get('prNumber', '')}:[/bold green] {pr['prUrl']}"
                )
        except SystemExit:
            pass
    elif elapsed >= timeout:
        console.print("  [yellow]Timed out watching. The build may still be running.[/yellow]")
