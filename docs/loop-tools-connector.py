"""
Machina Loop Tools — meta-dispatcher connector for the agentic loop (cap 6).

Routes the `tool_name` argument to internal tools, so a single statically-named
connector gives the loop dynamic multi-tool dispatch (workflow tasks can't name a
connector dynamically). Pure stdlib — no third-party deps.

LIVE in the dev project and wired into `loop-turn`'s `run-tool` task. Verified
end-to-end: "1234 * 5678" → calculate → 7006652; echo; get_datetime.

Connector contract (verified in machina-client-api core/connector/executor.py):
- A pyscript connector is exec()'d from its DB `filecontent` at call time — there
  is NO code deploy; creating the connector via the API is enough.
- Inputs arrive under request_data["params"] (fallback: request_data).
- The function MUST return {"status": True, "data": {...}}. The `data` dict is what
  gets merged into workflow context (so the run-tool task reads $.get('tool_result')).
  Returning a bare dict without status:True is treated as a FAILED connector.

Connector record fields: filename=tools.py, filetype=pyscript,
commands=[{"name": "Dispatch", "value": "dispatch"}], filecontent=<this file>.

Wire-up in `loop-turn` (run-tool task):

    {"name": "run-tool", "type": "connector",
     "condition": "$.get('reasoning', {}).get('needs_tool_call') is True",
     "connector": {"command": "dispatch", "name": "loop-tools"},
     "inputs": {
       "tool_name": "$.get('reasoning', {}).get('tool_calls', [{}])[0].get('name','')",
       "args_json": "$.get('reasoning', {}).get('tool_calls', [{}])[0].get('arguments_json','{}')"},
     "outputs": {"tool_result_value": "$.get('tool_result','')"}}

Add tools by extending the if/elif in dispatch() and the catalog in loop-reasoning's
`_3-available-tools` input.
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
    """Single entry point. Inputs under request_data['params']; returns {status, data}."""
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

    return {
        "status": True,
        "data": {"tool_result": str(result), "tool_ok": tool in ("get_datetime", "calculate", "echo")},
    }
