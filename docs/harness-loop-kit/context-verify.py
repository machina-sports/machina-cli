#!/usr/bin/env python3
"""
Context Graph — `context-verify` (multi-edge audit).

A durable verifier built on the same Studio primitives as the harness loop. It
audits **context edges** — is a piece of data attributed to / linkable to the
*right* entity? — and writes a queryable **graph-health** document per edge,
instead of a throwaway script result.

Two layers, mirroring the loop's gate + evaluator:
  - deterministic gate (connector `context-verify-tools`): cheap, irrefutable
    checks (identical analyses; a market's options referencing the wrong fixture;
    accent-normalized name linking).
  - semantic layer (prompt, edge-agnostic or edge-specific): turns findings into a
    precise assessment AND, for the linkability edge, RESOLVES the cross-language
    links a deterministic join can't (Egito→Egypt) — the value an LLM adds.

Edges in v0:
  analysis ↔ fixture            sportradar-fixture.pre_match_research  (the #705 class)
  odd ↔ market ↔ fixture        entain-markets-tier3.markets_tier3     (option/fixture consistency)
  market → fixture (linkability) markets PT names ↔ fixtures EN names   (semantic join)

Provisions:
  connector context-verify-tools     scan_edges + scan_odds + scan_link
  prompt    context-verify-eval      edge-agnostic assessment (analysis, odds)
  prompt    context-verify-link      semantic resolver for the linkability edge
  workflow  context-verify / -odds / -link
  agent     context-verify-runner    runs every edge audit (inactive by default)

Usage:
    CLIENT_API_URL="https://<org>-<project>.org.machina.gg" \\
    API_TOKEN="<project X-Api-Token>" [MODEL="gemini-3.1-flash-lite"] \\
    python3 context-verify.py            # provision
    python3 context-verify.py --run      # provision, run all audits, print graph health
    python3 context-verify.py --teardown # remove

Runs entirely server-side in the pod — unaffected by the MCP agent-by-name
limitation (machina-client-api#287).
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


# --- connector source: deterministic edge gates (pyscript, exec'd from the DB) ---
SCAN_SRC = r'''"""Context Graph edge scanners (analysis, odds, linkability)."""
import re, unicodedata
from collections import defaultdict

def _docs(name, extra, limit):
    from core.document.controller import document_search
    out, page = [], 1
    flt = {"name": name}; flt.update(extra or {})
    while len(out) < limit and page <= 8:
        r = document_search(filters=flt, page=page, page_size=50, sorters=["_id", -1])
        dd = r.get("data") if isinstance(r, dict) else None
        batch = dd.get("data") if isinstance(dd, dict) else (dd if isinstance(dd, list) else [])
        if not batch: break
        out += batch; page += 1
    return out

def _limit(p):
    try: return int((p or {}).get("limit", 200))
    except Exception: return 200

def _norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]", "", s).strip()

def _pairing(v):
    for _mt, md in (v.get("markets_tier3") or {}).items():
        if isinstance(md, dict):
            for o in md.get("options", []) or []:
                if isinstance(o, dict) and (o.get("home_team") or o.get("away_team")):
                    return o.get("home_team"), o.get("away_team")
    return None, None

def scan_edges(request_data: dict) -> dict:
    """analysis <-> fixture: distinct matches can't share an identical pre-match analysis."""
    p = request_data.get("params", {}) or request_data
    try: docs = _docs("sportradar-fixture", {"value.has_pre_match_research": True}, _limit(p))
    except Exception as ex:
        return {"status": True, "data": {"health": {"edge": "analysis<->fixture", "error": str(ex)}, "flagged": []}}
    enriched = []
    for d in docs:
        v = d.get("value", {}) or {}
        tf = (v.get("pre_match_research") or {}).get("team_form") or {}
        ha = ((tf.get("home") or {}).get("analysis") or "").strip()
        title = re.sub(r"\s*\(\d+\)\s*$", "", str(v.get("title") or "")).strip()
        if ha and title: enriched.append((title, re.sub(r"\s+", " ", ha.lower())[:160]))
    groups = defaultdict(set)
    for title, key in enriched: groups[key].add(title)
    collapsed = {k: sorted(v) for k, v in groups.items() if len(v) > 1}
    broken = sum(len(v) - 1 for v in collapsed.values())
    flagged = [{"fixtures": v, "analysis": k[:120]} for k, v in list(collapsed.items())[:10]]
    n = len(enriched)
    health = {"edge": "analysis<->fixture", "sampled": n, "collapsed_groups": len(collapsed),
              "broken_edges": broken, "broken_rate_pct": round(100 * broken / n) if n else 0}
    return {"status": True, "data": {"health": health, "flagged": flagged}}

def scan_odds(request_data: dict) -> dict:
    """odd <-> market <-> fixture: a market's options must reference the fixture it declares."""
    p = request_data.get("params", {}) or request_data
    try: docs = _docs("entain-markets-tier3", {}, _limit(p))
    except Exception as ex:
        return {"status": True, "data": {"health": {"edge": "odd<->market<->fixture", "error": str(ex)}, "flagged": []}}
    n = broken = 0; flagged = []
    for d in docs:
        v = d.get("value", {}) or {}; top = v.get("bwin_fixture_id")
        fids, teams = set(), set()
        for _mt, md in (v.get("markets_tier3") or {}).items():
            if not isinstance(md, dict): continue
            for o in md.get("options", []) or []:
                if not isinstance(o, dict): continue
                if o.get("fixture_id"): fids.add(o["fixture_id"])
                ht, at = o.get("home_team"), o.get("away_team")
                if ht or at: teams.add((ht, at))
        if not (fids or teams): continue
        n += 1
        bad = (bool(fids) and (len(fids) > 1 or (top and top not in fids))) or (len(teams) > 1)
        if bad:
            broken += 1
            if len(flagged) < 10:
                flagged.append({"declared_fixture": top, "option_fixtures": sorted(fids)[:4],
                                "pairings": [list(t) for t in list(teams)[:4]]})
    health = {"edge": "odd<->market<->fixture", "sampled": n, "misattributed": broken,
              "broken_rate_pct": round(100 * broken / n) if n else 0}
    return {"status": True, "data": {"health": health, "flagged": flagged}}

def scan_link(request_data: dict) -> dict:
    """market -> fixture linkability: can each market be linked to a fixture? Deterministic
    (accent-normalized name match) links the cognates; the unresolved set (cross-language
    translations) is handed to the semantic resolver."""
    p = request_data.get("params", {}) or request_data
    lim = _limit(p)
    try:
        fdocs = _docs("sportradar-fixture", {}, max(lim, 300))
        mdocs = _docs("entain-markets-tier3", {}, lim)
    except Exception as ex:
        return {"status": True, "data": {"health": {"edge": "market->fixture(link)", "error": str(ex)}, "unresolved_sample": [], "fixture_universe": []}}
    fixture_keys = set(); universe = []
    for d in fdocs:
        v = d.get("value", {}) or {}
        for hk, ak in (("home_competitor_name", "away_competitor_name"),
                       ("home_competitor_name_original", "away_competitor_name_original")):
            h, a = v.get(hk), v.get(ak)
            if h and a: fixture_keys.add(frozenset([_norm(h), _norm(a)]))
        h, a = v.get("home_competitor_name"), v.get("away_competitor_name")
        if h and a: universe.append(f"{h} vs {a}")
    total = linked = 0; unresolved = []
    for d in mdocs:
        v = d.get("value", {}) or {}
        ht, at = _pairing(v)
        if not (ht and at): continue
        total += 1
        if frozenset([_norm(ht), _norm(at)]) in fixture_keys: linked += 1
        else: unresolved.append(f"{ht} vs {at}")
    health = {"edge": "market->fixture(link)", "markets": total, "linked_deterministic": linked,
              "det_link_rate_pct": round(100 * linked / total) if total else 0, "unresolved": len(unresolved)}
    return {"status": True, "data": {"health": health,
            "unresolved_sample": unresolved[:25], "fixture_universe": sorted(set(universe))[:150]}}
'''

EVAL_SCHEMA = {"title": "ContextGraphAssessment", "type": "object", "properties": {
    "assessment": {"type": "string"}}, "required": ["assessment"]}
EVAL_INSTR = (
    "You audit a sports **Context Graph**. You receive edge-health counts (_1-health) and a list of "
    "flagged broken edges (_2-flagged) for ONE edge type. A broken edge means data attributed to the "
    "WRONG entity — e.g. a pre-match analysis or an odds line filed under the wrong fixture.\n"
    "Write a precise 2-3 sentence assessment for an engineering/exec reader: name the edge, how many "
    "are broken and the rate, plus ONE concrete example drawn from _2-flagged. If nothing is broken, "
    "state plainly that the edge is internally consistent. Be terse and factual — no advice, no fluff.")

LINK_SCHEMA = {"title": "ContextGraphLink", "type": "object", "properties": {
    "recovered": {"type": "integer"}, "orphans": {"type": "integer"}, "assessment": {"type": "string"}},
    "required": ["recovered", "orphans", "assessment"]}
LINK_INSTR = (
    "You resolve a Context Graph **linkability** edge — the value a semantic layer adds over a "
    "deterministic join.\n"
    "_1-unresolved is a list of betting-market team pairings (often Portuguese, from the bookmaker) that "
    "a deterministic accent-normalized match could NOT link to a fixture. _2-fixtures is the list of real "
    "fixtures (team names, often English).\n"
    "For EACH unresolved pairing, decide whether the SAME match exists in _2-fixtures, accounting for "
    "language and spelling (e.g. 'Egito vs Austrália' = 'Egypt vs Australia'; 'Alemanha vs Paraguai' = "
    "'Germany vs Paraguay'). Count how many you can confidently link (recovered) vs genuine orphans (no "
    "matching fixture). Output recovered (int), orphans (int), and a 2-sentence assessment naming ONE "
    "recovered example (PT→EN) — this is exactly the link a deterministic join misses.")

# --- workflow fragments ---
HVAL = ("{'edge':$.get('cg_health', {}).get('edge','?'),'health':$.get('cg_health', {}),"
        "'flagged':$.get('cg_flagged', []),'assessment':$.get('cg_summary', {}).get('assessment',''),"
        "'generator':'context-verify v0'}")
LINKVAL = ("{'edge':'market->fixture(link)','health':$.get('cg_health', {}),"
           "'recovered_by_semantic':$.get('cg_link', {}).get('recovered',0),"
           "'orphans':$.get('cg_link', {}).get('orphans',0),"
           "'assessment':$.get('cg_link', {}).get('assessment',''),"
           "'unresolved_sample':$.get('cg_unresolved', []),'generator':'context-verify link v0'}")


def _audit_workflow(name, title, desc, scan_command):
    return {"name": name, "title": title, "status": "active", "description": desc,
            "context-variables": CTX_VARS, "inputs": {"limit": "$.get('limit', 200)"},
            "outputs": {"health": "$.get('cg_health', {})",
                        "assessment": "$.get('cg_summary', {}).get('assessment','')", "workflow-status": "'executed'"},
            "tasks": [
                {"name": "scan", "type": "connector", "connector": {"command": scan_command, "name": "context-verify-tools"},
                 "inputs": {"limit": "$.get('limit', 200)"},
                 "outputs": {"cg_health": "$.get('health')", "cg_flagged": "$.get('flagged')"}},
                {"name": "context-verify-eval", "type": "prompt", "connector": GENAI,
                 "inputs": {"_1-health": "$.get('cg_health', {})", "_2-flagged": "$.get('cg_flagged', [])"},
                 "outputs": {"cg_summary": "$"}},
                {"name": "save-health", "type": "document",
                 "config": {"action": "save", "embed-vector": False, "force-update": True},
                 "documents": {"context_graph_health": HVAL}},
            ]}


def _link_workflow():
    return {"name": "context-verify-link", "title": "Context Verify Link", "status": "active",
            "description": "audit market->fixture linkability (deterministic + semantic recovery)",
            "context-variables": CTX_VARS, "inputs": {"limit": "$.get('limit', 200)"},
            "outputs": {"health": "$.get('cg_health', {})",
                        "recovered": "$.get('cg_link', {}).get('recovered',0)", "workflow-status": "'executed'"},
            "tasks": [
                {"name": "scan", "type": "connector", "connector": {"command": "scan_link", "name": "context-verify-tools"},
                 "inputs": {"limit": "$.get('limit', 200)"},
                 "outputs": {"cg_health": "$.get('health')", "cg_unresolved": "$.get('unresolved_sample')", "cg_fixtures": "$.get('fixture_universe')"}},
                {"name": "context-link-eval", "type": "prompt", "connector": GENAI,
                 "inputs": {"_1-unresolved": "$.get('cg_unresolved', [])", "_2-fixtures": "$.get('cg_fixtures', [])"},
                 "outputs": {"cg_link": "$"}},
                {"name": "save-health", "type": "document",
                 "config": {"action": "save", "embed-vector": False, "force-update": True},
                 "documents": {"context_graph_health": LINKVAL}},
            ]}


def definitions():
    tools = {"name": "context-verify-tools", "title": "Context Verify Tools", "status": "active",
             "description": "deterministic edge scanners (analysis + odds + linkability)",
             "filename": "context_verify.py", "filetype": "pyscript", "filecontent": SCAN_SRC,
             "commands": [{"name": "Scan", "value": "scan_edges"}, {"name": "ScanOdds", "value": "scan_odds"},
                          {"name": "ScanLink", "value": "scan_link"}]}
    evaluate = {"name": "context-verify-eval", "title": "Context Verify Eval", "type": "prompt", "status": "active",
                "description": "edge-agnostic semantic lens over graph-health findings",
                "instruction": EVAL_INSTR, "schema": EVAL_SCHEMA}
    link_eval = {"name": "context-link-eval", "title": "Context Link Eval", "type": "prompt", "status": "active",
                 "description": "semantic resolver for the market->fixture linkability edge",
                 "instruction": LINK_INSTR, "schema": LINK_SCHEMA}
    wf_a = _audit_workflow("context-verify", "Context Verify", "audit the analysis<->fixture edge", "scan_edges")
    wf_o = _audit_workflow("context-verify-odds", "Context Verify Odds", "audit the odd<->market<->fixture edge", "scan_odds")
    wf_l = _link_workflow()
    runner = {"name": "context-verify-runner", "title": "Context Verify Runner", "status": "inactive", "scheduled": False,
              "description": "on-demand executor — runs every edge audit",
              "context-agent": {"limit": "$.get('limit', 200)"},
              "workflows": [
                  {"name": "context-verify", "description": "analysis<->fixture", "inputs": {"limit": "$.get('limit', 200)"}, "outputs": {"health": "$.get('health', {})"}},
                  {"name": "context-verify-odds", "description": "odd<->market<->fixture", "inputs": {"limit": "$.get('limit', 200)"}, "outputs": {"health": "$.get('health', {})"}},
                  {"name": "context-verify-link", "description": "market->fixture linkability", "inputs": {"limit": "$.get('limit', 200)"}, "outputs": {"health": "$.get('health', {})"}},
              ]}
    return [("connector", tools), ("prompt", evaluate), ("prompt", link_eval),
            ("workflow", wf_a), ("workflow", wf_o), ("workflow", wf_l), ("agent", runner)]


def _run_once():
    print("\nRunning context-verify (all edges, async) ...")
    _req("POST", "agent/executor/context-verify-runner",
         {"context-agent": {"limit": 200}, "agent-config": {"delay": True}})
    seen = {}
    waited = 0
    while waited < 150 and len(seen) < 3:
        time.sleep(7)
        waited += 7
        d = _req("POST", "document/search",
                 {"filters": {"name": "context_graph_health"}, "sorters": ["created", -1], "page_size": 8}).get("data", [])
        for doc in d:
            v = doc.get("value") or {}
            edge = (v.get("health") or {}).get("edge")
            if edge and edge not in seen:
                seen[edge] = v
    if not seen:
        print("  (no health docs yet — re-run, or check the pod)")
        return
    print("\n=== Context Graph — edge health (saved in the pod) ===")
    for edge, v in seen.items():
        h = v.get("health") or {}
        extra = ""
        if "recovered_by_semantic" in v:
            extra = f"  recovered by semantic: {v.get('recovered_by_semantic')} | orphans: {v.get('orphans')}"
        print(f"\n  edge       : {edge}")
        print(f"  health     : {json.dumps({k: h[k] for k in h if k != 'edge'}, ensure_ascii=False)}")
        if extra:
            print(extra)
        print(f"  assessment : {v.get('assessment','')}")


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
