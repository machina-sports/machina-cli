"""Bayesian investigator for Context Graph edges -- belief state v0.

Pure, deterministic, stdlib-only. This file is embedded VERBATIM into the
`context-verify-tools` and `surface-verify-tools` connectors (they run server-side in the
pod, exec'd from the DB) and is also imported locally by the tests and by
`context-verify.py --replay`, so the same code produces the same belief everywhere. Keep
it free of pod imports and of any `__main__` block (the pod exec's the source; module-level
code runs there).

What it replaces. The heal step used to decide "what next" by COUNTING: repeat the same
remedy and, after N no-progress rounds, page a human. Counting answers how many times
healing failed -- not WHY. The investigator keeps a distribution over competing causes
for one edge and updates it from cheap, deterministic evidence every scan:

    posterior(H)  ∝  prior(H) · Π P(evidence_i | H)

Design rules (they matter more than the numbers):
  * Code decides, the LLM narrates. Hypotheses, priors and likelihoods live HERE, in a
    table a reviewer can read and argue with; the prompt only turns the resulting belief
    into a sentence for Slack.
  * Evidence is recomputed from the persisted health-doc trail on every scan -- no
    hidden state, no double counting. Each scan is a fresh process; the trail is the
    loop's only memory (same contract as the stuck-heal budget and the timeline).
  * The belief can only make healing MORE conservative: skip a heal that a not-a-defect
    hypothesis explains, or escalate EARLIER and WITH A REASON. It never dispatches more
    than the legacy no-progress budget allows -- that cap stays, fail-closed.
  * A belief is a distribution + cause codes + evidence lines. It is not chain-of-thought,
    it grants nothing, and it never enters a guardrail hot path.

Edges covered (v0):
  analysis<->fixture      count edge   heal = per-fixture re-research (opt-in)   VALIDATED LIVE
  odd<->market<->fixture  count edge   detect-only                               catalog only
  surface<->users         verdict edge heal = markets refresh on degraded:odds  catalog only
The odds and surface catalogs were written from the scanners' semantics and the known
failure modes, not from a live incident yet -- treat their numbers as a starting prior.
"""
import math

BELIEF_VERSION = "belief v0"

# Raw broken-count field per COUNT edge (exact signal; the rounded rate can hide 1/500).
COUNT_FIELD = {"analysis<->fixture": "broken_edges", "odd<->market<->fixture": "misattributed"}
# VERDICT edges: the incident is a degraded verdict, not a count.
DEGRADED_VERDICTS = {"surface<->users": ("degraded:odds", "degraded:errors")}

# Below this posterior mass on the leading cause the investigator calls itself undecided
# and keeps running the cheapest informative experiment (a heal round) instead of acting
# on a guess -- the anti-anchoring rule.
UNDECIDED_BELOW = 0.5

# Markets older than this are "stale" for the refresh-age evidence (odds + surface).
REFRESH_STALE_HOURS = 12.0

# Hypothesis catalog per edge: the competing causes of an incident. Priors sum to 1 per
# edge (per verdict, for verdict edges) and encode where incidents have historically come
# from.
#   automatable      the heal step may act on this cause by itself
#   not_a_defect     under this cause the incident is not a live defect (no heal, no page)
#   root_cause_human healing only treats the symptom; a human owns the root cause
#   needs_heal       only a meaningful hypothesis when auto-heal is configured
#   verdicts         (verdict edges) the verdicts this hypothesis explains
HYPOTHESES = {
    "analysis<->fixture": [
        {"cause": "pipeline_batch_inheritance", "prior": 0.40,
         "label": "the enrich pipeline copies one fixture's analysis across a whole batch (#705 class)",
         "remedy": "re-research each affected fixture (symptom); fix the batch step (root cause)",
         "automatable": True, "root_cause_human": True,
         "next_check": "do NEW collapsed groups keep appearing after heal rounds?"},
        {"cause": "stale_backlog_draining", "prior": 0.30,
         "label": "a one-off misattribution backlog that re-research is draining",
         "remedy": "keep re-researching; the backlog drains across scheduled scans",
         "automatable": True,
         "next_check": "does the broken count drop after each heal round?"},
        {"cause": "not_live_false_positive", "prior": 0.15,
         "label": "the flagged fixtures are finished or status-less; no upcoming page is affected",
         "remedy": "none (not a live defect) -- verify the fixture statuses",
         "automatable": False, "not_a_defect": True,
         "next_check": "are the flagged fixtures really upcoming matches?"},
        {"cause": "heal_mechanism_failing", "prior": 0.15,
         "label": "heal dispatches error out or never run (agent inactive, workflow missing)",
         "remedy": "inspect context-heal-runner dispatches and executions",
         "automatable": False, "root_cause_human": True, "needs_heal": True,
         "next_check": "did the last dispatches error, or is the heal-runner missing?"},
    ],
    "odd<->market<->fixture": [
        {"cause": "refresh_merge_collision", "prior": 0.35,
         "label": "the markets refresh merged options from two fixtures into one market doc",
         "remedy": "fix the refresh merge step; re-run the markets refresh for the affected seasons",
         "automatable": False, "root_cause_human": True,
         "next_check": "do flagged docs mix two team pairings, and do new ones keep appearing?"},
        {"cause": "bookmaker_id_remap", "prior": 0.25,
         "label": "the bookmaker re-issued a fixture id: the doc's declared id lags the options' id, same teams",
         "remedy": "re-run the markets refresh so the declared id catches up",
         "automatable": False, "root_cause_human": True,
         "next_check": "is the mismatch id-only (one pairing, one other id) rather than mixed content?"},
        {"cause": "multi_fixture_market_expected", "prior": 0.25,
         "label": "outright / group / special markets legitimately span several fixtures",
         "remedy": "none (not a defect) -- exclude outright-like market types from the edge",
         "automatable": False, "not_a_defect": True,
         "next_check": "are the flagged market types outright-like rather than match markets?"},
        {"cause": "stale_unrefreshed_markets", "prior": 0.15,
         "label": "the markets refresh has not run for a while; the docs are frozen in a past incident",
         "remedy": "check the refresh agent; run the markets refresh",
         "automatable": False, "root_cause_human": True,
         "next_check": "how old is the newest market doc?"},
    ],
    "surface<->users": [
        # degraded:odds -- real users are not seeing odds
        {"cause": "markets_not_refreshed", "prior": 0.40, "verdicts": ("degraded:odds",),
         "label": "odds are stale or missing because the markets refresh stopped running",
         "remedy": "re-run the markets refresh (the odds heal)",
         "automatable": True,
         "next_check": "does odds/session recover after the refresh runs?"},
        {"cause": "bookmaker_api_failure", "prior": 0.25, "verdicts": ("degraded:odds",),
         "label": "the refresh runs but the bookmaker API fails or returns nothing",
         "remedy": "check bookmaker credentials and API status",
         "automatable": False, "root_cause_human": True, "needs_heal": True,
         "next_check": "did the refresh error out, or run without bringing the odds back?"},
        {"cause": "widget_regression", "prior": 0.20, "verdicts": ("degraded:odds",),
         "label": "odds exist and are fresh, but the widget no longer renders or emits its event",
         "remedy": "inspect the latest frontend release and the widget",
         "automatable": False, "root_cause_human": True,
         "next_check": "are markets fresh while odds/session stays collapsed?"},
        {"cause": "traffic_mix_shift", "prior": 0.15, "verdicts": ("degraded:odds",),
         "label": "a surge of sessions from a surface without the widget (in-app webview, campaign traffic)",
         "remedy": "none (not a defect of the odds) -- segment the metric by surface",
         "automatable": False, "not_a_defect": True,
         "next_check": "did sessions spike while errors stayed normal?"},
        # degraded:errors -- chat errors / exceptions per session spiked
        {"cause": "frontend_regression", "prior": 0.40, "verdicts": ("degraded:errors",),
         "label": "a release introduced client-side exceptions",
         "remedy": "inspect the latest frontend deploy; roll back if needed",
         "automatable": False, "root_cause_human": True,
         "next_check": "are exceptions (not chat errors) the bulk of the spike?"},
        {"cause": "upstream_chat_failures", "prior": 0.40, "verdicts": ("degraded:errors",),
         "label": "the chat backend or the LLM provider is failing requests",
         "remedy": "check the pod's workflow executions and the provider status",
         "automatable": False, "root_cause_human": True,
         "next_check": "are chat errors (not exceptions) the bulk of the spike?"},
        {"cause": "abusive_traffic", "prior": 0.20, "verdicts": ("degraded:errors",),
         "label": "a burst of sessions producing errors (bots, abuse)",
         "remedy": "inspect traffic sources; rate-limit",
         "automatable": False, "root_cause_human": True,
         "next_check": "did sessions spike together with the errors?"},
    ],
}

# Likelihood table P(evidence = value | cause). A cause missing from a row has likelihood
# 1.0 -- that evidence does not discriminate it. Causes are unique across edges, so one
# table serves every catalog. Numbers are operator judgment kept deliberately coarse: what
# matters is the direction and the audit trail, not precision.
LIKELIHOOD = {
    # --- generic: did the last heal round move the incident? (only observable after a heal)
    "progress=improved": {"pipeline_batch_inheritance": 0.50, "stale_backlog_draining": 0.90,
                          "not_live_false_positive": 0.20, "heal_mechanism_failing": 0.10},
    "progress=stuck_1": {"pipeline_batch_inheritance": 0.50, "stale_backlog_draining": 0.15,
                         "not_live_false_positive": 0.80, "heal_mechanism_failing": 0.90,
                         "markets_not_refreshed": 0.15, "bookmaker_api_failure": 0.80,
                         "widget_regression": 0.85, "traffic_mix_shift": 0.80},
    "progress=stuck_2plus": {"pipeline_batch_inheritance": 0.50, "stale_backlog_draining": 0.03,
                             "not_live_false_positive": 0.85, "heal_mechanism_failing": 0.95,
                             "markets_not_refreshed": 0.05, "bookmaker_api_failure": 0.90,
                             "widget_regression": 0.90, "traffic_mix_shift": 0.85},
    # --- generic: are the flagged items the same ones as last scan, or freshly broken?
    "new_groups=new_breakage": {"pipeline_batch_inheritance": 0.80, "stale_backlog_draining": 0.15,
                                "not_live_false_positive": 0.30, "heal_mechanism_failing": 0.30,
                                "refresh_merge_collision": 0.80, "bookmaker_id_remap": 0.60,
                                "multi_fixture_market_expected": 0.30, "stale_unrefreshed_markets": 0.20},
    "new_groups=same_set": {"pipeline_batch_inheritance": 0.20, "stale_backlog_draining": 0.85,
                            "not_live_false_positive": 0.70, "heal_mechanism_failing": 0.70},
    # --- generic: did the heal dispatches themselves succeed last round?
    "dispatch=errors": {"pipeline_batch_inheritance": 0.20, "stale_backlog_draining": 0.20,
                        "not_live_false_positive": 0.20, "heal_mechanism_failing": 0.90,
                        "markets_not_refreshed": 0.30, "bookmaker_api_failure": 0.90,
                        "widget_regression": 0.10, "traffic_mix_shift": 0.10},
    "dispatch=clean": {"pipeline_batch_inheritance": 0.80, "stale_backlog_draining": 0.80,
                       "not_live_false_positive": 0.80, "heal_mechanism_failing": 0.10,
                       "markets_not_refreshed": 0.70, "bookmaker_api_failure": 0.40,
                       "widget_regression": 0.90, "traffic_mix_shift": 0.90},
    # --- analysis<->fixture: do we KNOW the flagged fixtures are upcoming? one pipeline batch?
    "status=mostly_unknown": {"pipeline_batch_inheritance": 0.30, "stale_backlog_draining": 0.30,
                              "not_live_false_positive": 0.90, "heal_mechanism_failing": 0.30},
    "status=known_live": {"pipeline_batch_inheritance": 0.70, "stale_backlog_draining": 0.70,
                          "not_live_false_positive": 0.10, "heal_mechanism_failing": 0.70},
    "batch=signature": {"pipeline_batch_inheritance": 0.85, "stale_backlog_draining": 0.40,
                        "not_live_false_positive": 0.40, "heal_mechanism_failing": 0.40},
    "batch=spread": {"pipeline_batch_inheritance": 0.15, "stale_backlog_draining": 0.60,
                     "not_live_false_positive": 0.60, "heal_mechanism_failing": 0.60},
    # --- odd<->market<->fixture: what kind of mismatch, what kind of market, how old
    "mismatch=content": {"refresh_merge_collision": 0.90, "bookmaker_id_remap": 0.15,
                         "multi_fixture_market_expected": 0.70, "stale_unrefreshed_markets": 0.50},
    "mismatch=id_only": {"refresh_merge_collision": 0.10, "bookmaker_id_remap": 0.85,
                         "multi_fixture_market_expected": 0.30, "stale_unrefreshed_markets": 0.50},
    "market_types=outright_like": {"refresh_merge_collision": 0.20, "bookmaker_id_remap": 0.20,
                                   "multi_fixture_market_expected": 0.90, "stale_unrefreshed_markets": 0.40},
    "market_types=match_like": {"refresh_merge_collision": 0.80, "bookmaker_id_remap": 0.80,
                                "multi_fixture_market_expected": 0.10, "stale_unrefreshed_markets": 0.60},
    # --- refresh age (odds edge AND surface degraded:odds): how old is the newest market doc?
    "refresh_age=stale": {"refresh_merge_collision": 0.40, "bookmaker_id_remap": 0.40,
                          "multi_fixture_market_expected": 0.50, "stale_unrefreshed_markets": 0.90,
                          "markets_not_refreshed": 0.90, "bookmaker_api_failure": 0.70,
                          "widget_regression": 0.20, "traffic_mix_shift": 0.40},
    "refresh_age=fresh": {"refresh_merge_collision": 0.60, "bookmaker_id_remap": 0.60,
                          "multi_fixture_market_expected": 0.50, "stale_unrefreshed_markets": 0.10,
                          "markets_not_refreshed": 0.10, "bookmaker_api_failure": 0.30,
                          "widget_regression": 0.80, "traffic_mix_shift": 0.60},
    # --- surface<->users: traffic shape and error mix
    "sessions=spike": {"markets_not_refreshed": 0.30, "bookmaker_api_failure": 0.30,
                       "widget_regression": 0.30, "traffic_mix_shift": 0.85,
                       "frontend_regression": 0.30, "upstream_chat_failures": 0.30, "abusive_traffic": 0.85},
    "sessions=normal": {"markets_not_refreshed": 0.70, "bookmaker_api_failure": 0.70,
                        "widget_regression": 0.70, "traffic_mix_shift": 0.20,
                        "frontend_regression": 0.70, "upstream_chat_failures": 0.70, "abusive_traffic": 0.20},
    "error_mix=exceptions": {"frontend_regression": 0.85, "upstream_chat_failures": 0.15, "abusive_traffic": 0.50},
    "error_mix=chat": {"frontend_regression": 0.15, "upstream_chat_failures": 0.85, "abusive_traffic": 0.50},
}


def supported(edge):
    return edge in COUNT_FIELD or edge in DEGRADED_VERDICTS


def broken_of(edge, health):
    """The incident magnitude of a reading: the raw broken count for count edges, 1/0 for
    verdict edges (degraded or not)."""
    health = health or {}
    if edge in DEGRADED_VERDICTS:
        return 1 if health.get("verdict") in DEGRADED_VERDICTS[edge] else 0
    field = COUNT_FIELD.get(edge)
    return (health.get(field) or 0) if field else 0


def hypotheses_for(edge, heal_configured=True, verdict=None):
    """The applicable hypotheses for an edge: heal-only ones drop out on detect-only pods,
    and verdict edges keep only the causes that explain the current verdict."""
    hs = [dict(h) for h in HYPOTHESES.get(edge, [])]
    if not heal_configured:
        hs = [h for h in hs if not h.get("needs_heal")]
    if verdict is not None:
        hs = [h for h in hs if not h.get("verdicts") or verdict in h["verdicts"]]
    return hs


def edge_history(history, edge):
    """Keep only this edge's prior readings (newest first), tolerating a mixed trail."""
    return [v for v in (history or []) if isinstance(v, dict)
            and ((v.get("health") or {}).get("edge") == edge)]


def stuck_rounds(edge, current_broken, history):
    """Consecutive prior scans that attempted a heal WITHOUT the incident improving,
    walking back from now. Progress resets the chain: 13 -> 10 -> 7 never counts,
    13 -> 13 -> 13 counts 2. Mirrors the legacy budget so the two never disagree."""
    n, cur = 0, current_broken
    for v in history or []:
        broken = broken_of(edge, v.get("health"))
        attempted = ((v.get("healed") or {}).get("heal_count") or 0) > 0
        if broken > 0 and attempted and cur >= broken:
            n += 1
            cur = broken
        else:
            break
    return n


def _flagged_ids(flagged):
    ids = set()
    for g in flagged or []:
        if isinstance(g, dict):
            for fid in g.get("fixture_ids") or []:
                if fid:
                    ids.add(str(fid))
    return ids


def _ratio_label(health, num_key, den_key, hi_label, lo_label, note_hi, note_lo, threshold=0.5):
    """Evidence from a numerator/denominator pair the scanner emitted, or None when absent."""
    num, den = (health or {}).get(num_key), (health or {}).get(den_key)
    if not (isinstance(num, (int, float)) and isinstance(den, (int, float)) and den > 0):
        return None
    if num / den >= threshold:
        return (hi_label, note_hi % (num, den))
    return (lo_label, note_lo % (den - num, den))


def observe(edge, health, flagged, history, heal_configured=True):
    """Turn the current scan + the trail into evidence: a list of (label, note).

    Every signal is deterministic and cheap -- it is computed from data the scan and the
    previous health docs already carry. Missing inputs (older docs without the new
    fields, first scan of an incident) simply produce no evidence for that signal."""
    ev = []
    health = health or {}
    broken = broken_of(edge, health)
    prev = history[0] if history else None
    prev_h = (prev or {}).get("health") or {}
    prev_healed = (prev or {}).get("healed") or {}
    prev_broken = broken_of(edge, prev_h)
    prev_attempted = (prev_healed.get("heal_count") or 0) > 0

    # generic: progress after a heal round
    if prev_attempted and prev_broken > 0:
        if broken < prev_broken:
            ev.append(("progress=improved", "%s -> %s after a heal round" % (prev_broken, broken)))
        else:
            s = stuck_rounds(edge, broken, history)
            label = "progress=stuck_2plus" if s >= 2 else "progress=stuck_1"
            ev.append((label, "%s -> %s after %s heal round(s) with no progress" % (prev_broken, broken, s)))

    # generic: same flagged items as last scan?
    cur_ids = _flagged_ids(flagged)
    prev_ids = _flagged_ids((prev or {}).get("flagged") or [])
    if cur_ids and prev_ids:
        new = cur_ids - prev_ids
        if len(new) / len(cur_ids) >= 0.5:
            ev.append(("new_groups=new_breakage",
                       "%s/%s flagged items are new since the last scan" % (len(new), len(cur_ids))))
        elif prev_attempted:
            # "same items as last scan" only discriminates AFTER a heal round: healed items
            # leave the set, so what remains is the backlog. With nothing healed in between,
            # every hypothesis predicts the same set -- no evidence either way.
            ev.append(("new_groups=same_set",
                       "%s/%s flagged items were already flagged last scan" % (len(cur_ids) - len(new), len(cur_ids))))

    # generic: did the heal dispatches themselves succeed?
    if heal_configured and prev_attempted:
        items = [i for i in (prev_healed.get("healed") or []) if isinstance(i, dict)]
        errs = [i for i in items if i.get("error") or str(i.get("status", "")).lower() in ("error", "failed")]
        if items and len(errs) / len(items) >= 0.5:
            ev.append(("dispatch=errors", "%s/%s heal dispatches errored last round" % (len(errs), len(items))))
        elif items:
            ev.append(("dispatch=clean", "%s heal dispatches accepted last round" % len(items)))

    if edge == "analysis<->fixture":
        e = _ratio_label(health, "unknown_status_ids", "live_ids", "status=mostly_unknown", "status=known_live",
                         "%s/%s flagged fixtures have no status (may already be finished)",
                         "%s/%s flagged fixtures are confirmed upcoming")
        if e: ev.append(e)
        e = _ratio_label(health, "batch_groups", "live_groups", "batch=signature", "batch=spread",
                         "%s/%s collapsed groups were written within one pipeline batch",
                         "%s/%s collapsed groups span separate pipeline runs")
        if e: ev.append(e)

    if edge == "odd<->market<->fixture":
        e = _ratio_label(health, "flagged_id_only", "flagged_total", "mismatch=id_only", "mismatch=content",
                         "%s/%s flagged markets differ from their declared fixture by id only (same teams)",
                         "%s/%s flagged markets mix options or teams from more than one fixture")
        if e: ev.append(e)
        e = _ratio_label(health, "flagged_outright_like", "flagged_total", "market_types=outright_like",
                         "market_types=match_like",
                         "%s/%s flagged markets are outright/group/special types",
                         "%s/%s flagged markets are match markets")
        if e: ev.append(e)

    # refresh age: odds edge and the surface (how old is the newest market doc?)
    age = health.get("hours_since_refresh")
    if isinstance(age, (int, float)) and edge in ("odd<->market<->fixture", "surface<->users") \
            and (edge != "surface<->users" or health.get("verdict") == "degraded:odds"):
        if age >= REFRESH_STALE_HOURS:
            ev.append(("refresh_age=stale", "newest market doc is %sh old" % round(age, 1)))
        else:
            ev.append(("refresh_age=fresh", "newest market doc is %sh old" % round(age, 1)))

    if edge == "surface<->users":
        sessions, prev_sessions = health.get("sessions"), prev_h.get("sessions")
        if isinstance(sessions, (int, float)) and isinstance(prev_sessions, (int, float)) and prev_sessions > 0:
            if sessions >= 2 * prev_sessions:
                ev.append(("sessions=spike", "%s sessions vs %s last scan" % (sessions, prev_sessions)))
            else:
                ev.append(("sessions=normal", "%s sessions vs %s last scan" % (sessions, prev_sessions)))
        if health.get("verdict") == "degraded:errors":
            exc, chat = health.get("exceptions"), health.get("chat_err")
            if isinstance(exc, (int, float)) and isinstance(chat, (int, float)) and (exc + chat) > 0:
                if exc >= chat:
                    ev.append(("error_mix=exceptions", "%s exceptions vs %s chat errors" % (exc, chat)))
                else:
                    ev.append(("error_mix=chat", "%s chat errors vs %s exceptions" % (chat, exc)))
    return ev


def update(edge, evidence, heal_configured=True, verdict=None):
    """posterior ∝ prior · Π likelihood. Returns the hypotheses sorted by posterior."""
    hs = hypotheses_for(edge, heal_configured, verdict)
    if not hs:
        return []
    weights = {}
    for h in hs:
        w = float(h["prior"])
        for label, _note in evidence or []:
            w *= LIKELIHOOD.get(label, {}).get(h["cause"], 1.0)
        weights[h["cause"]] = w
    z = sum(weights.values()) or 1.0
    out = []
    for h in hs:
        out.append({"cause": h["cause"], "p": round(weights[h["cause"]] / z, 3), "prior": h["prior"],
                    "label": h["label"], "remedy": h["remedy"], "next_check": h["next_check"],
                    "automatable": bool(h.get("automatable"))})
    out.sort(key=lambda x: -x["p"])
    return out


def entropy_bits(posterior):
    return round(-sum(x["p"] * math.log2(x["p"]) for x in posterior if x["p"] > 0), 3)


def _meta(edge, cause):
    for h in HYPOTHESES.get(edge, []):
        if h["cause"] == cause:
            return h
    return {}


def decide(edge, posterior, stuck, max_attempts, heal_configured=True):
    """(action, escalate, reason, confidence) from the posterior.

    action: heal | skip_heal | none. The belief may only make healing more conservative;
    the legacy no-progress budget is kept as the hard cap (fail-closed)."""
    top = posterior[0]
    meta = _meta(edge, top["cause"])
    pct = int(round(top["p"] * 100))
    confidence = "high" if top["p"] >= 0.7 else "medium" if top["p"] >= UNDECIDED_BELOW else "low"
    action = "heal" if heal_configured else "none"
    escalate, reason = False, None
    if top["p"] >= UNDECIDED_BELOW and meta.get("not_a_defect"):
        action = "skip_heal" if heal_configured else "none"
    elif top["p"] >= UNDECIDED_BELOW and not meta.get("automatable"):
        action = "skip_heal" if heal_configured else "none"
        escalate = True
        reason = "%s (%s%%) has no automatable remedy: %s" % (top["cause"], pct, meta.get("remedy", "?"))
    elif meta.get("root_cause_human") and stuck >= 2:
        escalate = True
        reason = ("%s (%s%%): healing treats the symptom only, the root cause needs a human "
                  "(%s round(s) without progress)" % (top["cause"], pct, stuck))
    if not escalate and heal_configured and stuck >= max_attempts:
        escalate = True
        reason = "no progress after %s heal rounds (budget)" % stuck
    if not escalate and not heal_configured and top["p"] >= UNDECIDED_BELOW and not meta.get("not_a_defect"):
        escalate = True
        reason = "no auto-heal is wired for this edge here; most likely %s (%s%%)" % (top["cause"], pct)
    return action, escalate, reason, confidence


def explain_line(belief):
    """One deterministic sentence -- the fallback when the narrating prompt is unavailable."""
    hs = belief.get("hypotheses") or []
    if not hs:
        return "no hypothesis catalog for this edge yet"
    top = hs[0]
    pct = int(round(top["p"] * 100))
    labels = [e.split(" (", 1)[0] for e in belief.get("evidence") or []]
    because = ("because " + ", ".join(labels)) if labels else "on priors alone (first reading of this incident)"
    line = "Most likely %s (%s%%, %s confidence) %s. Next: %s" % (
        top["cause"], pct, belief.get("confidence", "?"), because, top["next_check"])
    if len(hs) > 1:
        line += " Runner-up: %s (%s%%)." % (hs[1]["cause"], int(round(hs[1]["p"] * 100)))
    return line


def investigate(edge, health, flagged, history, heal_configured=True, max_attempts=3):
    """The belief state for one scan of one edge. `history` = prior health-doc values,
    newest first (the current scan must NOT be in it). Never raises."""
    base = {"version": BELIEF_VERSION, "edge": edge, "incident": False, "action": "none",
            "escalate": False, "escalate_reason": None}
    health = health or {}
    if not supported(edge):
        base["unsupported_edge"] = True
        return base
    if health.get("error"):
        base["scan_error"] = True
        return base
    broken = broken_of(edge, health)
    if broken <= 0:
        return base
    verdict = health.get("verdict") if edge in DEGRADED_VERDICTS else None
    hist = edge_history(history, edge)
    evidence = observe(edge, health, flagged, hist, heal_configured)
    posterior = update(edge, evidence, heal_configured, verdict)
    stuck = stuck_rounds(edge, broken, hist)
    belief = dict(base)
    belief.update({"incident": True, "broken": broken, "heal_configured": bool(heal_configured),
                   "stuck_rounds": stuck, "hypotheses": posterior,
                   "evidence": ["%s (%s)" % (label, note) for label, note in evidence]})
    if verdict:
        belief["verdict"] = verdict
    if not posterior:
        belief.update({"unsupported_edge": True, "explain": explain_line(belief)})
        return belief
    action, escalate, reason, confidence = decide(edge, posterior, stuck, max_attempts, heal_configured)
    belief.update({"top": posterior[0]["cause"], "top_p": posterior[0]["p"], "confidence": confidence,
                   "entropy_bits": entropy_bits(posterior), "action": action, "escalate": escalate,
                   "escalate_reason": reason})
    belief["explain"] = explain_line(belief)
    return belief


def replay(values_oldest_first, edge, heal_configured=True, max_attempts=3):
    """What the investigator would have said at each scan of a persisted trail (oldest
    first). Retroactive and read-only: the same function the live connector runs."""
    out = []
    for i, v in enumerate(values_oldest_first or []):
        history = list(reversed(values_oldest_first[:i]))
        h = (v or {}).get("health") or {}
        out.append(investigate(edge, h, (v or {}).get("flagged") or [], history, heal_configured, max_attempts))
    return out
