"""
Machina Loop Tools — meta-dispatcher connector for the agentic loop (cap 6).

Routes the `tool_name` argument to internal tools, so a single statically-named
connector gives the loop dynamic multi-tool dispatch (workflow tasks can't name a
connector dynamically). Pure stdlib — no third-party deps.

⚠️ NOT LIVE UNTIL DEPLOYED. Creating this connector via the Client API persists
the record in the DB, but the running machina-client-api only executes connectors
bundled into its DEPLOY (verified: even a no-import connector created via the API
fails at call time with the same error as this one; the record is byte-identical to
a working connector — the only difference is deployment). To make this tool live,
add it to the client-api connector set and deploy (promote → release-beta / release).
See memory: pyscript-connector-deps-in-client-api, copilot-chat-tools-and-clientapi-deploy.

Wire-up in the `loop-turn` workflow (run-tool task), once deployed:

    {"name": "run-tool", "type": "connector",
     "condition": "$.get('reasoning', {}).get('needs_tool_call') is True",
     "connector": {"command": "dispatch", "name": "loop-tools"},
     "inputs": {
       "tool_name": "$.get('reasoning', {}).get('tool_calls', [{}])[0].get('name','')",
       "args_json": "$.get('reasoning', {}).get('tool_calls', [{}])[0].get('arguments_json','{}')"},
     "outputs": {"tool_result_value": "$.get('tool_result','')"}}

Connector record fields: filename=tools.py, filetype=pyscript,
commands=[{"name": "Dispatch", "value": "dispatch"}], filecontent=<this file>.
"""

import ast
import json
import operator
from datetime import datetime, timezone

_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
    ast.USub: operator.neg, ast.UAdd: operator.pos, ast.FloorDiv: operator.floordiv,
}


def _safe_eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("unsupported expression")


def _calculate(args):
    expr = str(args.get("expression", "")).strip()
    if not expr:
        return "error: no expression"
    try:
        return _safe_eval(ast.parse(expr, mode="eval").body)
    except Exception as e:  # noqa: BLE001
        return "error: " + str(e)


def dispatch(request_data: dict) -> dict:
    """Single entry point. Inputs arrive under request_data['params'] (pyscript pattern)."""
    params = request_data.get("params", {}) or request_data
    tool = (params.get("tool_name") or "").strip()
    raw = params.get("args_json", "{}")
    try:
        if isinstance(raw, dict):
            args = raw
        elif isinstance(raw, str) and raw.strip():
            args = json.loads(raw)
        else:
            args = {}
    except Exception:  # noqa: BLE001
        args = {}

    if tool == "get_datetime":
        result = datetime.now(timezone.utc).strftime("%A, %d %B %Y, %H:%M UTC")
    elif tool == "calculate":
        result = _calculate(args)
    elif tool == "echo":
        result = str(args.get("text", ""))
    else:
        result = "unknown tool: " + tool
    return {"tool_result": str(result), "tool_ok": tool in ("get_datetime", "calculate", "echo")}
