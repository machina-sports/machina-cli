#!/usr/bin/env python3
"""
Context Graph — `context-verify` v0 (edge: analysis ↔ fixture).

A durable verifier built on the same Studio primitives as the harness loop. It
audits one **context edge** — does a fixture's `pre_match_research` actually belong
to THAT fixture? — and writes a queryable **graph-health** document instead of a
throwaway script result.

Two layers, mirroring the loop's gate + evaluator:
  - deterministic gate (connector `context-verify-tools`): distinct matches cannot
    share an identical pre-match analysis, so every collision is a mis-attributed
    edge. Cheap, language-agnostic, irrefutable.
  - semantic evaluator (prompt `context-verify-eval`): turns the raw collisions into
    a precise assessment (an LLM lens that also catches subtler mismatches).

Provisions:
  connector context-verify-tools   scan_edges → fixtures + collision detection
  prompt    context-verify-eval    summarize the broken edges for a human
  workflow  context-verify         scan → assess → save `context_graph_health`
  agent     context-verify-runner  on-demand executor (inactive by default)

Usage:
    CLIENT_API_URL="https://<org>-<project>.org.machina.gg" \\
    API_TOKEN="<project X-Api-Token>" [MODEL="gemini-3.1-flash-lite"] \\
    python3 context-verify.py            # provision
    python3 context-verify.py --run      # provision, run once, print graph health
    python3 context-verify.py --teardown # remove

Runs entirely server-side in the pod (workflow + connector) — unaffected by the
MCP agent-by-name limitation (machina-client-api#287).
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error

BASE = os.environ.get("CLIENT_API_URL", "").rstrip("/")
TOKEN = os.environ.get("API_TOKEN", "")
MODEL = os.environ.get("MODEL", "gemini-3.1-flash-lite")
GENAI = {"command": "invoke_prompt", "location": "global", "model": MODEL,
         "name": "google-genai", "provider": "vertex_ai"}
CTX_VARS = {"debugger": {"enabled": True}, "google-genai": {
    "credential": "$TEMP_CONTEXT_VARIABLE_VERTEX_AI_CREDENTIAL",
    "project_id": "$TEMP_CONTEXT_VARIABLE_VERTEX_AI_PROJECT_ID"}}


def _req(method, path, body=None):
    url = f"{BASE}/{path.lstrip('/')}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"X-Api-Token": TOKEN, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
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
          + ("" if ok else f"  -> {json.dumps(res.get('error'))[:120]}"))
    return ok


# --- connector source: deterministic edge gate (pyscript, exec'd from the DB) ---
# Returns {status: True, data: {health, flagged}} — the connector contract.
SCAN_SRC = r'''"""Context Graph edge scanner — analysis<->fixture collision detection."""
import re
from collections import defaultdict

def _teams(title):
    return re.sub(r"\s*\(\d+\)\s*$", "", str(title or "")).strip()

def scan_edges(request_data: dict) -> dict:
    try:
        from core.document.controller import document_search
    except Exception as ex:
        return {"status": True, "data": {"health": {"error": "document_search unavailable: " + str(ex)}, "flagged": []}}
    p = request_data.get("params", {}) or request_data
    try: limit = int(p.get("limit", 200))
    except Exception: limit = 200
    docs, page = [], 1
    while len(docs) < limit and page <= 6:
        r = document_search(filters={"name": "sportradar-fixture", "value.has_pre_match_research": True},
                            page=page, page_size=50, sorters=["_id", -1])
        dd = r.get("data") if isinstance(r, dict) else None
        batch = dd.get("data") if isinstance(dd, dict) else (dd if isinstance(dd, list) else [])
        if not batch: break
        docs += batch; page += 1
    enriched = []
    for d in (docs or []):
        v = d.get("value", {}) or {}
        tf = (v.get("pre_match_research") or {}).get("team_form") or {}
        ha = ((tf.get("home") or {}).get("analysis") or "").strip()
        title = _teams(v.get("title"))
        if ha and title:
            enriched.append((title, re.sub(r"\s+", " ", ha.lower())[:160]))
    groups = defaultdict(set)
    for title, key in enriched:
        groups[key].add(title)
    collapsed = {k: sorted(v) for k, v in groups.items() if len(v) > 1}
    broken = sum(len(v) - 1 for v in collapsed.values())
    flagged = [{"fixtures": v, "analysis": k[:120]} for k, v in list(collapsed.items())[:10]]
    n = len(enriched)
    health = {"edge": "analysis<->fixture", "enriched_sampled": n,
              "collapsed_groups": len(collapsed), "broken_edges": broken,
              "broken_rate_pct": round(100 * broken / n) if n else 0}
    return {"status": True, "data": {"health": health, "flagged": flagged}}
'''

EVAL_SCHEMA = {"title": "ContextGraphAssessment", "type": "object", "properties": {
    "assessment": {"type": "string"}}, "required": ["assessment"]}

EVAL_INSTR = (
    "You audit a sports **Context Graph**. You receive groups of fixtures (_2-flagged) that each "
    "share an IDENTICAL pre-match analysis. Distinct matches cannot legitimately share one analysis, "
    "so every group is a mis-attributed 'analysis-to-fixture' edge.\n"
    "Using _1-health (the counts) and _2-flagged (the groups), write a precise 2-3 sentence "
    "assessment for an engineering/exec reader: how many edges are broken and the rate, plus one "
    "concrete example (which fixtures collide on one analysis). Be terse and factual — no fluff, no advice.")

# --- workflow expression fragments ---
HVAL = ("{'edge':'analysis<->fixture',"
        "'health':$.get('cg_health', {}),"
        "'flagged':$.get('cg_flagged', []),"
        "'assessment':$.get('cg_summary', {}).get('assessment',''),"
        "'generator':'context-verify v0'}")


def definitions():
    tools = {"name": "context-verify-tools", "title": "Context Verify Tools", "status": "active",
             "description": "deterministic edge scanner (analysis<->fixture collisions)",
             "filename": "context_verify.py", "filetype": "pyscript", "filecontent": SCAN_SRC,
             "commands": [{"name": "Scan", "value": "scan_edges"}]}
    evaluate = {"name": "context-verify-eval", "title": "Context Verify Eval", "type": "prompt", "status": "active",
                "description": "semantic lens: summarize the broken context edges",
                "instruction": EVAL_INSTR, "schema": EVAL_SCHEMA}
    workflow = {
        "name": "context-verify", "title": "Context Verify", "status": "active",
        "description": "audit the analysis<->fixture edge; write a graph-health document",
        "context-variables": CTX_VARS,
        "inputs": {"limit": "$.get('limit', 200)"},
        "outputs": {"health": "$.get('cg_health', {})",
                    "assessment": "$.get('cg_summary', {}).get('assessment','')",
                    "workflow-status": "'executed'"},
        "tasks": [
            {"name": "scan", "type": "connector", "connector": {"command": "scan_edges", "name": "context-verify-tools"},
             "inputs": {"limit": "$.get('limit', 200)"},
             "outputs": {"cg_health": "$.get('health')", "cg_flagged": "$.get('flagged')"}},
            {"name": "context-verify-eval", "type": "prompt", "connector": GENAI,
             "inputs": {"_1-health": "$.get('cg_health', {})", "_2-flagged": "$.get('cg_flagged', [])"},
             "outputs": {"cg_summary": "$"}},
            {"name": "save-health", "type": "document",
             "config": {"action": "save", "embed-vector": False, "force-update": True},
             "documents": {"context_graph_health": HVAL}},
        ]}
    runner = {"name": "context-verify-runner", "title": "Context Verify Runner", "status": "inactive", "scheduled": False,
              "description": "on-demand executor for the context-verify audit",
              "context-agent": {"limit": "$.get('limit', 200)"},
              "workflows": [{"name": "context-verify", "description": "run the edge audit",
                             "inputs": {"limit": "$.get('limit', 200)"},
                             "outputs": {"health": "$.get('health', {})", "assessment": "$.get('assessment','')"}}]}
    return [("connector", tools), ("prompt", evaluate), ("workflow", workflow), ("agent", runner)]


def _run_once():
    print("\nRunning context-verify (async) ...")
    _req("POST", "agent/executor/context-verify-runner",
         {"context-agent": {"limit": 200}, "agent-config": {"delay": True}})
    waited = 0
    while waited < 90:
        time.sleep(6)
        waited += 6
        d = _req("POST", "document/search",
                 {"filters": {"name": "context_graph_health"}, "sorters": ["created", -1], "page_size": 1}).get("data", [])
        if d:
            v = d[0].get("value") or {}
            h = v.get("health") or {}
            if h:
                print("\n=== context_graph_health (saved in the pod) ===")
                print(f"  edge          : {h.get('edge')}")
                print(f"  enriched      : {h.get('enriched_sampled')}")
                print(f"  collapsed grp : {h.get('collapsed_groups')}")
                print(f"  broken edges  : {h.get('broken_edges')} ({h.get('broken_rate_pct')}%)")
                print(f"  assessment    : {v.get('assessment','')}")
                return
    print("  (no health doc yet — re-run, or check the pod)")


def main():
    if not BASE or not TOKEN:
        sys.exit("Set CLIENT_API_URL and API_TOKEN environment variables.")
    defs = definitions()
    if "--teardown" in sys.argv:
        print(f"Tearing down context-verify on {BASE} ...")
        for kind, body in reversed(defs):
            _delete_by_name(kind, body["name"])
            print(f"  removed {kind}/{body['name']}")
        return
    print(f"Provisioning context-verify on {BASE} (model={MODEL}) ...")
    ok = all(_create(kind, body) for kind, body in defs)
    print("\nDone." if ok else "\nDone with errors — check output above.")
    if "--run" in sys.argv:
        _run_once()
    else:
        print("Run it:  python3 context-verify.py --run   (or trigger context-verify-runner)")


if __name__ == "__main__":
    main()
