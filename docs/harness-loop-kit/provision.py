#!/usr/bin/env python3
"""
Machina Harness Loop — reproducible provisioner.

Stands up the durable agentic turn loop ("harness") in ANY Machina project pod,
so a reviewer can validate it locally against real project data. Idempotent:
re-running deletes-by-name and recreates (PUT does a shallow merge on this API,
so nested `tasks`/`instruction` don't update reliably — delete+create is the
contract that works).

Usage:
    CLIENT_API_URL="https://<org>-<project>.org.machina.gg" \\
    API_TOKEN="<project X-Api-Token>" \\
    [MODEL="gemini-3.1-flash-lite"] \\
    [EVAL_MODEL="<a different/stronger model>"] \\
    [LOOP_MAX_ATTEMPTS="3"] \\
    python3 provision.py            # provision (default)
    python3 provision.py --teardown # remove all loop resources

What it creates (maps to the Loop-Engineering five moves — see VALIDATION.md):
    prompt    loop-reasoning   reason: answer directly or emit tool_calls   (discovery/decide)
    prompt    loop-respond     synthesize the final answer from tool output
    prompt    loop-evaluate    INDEPENDENT verifier: judge the answer        (verification)
    prompt    loop-repair      bounded self-repair of a rejected answer      (Cap 8.2)
    prompt    loop-evaluate-2  re-verify the repaired answer                 (Cap 8.2)
    connector loop-tools       dispatcher: calculate / get_datetime / echo / find_fixtures
    workflow  loop-turn        load -> ingest -> reason -> tool -> respond -> EVALUATE -> [repair -> re-eval] -> finalize
    workflow  loop-resume      beat path: resume an orphaned `active` session  (scheduling)
    agent     loop-runner      executor path (inactive; CLI/MCP invokes it)
    agent     loop-beat        durability tick (created INACTIVE by default)   (scheduling)

VERIFICATION (generator/evaluator separation — the playbook's "floor"):
    A turn is finalized `idle` (done) ONLY if it clears a deterministic gate
    (cheap, code-only — the Stripe-Minions pattern) AND an independent evaluator
    prompt (loop-evaluate; fresh context + skeptical posture, EVAL_MODEL). On any
    failure the session is marked `needs_review` — the human checkpoint, never a
    silent pass. The resume path adds an attempt budget (LOOP_MAX_ATTEMPTS) so the
    beat can never re-run a stuck session forever.
    Cap 8.2 — retry-with-critique: if the gate passed but the evaluator REJECTED the
    answer, the loop does ONE bounded repair pass (feeding the rejection reason back)
    and re-verifies before deciding idle vs needs_review (value.verification.repaired).
"""

import json
import os
import sys
import urllib.request
import urllib.error

BASE = os.environ.get("CLIENT_API_URL", "").rstrip("/")
TOKEN = os.environ.get("API_TOKEN", "")
MODEL = os.environ.get("MODEL", "gemini-3.1-flash-lite")
GENAI = {"command": "invoke_prompt", "location": "global", "model": MODEL,
         "name": "google-genai", "provider": "vertex_ai"}
# The evaluator should ideally be a DIFFERENT (fresh / stronger) model than the
# generator — the playbook's generator/evaluator separation. Defaults to MODEL so
# it always runs; override EVAL_MODEL to get true model diversity. Either way the
# evaluator gets a fresh context + a skeptical "assume broken" posture.
EVAL_MODEL = os.environ.get("EVAL_MODEL", MODEL)
GENAI_EVAL = {**GENAI, "model": EVAL_MODEL}
# Resume attempt budget — the stop condition that stops the beat re-running a
# stuck session forever (the playbook's "token blowout" guard).
MAX_ATTEMPTS = int(os.environ.get("LOOP_MAX_ATTEMPTS", "3"))
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


# --- loop-tools connector source (pyscript, exec'd from the DB at call time) ---
# Returns {status: True, data: {...}} — the connector contract; a bare dict is
# treated as a FAILED connector. Inputs arrive under request_data['params'].
LOOP_TOOLS_SRC = r'''"""Machina Loop Tools — meta-dispatcher (calculate/get_datetime/echo/find_fixtures)."""
import ast, json, operator
from datetime import datetime, timezone
_OPS={ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul,ast.Div:operator.truediv,ast.Pow:operator.pow,ast.Mod:operator.mod,ast.USub:operator.neg,ast.UAdd:operator.pos,ast.FloorDiv:operator.floordiv}
def _ev(n):
    if isinstance(n,ast.Constant) and isinstance(n.value,(int,float)): return n.value
    if isinstance(n,ast.BinOp) and type(n.op) in _OPS: return _OPS[type(n.op)](_ev(n.left),_ev(n.right))
    if isinstance(n,ast.UnaryOp) and type(n.op) in _OPS: return _OPS[type(n.op)](_ev(n.operand))
    raise ValueError("bad expr")
def _calc(a):
    e=str(a.get("expression","")).strip()
    if not e: return "error: no expression"
    try: return _ev(ast.parse(e,mode="eval").body)
    except Exception as ex: return "error: "+str(ex)
def _find_fixtures(a):
    # Real-data example tool: reads `sportradar-fixture` documents if the project
    # has them (e.g. an Entain coverage pod). Harmless elsewhere (returns "none").
    try:
        from core.document.controller import document_search
    except Exception as ex:
        return "find_fixtures unavailable: "+str(ex)
    team=str(a.get("team","")).strip()
    try: limit=int(a.get("limit",5))
    except Exception: limit=5
    filt={"name":"sportradar-fixture","value.status":"not_started"}
    if team: filt["value.title"]={"$regex":team,"$options":"i"}
    r=document_search(filters=filt,page=1,page_size=max(1,min(limit,8)),sorters=["value.start_time",1])
    dd=r.get("data") if isinstance(r,dict) else None
    docs=dd.get("data") if isinstance(dd,dict) else (dd if isinstance(dd,list) else [])
    out=[]
    for d in (docs or []):
        v=d.get("value",{}) or {}
        tf=(v.get("pre_match_research") or {}).get("team_form") or {}
        out.append({"match":v.get("title"),"kickoff_brt":v.get("brt_time") or v.get("start_time"),
                    "status":v.get("status"),"venue":v.get("venue_name"),
                    "home_analysis":(tf.get("home") or {}).get("analysis","")[:300] if v.get("has_pre_match_research") else "",
                    "away_analysis":(tf.get("away") or {}).get("analysis","")[:300] if v.get("has_pre_match_research") else ""})
    return out if out else "no upcoming fixtures found"+((" for team "+team) if team else "")
def dispatch(request_data: dict) -> dict:
    p=request_data.get("params",{}) or request_data
    tool=(p.get("tool_name") or "").strip()
    raw=p.get("args_json","{}")
    try:
        args=raw if isinstance(raw,dict) else (json.loads(raw) if isinstance(raw,str) and raw.strip() else {})
    except Exception:
        args={}
    if tool=="find_fixtures": r=_find_fixtures(args)
    elif tool=="get_datetime": r=datetime.now(timezone.utc).strftime("%A, %d %B %Y, %H:%M UTC")
    elif tool=="calculate": r=_calc(args)
    elif tool=="echo": r=str(args.get("text",""))
    else: r="unknown tool: "+tool
    return {"status": True, "data": {"tool_result": json.dumps(r, ensure_ascii=False, default=str)[:2800],
                                     "tool_ok": tool in ("find_fixtures","get_datetime","calculate","echo")}}
'''

CATALOG = [
    {"name": "find_fixtures", "params_hint": "team(str), limit(int=5)",
     "description": "Upcoming football fixtures (real project data) + AI pre-match analysis. Use for schedule / who-plays / pre-match questions."},
    {"name": "calculate", "params_hint": "expression*(str)", "description": "Evaluate arithmetic; never compute it yourself."},
    {"name": "get_datetime", "params_hint": "(no args)", "description": "Current UTC date/time."},
    {"name": "echo", "params_hint": "text*(str)", "description": "Echo text back verbatim."},
]

# --- workflow expression fragments (verified) ---
NEEDS = "$.get('reasoning', {}).get('needs_tool_call') is True"
USER = "{'id':'u'+str($.get('next_turn')),'turn':$.get('next_turn'),'role':'user','type':'message','content':$.get('input_message')}"
TC = ("{'id':'tc'+str($.get('next_turn')),'turn':$.get('next_turn'),'role':'assistant','type':'tool_call',"
      "'tool':$.get('reasoning', {}).get('tool_calls', [{}])[0].get('name','tool'),"
      "'content':$.get('reasoning', {}).get('tool_calls', [{}])[0].get('arguments_json','{}')}")
TR = "{'id':'tr'+str($.get('next_turn')),'turn':$.get('next_turn'),'role':'tool','type':'tool_result','content':$.get('tool_result_value','')}"
FA = "($.get('reasoning2', {}).get('assistant_message','') if (" + NEEDS + ") else $.get('reasoning', {}).get('assistant_message',''))"
ASST = "{'id':'a'+str($.get('next_turn')),'turn':$.get('next_turn'),'role':'assistant','type':'message','content':" + FA + "}"
ENTRIES = "[*$.get('existing_entries', []), " + USER + "] + ([" + TC + ", " + TR + "] if (" + NEEDS + ") else []) + [" + ASST + "]"
INEW = "{'session_id':$.get('session_id'),'persona_agent':$.get('persona_agent'),'turn':$.get('next_turn'),'status':'active','entries':[*$.get('existing_entries', []), " + USER + "]}"
IUPD = "{**$.get('existing_value', {}),'session_id':$.get('session_id'),'turn':$.get('next_turn'),'status':'active','entries':[*$.get('existing_entries', []), " + USER + "]}"
# --- verification: generator/evaluator separation (the playbook "floor") ---
# Deterministic gate (cheap, code-only — the Stripe-Minions pattern): a non-trivial
# answer, no error marker, and — if a tool ran — the tool actually succeeded.
GATE = ("(len((" + FA + " or '').strip()) > 4)"
        " and ('error:' not in (" + FA + " or '').lower())"
        " and (((" + NEEDS + ") is not True)"
        " or ($.get('tool_ok_value') is True and 'error' not in str($.get('tool_result_value','')).lower()))")
VPASS = "($.get('verdict_obj', {}).get('verdict','fail') == 'pass')"
VERIFIED = "((" + GATE + ") and " + VPASS + ")"
# idle ONLY if verified; else needs_review (the human checkpoint — "stay the engineer").
STATUS = "('idle' if " + VERIFIED + " else 'needs_review')"
VERIF = ("{'gate_pass':(" + GATE + "),"
         "'verdict':$.get('verdict_obj', {}).get('verdict','skipped'),"
         "'reason':$.get('verdict_obj', {}).get('reason',''),"
         "'severity':$.get('verdict_obj', {}).get('severity','none'),"
         "'model':'" + EVAL_MODEL + "'}")
# --- Cap 8.2: retry-with-critique (bounded self-repair) ---
# If the gate passed but the evaluator REJECTED the answer, do ONE repair pass (feed the
# rejection reason back) and re-evaluate. generator/evaluator -> .../repairer. A *gate*
# failure is never repaired here — it still goes straight to needs_review.
REPAIR_NEEDED = "((" + GATE + ") and ($.get('verdict_obj', {}).get('verdict','fail') == 'fail'))"
REPAIR_ANS = "$.get('repair', {}).get('assistant_message','')"
V2PASS = "($.get('verdict_obj2', {}).get('verdict','fail') == 'pass')"
# the kept answer: the repaired one if a repair happened, else the first answer.
FINAL_ANSWER = "(" + REPAIR_ANS + " if " + REPAIR_NEEDED + " else " + FA + ")"
VERIFIED2 = "(((" + GATE + ") and " + VPASS + ") or (" + REPAIR_NEEDED + " and " + V2PASS + "))"
STATUS2 = "('idle' if " + VERIFIED2 + " else 'needs_review')"
# verification reflects the OPERATIVE attempt (the repair's verdict, if we repaired).
VERIF2 = ("{'gate_pass':(" + GATE + "),"
          "'verdict':($.get('verdict_obj2', {}).get('verdict','skipped') if " + REPAIR_NEEDED + " else $.get('verdict_obj', {}).get('verdict','skipped')),"
          "'reason':($.get('verdict_obj2', {}).get('reason','') if " + REPAIR_NEEDED + " else $.get('verdict_obj', {}).get('reason','')),"
          "'severity':($.get('verdict_obj2', {}).get('severity','none') if " + REPAIR_NEEDED + " else $.get('verdict_obj', {}).get('severity','none')),"
          "'repaired':" + REPAIR_NEEDED + ",'model':'" + EVAL_MODEL + "'}")
# the stored assistant entry uses the FINAL (post-repair) answer.
ASST2 = "{'id':'a'+str($.get('next_turn')),'turn':$.get('next_turn'),'role':'assistant','type':'message','content':" + FINAL_ANSWER + "}"
ENTRIES2 = "[*$.get('existing_entries', []), " + USER + "] + ([" + TC + ", " + TR + "] if (" + NEEDS + ") else []) + [" + ASST2 + "]"
# attempts reset to 0 on a completed turn (the budget counts consecutive resume failures).
FVAL = ("{**$.get('existing_value', {}),'session_id':$.get('session_id'),'persona_agent':$.get('persona_agent'),"
        "'turn':$.get('next_turn'),'attempts':0,'status':" + STATUS2 + ",'verification':" + VERIF2 + ",'entries':" + ENTRIES2 + "}")
RAE = "{'id':'a'+str($.get('r_turn')),'turn':$.get('r_turn'),'role':'assistant','type':'message','content':$.get('reasoning', {}).get('assistant_message','')}"
# Resume path: same verification, PLUS an attempt budget (stop condition) so the
# beat can never re-run a stuck session forever (the "token blowout" guard).
RANS = "$.get('reasoning', {}).get('assistant_message','')"
RGATE = "((len((" + RANS + " or '').strip()) > 4) and ('error:' not in (" + RANS + " or '').lower()))"
RVERIFIED = "((" + RGATE + ") and ($.get('verdict_obj', {}).get('verdict','fail') == 'pass'))"
RCAP = "($.get('r_attempts', 0) >= " + str(MAX_ATTEMPTS) + ")"
RNOTCAP = "($.get('r_attempts', 0) < " + str(MAX_ATTEMPTS) + ")"
RSTATUS = "('needs_review' if (" + RCAP + " or not " + RVERIFIED + ") else 'idle')"
RVERIF = ("{'gate_pass':(" + RGATE + "),"
          "'verdict':$.get('verdict_obj', {}).get('verdict','skipped'),"
          "'reason':($.get('verdict_obj', {}).get('reason','') if " + RNOTCAP + " else 'resume attempt budget exhausted'),"
          "'severity':$.get('verdict_obj', {}).get('severity','none'),'model':'" + EVAL_MODEL + "'}")
RENTRIES = "([*$.get('r_entries', [])] + ([" + RAE + "] if " + RNOTCAP + " else []))"
RFVAL = ("{**$.get('r_value', {}),'attempts':$.get('r_attempts',0)+1,'status':" + RSTATUS + ",'verification':" + RVERIF + ",'entries':" + RENTRIES + "}")

LOAD_OUT = {
    "exists": "len($.get('documents', [])) > 0",
    "existing_value": "$.get('documents')[0].get('value', {}) if len($.get('documents', [])) > 0 else {}",
    "existing_entries": "$.get('documents')[0].get('value', {}).get('entries', []) if len($.get('documents', [])) > 0 else []",
    "next_turn": "($.get('documents')[0].get('value', {}).get('turn', 0) if len($.get('documents', [])) > 0 else 0) + 1",
}

R_SCHEMA = {"title": "LoopReasoning", "type": "object", "properties": {
    "needs_tool_call": {"type": "boolean"},
    "tool_calls": {"type": "array", "items": {"type": "object", "properties": {
        "name": {"type": "string"}, "arguments_json": {"type": "string"}}, "required": ["name", "arguments_json"]}},
    "assistant_message": {"type": "string"}, "short_message": {"type": "string"}},
    "required": ["needs_tool_call", "tool_calls", "assistant_message", "short_message"]}

REASON_INSTR = (
    "You are the Machina Loop reasoning step.\nRULES:\n"
    "- For ANY math -> needs_tool_call=true, call calculate {expression}. Never compute yourself.\n"
    "- For current date/time -> call get_datetime.\n"
    "- For upcoming matches / schedule / pre-match analysis -> call find_fixtures {team?, limit?}.\n"
    "- To repeat text -> call echo {text}.\n"
    "- Otherwise answer directly: needs_tool_call=false.\n"
    "name = exact tool from _3-available-tools; arguments_json = JSON-stringified args ('{}' if none). short_message = 1 line.")

# Evaluator: a SEPARATE step with a skeptical posture and a fresh context. It does
# not see the generator's reasoning — only the question, the candidate answer, and
# the tool result — so it judges with independent eyes (generator/evaluator split).
EVAL_SCHEMA = {"title": "LoopVerdict", "type": "object", "properties": {
    "verdict": {"type": "string", "enum": ["pass", "fail"]},
    "reason": {"type": "string"},
    "severity": {"type": "string", "enum": ["none", "minor", "major"]}},
    "required": ["verdict", "reason", "severity"]}

EVAL_INSTR = (
    "You are an INDEPENDENT VERIFIER for the Machina loop. You did NOT write the candidate "
    "answer; assume it is WRONG until the evidence proves otherwise.\n"
    "Given the user's question (_1-question), the candidate answer (_2-candidate-answer) and any "
    "tool result (_3-tool-result), decide if the answer ACTUALLY, CORRECTLY and COMPLETELY "
    "addresses the question.\n"
    "FAIL if it: leaves part of the question unanswered; states a value/fact not supported by the "
    "tool result; ignores a stated constraint; is evasive, empty, or off-topic.\n"
    "PASS only if a careful user would accept it as-is. severity: 'major' for a wrong/unsupported "
    "fact, 'minor' for incompleteness, 'none' when verdict=pass.\n"
    "Output verdict ('pass'|'fail'), a one-sentence reason, and severity. Be terse and skeptical.")

# Repairer (Cap 8.2): runs ONLY when the evaluator rejected a gate-passing answer.
# It sees the rejection reason and rewrites — bounded to ONE pass (no infinite loop).
REPAIR_INSTR = (
    "Your previous answer was REJECTED by an independent verifier. Rewrite it so it is correct "
    "and complete.\n"
    "Inputs: the question (_1-question); your rejected answer (_2-rejected-answer); the verifier's "
    "reason (_3-rejection-reason); the tool result, if any (_4-tool-result).\n"
    "Use the tool result as the source of truth, address EVERY part of the question, and do not "
    "repeat the rejected mistake. If a fact is not supported by the tool result, say so plainly "
    "instead of inventing it.\n"
    "Put the corrected answer in assistant_message (in the user's language); needs_tool_call=false, tool_calls=[].")


def definitions():
    reasoning = {"name": "loop-reasoning", "title": "Loop Reasoning", "type": "prompt", "status": "active",
                 "description": "reason: answer or emit tool_calls", "instruction": REASON_INSTR, "schema": R_SCHEMA}
    respond = {"name": "loop-respond", "title": "Loop Respond", "type": "prompt", "status": "active",
               "description": "synthesize final answer from tool output",
               "instruction": "Given the user's question and the tool results, write the final answer in assistant_message, in the user's language. Always needs_tool_call=false, tool_calls=[].",
               "schema": R_SCHEMA}
    evaluate = {"name": "loop-evaluate", "title": "Loop Evaluate", "type": "prompt", "status": "active",
                "description": "independent verifier (generator/evaluator separation)",
                "instruction": EVAL_INSTR, "schema": EVAL_SCHEMA}
    # Cap 8.2 — a prompt task selects its prompt by TASK NAME, so the repair pass and
    # its re-verification need their own prompts (a workflow can't reuse a task name).
    repair = {"name": "loop-repair", "title": "Loop Repair", "type": "prompt", "status": "active",
              "description": "bounded self-repair: rewrite a rejected answer (Cap 8.2)",
              "instruction": REPAIR_INSTR, "schema": R_SCHEMA}
    evaluate2 = {"name": "loop-evaluate-2", "title": "Loop Evaluate 2", "type": "prompt", "status": "active",
                 "description": "independent verifier — re-judge the repaired answer (Cap 8.2)",
                 "instruction": EVAL_INSTR, "schema": EVAL_SCHEMA}
    tools = {"name": "loop-tools", "title": "Loop Tools", "status": "active", "description": "meta-dispatcher",
             "filename": "tools.py", "filetype": "pyscript", "filecontent": LOOP_TOOLS_SRC,
             "commands": [{"name": "Dispatch", "value": "dispatch"}]}
    loop_turn = {
        "name": "loop-turn", "title": "Loop Turn", "status": "active", "description": "one conversational turn",
        "context-variables": CTX_VARS,
        "inputs": {"session_id": "$.get('session_id')", "input_message": "$.get('input_message')", "persona_agent": "$.get('persona_agent', 'loop-reasoning')"},
        "outputs": {"session_id": "$.get('session_id')", "assistant_message": FINAL_ANSWER, "turn": "$.get('next_turn')", "workflow-status": "'executed'"},
        "tasks": [
            {"name": "load-session", "type": "document", "config": {"action": "search", "search-limit": 1, "search-vector": False},
             "filters": {"name": "'harness_session'", "value.session_id": "$.get('session_id')"}, "outputs": LOAD_OUT},
            {"name": "ingest-new", "type": "document", "condition": "$.get('exists') is not True",
             "config": {"action": "save", "embed-vector": False, "force-update": True}, "documents": {"harness_session": INEW}},
            {"name": "ingest-append", "type": "document", "condition": "$.get('exists') is True",
             "config": {"action": "update", "embed-vector": False, "force-update": True},
             "filters": {"name": "'harness_session'", "value.session_id": "$.get('session_id')"}, "documents": {"harness_session": IUPD}},
            {"name": "loop-reasoning", "type": "prompt", "connector": GENAI,
             "inputs": {"_1-message-history": "$.get('existing_entries', [])", "_2-user-message": "$.get('input_message')", "_3-available-tools": json.dumps(CATALOG)},
             "outputs": {"reasoning": "$"}},
            {"name": "run-tool", "type": "connector", "condition": NEEDS, "connector": {"command": "dispatch", "name": "loop-tools"},
             "inputs": {"tool_name": "$.get('reasoning', {}).get('tool_calls', [{}])[0].get('name','')", "args_json": "$.get('reasoning', {}).get('tool_calls', [{}])[0].get('arguments_json','{}')"},
             "outputs": {"tool_result_value": "$.get('tool_result','')", "tool_ok_value": "$.get('tool_ok')"}},
            {"name": "loop-respond", "type": "prompt", "condition": NEEDS, "connector": GENAI,
             "inputs": {"_2-user-message": "$.get('input_message')", "_4-tool-result": "$.get('tool_result_value','')"}, "outputs": {"reasoning2": "$"}},
            # Verify (only if the deterministic gate passed — Minions-style): an
            # independent evaluator judges the candidate answer with fresh eyes.
            {"name": "loop-evaluate", "type": "prompt", "condition": GATE, "connector": GENAI_EVAL,
             "inputs": {"_1-question": "$.get('input_message')", "_2-candidate-answer": FA, "_3-tool-result": "$.get('tool_result_value','')"},
             "outputs": {"verdict_obj": "$"}},
            # Cap 8.2 — retry-with-critique: if the gate passed but the evaluator REJECTED
            # the answer, repair once (feed the reason back) and re-judge the new answer.
            {"name": "loop-repair", "type": "prompt", "condition": REPAIR_NEEDED, "connector": GENAI,
             "inputs": {"_1-question": "$.get('input_message')", "_2-rejected-answer": FA,
                        "_3-rejection-reason": "$.get('verdict_obj', {}).get('reason','')", "_4-tool-result": "$.get('tool_result_value','')"},
             "outputs": {"repair": "$"}},
            {"name": "loop-evaluate-2", "type": "prompt", "condition": REPAIR_NEEDED, "connector": GENAI_EVAL,
             "inputs": {"_1-question": "$.get('input_message')", "_2-candidate-answer": REPAIR_ANS, "_3-tool-result": "$.get('tool_result_value','')"},
             "outputs": {"verdict_obj2": "$"}},
            {"name": "finalize", "type": "document", "config": {"action": "update", "embed-vector": False, "force-update": True},
             "filters": {"name": "'harness_session'", "value.session_id": "$.get('session_id')"}, "documents": {"harness_session": FVAL}},
        ]}
    loop_resume = {
        "name": "loop-resume", "title": "Loop Resume", "status": "active", "description": "beat path: resume an orphaned active session",
        "context-variables": CTX_VARS, "inputs": {},
        "outputs": {"resumed_session": "$.get('r_session_id')", "workflow-status": "'executed'"},
        "tasks": [
            {"name": "find-active", "type": "document", "config": {"action": "search", "search-limit": 1, "search-vector": False},
             "filters": {"name": "'harness_session'", "value.status": "'active'"}, "outputs": {
                "r_exists": "len($.get('documents', [])) > 0",
                "r_session_id": "$.get('documents')[0].get('value', {}).get('session_id') if len($.get('documents', [])) > 0 else None",
                "r_value": "$.get('documents')[0].get('value', {}) if len($.get('documents', [])) > 0 else {}",
                "r_entries": "$.get('documents')[0].get('value', {}).get('entries', []) if len($.get('documents', [])) > 0 else []",
                "r_turn": "$.get('documents')[0].get('value', {}).get('turn', 0) if len($.get('documents', [])) > 0 else 0",
                "r_last_user": "$.get('documents')[0].get('value', {}).get('entries', [])[-1].get('content','') if len($.get('documents', [])) > 0 else ''",
                "r_attempts": "$.get('documents')[0].get('value', {}).get('attempts', 0) if len($.get('documents', [])) > 0 else 0"}},
            {"name": "loop-reasoning", "type": "prompt", "condition": "$.get('r_exists') is True and " + RNOTCAP, "connector": GENAI,
             "inputs": {"_1-message-history": "$.get('r_entries', [])", "_2-user-message": "$.get('r_last_user')"}, "outputs": {"reasoning": "$"}},
            # Verify the resumed answer too; skipped when the attempt budget is spent.
            {"name": "loop-evaluate", "type": "prompt", "condition": "$.get('r_exists') is True and " + RNOTCAP, "connector": GENAI_EVAL,
             "inputs": {"_1-question": "$.get('r_last_user')", "_2-candidate-answer": RANS, "_3-tool-result": "''"},
             "outputs": {"verdict_obj": "$"}},
            {"name": "resume-finalize", "type": "document", "condition": "$.get('r_exists') is True",
             "config": {"action": "update", "embed-vector": False, "force-update": True},
             "filters": {"name": "'harness_session'", "value.session_id": "$.get('r_session_id')"}, "documents": {"harness_session": RFVAL}},
        ]}
    runner = {"name": "loop-runner", "title": "Loop Runner", "status": "inactive", "scheduled": False,
              "description": "executor path (CLI/MCP invokes via execute_agent)",
              "context-agent": {"op": "$.get('op', 'advance')", "session_id": "$.get('session_id')", "input_message": "$.get('input_message')", "persona_agent": "$.get('persona_agent', 'loop-reasoning')"},
              "workflows": [{"name": "loop-turn", "description": "run a turn",
                             "inputs": {"session_id": "$.get('session_id')", "input_message": "$.get('input_message')", "persona_agent": "$.get('persona_agent', 'loop-reasoning')"},
                             "outputs": {"session_id": "$.get('session_id')", "assistant_message": "$.get('assistant_message','')"}}]}
    # loop-beat is the durability tick (scheduling move). Created INACTIVE so it
    # does not run in a shared pod until a reviewer opts in by setting status:active.
    beat = {"name": "loop-beat", "title": "Loop Beat", "status": "inactive", "scheduled": True,
            "description": "durability tick: resume orphaned active sessions (set status:active to enable)",
            "context": {"config-frequency": 0.5}, "context-agent": {},
            "workflows": [{"name": "loop-resume", "description": "resume an orphaned active session", "inputs": {}, "outputs": {"resumed_session": "$.get('resumed_session')"}}]}
    return [("prompt", reasoning), ("prompt", respond), ("prompt", evaluate),
            ("prompt", repair), ("prompt", evaluate2), ("connector", tools),
            ("workflow", loop_turn), ("workflow", loop_resume), ("agent", runner), ("agent", beat)]


def main():
    if not BASE or not TOKEN:
        sys.exit("Set CLIENT_API_URL and API_TOKEN environment variables.")
    teardown = "--teardown" in sys.argv
    defs = definitions()
    if teardown:
        print(f"Tearing down loop resources on {BASE} ...")
        for kind, body in reversed(defs):
            _delete_by_name(kind, body["name"])
            print(f"  removed {kind}/{body['name']}")
        return
    print(f"Provisioning Machina harness loop on {BASE} (model={MODEL}) ...")
    ok = all(_create(kind, body) for kind, body in defs)
    print("\nDone." if ok else "\nDone with errors — check output above.")
    print("Validate:  see VALIDATION.md (or: machina loop run \"...\" --watch with the CLI pointed here).")


if __name__ == "__main__":
    main()
