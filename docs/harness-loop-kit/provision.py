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
    python3 provision.py            # provision (default)
    python3 provision.py --teardown # remove all loop resources

What it creates (maps to the Loop-Engineering five moves — see VALIDATION.md):
    prompt   loop-reasoning   reason: answer directly or emit tool_calls   (discovery/decide)
    prompt   loop-respond     synthesize the final answer from tool output
    connector loop-tools      dispatcher: calculate / get_datetime / echo / find_fixtures
    workflow loop-turn        load -> ingest(active) -> reason -> tool -> respond -> finalize(idle)
    workflow loop-resume      beat path: resume an orphaned `active` session   (scheduling)
    agent    loop-runner      executor path (inactive; CLI/MCP invokes it)
    agent    loop-beat        durability tick (created INACTIVE by default)    (scheduling)

NOTE: this loop has discovery, handoff(partial), persistence and scheduling, but
NO independent VERIFICATION (generator/evaluator) yet — see VALIDATION.md §Gaps.
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
FVAL = "{**$.get('existing_value', {}),'session_id':$.get('session_id'),'persona_agent':$.get('persona_agent'),'turn':$.get('next_turn'),'status':'idle','entries':" + ENTRIES + "}"
RAE = "{'id':'a'+str($.get('r_turn')),'turn':$.get('r_turn'),'role':'assistant','type':'message','content':$.get('reasoning', {}).get('assistant_message','')}"
RFVAL = "{**$.get('r_value', {}),'status':'idle','entries':[*$.get('r_entries', []), " + RAE + "]}"

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


def definitions():
    reasoning = {"name": "loop-reasoning", "title": "Loop Reasoning", "type": "prompt", "status": "active",
                 "description": "reason: answer or emit tool_calls", "instruction": REASON_INSTR, "schema": R_SCHEMA}
    respond = {"name": "loop-respond", "title": "Loop Respond", "type": "prompt", "status": "active",
               "description": "synthesize final answer from tool output",
               "instruction": "Given the user's question and the tool results, write the final answer in assistant_message, in the user's language. Always needs_tool_call=false, tool_calls=[].",
               "schema": R_SCHEMA}
    tools = {"name": "loop-tools", "title": "Loop Tools", "status": "active", "description": "meta-dispatcher",
             "filename": "tools.py", "filetype": "pyscript", "filecontent": LOOP_TOOLS_SRC,
             "commands": [{"name": "Dispatch", "value": "dispatch"}]}
    loop_turn = {
        "name": "loop-turn", "title": "Loop Turn", "status": "active", "description": "one conversational turn",
        "context-variables": CTX_VARS,
        "inputs": {"session_id": "$.get('session_id')", "input_message": "$.get('input_message')", "persona_agent": "$.get('persona_agent', 'loop-reasoning')"},
        "outputs": {"session_id": "$.get('session_id')", "assistant_message": FA, "turn": "$.get('next_turn')", "workflow-status": "'executed'"},
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
             "outputs": {"tool_result_value": "$.get('tool_result','')"}},
            {"name": "loop-respond", "type": "prompt", "condition": NEEDS, "connector": GENAI,
             "inputs": {"_2-user-message": "$.get('input_message')", "_4-tool-result": "$.get('tool_result_value','')"}, "outputs": {"reasoning2": "$"}},
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
                "r_last_user": "$.get('documents')[0].get('value', {}).get('entries', [])[-1].get('content','') if len($.get('documents', [])) > 0 else ''"}},
            {"name": "loop-reasoning", "type": "prompt", "condition": "$.get('r_exists') is True", "connector": GENAI,
             "inputs": {"_1-message-history": "$.get('r_entries', [])", "_2-user-message": "$.get('r_last_user')"}, "outputs": {"reasoning": "$"}},
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
    return [("prompt", reasoning), ("prompt", respond), ("connector", tools),
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
