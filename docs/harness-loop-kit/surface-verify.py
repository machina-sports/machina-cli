#!/usr/bin/env python3
"""
Context Graph — `surface-verify` (the live-surface defense edge).

Extends the self-healing loop from the DATA layer to the LIVE USER-FACING surface.
It reads PostHog (the SportingBOT project's real user signals) to judge whether the
enrichment is actually reaching users — and, when the odds break for users, triggers
the existing odds heal. This closes the loop:

    enrichment data -> webmaster/site -> users -> PostHog signal -> verify -> heal

New edge: **surface <-> users**. The check is a rolling-window HogQL query for
odds-widget + error rates PER USER (scale-free, so window size doesn't bias it).
Thresholds were calibrated on 14 days of real history (it flags the real error spikes
and traffic collapses while staying `ok` on normal days, zero false positives).

  ok               odds + errors within band
  degraded:odds    traffic normal but odds-widget views per user collapsed -> HEAL
  degraded:errors  chat-error rate per user spiked (flag for review)
  low_traffic      not enough traffic to judge (or the surface is down)

The PostHog read key lives in the pod VAULT as POSTHOG_QUERY_KEY (never in code) and is
injected via $TEMP_CONTEXT_VARIABLE_POSTHOG_QUERY_KEY. Read-only against PostHog; the only
write is the optional odds heal (re-running entain-coverage-fut-refresh-markets, idempotent).

Usage (run from inside the enrichment pod, like context-verify.py):
    CLIENT_API_URL="http://localhost:5003" API_TOKEN="$MACHINA_PROJECT_KEY" \\
    python3 surface-verify.py            # provision
    python3 surface-verify.py --run      # provision + run one surface check
    python3 surface-verify.py --teardown # remove
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error

BASE = os.environ.get("CLIENT_API_URL", "").rstrip("/")
TOKEN = os.environ.get("API_TOKEN", "")
PH_PROJECT = os.environ.get("POSTHOG_PROJECT_ID", "257767")


def _req(method, path, body=None):
    url = f"{BASE}/{path.lstrip('/')}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"X-Api-Token": TOKEN, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=200) as r:
            return json.loads(r.read() or "{}")
    except urllib.error.HTTPError as e:
        return {"status": False, "error": {"message": f"HTTP {e.code}: {e.read()[:200]}"}}
    except Exception as e:  # noqa: BLE001
        return {"status": False, "error": {"message": str(e)}}


def _delete_by_name(kind, name):
    d = _req("GET", f"{kind}/{name}").get("data", {})
    if isinstance(d, dict) and d.get("_id"):
        _req("DELETE", f"{kind}/{d['_id']}")


def _create(kind, body):
    _delete_by_name(kind, body["name"])
    res = _req("POST", kind, body)
    ok = res.get("status") in (True, "success")
    print(f"  {'OK ' if ok else 'ERR'} {kind}/{body['name']}"
          + ("" if ok else f"  -> {json.dumps(res.get('error'))[:140]}"))
    return ok


# --- connector source: PostHog surface scanner + odds heal trigger (pyscript) ---
SCAN_SRC = r'''"""Live-surface defense: PostHog signals -> verdict -> odds heal."""
import os, json, urllib.request, urllib.error

PH_BASE = "https://us.posthog.com"

def _hogql(key, project, sql):
    body = json.dumps({"query": {"kind": "HogQLQuery", "query": sql}}).encode()
    req = urllib.request.Request(PH_BASE + "/api/projects/" + str(project) + "/query/",
        data=body, method="POST",
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read() or "{}")

def scan_surface(request_data):
    """Rolling-window PostHog read: odds-widget + error rate PER USER -> health verdict.
    Read-only. Thresholds are scale-free ratios calibrated on 14d of history."""
    p = request_data.get("params", {}) or request_data
    key = (p.get("posthog_key") or "").strip()
    project = p.get("posthog_project") or "257767"
    if not key or key.startswith("$"):
        # fallback: read the read-only key from a brand-local config doc (in-process),
        # since $TEMP_CONTEXT_VARIABLE_* resolves from pod ENV (set via the deployment),
        # not from a doc/vault we can populate at runtime. Hardening TODO: move to a k8s
        # secret env var TEMP_CONTEXT_VARIABLE_POSTHOG_QUERY_KEY.
        try:
            from core.document.controller import document_search
            r = document_search(filters={"name": "posthog-surface-config"}, page=1, page_size=1)
            dd = r.get("data") if isinstance(r, dict) else None
            rows = dd.get("data") if isinstance(dd, dict) else (dd if isinstance(dd, list) else [])
            if rows:
                cv = rows[0].get("value") or {}
                key = (cv.get("query_key") or "").strip()
                project = cv.get("project") or project
        except Exception:
            pass
    try: hours = int(p.get("window_hours", 6) or 6)
    except Exception: hours = 6
    traffic_floor = int(p.get("traffic_floor", 300) or 300)
    odds_floor = float(p.get("odds_floor", 0.004) or 0.004)
    err_ceiling = float(p.get("err_ceiling", 0.01) or 0.01)
    if not key:
        return {"status": True, "data": {"health": {"edge": "surface<->users", "error": "no posthog_key (vault POSTHOG_QUERY_KEY)"}, "verdict": "unknown", "heal_needed": False}}
    sql = ("SELECT countIf(event='odds_widget_viewed') AS odds, "
           "countIf(event='chat_error') AS chat_err, "
           "countIf(event='$exception') AS exceptions, "
           "count(DISTINCT person_id) AS users "
           "FROM events WHERE timestamp > now() - INTERVAL " + str(hours) + " HOUR")
    try:
        res = _hogql(key, project, sql)
        row = (res.get("results") or [[0, 0, 0, 0]])[0]
        odds, chat_err, exceptions, users = int(row[0]), int(row[1]), int(row[2]), int(row[3])
    except urllib.error.HTTPError as e:
        return {"status": True, "data": {"health": {"edge": "surface<->users", "error": "posthog HTTP %s" % e.code}, "verdict": "unknown", "heal_needed": False}}
    except Exception as e:
        return {"status": True, "data": {"health": {"edge": "surface<->users", "error": str(e)[:150]}, "verdict": "unknown", "heal_needed": False}}
    opu = (odds / users) if users else 0.0
    epu = (chat_err / users) if users else 0.0
    if users < traffic_floor:
        verdict = "low_traffic"
    elif epu > err_ceiling:
        verdict = "degraded:errors"
    elif opu < odds_floor:
        verdict = "degraded:odds"
    else:
        verdict = "ok"
    heal = verdict == "degraded:odds"
    health = {"edge": "surface<->users", "window_hours": hours, "users": users,
              "odds_viewed": odds, "chat_err": chat_err, "exceptions": exceptions,
              "odds_per_user": round(opu, 5), "err_per_user": round(epu, 5),
              "verdict": verdict, "heal_needed": heal, "source": "posthog"}
    return {"status": True, "data": {"health": health, "verdict": verdict, "heal_needed": heal}}

def trigger_odds_heal(request_data):
    """On degraded:odds, re-run the odds refresh (re-attach bwin odds to fixtures) for the
    configured seasons. Idempotent — same workflow the scheduler runs, just on demand.
    Uses the pod's own X-Api-Token (from env) to call the local client-api."""
    p = request_data.get("params", {}) or request_data
    if not p.get("heal_needed"):
        return {"status": True, "data": {"healed": [], "heal_count": 0, "skipped": "verdict not degraded:odds"}}
    token = os.environ.get("MACHINA_PROJECT_KEY", "")
    seasons = p.get("season_ids") or ["sr:season:101177"]
    if not isinstance(seasons, list): seasons = [seasons]
    out = []
    for sid in seasons:
        try:
            req = urllib.request.Request("http://localhost:5003/workflow/execute/entain-coverage-fut-refresh-markets",
                data=json.dumps({"season_id": sid}).encode(), method="POST",
                headers={"X-Api-Token": token, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=240) as r:
                d = json.loads(r.read() or "{}")
            out.append({"season_id": sid, "status": d.get("status", "executed")})
        except Exception as e:
            out.append({"season_id": sid, "error": str(e)[:120]})
    return {"status": True, "data": {"healed": out, "heal_count": len(out)}}
'''

SURFVAL = ("{'edge':'surface<->users','verdict':$.get('sv_verdict','unknown'),"
           "'health':$.get('sv_health', {}),'heal_needed':$.get('sv_heal', False),"
           "'healed':$.get('sv_healed', {}),'source':'posthog','generator':'surface-verify v1'}")


def _workflow():
    return {"name": "surface-verify", "title": "Surface Verify", "status": "active",
            "description": "live-surface defense: PostHog signal -> verdict -> odds heal",
            "context-variables": {"debugger": {"enabled": True}},
            "inputs": {"window_hours": "$.get('window_hours', 6)",
                       "season_ids": "$.get('season_ids', ['sr:season:101177'])"},
            "outputs": {"verdict": "$.get('sv_verdict', 'unknown')",
                        "health": "$.get('sv_health', {})", "workflow-status": "'executed'"},
            "tasks": [
                {"name": "scan", "type": "connector",
                 "connector": {"command": "scan_surface", "name": "surface-verify-tools"},
                 "inputs": {"posthog_key": "$TEMP_CONTEXT_VARIABLE_POSTHOG_QUERY_KEY",
                            "posthog_project": "'257767'",
                            "window_hours": "$.get('window_hours', 6)"},
                 "outputs": {"sv_health": "$.get('health')", "sv_verdict": "$.get('verdict')",
                             "sv_heal": "$.get('heal_needed')"}},
                # auto-heal: only fires when scan said degraded:odds
                {"name": "heal", "type": "connector",
                 "condition": "$.get('sv_heal', False) == True",
                 "connector": {"command": "trigger_odds_heal", "name": "surface-verify-tools"},
                 "inputs": {"heal_needed": "$.get('sv_heal', False)",
                            "season_ids": "$.get('season_ids', ['sr:season:101177'])"},
                 "outputs": {"sv_healed": "$"}},
                {"name": "save-health", "type": "document",
                 "config": {"action": "save", "embed-vector": False, "force-update": True},
                 "documents": {"context_graph_surface_health": SURFVAL}},
            ]}


def definitions():
    tools = {"name": "surface-verify-tools", "title": "Surface Verify Tools", "status": "active",
             "description": "PostHog live-surface scanner + odds heal trigger",
             "filename": "surface_verify.py", "filetype": "pyscript", "filecontent": SCAN_SRC,
             "commands": [{"name": "ScanSurface", "value": "scan_surface"},
                          {"name": "TriggerOddsHeal", "value": "trigger_odds_heal"}]}
    wf = _workflow()
    # self-evolving: a scheduled sweep of the live surface. INACTIVE by default — set
    # status:active + tune config-frequency to enable continuous defense (shared pod).
    beat = {"name": "surface-watch-beat", "title": "Surface Watch Beat", "status": "inactive",
            "scheduled": True, "description": "continuous live-surface defense (set status:active to enable)",
            "context": {"config-frequency": 30}, "context-agent": {"window_hours": "$.get('window_hours', 6)"},
            "workflows": [{"name": "surface-verify", "description": "surface<->users defense",
                           "inputs": {"window_hours": "$.get('window_hours', 6)"},
                           "outputs": {"verdict": "$.get('verdict', 'unknown')"}}]}
    return [("connector", tools), ("workflow", wf), ("agent", beat)]


def _run_once():
    print("\nRunning surface-verify once ...")
    r = _req("POST", "workflow/execute/surface-verify", {"window_hours": 6})
    data = r.get("data", {}) if isinstance(r, dict) else {}
    print("  workflow status:", r.get("status"))
    # read back the persisted surface-health doc
    time.sleep(2)
    d = _req("POST", "document/search",
             {"filters": {"name": "context_graph_surface_health"}, "sorters": ["created", -1], "page_size": 1}).get("data", [])
    rows = d.get("data") if isinstance(d, dict) else d
    if rows:
        v = rows[0].get("value") or {}
        h = v.get("health") or {}
        print("\n=== Surface health (saved) ===")
        print("  verdict   :", v.get("verdict"))
        print("  signals   :", json.dumps({k: h.get(k) for k in ("users", "odds_viewed", "chat_err", "odds_per_user", "err_per_user", "window_hours")}, ensure_ascii=False))
        if v.get("heal_needed"):
            print("  >> HEAL triggered:", json.dumps(v.get("healed"))[:200])
    else:
        print("  (no surface-health doc yet — check the pod / vault key)")


def main():
    if not BASE or not TOKEN:
        sys.exit("Set CLIENT_API_URL and API_TOKEN environment variables.")
    defs = definitions()
    if "--teardown" in sys.argv:
        print(f"Tearing down surface-verify on {BASE} ...")
        for kind, body in reversed(defs):
            _delete_by_name(kind, body["name"])
            print(f"  removed {kind}/{body['name']}")
        return
    print(f"Provisioning surface-verify on {BASE} (posthog project={PH_PROJECT}) ...")
    ok = all(_create(kind, body) for kind, body in defs)
    print("\nDone." if ok else "\nDone with errors — check output above.")
    if "--run" in sys.argv:
        _run_once()
    else:
        print("Run it:  python3 surface-verify.py --run")


if __name__ == "__main__":
    main()
