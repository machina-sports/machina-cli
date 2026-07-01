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

Slack awareness: on every scan, a Slack message fires on a verdict TRANSITION only --
entering a degraded state (self-healed, or "needs a human" when no heal applies/fired),
or recovering back to ok. An unchanged ongoing state never re-notifies (the Studio/CLI
dashboards already show that continuously) -- so the channel only gets pinged for news.
The webhook lives in a `slack-notify-config` document (or $TEMP_CONTEXT_VARIABLE_
SLACK_WEBHOOK_URL, same posture as the PostHog key); provision it by setting
SLACK_WEBHOOK_URL when running this script.

Usage (run from inside the enrichment pod, like context-verify.py):
    CLIENT_API_URL="http://localhost:5003" API_TOKEN="$MACHINA_PROJECT_KEY" \\
    SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..." \\
    python3 surface-verify.py            # provision (+ upsert the Slack config if set)
    python3 surface-verify.py --run      # provision + run one surface check
    python3 surface-verify.py --teardown # remove

To prove the Slack notify fires for real (not just the local dry-run harness),
force a transition with the workflow's threshold overrides -- degraded:errors
never triggers the odds heal, so this is side-effect-free:
    POST workflow/execute/surface-verify {"window_hours": 6, "err_ceiling": 0.001}   # -> degraded:errors, alerts
    POST workflow/execute/surface-verify {"window_hours": 6}                         # -> back to ok, alerts "recovered"
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
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "").strip()


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
    session_floor = int(p.get("session_floor", 80) or 80)
    odds_floor = float(p.get("odds_floor", 0.02) or 0.02)
    err_ceiling = float(p.get("err_ceiling", 0.08) or 0.08)
    if not key:
        return {"status": True, "data": {"health": {"edge": "surface<->users", "error": "no posthog_key (vault POSTHOG_QUERY_KEY)"}, "verdict": "unknown", "heal_needed": False}}
    # Denominator is chat SESSIONS (bot engagement), NOT count(DISTINCT person_id)
    # over all events — the latter is diluted by total site traffic (e.g. 7k site
    # visitors vs ~600 chat sessions) and is not an odds-health signal. Calibrated on
    # 14d: odds/session on busy days floors at ~0.07, so 0.02 only fires on a real
    # collapse; sessions<80 (6h) is genuine low-traffic (skip).
    sql = ("SELECT countIf(event='odds_widget_viewed') AS odds, "
           "countIf(event='chat_session_started') AS sessions, "
           "countIf(event='chat_error') AS chat_err, "
           "countIf(event='$exception') AS exceptions, "
           "count(DISTINCT person_id) AS users "
           "FROM events WHERE timestamp > now() - INTERVAL " + str(hours) + " HOUR "
           "AND event IN ('odds_widget_viewed','chat_session_started','chat_error','$exception')")
    try:
        res = _hogql(key, project, sql)
        row = (res.get("results") or [[0, 0, 0, 0, 0]])[0]
        odds, sessions, chat_err, exceptions, users = int(row[0]), int(row[1]), int(row[2]), int(row[3]), int(row[4])
    except urllib.error.HTTPError as e:
        return {"status": True, "data": {"health": {"edge": "surface<->users", "error": "posthog HTTP %s" % e.code}, "verdict": "unknown", "heal_needed": False}}
    except Exception as e:
        return {"status": True, "data": {"health": {"edge": "surface<->users", "error": str(e)[:150]}, "verdict": "unknown", "heal_needed": False}}
    errs = chat_err + exceptions
    ops = (odds / sessions) if sessions else 0.0
    eps = (errs / sessions) if sessions else 0.0
    opu = (odds / users) if users else 0.0
    epu = (errs / users) if users else 0.0
    if sessions < session_floor:
        verdict = "low_traffic"
    elif eps > err_ceiling:
        verdict = "degraded:errors"
    elif ops < odds_floor:
        verdict = "degraded:odds"
    else:
        verdict = "ok"
    heal = verdict == "degraded:odds"
    health = {"edge": "surface<->users", "window_hours": hours, "sessions": sessions, "users": users,
              "odds_viewed": odds, "chat_err": chat_err, "exceptions": exceptions,
              "odds_per_session": round(ops, 5), "err_per_session": round(eps, 5),
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

def notify_slack(request_data):
    """Post to Slack on a verdict TRANSITION only -- entering a degraded state, or
    recovering from one. Never repeats an alert for an unchanged ongoing state (the
    Studio/CLI dashboards already show that continuously), so the channel only gets
    pinged for news. Read-only against PostHog; the Slack POST is best-effort and
    never raises (a notify failure must never fail the surface-verify workflow)."""
    p = request_data.get("params", {}) or request_data
    verdict = p.get("verdict", "unknown")
    webhook = (p.get("webhook_url") or "").strip()
    if not webhook or webhook.startswith("$"):
        try:
            from core.document.controller import document_search
            r = document_search(filters={"name": "slack-notify-config"}, page=1, page_size=1)
            dd = r.get("data") if isinstance(r, dict) else None
            rows = dd.get("data") if isinstance(dd, dict) else (dd if isinstance(dd, list) else [])
            if rows:
                webhook = ((rows[0].get("value") or {}).get("webhook_url") or "").strip()
        except Exception:
            pass
    if not webhook:
        return {"status": True, "data": {"notified": False, "skipped": "no webhook configured"}}

    # This task runs BEFORE save-health persists the current scan's doc, so this
    # search returns the PREVIOUS scan's verdict -- exactly what's needed to tell
    # a transition from an unchanged ongoing state.
    prev_verdict = None
    try:
        from core.document.controller import document_search
        r = document_search(filters={"name": "context_graph_surface_health"}, page=1, page_size=1)
        dd = r.get("data") if isinstance(r, dict) else None
        rows = dd.get("data") if isinstance(dd, dict) else (dd if isinstance(dd, list) else [])
        if rows:
            prev_verdict = (rows[0].get("value") or {}).get("verdict")
    except Exception:
        pass

    degraded = ("degraded:odds", "degraded:errors")
    if verdict not in degraded:
        if prev_verdict in degraded:
            text = (":white_check_mark: *Context Graph -- recovered*\n"
                    ">Live surface is back to `%s` (was `%s`)." % (verdict, prev_verdict))
        else:
            return {"status": True, "data": {"notified": False, "skipped": "no transition"}}
    else:
        if prev_verdict == verdict:
            return {"status": True, "data": {"notified": False, "skipped": "unchanged degraded state"}}
        health = p.get("health") or {}
        healed = p.get("healed") or {}
        heal_items = healed.get("healed") if isinstance(healed, dict) else None
        heal_ok = bool(heal_items) and not any(isinstance(h, dict) and h.get("error") for h in (heal_items or []))
        if verdict == "degraded:odds" and heal_ok:
            headline = ":adhesive_bandage: *Context Graph -- self-healed*"
            body = ("Odds looked broken to users -- auto-heal re-triggered the odds refresh "
                     "automatically. Flagging for visibility, no action needed.")
        elif verdict == "degraded:odds":
            headline = ":rotating_light: *Context Graph -- could NOT self-heal*"
            body = ("Odds looked broken to users and the auto-heal (odds refresh) didn't run "
                     "or errored. *Needs a human.*")
        else:
            headline = ":rotating_light: *Context Graph -- needs review*"
            body = ("Chat error rate spiked for users -- not fixable by auto-heal (likely a "
                     "code regression). *Needs a human.*")
        sig = ("sessions=%s . odds/session=%s . err/session=%s . exceptions=%s . window=%sh"
               % (health.get("sessions"), health.get("odds_per_session"), health.get("err_per_session"),
                  health.get("exceptions"), health.get("window_hours")))
        text = "%s\n>%s\n>`%s`" % (headline, body, sig)

    body_bytes = json.dumps({"text": text}).encode()
    req = urllib.request.Request(webhook, data=body_bytes, method="POST",
                                  headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            r.read()
        return {"status": True, "data": {"notified": True, "verdict": verdict, "prev_verdict": prev_verdict}}
    except Exception as e:
        return {"status": True, "data": {"notified": False, "error": str(e)[:150]}}
'''

SURFVAL = ("{'edge':'surface<->users','verdict':$.get('sv_verdict','unknown'),"
           "'health':$.get('sv_health', {}),'heal_needed':$.get('sv_heal', False),"
           "'healed':$.get('sv_healed', {}),'source':'posthog','generator':'surface-verify v1'}")


def _workflow():
    return {"name": "surface-verify", "title": "Surface Verify", "status": "active",
            "description": "live-surface defense: PostHog signal -> verdict -> odds heal",
            "context-variables": {"debugger": {"enabled": True}},
            "inputs": {"window_hours": "$.get('window_hours', 6)",
                       "season_ids": "$.get('season_ids', ['sr:season:101177'])",
                       # threshold overrides -- default to the calibrated values (see module
                       # docstring), only used to force a verdict on demand for testing (e.g.
                       # to prove the Slack notify fires end-to-end). GOTCHA: the workflow
                       # engine's $.get(key, default) appears to treat 0 as "not provided" and
                       # falls back to default -- pass a small non-zero value (e.g. 0.001), not
                       # 0.0, to force degraded:errors. Confirmed live against enrichment-
                       # production 2026-07-01.
                       "session_floor": "$.get('session_floor', 80)",
                       "odds_floor": "$.get('odds_floor', 0.02)",
                       "err_ceiling": "$.get('err_ceiling', 0.08)"},
            "outputs": {"verdict": "$.get('sv_verdict', 'unknown')",
                        "health": "$.get('sv_health', {})", "workflow-status": "'executed'"},
            "tasks": [
                {"name": "scan", "type": "connector",
                 "connector": {"command": "scan_surface", "name": "surface-verify-tools"},
                 "inputs": {"posthog_key": "$TEMP_CONTEXT_VARIABLE_POSTHOG_QUERY_KEY",
                            "posthog_project": "'257767'",
                            "window_hours": "$.get('window_hours', 6)",
                            "session_floor": "$.get('session_floor', 80)",
                            "odds_floor": "$.get('odds_floor', 0.02)",
                            "err_ceiling": "$.get('err_ceiling', 0.08)"},
                 "outputs": {"sv_health": "$.get('health')", "sv_verdict": "$.get('verdict')",
                             "sv_heal": "$.get('heal_needed')"}},
                # auto-heal: only fires when scan said degraded:odds
                {"name": "heal", "type": "connector",
                 "condition": "$.get('sv_heal', False) == True",
                 "connector": {"command": "trigger_odds_heal", "name": "surface-verify-tools"},
                 "inputs": {"heal_needed": "$.get('sv_heal', False)",
                            "season_ids": "$.get('season_ids', ['sr:season:101177'])"},
                 "outputs": {"sv_healed": "$"}},
                # runs before save-health so it still reads the PREVIOUS scan's
                # verdict (for transition detection) -- see notify_slack docstring.
                # Always runs (no condition): it also fires the "recovered" message,
                # which only makes sense when heal_needed is False.
                {"name": "notify", "type": "connector",
                 "connector": {"command": "notify_slack", "name": "surface-verify-tools"},
                 "inputs": {"verdict": "$.get('sv_verdict', 'unknown')",
                            "health": "$.get('sv_health', {})",
                            "healed": "$.get('sv_healed', {})",
                            "webhook_url": "$TEMP_CONTEXT_VARIABLE_SLACK_WEBHOOK_URL"},
                 "outputs": {"sv_notified": "$"}},
                {"name": "save-health", "type": "document",
                 "config": {"action": "save", "embed-vector": False, "force-update": True},
                 "documents": {"context_graph_surface_health": SURFVAL}},
            ]}


def definitions():
    tools = {"name": "surface-verify-tools", "title": "Surface Verify Tools", "status": "active",
             "description": "PostHog live-surface scanner + odds heal trigger",
             "filename": "surface_verify.py", "filetype": "pyscript", "filecontent": SCAN_SRC,
             "commands": [{"name": "ScanSurface", "value": "scan_surface"},
                          {"name": "TriggerOddsHeal", "value": "trigger_odds_heal"},
                          {"name": "NotifySlack", "value": "notify_slack"}]}
    wf = _workflow()
    # self-evolving: a scheduled sweep of the live surface. INACTIVE by default — set
    # status:active + tune config-frequency to enable continuous defense (shared pod).
    beat = {"name": "surface-watch-beat", "title": "Surface Watch Beat", "status": "inactive",
            "scheduled": False, "description": "continuous live-surface defense (set status:active to enable)",
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
    # CAUTION when re-running against a pod where the beat was since promoted to
    # active (e.g. via a direct PUT /agent/<id>): `beat` above defaults to
    # status="inactive", so this overwrites it back off. If surface-watch-beat is
    # live in this pod, re-activate it after provisioning (or provision just the
    # connector + workflow entries, skipping the agent, to update the code without
    # touching the running beat's status).
    ok = all(_create(kind, body) for kind, body in defs)
    if SLACK_WEBHOOK_URL:
        # Same posture as the PostHog key: a config document notify_slack reads at
        # runtime, not baked into the workflow. Re-running provisioning updates it
        # (idempotent, like every other resource in `defs`).
        _create("document", {"name": "slack-notify-config", "status": "active",
                              "value": {"webhook_url": SLACK_WEBHOOK_URL}})
    print("\nDone." if ok else "\nDone with errors — check output above.")
    if "--run" in sys.argv:
        _run_once()
    else:
        print("Run it:  python3 surface-verify.py --run")


if __name__ == "__main__":
    main()
