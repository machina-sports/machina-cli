"""Organization management commands."""

import httpx
import typer
from rich.console import Console
from rich.table import Table

from machina_cli.client import MachinaClient
from machina_cli.config import get_config, set_config

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
    slug: str | None = typer.Option(
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


# Token usage is read from the permanent `organization_ledger` collection via
# core-api — the SAME source the Studio usage view uses — so totals cover the full
# window and match Studio. (Earlier versions summed per-project agent-execution
# `execution_tokens` via the Client-API; that collection is purged after a few days,
# so a "last 30d" scan really only summed the ~5 retained days and undercounted ~6x.)
#
# Headline + by-day come from the cheap paginated `.../usage` endpoint (page_size=1
# still returns full-window `totals` + `chart_data`). Per-project / per-agent
# breakdowns need the individual ledger rows, so they are fetched best-effort from
# `.../usage/export` (all rows in one unpaginated call); if that call fails or times
# out on a very large org, the headline and by-day are still exact and correct.


def _resolve_org_projects(org_id: str) -> dict:
    """Return {project_id: project_name} for the org's projects.

    Used only to render a readable project name in the by-project table; the token
    totals themselves come from the ledger, not from enumerating projects.
    """
    core = MachinaClient()
    names: dict = {}
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
            pid = proj.get("project_id") or proj.get("_id") or ""
            if not pid:
                continue
            names[pid] = proj.get("project_name") or proj.get("name") or f"(unnamed:{pid[:8]})"
        pagination = res.get("pagination", {})
        total = pagination.get("total", pagination.get("total_documents", 0))
        if not total or page * 100 >= total or len(rows) < 100:
            break
        page += 1
    return names


def _nullctx():
    """No-op context manager (so --json skips the spinner without duplicating logic)."""
    from contextlib import nullcontext

    return nullcontext()


@app.command()
def usage(
    org_id: str | None = typer.Option(
        None, "--org", "-o", help="Organization ID (uses default if omitted)"
    ),
    project_id: str | None = typer.Option(
        None, "--project", "-p", help="Limit to a single project"
    ),
    days: int = typer.Option(30, "--days", "-d", help="Rolling window: look back this many days"),
    month: str | None = typer.Option(
        None,
        "--month",
        "-m",
        help="Full calendar month YYYY-MM (e.g. 2026-06) — for invoicing. Overrides --days.",
    ),
    last_month: bool = typer.Option(
        False,
        "--last-month",
        help="Full previous calendar month (relative to today). Overrides --days.",
    ),
    top: int = typer.Option(10, "--top", help="Number of top agents to show"),
    limit: int | None = typer.Option(
        None,
        "--limit",
        "-l",
        hidden=True,
        help="Deprecated and ignored: the ledger returns the full window in one call.",
    ),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Aggregate LLM token consumption for an organization from the usage ledger.

    Reads the permanent `organization_ledger` via core-api — the same source the
    Studio usage view uses — so the total covers the full window and matches Studio.
    Broken down by project, agent, and day.
    """
    import calendar as _calendar
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
    # Window precedence: --month (explicit calendar month, for invoicing) >
    # --last-month (previous full calendar month) > --days (rolling). Calendar
    # months use inclusive first..last day; the server treats end_date as
    # end-of-day, so a month captures 00:00:00 day 1 .. 23:59:59 last day (UTC).
    if month:
        try:
            year, mon = (int(part) for part in str(month).split("-"))
            first = datetime(year, mon, 1, tzinfo=timezone.utc)
        except (ValueError, TypeError):
            console.print("[red]--month must be YYYY-MM (e.g. 2026-06).[/red]")
            raise typer.Exit(1)
        last_day = _calendar.monthrange(year, mon)[1]
        start_date = first.strftime("%Y-%m-%d")
        end_date = f"{year:04d}-{mon:02d}-{last_day:02d}"
        window_label = first.strftime("%B %Y")
    elif last_month:
        prev_end = datetime(now.year, now.month, 1, tzinfo=timezone.utc) - timedelta(days=1)
        last_day = _calendar.monthrange(prev_end.year, prev_end.month)[1]
        start_date = f"{prev_end.year:04d}-{prev_end.month:02d}-01"
        end_date = f"{prev_end.year:04d}-{prev_end.month:02d}-{last_day:02d}"
        window_label = prev_end.strftime("%B %Y")
    else:
        start_date = (now - timedelta(days=days)).strftime("%Y-%m-%d")
        end_date = now.strftime("%Y-%m-%d")
        window_label = f"last {days}d"

    window_body = {
        "filters": {},
        "start_date": start_date,
        "end_date": end_date,
        "sorters": ["_id", -1],
    }
    scope = "project" if project_id else "organization"
    scope_id = project_id or org_id

    client = MachinaClient()

    status_cm = (
        console.status(f"Fetching ledger usage (last {days}d)…", spinner="dots")
        if not json_output
        else _nullctx()
    )

    by_project: dict = defaultdict(lambda: {"prompt": 0, "completion": 0, "total": 0, "count": 0})
    by_agent: dict = defaultdict(lambda: {"prompt": 0, "completion": 0, "total": 0, "count": 0})
    by_day: dict = defaultdict(lambda: {"total": 0, "count": 0})
    breakdown_available = True
    has_unnamed = False

    with status_cm:
        # 1) Authoritative headline + by-day. `totals` and `chart_data` are computed
        #    server-side over the FULL window; page_size=1 only shrinks the HTTP
        #    response (the server still scans the whole window), so on a very large
        #    org this call can be slow — surface a timeout as an actionable message
        #    rather than an unhandled traceback.
        try:
            res = client.post(
                f"{scope}/{scope_id}/usage", {**window_body, "page": 1, "page_size": 1}
            )
        except httpx.HTTPError:
            console.print(
                f"[red]Usage query for this {scope} timed out or failed. "
                f"Try a narrower window with --days.[/red]"
            )
            raise typer.Exit(1)

        data = (res or {}).get("data", {}) or {}
        totals = data.get("totals", {}) or {}
        grand_prompt = int(totals.get("input", 0) or 0)
        grand_completion = int(totals.get("output", 0) or 0)
        grand_total = grand_prompt + grand_completion
        count = int((res or {}).get("pagination", {}).get("total_documents", 0) or 0)

        for entry in data.get("chart_data", []) or []:
            day = str(entry.get("timestamp") or "")[:10] or "unknown"
            by_day[day]["total"] += int(entry.get("input_tokens", 0) or 0) + int(
                entry.get("output_tokens", 0) or 0
            )
            by_day[day]["count"] += int(entry.get("count", 0) or 0)

        # 2) Best-effort by-project / by-agent from the (unpaginated) export. If it
        #    fails/times out on a large org, the headline + by-day above stay exact.
        #    The org and project export endpoints project token fields under DIFFERENT
        #    keys (org: input/output/pid; project: input_tokens/output_tokens/
        #    project_id), so read both shapes. Resolving project names is part of the
        #    same best-effort block: a failure there degrades the breakdown, it must
        #    not abort the already-computed headline.
        try:
            pid_names = {} if project_id else _resolve_org_projects(org_id)
            exp = client.post(f"{scope}/{scope_id}/usage/export", window_body, quiet=True)
            documents = ((exp or {}).get("data", {}) or {}).get("documents", []) or []
            for doc in documents:
                p = int(doc.get("input", doc.get("input_tokens", 0)) or 0)
                c = int(doc.get("output", doc.get("output_tokens", 0)) or 0)
                t = p + c
                raw_pid = doc.get("pid") or doc.get("project_id") or ""
                proj_label = pid_names.get(raw_pid, raw_pid or "(no project)")
                agent_label = doc.get("name") or "(unnamed)"
                if not doc.get("name"):
                    has_unnamed = True
                for bucket, key in ((by_project, proj_label), (by_agent, agent_label)):
                    b = bucket[key]
                    b["prompt"] += p
                    b["completion"] += c
                    b["total"] += t
                    b["count"] += 1
        except (SystemExit, httpx.HTTPError):
            breakdown_available = False

    grand = {
        "prompt": grand_prompt,
        "completion": grand_completion,
        "total": grand_total,
        "count": count,
    }

    if json_output:
        payload = {
            "organization_id": org_id,
            "project_id": project_id,
            "source": "organization_ledger",
            "window": {"from": start_date, "to": end_date, "label": window_label, "days": days},
            "totals": grand,
            "by_project": dict(sorted(by_project.items(), key=lambda kv: -kv[1]["total"])),
            "by_agent": dict(sorted(by_agent.items(), key=lambda kv: -kv[1]["total"])),
            "by_day": dict(sorted(by_day.items())),
            "breakdown_available": breakdown_available,
            # Retained for back-compat. Reading the central ledger has no per-project
            # scan, so these are always empty/false now (a failed read is a hard error).
            "incomplete": False,
            "projects_errored": [],
            "projects_skipped": [],
            "projects_truncated": [],
        }
        console.print_json(_json.dumps(payload, default=str))
        return

    if grand_total == 0:
        console.print(f"[yellow]No token usage in {window_label} for {scope} {scope_id}.[/yellow]")
        return

    prompt_pct = grand_prompt / grand_total * 100 if grand_total else 0
    completion_pct = grand_completion / grand_total * 100 if grand_total else 0
    avg = grand_total / count if count else 0

    from rich.panel import Panel

    scope_line = (
        f"[bold]Project:[/bold] {project_id}\n"
        if project_id
        else f"[bold]Organization:[/bold] {org_id}\n"
    )
    console.print(
        Panel.fit(
            scope_line + f"[bold]Window:[/bold] {window_label} ({start_date} → {end_date})\n"
            f"[bold]Total tokens:[/bold] {grand_total:,}\n"
            f"[bold]  input:[/bold] {grand_prompt:,} ({prompt_pct:.1f}%)   "
            f"[bold]output:[/bold] {grand_completion:,} ({completion_pct:.1f}%)\n"
            f"[bold]Metered calls:[/bold] {count:,}   "
            f"[bold]avg:[/bold] {avg:,.0f} tok/call\n"
            f"[dim]source: organization_ledger (matches Studio)[/dim]",
            title="Token consumption",
            border_style="#FF5C1F",
        )
    )

    if not breakdown_available:
        console.print(
            "[yellow]Note:[/yellow] per-project / per-agent breakdown unavailable "
            "(usage export failed or timed out); totals and by-day above are exact."
        )
    elif len(by_project) > 1:
        pt = Table(title="By project")
        pt.add_column("Project", style="bold")
        pt.add_column("Calls", justify="right", style="dim")
        pt.add_column("Total tokens", justify="right")
        pt.add_column("%", justify="right", style="dim")
        for pname, agg in sorted(by_project.items(), key=lambda kv: -kv[1]["total"]):
            pt.add_row(
                pname,
                f"{agg['count']:,}",
                f"{agg['total']:,}",
                f"{agg['total'] / grand_total * 100:.1f}%",
            )
        console.print(pt)

    if breakdown_available and by_agent:
        at = Table(title=f"Top {top} agents")
        at.add_column("Agent", style="bold")
        at.add_column("Calls", justify="right", style="dim")
        at.add_column("Total tokens", justify="right")
        at.add_column("Avg/call", justify="right", style="dim")
        at.add_column("%", justify="right", style="dim")
        for name, agg in sorted(by_agent.items(), key=lambda kv: -kv[1]["total"])[:top]:
            a_avg = agg["total"] / agg["count"] if agg["count"] else 0
            at.add_row(
                name,
                f"{agg['count']:,}",
                f"{agg['total']:,}",
                f"{a_avg:,.0f}",
                f"{agg['total'] / grand_total * 100:.1f}%",
            )
        console.print(at)

    if by_day:
        dt = Table(title="By day")
        dt.add_column("Day", style="bold")
        dt.add_column("Calls", justify="right", style="dim")
        dt.add_column("Total tokens", justify="right")
        for day, agg in sorted(by_day.items()):
            dt.add_row(day, f"{agg['count']:,}", f"{agg['total']:,}")
        console.print(dt)

    if breakdown_available and has_unnamed:
        console.print(
            "[dim]Note: the ledger includes non-LLM metered API calls (no agent name); "
            "these appear under '(unnamed)' / '(no project)'.[/dim]"
        )
