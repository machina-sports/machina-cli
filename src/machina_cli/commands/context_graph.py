"""Context Graph — self-healing / monitoring status across projects.

Answers "what self-healing is running, where, and how healthy is it" — the same
truth the Studio Context Graph page shows, from the CLI. Derives status live from
each project's context_graph_* docs + its self-heal agents (no extra state).
"""

import json as json_lib
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from machina_cli.client import MachinaClient
from machina_cli.config import get_config
from machina_cli.project_client import ProjectClient

app = typer.Typer(help="Context Graph — self-healing status")
console = Console()

# agents that make up the self-healing / monitoring layer
SELF_HEAL_AGENTS = ("surface-watch-beat", "loop-beat", "loop-runner")


def _docs(client: ProjectClient, name: str, page_size: int = 12) -> list:
    r = client.post(
        "document/search",
        {"compact": False, "filters": {"name": name}, "page": 1, "page_size": page_size, "sorters": ["updated", -1]},
    )
    d = r.get("data")
    return (d.get("data") if isinstance(d, dict) else d) or []


def _edge_summary(edge: str, h: dict) -> tuple:
    """(badge, color, detail) for one context_graph_health edge."""
    if edge == "market<->team_urn":
        unresolved = h.get("linkable_unresolved")
        if unresolved and unresolved > 0:
            return ("unlinked", "red", f"{unresolved} unresolved · {h.get('team_markets', 0)} named")
        lr = h.get("link_rate_pct")
        return ("linked", "green", f"{lr}% linked" if lr is not None else f"{h.get('resolved', 0)} linked")
    rate = h.get("broken_rate_pct")
    if rate is not None:
        return ("degraded" if rate > 0 else "ok", "red" if rate > 0 else "green", f"{rate}%")
    return ("ok", "green", "—")


def _collect(project_id: str) -> dict:
    """Live self-healing status for one project. Raises on unreachable/no-access."""
    client = ProjectClient(project_id)
    edges = {}
    for doc in _docs(client, "context_graph_health", 12):
        h = (doc.get("value") or {}).get("health") or {}
        e = h.get("edge")
        if e and e not in edges:
            edges[e] = h
    surf_docs = _docs(client, "context_graph_surface_health", 1)
    surface = (surf_docs[0].get("value") or {}) if surf_docs else None
    agents = {}
    ar = client.post("agent/search", {"filters": {}, "page": 1, "page_size": 100})
    ad = ar.get("data")
    for a in (ad.get("data") if isinstance(ad, dict) else ad) or []:
        if a.get("name") in SELF_HEAL_AGENTS:
            agents[a["name"]] = {
                "status": a.get("status"),
                "scheduled": a.get("scheduled"),
                "freq": (a.get("context") or {}).get("config-frequency"),
                "last": str(a.get("last_execution_date") or a.get("updated") or "")[:19],
            }
    return {"edges": edges, "surface": surface, "agents": agents}


def _render_one(name: str, pid: str, st: dict) -> None:
    console.print(f"\n[bold]{name}[/] [dim]({pid})[/]")
    if not st["edges"] and not st["surface"] and not st["agents"]:
        console.print("  [dim]no self-healing provisioned here[/]")
        return
    for edge, h in st["edges"].items():
        badge, color, detail = _edge_summary(edge, h)
        console.print(f"  edge [bold]{edge:24}[/] [{color}]{badge:9}[/] [dim]{detail}[/]")
    s = st["surface"]
    if s:
        v = s.get("verdict", "?")
        h = s.get("health") or {}
        color = "green" if v == "ok" else "yellow" if v == "low_traffic" else "red"
        sig = f"sessions {h.get('sessions', h.get('users', 0))} · {h.get('exceptions', 0)} exc · err/s {h.get('err_per_session', h.get('err_per_user', 0))}"
        console.print(f"  surface [bold]odds/errors[/]        [{color}]{v:9}[/] [dim]{sig}[/]")
    for an in SELF_HEAL_AGENTS:
        a = st["agents"].get(an)
        if not a:
            continue
        alive = a["status"] == "active" and a["scheduled"] is False
        c = "green" if a["status"] == "active" else "dim"
        note = "" if a["status"] != "active" else (f" · freq={a['freq']}" + ("" if alive else " · [red]scheduled=True (won't fire)[/]"))
        console.print(f"  agent [bold]{an:20}[/] [{c}]{a['status']}[/]{note} [dim]{a['last']}[/]")


@app.command("status")
def status(
    project_id: Optional[str] = typer.Option(None, "--project", "-p", help="Project ID (default: selected project)"),
    org: bool = typer.Option(False, "--org", help="Roll up across all projects in the org"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Show the self-healing / monitoring status (edges, surface, beats)."""
    if not org:
        pid = project_id or get_config("default_project_id")
        if not pid:
            console.print("[red]No project selected. Run `machina project use <id>` or pass --project.[/red]")
            raise typer.Exit(1)
        st = _collect(pid)
        if json_output:
            console.print_json(json_lib.dumps(st, default=str))
            return
        _render_one(get_config("default_project_name") or pid, pid, st)
        return

    # --org: iterate the org's projects
    core = MachinaClient()
    res = core.post("user/projects/search", {"filters": {}, "page": 1, "page_size": 200, "sorters": ["name", 1]})
    projects = res.get("data", []) or []
    rows, skipped = [], 0
    for p in projects:
        pid = p.get("project_id") or p.get("id")
        pname = p.get("project_name") or p.get("name") or pid
        if not pid:
            continue
        try:
            st = _collect(pid)
        except (SystemExit, Exception):  # noqa: BLE001
            skipped += 1
            continue
        if not st["edges"] and not st["surface"] and not st["agents"]:
            continue  # not provisioned — omit from the rollup
        rows.append((pname, pid, st))

    if json_output:
        console.print_json(json_lib.dumps({"projects": [{"name": n, "id": i, **s} for n, i, s in rows], "skipped": skipped}, default=str))
        return

    if not rows:
        console.print("[yellow]No projects have self-healing provisioned (or reachable).[/yellow]")
        return
    table = Table(title="Self-healing across the org")
    table.add_column("Project", style="bold")
    table.add_column("Edges", justify="right")
    table.add_column("Surface")
    table.add_column("Beat")
    for pname, pid, st in rows:
        n_edges = str(len(st["edges"]))
        s = st["surface"]
        surf = "—"
        if s:
            v = s.get("verdict", "?")
            surf = f"[{'green' if v == 'ok' else 'yellow' if v == 'low_traffic' else 'red'}]{v}[/]"
        beat = st["agents"].get("surface-watch-beat") or st["agents"].get("loop-beat")
        if beat:
            live = beat["status"] == "active" and beat["scheduled"] is False
            beat_s = "[green]live[/]" if live else ("[red]active/scheduled=True[/]" if beat["status"] == "active" else "[dim]off[/]")
        else:
            beat_s = "[dim]none[/]"
        table.add_row(pname, n_edges, surf, beat_s)
    console.print(table)
    if skipped:
        console.print(f"[dim]{skipped} project(s) skipped (unreachable / no access).[/]")
