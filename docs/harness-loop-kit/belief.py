"""Bayesian investigator for Context Graph edges -- belief state v0.

Pure, deterministic, stdlib-only. This file is embedded VERBATIM into the
`context-verify-tools` connector (it runs server-side in the pod, exec'd from the DB)
and is also imported locally by the tests and by `context-verify.py --replay`, so the
same code produces the same belief in both places. Keep it free of pod imports and of
any `__main__` block (the pod exec's the source; module-level code runs there).

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
"""
import math

BELIEF_VERSION = "belief v0"

# Raw broken-count field per edge (exact signal; the rounded rate can hide 1/500).
COUNT_FIELD = {"analysis<->fixture": "broken_edges", "odd<->market<->fixture": "misattributed"}

# Below this posterior mass on the leading cause the investigator calls itself undecided
# and keeps running the cheapest informative experiment (a heal round) instead of acting
# on a guess -- the anti-anchoring rule.
UNDECIDED_BELOW = 0.5

# Hypothesis catalog per edge: the competing causes of "broken > 0". Priors sum to 1 and
# encode where incidents on this edge have historically come from (the #705 class first).
#   automatable      the heal step may act on this cause by itself
#   not_a_defect     under this cause the count is not a live incident (no heal, no page)
#   root_cause_human healing only treats the symptom; a human owns the root cause
#   needs_heal       only a meaningful hypothesis when auto-heal is configured
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
}

# Likelihood table P(evidence = value | cause). A cause missing from a row has likelihood
# 1.0 -- that evidence does not discriminate it. Numbers are operator judgment kept
# deliberately coarse: what matters is the direction and the audit trail, not precision.
LIKELIHOOD = {
    # did the broken count move after the last heal round? (only observable after a heal)
    "progress=improved": {"pipeline_batch_inheritance": 0.50, "stale_backlog_draining": 0.90,
                          "not_live_false_positive": 0.20, "heal_mechanism_failing": 0.10},
    "progress=stuck_1": {"pipeline_batch_inheritance": 0.50, "stale_backlog_draining": 0.15,
                         "not_live_false_positive": 0.80, "heal_mechanism_failing": 0.90},
    "progress=stuck_2plus": {"pipeline_batch_inheritance": 0.50, "stale_backlog_draining": 0.03,
                             "not_live_false_positive": 0.85, "heal_mechanism_failing": 0.95},
    # are the flagged fixtures the same ones as last scan, or freshly broken?
    "new_groups=new_breakage": {"pipeline_batch_inheritance": 0.80, "stale_backlog_draining": 0.15,
                                "not_live_false_positive": 0.30, "heal_mechanism_failing": 0.30},
    "new_groups=same_set": {"pipeline_batch_inheritance": 0.20, "stale_backlog_draining": 0.85,
                            "not_live_false_positive": 0.70, "heal_mechanism_failing": 0.70},
    # did the heal dispatches themselves succeed last round?
    "dispatch=errors": {"pipeline_batch_inheritance": 0.20, "stale_backlog_draining": 0.20,
                        "not_live_false_positive": 0.20, "heal_mechanism_failing": 0.90},
    "dispatch=clean": {"pipeline_batch_inheritance": 0.80, "stale_backlog_draining": 0.80,
                       "not_live_false_positive": 0.80, "heal_mechanism_failing": 0.10},
    # do we actually know the flagged fixtures are upcoming? (scan_edges: unknown_status_ids)
    "status=mostly_unknown": {"pipeline_batch_inheritance": 0.30, "stale_backlog_draining": 0.30,
                              "not_live_false_positive": 0.90, "heal_mechanism_failing": 0.30},
    "status=known_live": {"pipeline_batch_inheritance": 0.70, "stale_backlog_draining": 0.70,
                          "not_live_false_positive": 0.10, "heal_mechanism_failing": 0.70},
    # were the collapsed groups written within one pipeline batch? (scan_edges: batch_groups)
    "batch=signature": {"pipeline_batch_inheritance": 0.85, "stale_backlog_draining": 0.40,
                        "not_live_false_positive": 0.40, "heal_mechanism_failing": 0.40},
    "batch=spread": {"pipeline_batch_inheritance": 0.15, "stale_backlog_draining": 0.60,
                     "not_live_false_positive": 0.60, "heal_mechanism_failing": 0.60},
}


def hypotheses_for(edge, heal_configured=True):
    """The applicable hypotheses for an edge (heal-only ones drop out on detect-only pods)."""
    hs = [dict(h) for h in HYPOTHESES.get(edge, [])]
    if not heal_configured:
        hs = [h for h in hs if not h.get("needs_heal")]
    return hs


def edge_history(history, edge):
    """Keep only this edge's prior readings (newest first), tolerating a mixed trail."""
    return [v for v in (history or []) if isinstance(v, dict)
            and ((v.get("health") or {}).get("edge") == edge)]


def stuck_rounds(current_broken, history, count_field="broken_edges"):
    """Consecutive prior scans that attempted a heal WITHOUT the broken count improving,
    walking back from now. Progress resets the chain: 13 -> 10 -> 7 never counts,
    13 -> 13 -> 13 counts 2. Mirrors the legacy budget so the two never disagree."""
    n, cur = 0, current_broken
    for v in history or []:
        h = v.get("health") or {}
        broken = h.get(count_field) or 0
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


def observe(edge, health, flagged, history, heal_configured=True):
    """Turn the current scan + the trail into evidence: a list of (label, note).

    Every signal is deterministic and cheap -- it is computed from data the scan and the
    previous health docs already carry. Missing inputs (older docs without the new
    fields, first scan of an incident) simply produce no evidence for that signal."""
    ev = []
    count_field = COUNT_FIELD.get(edge, "broken_edges")
    broken = (health or {}).get(count_field) or 0
    prev = history[0] if history else None
    prev_h = (prev or {}).get("health") or {}
    prev_healed = (prev or {}).get("healed") or {}
    prev_broken = prev_h.get(count_field) or 0
    prev_attempted = (prev_healed.get("heal_count") or 0) > 0

    if prev_attempted and prev_broken > 0:
        if broken < prev_broken:
            ev.append(("progress=improved", "%s -> %s after a heal round" % (prev_broken, broken)))
        else:
            s = stuck_rounds(broken, history, count_field)
            label = "progress=stuck_2plus" if s >= 2 else "progress=stuck_1"
            ev.append((label, "%s -> %s after %s heal round(s) with no progress" % (prev_broken, broken, s)))

    cur_ids = _flagged_ids(flagged)
    prev_ids = _flagged_ids((prev or {}).get("flagged") or [])
    if cur_ids and prev_ids:
        new = cur_ids - prev_ids
        if len(new) / len(cur_ids) >= 0.5:
            ev.append(("new_groups=new_breakage",
                       "%s/%s flagged fixtures are new since the last scan" % (len(new), len(cur_ids))))
        else:
            ev.append(("new_groups=same_set",
                       "%s/%s flagged fixtures were already flagged last scan" % (len(cur_ids) - len(new), len(cur_ids))))

    if heal_configured and prev_attempted:
        items = [i for i in (prev_healed.get("healed") or []) if isinstance(i, dict)]
        errs = [i for i in items if i.get("error")]
        if items and len(errs) / len(items) >= 0.5:
            ev.append(("dispatch=errors", "%s/%s heal dispatches errored last round" % (len(errs), len(items))))
        elif items:
            ev.append(("dispatch=clean", "%s heal dispatches accepted last round" % len(items)))

    live_ids, unknown = (health or {}).get("live_ids"), (health or {}).get("unknown_status_ids")
    if isinstance(live_ids, int) and live_ids > 0 and isinstance(unknown, int):
        if unknown / live_ids >= 0.5:
            ev.append(("status=mostly_unknown",
                       "%s/%s flagged fixtures have no status (may already be finished)" % (unknown, live_ids)))
        else:
            ev.append(("status=known_live",
                       "%s/%s flagged fixtures are confirmed upcoming" % (live_ids - unknown, live_ids)))

    live_groups, batch_groups = (health or {}).get("live_groups"), (health or {}).get("batch_groups")
    if isinstance(live_groups, int) and live_groups > 0 and isinstance(batch_groups, int):
        if batch_groups / live_groups >= 0.5:
            ev.append(("batch=signature",
                       "%s/%s collapsed groups were written within one pipeline batch" % (batch_groups, live_groups)))
        else:
            ev.append(("batch=spread",
                       "%s/%s collapsed groups span separate pipeline runs" % (live_groups - batch_groups, live_groups)))
    return ev


def update(edge, evidence, heal_configured=True):
    """posterior ∝ prior · Π likelihood. Returns the hypotheses sorted by posterior."""
    hs = hypotheses_for(edge, heal_configured)
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
        reason = "auto-heal is not configured on this pod; most likely %s (%s%%)" % (top["cause"], pct)
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
    count_field = COUNT_FIELD.get(edge)
    health = health or {}
    if count_field is None:
        base["unsupported_edge"] = True
        return base
    if health.get("error"):
        base["scan_error"] = True
        return base
    broken = health.get(count_field) or 0
    if broken <= 0:
        return base
    hist = edge_history(history, edge)
    evidence = observe(edge, health, flagged, hist, heal_configured)
    posterior = update(edge, evidence, heal_configured)
    stuck = stuck_rounds(broken, hist, count_field)
    belief = dict(base)
    belief.update({"incident": True, "broken": broken, "heal_configured": bool(heal_configured),
                   "stuck_rounds": stuck, "hypotheses": posterior,
                   "evidence": ["%s (%s)" % (label, note) for label, note in evidence]})
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
