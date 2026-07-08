"""Context Graph — self-healing / monitoring status across projects.

Answers "what self-healing is running, where, and how healthy is it" — the same
truth the Studio Context Graph page shows, from the CLI. Derives status live from
each project's context_graph_* docs + its self-heal agents (no extra state).
"""

import contextlib
import io
import json as json_lib
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
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
    if edge.startswith("arena:"):
        decision = h.get("decision")
        badge, color = {
            "pass": ("certified", "green"),
            "repair": ("repair", "yellow"),
            "block": ("blocked", "red"),
        }.get(decision, (decision or "arena", "yellow"))
        parts = []
        gates = h.get("gate_pass_rate_pct")
        if gates is not None:
            parts.append(f"gates {gates}%")
        judge = h.get("judge_score")
        if judge is not None:
            parts.append(f"judge {judge}")
        if "approval" in str(h.get("next_action", "")):
            parts.append("approval")
        failed = h.get("failed_gates")
        if failed:
            parts.append(",".join(str(g) for g in failed))
        return (badge, color, " · ".join(parts) if parts else "—")
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
            # ProjectClient prints errors + raises SystemExit for unreachable /
            # forbidden projects; silence that per-project noise (it otherwise
            # corrupts --json and clutters the table) and skip cleanly.
            with contextlib.redirect_stderr(io.StringIO()):
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


# ---------------------------------------------------------------------------
# timeline — the self-healing event history, reconstructed from the doc trail
# ---------------------------------------------------------------------------

# Raw broken-count field per data edge (the exact signal; broken_rate_pct rounds
# 1/500 down to 0). Mirrors BROKEN_COUNT_FIELD in the harness-loop kit.
_DATA_EDGE_COUNT = {"analysis<->fixture": "broken_edges", "odd<->market<->fixture": "misattributed"}
_DEGRADED = ("degraded:odds", "degraded:errors")


def _parse_created(doc: dict):
    try:
        return parsedate_to_datetime(doc.get("created"))
    except Exception:  # noqa: BLE001
        return None


def _events_from_history(health_docs: list, surface_docs: list) -> list:
    """Reconstruct self-healing events from the persisted graph-health trail.

    Every scan appends a doc, so consecutive docs per edge encode the story:
    a 0->N broken step is a detection, healed.heal_count>0 is a heal round,
    healed.budget_exceeded is auto-heal pausing, N->0 is a recovery. Works
    retroactively on any pod that has history — no new writes needed.
    """
    events = []

    # data edges (analysis<->fixture, odd<->market<->fixture)
    per_edge: dict = {}
    for doc in health_docs:
        v = doc.get("value") or {}
        h = v.get("health") or {}
        edge = h.get("edge")
        if edge not in _DATA_EDGE_COUNT:
            continue
        ts = _parse_created(doc)
        if ts is None:
            continue
        per_edge.setdefault(edge, []).append((ts, h.get(_DATA_EDGE_COUNT[edge]) or 0, v.get("healed") or {}))
    for edge, rows in per_edge.items():
        rows.sort(key=lambda r: r[0])
        prev_broken = 0
        peak = 0  # incident peak, so a drained recovery reads "peaked at 13", not "was 1"
        for ts, broken, healed in rows:
            if broken > 0:
                peak = max(peak, broken)
            if broken > 0 and prev_broken == 0:
                events.append({"ts": ts, "edge": edge, "event": "detected", "detail": f"{broken} broken"})
            if (healed.get("heal_count") or 0) > 0:
                backlog = healed.get("backlog") or 0
                extra = f" (+{backlog} queued)" if backlog else ""
                events.append({"ts": ts, "edge": edge, "event": "heal",
                               "detail": f"re-research dispatched for {healed['heal_count']} fixture(s){extra}"})
            if healed.get("budget_exceeded"):
                events.append({"ts": ts, "edge": edge, "event": "heal-paused",
                               "detail": f"no progress after {healed.get('prior_attempts', '?')} rounds — needs a human"})
            if broken == 0 and prev_broken > 0:
                events.append({"ts": ts, "edge": edge, "event": "recovered",
                               "detail": f"back to 0 broken (incident peaked at {peak})"})
                peak = 0
            prev_broken = broken

    # live surface (surface<->users)
    srows = []
    for doc in surface_docs:
        v = doc.get("value") or {}
        ts = _parse_created(doc)
        if ts is None:
            continue
        srows.append((ts, v.get("verdict") or "?", v.get("healed") or {}))
    srows.sort(key=lambda r: r[0])
    prev_v = None
    for ts, verdict, healed in srows:
        if verdict in _DEGRADED and verdict != prev_v:
            events.append({"ts": ts, "edge": "surface<->users", "event": "detected", "detail": verdict})
        heal_items = healed.get("healed") if isinstance(healed, dict) else None
        if heal_items:
            events.append({"ts": ts, "edge": "surface<->users", "event": "heal",
                           "detail": f"odds refresh re-triggered ({len(heal_items)} season(s))"})
        if isinstance(healed, dict) and healed.get("budget_exceeded"):
            events.append({"ts": ts, "edge": "surface<->users", "event": "heal-paused",
                           "detail": "retry budget exceeded — needs a human"})
        if verdict not in _DEGRADED and prev_v in _DEGRADED:
            events.append({"ts": ts, "edge": "surface<->users", "event": "recovered",
                           "detail": f"back to {verdict} (was {prev_v})"})
        prev_v = verdict

    events.sort(key=lambda e: e["ts"])
    return events


def _collect_timeline(project_id: str) -> list:
    """Events for one project, from its persisted history (read-only)."""
    client = ProjectClient(project_id)
    health = _docs(client, "context_graph_health", 300)
    surface = _docs(client, "context_graph_surface_health", 300)
    return _events_from_history(health, surface)


_EVENT_STYLE = {"detected": "red", "heal": "cyan", "heal-paused": "bold red", "recovered": "green"}


@app.command("timeline")
def timeline(
    project_id: Optional[str] = typer.Option(None, "--project", "-p", help="Project ID (default: selected project)"),
    org: bool = typer.Option(False, "--org", help="Merge events across all projects in the org"),
    days: int = typer.Option(30, "--days", "-d", help="How far back to look"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """The self-healing event history: detected → healed → paused/recovered, per edge."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    rows = []  # (project_name, event)
    skipped = 0
    if org:
        core = MachinaClient()
        res = core.post("user/projects/search", {"filters": {}, "page": 1, "page_size": 200, "sorters": ["name", 1]})
        for p in res.get("data", []) or []:
            pid = p.get("project_id") or p.get("id")
            pname = p.get("project_name") or p.get("name") or pid
            if not pid:
                continue
            try:
                with contextlib.redirect_stderr(io.StringIO()):
                    for ev in _collect_timeline(pid):
                        rows.append((pname, ev))
            except (SystemExit, Exception):  # noqa: BLE001
                skipped += 1
    else:
        pid = project_id or get_config("default_project_id")
        if not pid:
            console.print("[red]No project selected. Run `machina project use <id>` or pass --project.[/red]")
            raise typer.Exit(1)
        pname = get_config("default_project_name") or pid
        for ev in _collect_timeline(pid):
            rows.append((pname, ev))

    rows = [(n, e) for n, e in rows if e["ts"] >= cutoff]
    rows.sort(key=lambda r: r[1]["ts"])
    counts = {"detected": 0, "heal": 0, "heal-paused": 0, "recovered": 0}
    for _, e in rows:
        counts[e["event"]] = counts.get(e["event"], 0) + 1

    if json_output:
        payload = {
            "events": [{"project": n, "ts": e["ts"].isoformat(), "edge": e["edge"],
                        "event": e["event"], "detail": e["detail"]} for n, e in rows],
            "summary": counts, "window_days": days, "skipped": skipped,
        }
        console.print_json(json_lib.dumps(payload))
        return

    if not rows:
        console.print(f"[yellow]No self-healing events in the last {days} day(s).[/yellow]")
        return
    table = Table(title=f"Self-healing timeline — last {days} day(s)")
    table.add_column("Time (UTC)", style="dim", no_wrap=True)
    if org:
        table.add_column("Project", style="bold")
    table.add_column("Edge")
    table.add_column("Event")
    table.add_column("Detail", overflow="fold")
    for pname, e in rows:
        style = _EVENT_STYLE.get(e["event"], "")
        cells = [e["ts"].strftime("%b %d %H:%M")]
        if org:
            cells.append(pname)
        cells += [e["edge"], f"[{style}]{e['event']}[/]" if style else e["event"], e["detail"]]
        table.add_row(*cells)
    console.print(table)
    console.print(
        f"  [dim]{counts['detected']} detected · {counts['heal']} heal round(s) · "
        f"{counts['recovered']} recovered · {counts['heal-paused']} escalated to a human[/]"
        + (f" [dim]· {skipped} project(s) skipped[/]" if skipped else "")
    )
