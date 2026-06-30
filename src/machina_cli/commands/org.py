"""Organization management commands."""

from contextlib import contextmanager
from typing import Optional

import httpx
import typer
from rich.console import Console
from rich.table import Table

from machina_cli.client import MachinaClient
from machina_cli.config import get_config, set_config
from machina_cli.project_client import ProjectClient

app = typer.Typer(help="Organization management")
console = Console()


@app.command("list")
def list_orgs(
    page: int = typer.Option(1, "--page", help="Page number"),
    page_size: int = typer.Option(20, "--limit", "-l", help="Items per page"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """List your organizations."""
    client = MachinaClient()
    result = client.post(
        "user/organizations/search",
        {
            "filters": {},
            "page": page,
            "page_size": page_size,
            "sorters": ["name", 1],
        },
    )

    orgs = result.get("data", [])
    default_org = get_config("default_organization_id")

    if json_output:
        import json

        console.print_json(json.dumps(orgs, default=str))
        return

    if not orgs:
        console.print("[yellow]No organizations found.[/yellow]")
        return

    table = Table(title="Organizations")
    table.add_column("ID", style="dim")
    table.add_column("Name")
    table.add_column("Slug")
    table.add_column("Status")
    table.add_column("Default", justify="center")

    for org in orgs:
        org_id = org.get("organization_id", org.get("_id", ""))
        is_default = "✦" if org_id == default_org else ""
        table.add_row(
            org_id,
            org.get("organization_name", org.get("name", "")),
            org.get("organization_slug", org.get("slug", "")),
            org.get("status", ""),
            is_default,
        )

    console.print(table)

    pagination = result.get("pagination", {})
    total = pagination.get("total", pagination.get("total_documents", 0))
    if total:
        console.print(f"\n  [dim]Page {page} ({len(orgs)} of {total} organizations)[/dim]")


@app.command()
def create(
    name: str = typer.Argument(..., help="Organization name"),
    slug: Optional[str] = typer.Option(
        None, "--slug", "-s", help="Organization slug (auto-generated if omitted)"
    ),
):
    """Create a new organization."""
    client = MachinaClient()

    # Generate slug if not provided
    if not slug:
        slug_result = client.post("organization/generate-slug", {"name": name})
        slug = slug_result.get("data", {}).get("slug", name.lower().replace(" ", "-"))

    result = client.post(
        "organization",
        {
            "name": name,
            "slug": slug,
            "status": "active",
        },
    )

    org_id = result.get("data", {}).get("id", "")
    console.print(f"[green]Organization created:[/green] {name} (ID: {org_id})")

    # Set as default if no default exists
    if not get_config("default_organization_id"):
        set_config("default_organization_id", org_id)
        console.print("Set as default organization.")


@app.command()
def use(
    org_id: str = typer.Argument(..., help="Organization ID to set as default"),
):
    """Set default organization."""
    set_config("default_organization_id", org_id)

    # Try to resolve org name for display and shell prompt
    try:
        client = MachinaClient()
        result = client.post(
            "user/organizations/search",
            {
                "filters": {},
                "page": 1,
                "page_size": 100,
                "sorters": ["name", 1],
            },
        )
        for org in result.get("data", []):
            if org.get("organization_id") == org_id:
                name = org.get("organization_name", "")
                if name:
                    set_config("default_organization_name", name)
                console.print(f"Default organization set to [bold]{name or org_id}[/bold]")
                return
    except Exception:
        pass

    console.print(f"Default organization set to [bold]{org_id}[/bold]")


# Token usage is recorded on AGENT executions (execution_tokens), not workflow
# executions. The Client-API `execution/agent-search` totals are page-level only, so
# we paginate and sum client-side. A frozen upper date bound keeps pagination stable
# as new executions arrive mid-scan.
_TOKEN_FILTER_KEY = "execution_tokens.total_tokens"
_SCAN_RETRIES = 3  # big collections (e.g. sbot-prd) 500 intermittently under load; retry recovers
_RETRY_BACKOFF = 0.8


class _ScanIncomplete(Exception):
    """A reachable project's scan kept failing after retries. Its tokens are missing,
    so the org total must be flagged PARTIAL — never silently dropped (that would turn
    a transient 500 on the biggest project into a plausible-looking but wrong total)."""


def _resolve_org_projects(org_id: str) -> list[tuple[str, str]]:
    """Return [(project_id, project_name)] for active projects in an organization."""
    core = MachinaClient()
    targets: list[tuple[str, str]] = []
    page = 1
    while True:
        res = core.post(
            "user/projects/search",
            {"filters": {}, "page": page, "page_size": 100, "sorters": ["name", 1]},
        )
        rows = res.get("data", [])
        if not rows:
            break
        for proj in rows:
            if proj.get("organization_id") != org_id:
                continue
            pid = proj.get("project_id", proj.get("_id", ""))
            pname = proj.get("project_name", proj.get("name", pid))
            if pid and proj.get("status") != "archived":
                targets.append((pid, pname))
        pagination = res.get("pagination", {})
        total = pagination.get("total", pagination.get("total_documents", 0))
        if not total or page * 100 >= total or len(rows) < 100:
            break
        page += 1
    return targets


def _sum_project_tokens(project_id: str, token_filter: dict, page_size: int, on_page=None):
    """Paginate a project's token-bearing agent executions, returning aggregates.

    Returns (project_totals, by_agent, by_day, truncated). Raises SystemExit (via
    ProjectClient) on auth/connection failure — callers should catch and skip.
    `on_page(count, total_tokens)` is invoked after each page for progress display.
    """
    import time
    from collections import defaultdict
    from email.utils import parsedate_to_datetime

    def _retry(fn, *, tries, incomplete_on_fail):
        # Retry transient failures: ProjectClient raises SystemExit on a 500, httpx
        # raises on a timeout. On give-up, either re-raise (caller skips an undeployed
        # project) or raise _ScanIncomplete (caller flags a reachable project's partial
        # scan loudly instead of silently dropping it).
        last = None
        for attempt in range(tries):
            try:
                return fn()
            except (SystemExit, httpx.HTTPError) as exc:
                last = exc
                if attempt == tries - 1:
                    if incomplete_on_fail:
                        raise _ScanIncomplete(project_id) from last
                    raise
                time.sleep(_RETRY_BACKOFF * (attempt + 1))

    # Project session. A persistent failure means undeployed/no-access — let it
    # propagate so the caller records a benign skip.
    client = _retry(lambda: ProjectClient(project_id), tries=2, incomplete_on_fail=False)
    proj = {"prompt": 0, "completion": 0, "total": 0, "count": 0}
    by_agent: dict = defaultdict(lambda: {"prompt": 0, "completion": 0, "total": 0, "count": 0})
    by_day: dict = defaultdict(lambda: {"total": 0, "count": 0})

    page = 1
    max_pages = 400  # safety net; the `total` check below normally breaks first
    truncated = False
    while True:
        # The search on a reachable project: a persistent failure (e.g. sbot-prd's
        # heavy collection 500ing) means the scan is INCOMPLETE, not skippable.
        res = _retry(
            lambda: client.post(
                "execution/agent-search",
                {
                    "filters": token_filter,
                    "page": page,
                    "page_size": page_size,
                    "sorters": ["_id", -1],
                },
            ),
            tries=_SCAN_RETRIES,
            incomplete_on_fail=True,
        )
        rows = res.get("data", [])
        if not rows:
            break
        for ex in rows:
            tk = ex.get("execution_tokens") or {}
            p = int(tk.get("prompt_tokens") or 0)
            c = int(tk.get("completion_tokens") or 0)
            t = int(tk.get("total_tokens") or 0)
            proj["prompt"] += p
            proj["completion"] += c
            proj["total"] += t
            proj["count"] += 1
            name = ex.get("name") or "(unnamed)"
            a = by_agent[name]
            a["prompt"] += p
            a["completion"] += c
            a["total"] += t
            a["count"] += 1
            try:
                day = parsedate_to_datetime(ex.get("date", "")).strftime("%Y-%m-%d")
            except Exception:
                day = "unknown"
            by_day[day]["total"] += t
            by_day[day]["count"] += 1

        if on_page is not None:
            on_page(proj["count"], proj["total"])

        pagination = res.get("pagination", {})
        total = (
            pagination.get("total")
            or pagination.get("total_documents")
            or res.get("total_documents")
            or 0
        )
        if total and page * page_size >= total:
            break
        if len(rows) < page_size:
            break
        page += 1
        if page > max_pages:
            truncated = True
            break
    return proj, dict(by_agent), dict(by_day), truncated


@app.command()
def usage(
    org_id: Optional[str] = typer.Option(
        None, "--org", "-o", help="Organization ID (uses default if omitted)"
    ),
    project_id: Optional[str] = typer.Option(
        None, "--project", "-p", help="Limit to a single project (skip org-wide scan)"
    ),
    days: int = typer.Option(30, "--days", "-d", help="Look back this many days"),
    page_size: int = typer.Option(500, "--limit", "-l", help="Executions fetched per request"),
    top: int = typer.Option(10, "--top", help="Number of top agents to show"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Aggregate LLM token consumption across an organization's agent executions.

    Sums `execution_tokens` over agent runs from the last N days, broken down by
    project, agent, and day. Token usage is recorded on agent executions (not
    workflow executions), so this is the authoritative source for "how many tokens
    did this org consume".
    """
    import json as _json
    from collections import defaultdict
    from datetime import datetime, timedelta, timezone

    org_id = org_id or get_config("default_organization_id")
    if not org_id and not project_id:
        console.print(
            "[red]No organization specified. Use --org or set default with `machina org use`.[/red]"
        )
        raise typer.Exit(1)

    now = datetime.now(timezone.utc)
    date_from = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    date_to = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    token_filter = {
        _TOKEN_FILTER_KEY: {"$gt": 0},
        "date": {"$gte": date_from, "$lt": date_to},
    }

    if project_id:
        targets = [(project_id, project_id)]
    else:
        targets = _resolve_org_projects(org_id)

    if not targets:
        if json_output:
            print(_json.dumps({"error": "no projects found", "organization_id": org_id}))
            raise typer.Exit(1)
        console.print(f"[yellow]No projects found for organization {org_id}.[/yellow]")
        raise typer.Exit(1)

    grand = {"prompt": 0, "completion": 0, "total": 0, "count": 0}
    by_project: dict = {}
    by_agent: dict = defaultdict(lambda: {"prompt": 0, "completion": 0, "total": 0, "count": 0})
    by_day: dict = defaultdict(lambda: {"total": 0, "count": 0})
    skipped: list[str] = []  # undeployed / no access — expected, excluded
    errored: list[str] = []  # reachable but scan failed after retries — total is PARTIAL
    truncated_projects: list[str] = []

    status_cm = (
        console.status(f"Scanning {len(targets)} project(s)…", spinner="dots")
        if not json_output
        else _nullctx()
    )
    n = len(targets)
    # _quiet_clients silences the core/project HTTP clients: undeployed or
    # inaccessible projects print a red error and raise SystemExit, which we catch
    # and record as skipped/errored — the leaked error would just be noise mid-scan.
    with status_cm as status, _quiet_clients():
        for i, (pid, pname) in enumerate(targets, 1):

            def _progress(count, tok, _i=i, _name=pname):
                if status is not None:
                    status.update(f"[{_i}/{n}] {_name} — {count:,} execs, {tok:,} tokens…")

            if status is not None:
                status.update(f"[{i}/{n}] {pname}…")
            try:
                proj, p_agents, p_days, truncated = _sum_project_tokens(
                    pid, token_filter, page_size, on_page=_progress
                )
            except _ScanIncomplete:
                # reachable project whose search kept failing — its tokens are MISSING,
                # so the org total is partial (flagged loudly below), not silently dropped.
                errored.append(pname)
                continue
            except (SystemExit, httpx.HTTPError):
                # login/lookup failed after retries -> undeployed or no access; expected.
                skipped.append(pname)
                continue
            if proj["count"] == 0:
                continue
            by_project[pname] = proj
            for k in grand:
                grand[k] += proj[k]
            for name, agg in p_agents.items():
                tgt = by_agent[name]
                for k in tgt:
                    tgt[k] += agg[k]
            for day, agg in p_days.items():
                by_day[day]["total"] += agg["total"]
                by_day[day]["count"] += agg["count"]
            if truncated:
                truncated_projects.append(pname)

    if json_output:
        payload = {
            "organization_id": org_id,
            "window": {"from": date_from, "to": date_to, "days": days},
            "totals": grand,
            "by_project": by_project,
            "by_agent": dict(sorted(by_agent.items(), key=lambda kv: -kv[1]["total"])),
            "by_day": dict(sorted(by_day.items())),
            "incomplete": bool(errored),
            "projects_errored": errored,
            "projects_skipped": skipped,
            "projects_truncated": truncated_projects,
        }
        console.print_json(_json.dumps(payload, default=str))
        return

    if grand["count"] == 0:
        if errored:
            console.print(
                f"[bold red]⚠ {len(errored)} project(s) failed to scan: "
                f"{', '.join(errored)} — re-run to retry (results would be partial).[/bold red]"
            )
        else:
            console.print(
                f"[yellow]No token-bearing agent executions in the last {days} day(s) "
                f"for organization {org_id}.[/yellow]"
            )
        if skipped:
            console.print(f"[dim]Skipped (undeployed/no access): {', '.join(skipped)}[/dim]")
        return

    total = grand["total"]
    prompt_pct = grand["prompt"] / total * 100 if total else 0
    completion_pct = grand["completion"] / total * 100 if total else 0
    avg = total / grand["count"] if grand["count"] else 0

    from rich.panel import Panel

    if errored:
        console.print(
            f"[bold red]⚠ INCOMPLETE — {len(errored)} reachable project(s) failed to scan "
            f"and are NOT in the totals below:[/bold red] {', '.join(errored)}\n"
            f"[red]The numbers below are PARTIAL. Re-run to retry those projects.[/red]\n"
        )
    total_label = "Total tokens (PARTIAL):" if errored else "Total tokens:"

    console.print(
        Panel.fit(
            f"[bold]Organization:[/bold] {org_id}\n"
            f"[bold]Window:[/bold] last {days}d ({date_from[:10]} → {date_to[:10]})\n"
            f"[bold]{total_label}[/bold] {total:,}\n"
            f"[bold]  prompt:[/bold] {grand['prompt']:,} ({prompt_pct:.1f}%)   "
            f"[bold]completion:[/bold] {grand['completion']:,} ({completion_pct:.1f}%)\n"
            f"[bold]Executions:[/bold] {grand['count']:,}   "
            f"[bold]avg:[/bold] {avg:,.0f} tok/exec",
            title="Token consumption",
            border_style="#FF5C1F",
        )
    )

    if len(by_project) > 1:
        pt = Table(title="By project")
        pt.add_column("Project", style="bold")
        pt.add_column("Executions", justify="right", style="dim")
        pt.add_column("Total tokens", justify="right")
        pt.add_column("%", justify="right", style="dim")
        for pname, agg in sorted(by_project.items(), key=lambda kv: -kv[1]["total"]):
            pt.add_row(
                pname,
                f"{agg['count']:,}",
                f"{agg['total']:,}",
                f"{agg['total'] / total * 100:.1f}%",
            )
        console.print(pt)

    at = Table(title=f"Top {top} agents")
    at.add_column("Agent", style="bold")
    at.add_column("Executions", justify="right", style="dim")
    at.add_column("Total tokens", justify="right")
    at.add_column("Avg/exec", justify="right", style="dim")
    at.add_column("%", justify="right", style="dim")
    for name, agg in sorted(by_agent.items(), key=lambda kv: -kv[1]["total"])[:top]:
        a_avg = agg["total"] / agg["count"] if agg["count"] else 0
        at.add_row(
            name,
            f"{agg['count']:,}",
            f"{agg['total']:,}",
            f"{a_avg:,.0f}",
            f"{agg['total'] / total * 100:.1f}%",
        )
    console.print(at)

    dt = Table(title="By day")
    dt.add_column("Day", style="bold")
    dt.add_column("Executions", justify="right", style="dim")
    dt.add_column("Total tokens", justify="right")
    for day, agg in sorted(by_day.items()):
        dt.add_row(day, f"{agg['count']:,}", f"{agg['total']:,}")
    console.print(dt)

    if errored:
        console.print(
            f"\n[bold red]⚠ Excluded (scan failed): {', '.join(errored)} — totals are PARTIAL; "
            "re-run to retry.[/bold red]"
        )
    if skipped:
        console.print(f"[dim]Skipped (undeployed/no access): {', '.join(skipped)}[/dim]")
    if truncated_projects:
        console.print(
            f"[yellow]Note:[/yellow] hit the page cap for {', '.join(truncated_projects)} — "
            "totals may be partial; narrow with --days."
        )


def _nullctx():
    """No-op context manager (so --json skips the spinner without duplicating logic)."""
    from contextlib import nullcontext

    return nullcontext()


@contextmanager
def _quiet_clients():
    """Silence the core/project HTTP clients' console for the duration of a scan.

    `MachinaClient` and `ProjectClient` print to a module-level stderr Console and
    raise SystemExit on a failed project session. During an org-wide scan those
    failures are expected (undeployed/inaccessible projects) and handled by the
    caller, so swap in a quiet console and restore it afterward.
    """
    from rich.console import Console as _Console

    import machina_cli.client as _client_mod
    import machina_cli.project_client as _project_mod

    saved = (_client_mod.console, _project_mod.console)
    quiet = _Console(quiet=True)
    _client_mod.console = quiet
    _project_mod.console = quiet
    try:
        yield
    finally:
        _client_mod.console, _project_mod.console = saved
