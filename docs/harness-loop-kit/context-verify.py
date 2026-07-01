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

Self-healing: the linkability workflow doesn't just measure the gap — its semantic step
RESOLVES the cross-language links a deterministic join misses and PERSISTS them as
`context_graph_links` documents, feeding the client's centralized semantic layer. The
`context-verify-beat` agent runs the whole sweep on a schedule (self-evolving) — the
harness loop's verify + self-repair (Cap 8/8.2) applied to the data graph.

Provisions:
  connector context-verify-tools     scan_edges + scan_odds + scan_link
  prompt    context-verify-eval      edge-agnostic assessment (analysis, odds)
  prompt    context-link-eval        semantic resolver/healer for the linkability edge
  workflow  context-verify / -odds / -link   (-link writes context_graph_health + context_graph_links)
  agent     context-verify-runner    on-demand: every edge audit + heal
  agent     context-verify-beat      scheduled continuous sweep (inactive by default)

Usage:
    CLIENT_API_URL="https://<org>-<project>.org.machina.gg" \\
    API_TOKEN="<project X-Api-Token>" [MODEL="gemini-3.1-flash-lite"] \\
    [FIXTURE_DOC_NAME="sportradar-fixture"] [MARKETS_DOC_NAME="entain-markets-tier3"] \\
    python3 context-verify.py            # provision
    python3 context-verify.py --run      # provision, run all audits, print graph health
    python3 context-verify.py --teardown # remove

If this pod stores the same fixture/markets schema under a brand-prefixed doc name
(check with a document/search sample first — same field names, different `name`),
override FIXTURE_DOC_NAME / MARKETS_DOC_NAME instead of assuming the entain default.

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
# Document names are per-tenant: some pods write the same schema (bwin_fixture_id,
# markets_tier3, pre_match_research, ...) under a brand-prefixed doc name instead of
# the entain/sportradar default (e.g. SBOT's own pods use sportingbot-fixture /
# sportingbot-markets-tier3). Verified field-identical before relying on this -- override
# per pod at provision time; the default is unchanged so existing deployments are unaffected.
FIXTURE_DOC_NAME = os.environ.get("FIXTURE_DOC_NAME", "sportradar-fixture")
MARKETS_DOC_NAME = os.environ.get("MARKETS_DOC_NAME", "entain-markets-tier3")
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
    # page cap follows the requested limit (was a hard `page <= 8` = max 400 docs, which
    # silently capped the fixture pull at 300 while 2k+ fixtures existed -> false orphans).
    while len(out) < limit and page <= (limit // 50 + 2):
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

# Deterministic tier of the semantic layer: national-team names are a finite, known
# set, so a PT/EN/abbrev -> canonical-code map links the bulk of cross-language pairs
# WITHOUT an LLM call and across the FULL fixture universe (no candidate truncation).
# The semantic LLM step is then reserved for the genuine long tail (spelling variants,
# entities not yet in the map). Raised the deterministic link rate 1% -> ~43% on staging.
COUNTRY_MAP = {
    "estados unidos": "us", "usa": "us", "united states": "us", "eua": "us",
    "bosnia": "ba", "bosnia and herzegovina": "ba", "bosnia e herzegovina": "ba",
    "holanda": "nl", "netherlands": "nl", "paises baixos": "nl",
    "marrocos": "ma", "morocco": "ma", "africa do sul": "za", "south africa": "za",
    "canada": "ca", "panama": "pa", "inglaterra": "eng", "england": "eng",
    "alemanha": "de", "germany": "de", "franca": "fr", "france": "fr",
    "suecia": "se", "sweden": "se", "egito": "eg", "egypt": "eg",
    "australia": "au", "austria": "at", "cabo verde": "cv", "cape verde": "cv",
    "argentina": "ar", "paraguai": "py", "paraguay": "py", "brasil": "br", "brazil": "br",
    "espanha": "es", "spain": "es", "uruguai": "uy", "uruguay": "uy",
    "belgica": "be", "belgium": "be", "nova zelandia": "nz", "new zealand": "nz",
    "arabia saudita": "sa", "saudi arabia": "sa", "japao": "jp", "japan": "jp",
    "coreia do sul": "kr", "south korea": "kr", "mexico": "mx", "portugal": "pt",
    "italia": "it", "italy": "it", "croacia": "hr", "croatia": "hr",
    "dinamarca": "dk", "denmark": "dk", "suica": "ch", "switzerland": "ch",
    "equador": "ec", "ecuador": "ec", "catar": "qa", "qatar": "qa",
    "senegal": "sn", "gana": "gh", "ghana": "gh", "camaroes": "cm", "cameroon": "cm",
    "nigeria": "ng", "tunisia": "tn", "argelia": "dz", "algeria": "dz",
    "colombia": "co", "peru": "pe", "chile": "cl", "costa rica": "cr",
    "polonia": "pl", "poland": "pl", "servia": "rs", "serbia": "rs",
    "gales": "wal", "wales": "wal", "escocia": "sco", "scotland": "sco",
    "noruega": "no", "norway": "no", "macedonia do norte": "mk", "north macedonia": "mk",
    "republica dominicana": "do", "dominican republic": "do", "rd congo": "cd",
    "republica democratica do congo": "cd", "dr congo": "cd", "congo dr": "cd",
    "jamaica": "jm", "nicaragua": "ni", "madagascar": "mg", "burundi": "bi",
    "costa do marfim": "ci", "ivory coast": "ci", "cote divoire": "ci", "cote d ivoire": "ci",
    "jordania": "jo", "jordan": "jo", "uzbequistao": "uz", "uzbekistan": "uz",
    "ira": "ir", "iran": "ir", "iraque": "iq", "iraq": "iq", "turquia": "tr", "turkey": "tr",
    "curacao": "cw", "haiti": "ht", "republica tcheca": "cz", "tchequia": "cz",
    "czech republic": "cz", "czechia": "cz", "russia": "ru", "ucrania": "ua", "ukraine": "ua",
    "grecia": "gr", "greece": "gr", "irlanda": "ie", "ireland": "ie", "venezuela": "ve",
    "bolivia": "bo", "honduras": "hn", "guatemala": "gt", "el salvador": "sv",
    "trinidad e tobago": "tt", "trinidad and tobago": "tt", "emirados arabes unidos": "ae",
    "uae": "ae", "nova caledonia": "nc", "new caledonia": "nc",
    # FIFA/fixture-side official name variants (the sportradar side often differs from common PT/EN)
    "korea republic": "kr", "korea dpr": "kp", "north korea": "kp", "coreia do norte": "kp",
    "ir iran": "ir", "china pr": "cn", "china": "cn", "turkiye": "tr", "czech republic": "cz",
}

def _canon(s):
    """Map a team name to a canonical country code when known; else fall back to _norm
    (so cognates still match and non-country names are unaffected)."""
    n = _norm(s)
    return COUNTRY_MAP.get(n, n)

def _sim(x, y):
    """Do two team names plausibly denote the same team? canonical-equal, substring, or
    >=50% token overlap. Used to GATE the LLM's semantic links."""
    if _canon(x) == _canon(y): return True
    nx, ny = _norm(x), _norm(y)
    if nx and ny and (nx in ny or ny in nx): return True
    tx, ty = set(nx.split()), set(ny.split())
    inter = tx & ty
    return bool(inter) and len(inter) / max(1, min(len(tx), len(ty))) >= 0.5

def _valid_link(mk, fx):
    """Deterministic gate over an LLM-proposed market->fixture link: BOTH teams must
    correspond (a bijection). Rejects partial/hallucinated matches like
    'Egito vs Irã' -> 'Australia vs Egypt' (Irã matches neither side)."""
    m, f = str(mk or "").split(" vs "), str(fx or "").split(" vs ")
    if len(m) != 2 or len(f) != 2: return False
    return (_sim(m[0], f[0]) and _sim(m[1], f[1])) or (_sim(m[0], f[1]) and _sim(m[1], f[0]))

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
        # Pull the FULL fixture set (not a 300-doc slice): markets must be linkable against
        # every fixture, not the first page. Markets are few; fixtures are the haystack.
        fdocs = _docs("sportradar-fixture", {}, max(lim, 5000))
        mdocs = _docs("entain-markets-tier3", {}, max(lim, 500))
    except Exception as ex:
        return {"status": True, "data": {"health": {"edge": "market->fixture(link)", "error": str(ex)}, "unresolved_sample": [], "fixture_universe": []}}
    fixture_keys = set(); universe = []; fidx_full = {}; canon_idx = {}
    for d in fdocs:
        v = d.get("value", {}) or {}
        sid = v.get("sport_event_id")
        for hk, ak in (("home_competitor_name", "away_competitor_name"),
                       ("home_competitor_name_original", "away_competitor_name_original")):
            h, a = v.get(hk), v.get(ak)
            if h and a: fixture_keys.add(frozenset([_canon(h), _canon(a)]))
        h, a = v.get("home_competitor_name"), v.get("away_competitor_name")
        if h and a:
            title = f"{h} vs {a}"; universe.append(title)
            if sid:
                fidx_full[title] = sid
                canon_idx[frozenset([_canon(h), _canon(a)])] = (title, sid)
    total = linked = 0; unresolved = []; midx = {}; det_links = []
    for d in mdocs:
        v = d.get("value", {}) or {}
        ht, at = _pairing(v)
        if not (ht and at): continue
        total += 1
        key = frozenset([_canon(ht), _canon(at)])
        if key in fixture_keys:
            linked += 1
            hit = canon_idx.get(key); bid = v.get("bwin_fixture_id")
            if hit and bid:
                det_links.append({"bwin_fixture_id": bid, "sport_event_id": hit[1],
                                  "market": f"{ht} vs {at}", "fixture": hit[0], "source": "deterministic"})
        else:
            pair = f"{ht} vs {at}"; unresolved.append(pair)
            if v.get("bwin_fixture_id"): midx[pair] = v["bwin_fixture_id"]
    # No silent caps: hand the FULL fixture universe + all unresolved markets to the
    # semantic step. Cap only as a prompt-size backstop, and REPORT anything dropped
    # (the old [:150] alphabetical cut silently hid ~half the fixtures -> false orphans).
    UNI_CAP, MKT_CAP = 600, 120
    uni_all = sorted(set(universe))
    uni = uni_all[:UNI_CAP]; sample = unresolved[:MKT_CAP]
    health = {"edge": "market->fixture(link)", "markets": total, "linked_deterministic": linked,
              "det_link_rate_pct": round(100 * linked / total) if total else 0, "unresolved": len(unresolved),
              "universe_dropped": len(uni_all) - len(uni), "unresolved_dropped": len(unresolved) - len(sample)}
    # market_index/fixture_index let a deterministic step attach ids to the semantic matches.
    return {"status": True, "data": {"health": health, "unresolved_sample": sample, "fixture_universe": uni,
            "deterministic_links": det_links,
            "market_index": {k: midx[k] for k in sample if k in midx},
            "fixture_index": {t: fidx_full[t] for t in uni if t in fidx_full}}}

def resolve_link_ids(request_data: dict) -> dict:
    """Attach ids to the semantic matches deterministically (no LLM id-handling):
    market pairing -> bwin_fixture_id, fixture title -> sport_event_id. The result is a
    usable bwin<->sportradar resolution table — the healed edge fed into the graph."""
    p = request_data.get("params", {}) or request_data
    matches = p.get("matches") or []
    mi = p.get("market_index") or {}
    fi = p.get("fixture_index") or {}
    # Start from the deterministic links (already id-resolved by scan_link), then add the
    # semantic recoveries on top -> a COMPLETE bwin<->sportradar resolution table.
    links = [l for l in (p.get("deterministic_links") or []) if isinstance(l, dict)]
    det_n = len(links); rejected = 0
    for m in matches:
        if not isinstance(m, dict): continue
        mk, fx = m.get("market"), m.get("fixture")
        if not _valid_link(mk, fx):   # deterministic gate: drop hallucinated/partial LLM links
            rejected += 1; continue
        bid, sid = mi.get(mk), fi.get(fx)
        if bid and sid:
            links.append({"bwin_fixture_id": bid, "sport_event_id": sid,
                          "market": mk, "fixture": fx, "source": "semantic-heal"})
    return {"status": True, "data": {"links": links, "resolved": len(links),
            "deterministic": det_n, "semantic": len(links) - det_n, "rejected": rejected}}
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
    "matches": {"type": "array", "items": {"type": "object", "properties": {
        "market": {"type": "string"}, "fixture": {"type": "string"}}, "required": ["market", "fixture"]}},
    "orphans": {"type": "array", "items": {"type": "string"}},
    "assessment": {"type": "string"}},
    "required": ["matches", "orphans", "assessment"]}
LINK_INSTR = (
    "You HEAL a Context Graph **linkability** edge — the value a semantic layer adds over a deterministic "
    "join.\n"
    "_1-unresolved is a list of betting-market team pairings (often Portuguese, from the bookmaker) that a "
    "deterministic accent-normalized match could NOT link to a fixture. _2-fixtures is the list of real "
    "fixtures (team names, often English).\n"
    "For EACH unresolved pairing, decide whether the SAME match exists in _2-fixtures, accounting for "
    "language and spelling (e.g. 'Egito vs Austrália' = 'Egypt vs Australia'; 'Alemanha vs Paraguai' = "
    "'Germany vs Paraguay').\n"
    "Output `matches`: for every pairing you can confidently link, an object {market: <the unresolved "
    "pairing, verbatim>, fixture: <the matching fixture from _2-fixtures, verbatim>}. Put pairings with NO "
    "matching fixture into `orphans` (verbatim). Do not invent fixtures — only link to entries present in "
    "_2-fixtures. Also a 2-sentence `assessment` naming ONE recovered example (PT→EN) — the link a "
    "deterministic join misses.")

# --- workflow fragments ---
HVAL = ("{'edge':$.get('cg_health', {}).get('edge','?'),'health':$.get('cg_health', {}),"
        "'flagged':$.get('cg_flagged', []),'assessment':$.get('cg_summary', {}).get('assessment',''),"
        "'generator':'context-verify v0'}")
LINKVAL = ("{'edge':'market->fixture(link)','health':$.get('cg_health', {}),"
           "'recovered_by_semantic':len($.get('cg_link', {}).get('matches', [])),"
           "'orphans':len($.get('cg_link', {}).get('orphans', [])),"
           "'assessment':$.get('cg_link', {}).get('assessment',''),"
           "'unresolved_sample':$.get('cg_unresolved', []),'generator':'context-verify link v0'}")
# The self-HEAL output: the recovered links, persisted back into the graph. This is the
# repaired sub-graph the loop feeds into the client's centralized semantic layer.
HEALVAL = ("{'edge':'market->fixture','links':$.get('cg_links', []),"
           "'healed_count':$.get('cg_resolved', 0),"
           "'deterministic_count':$.get('cg_det_count', 0),'semantic_count':$.get('cg_sem_count', 0),"
           "'rejected_count':$.get('cg_rejected', 0),"
           "'orphan_count':len($.get('cg_link', {}).get('orphans', [])),"
           "'orphans':$.get('cg_link', {}).get('orphans', []),"
           "'source':'deterministic+semantic','generator':'context-heal v2 (country-map + full universe)'}")


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
            "description": "heal market->fixture linkability (deterministic + semantic recovery, then persist the links)",
            "context-variables": CTX_VARS, "inputs": {"limit": "$.get('limit', 200)"},
            "outputs": {"health": "$.get('cg_health', {})",
                        "healed": "len($.get('cg_link', {}).get('matches', []))", "workflow-status": "'executed'"},
            "tasks": [
                {"name": "scan", "type": "connector", "connector": {"command": "scan_link", "name": "context-verify-tools"},
                 "inputs": {"limit": "$.get('limit', 200)"},
                 "outputs": {"cg_health": "$.get('health')", "cg_unresolved": "$.get('unresolved_sample')",
                             "cg_fixtures": "$.get('fixture_universe')", "cg_market_index": "$.get('market_index')",
                             "cg_fixture_index": "$.get('fixture_index')", "cg_det_links": "$.get('deterministic_links')"}},
                {"name": "context-link-eval", "type": "prompt", "connector": GENAI,
                 "inputs": {"_1-unresolved": "$.get('cg_unresolved', [])", "_2-fixtures": "$.get('cg_fixtures', [])"},
                 "outputs": {"cg_link": "$"}},
                # deterministic id-resolution: attach bwin_fixture_id + sport_event_id to the matches
                {"name": "resolve-ids", "type": "connector", "connector": {"command": "resolve_link_ids", "name": "context-verify-tools"},
                 "inputs": {"matches": "$.get('cg_link', {}).get('matches', [])",
                            "deterministic_links": "$.get('cg_det_links', [])",
                            "market_index": "$.get('cg_market_index', {})", "fixture_index": "$.get('cg_fixture_index', {})"},
                 "outputs": {"cg_links": "$.get('links')", "cg_resolved": "$.get('resolved')",
                             "cg_det_count": "$.get('deterministic')", "cg_sem_count": "$.get('semantic')",
                             "cg_rejected": "$.get('rejected')"}},
                {"name": "save-health", "type": "document",
                 "config": {"action": "save", "embed-vector": False, "force-update": True},
                 "documents": {"context_graph_health": LINKVAL}},
                # self-heal: persist the recovered links back into the graph
                {"name": "save-links", "type": "document",
                 "config": {"action": "save", "embed-vector": False, "force-update": True},
                 "documents": {"context_graph_links": HEALVAL}},
            ]}


def _scan_src_for_tenant():
    """SCAN_SRC with the two entain-specific doc names swapped for this pod's config.
    Plain string substitution (not .format()/f-string) because SCAN_SRC is full of
    literal { } from dict literals/comprehensions that would collide with either.
    json.dumps() re-quotes safely; with the defaults, this is a no-op (identical output)."""
    src = SCAN_SRC.replace('"sportradar-fixture"', json.dumps(FIXTURE_DOC_NAME))
    src = src.replace('"entain-markets-tier3"', json.dumps(MARKETS_DOC_NAME))
    return src


def definitions():
    tools = {"name": "context-verify-tools", "title": "Context Verify Tools", "status": "active",
             "description": "deterministic edge scanners (analysis + odds + linkability)",
             "filename": "context_verify.py", "filetype": "pyscript", "filecontent": _scan_src_for_tenant(),
             "commands": [{"name": "Scan", "value": "scan_edges"}, {"name": "ScanOdds", "value": "scan_odds"},
                          {"name": "ScanLink", "value": "scan_link"}, {"name": "ResolveIds", "value": "resolve_link_ids"}]}
    evaluate = {"name": "context-verify-eval", "title": "Context Verify Eval", "type": "prompt", "status": "active",
                "description": "edge-agnostic semantic lens over graph-health findings",
                "instruction": EVAL_INSTR, "schema": EVAL_SCHEMA}
    link_eval = {"name": "context-link-eval", "title": "Context Link Eval", "type": "prompt", "status": "active",
                 "description": "semantic resolver for the market->fixture linkability edge",
                 "instruction": LINK_INSTR, "schema": LINK_SCHEMA}
    wf_a = _audit_workflow("context-verify", "Context Verify", "audit the analysis<->fixture edge", "scan_edges")
    wf_o = _audit_workflow("context-verify-odds", "Context Verify Odds", "audit the odd<->market<->fixture edge", "scan_odds")
    wf_l = _link_workflow()
    edge_workflows = [
        {"name": "context-verify", "description": "analysis<->fixture", "inputs": {"limit": "$.get('limit', 200)"}, "outputs": {"health": "$.get('health', {})"}},
        {"name": "context-verify-odds", "description": "odd<->market<->fixture", "inputs": {"limit": "$.get('limit', 200)"}, "outputs": {"health": "$.get('health', {})"}},
        {"name": "context-verify-link", "description": "market->fixture linkability (heal)", "inputs": {"limit": "$.get('limit', 200)"}, "outputs": {"health": "$.get('health', {})"}},
    ]
    runner = {"name": "context-verify-runner", "title": "Context Verify Runner", "status": "inactive", "scheduled": False,
              "description": "on-demand executor — runs every edge audit + heal",
              "context-agent": {"limit": "$.get('limit', 200)"}, "workflows": edge_workflows}
    # self-evolving: a scheduled sweep that keeps the graph healed as new data lands.
    # Created INACTIVE (shared pod) — set status:active + tune config-frequency to enable.
    beat = {"name": "context-verify-beat", "title": "Context Verify Beat", "status": "inactive", "scheduled": True,
            "description": "continuous self-healing sweep of the context graph (set status:active to enable)",
            "context": {"config-frequency": 60}, "context-agent": {"limit": "$.get('limit', 200)"},
            "workflows": edge_workflows}
    return [("connector", tools), ("prompt", evaluate), ("prompt", link_eval),
            ("workflow", wf_a), ("workflow", wf_o), ("workflow", wf_l), ("agent", runner), ("agent", beat)]


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
    # self-heal: the persisted recovered links feeding the graph
    hl = _req("POST", "document/search",
              {"filters": {"name": "context_graph_links"}, "sorters": ["created", -1], "page_size": 1}).get("data", [])
    if hl:
        hv = hl[0].get("value") or {}
        links = hv.get("links") or []
        print(f"\n  >> self-heal: {hv.get('healed_count', len(links))} links persisted to context_graph_links "
              f"({hv.get('orphan_count', 0)} orphans)")
        for lk in links[:3]:
            print(f"       healed: {lk.get('bwin_fixture_id')} -> {lk.get('sport_event_id')}  ({lk.get('market')} -> {lk.get('fixture')})")


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
