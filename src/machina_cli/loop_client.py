"""HTTP client for the `machina loop` durable agentic turn loop (harness).

The loop is server-side: a scheduled agent (`loop-runner`) advances `harness_session`
documents one burst of turns at a time and is re-dispatched by the beat for durability.
This client is a thin driver — it never writes loop state itself. It only:

- triggers the runner via `POST agent/executor/loop-runner` (start / say / stop)
- reads session documents via `POST document/search`

Session ids are minted client-side so a freshly-started session can be watched
immediately, before the runner's first burst finishes.

See docs/agentic-harness-loop.md for the full design.
"""

import uuid
from typing import Optional

from machina_cli.project_client import ProjectClient

RUNNER = "loop-runner"
SESSION_NAME = "harness_session"  # doc `name` (collection-like); identity is value.session_id
DEFAULT_PERSONA = "loop-reasoning"


def new_session_id() -> str:
    return f"ses_{uuid.uuid4().hex[:24]}"


class LoopClient:
    """Driver for the server-side harness loop."""

    def __init__(self, project_id: Optional[str] = None):
        self._pc = ProjectClient(project_id)

    def _exec(self, op: str, **ctx) -> dict:
        """Trigger the runner asynchronously; durability is the runner's job."""
        context_agent = {"op": op}
        context_agent.update({k: v for k, v in ctx.items() if v is not None})
        body = {
            "context-agent": context_agent,
            "agent-config": {"delay": True},
        }
        return self._pc.post(f"agent/executor/{RUNNER}", body).get("data", {})

    def start(self, prompt: str, persona_agent: str = DEFAULT_PERSONA) -> str:
        """Start a new session. Returns the (client-minted) session id."""
        session_id = new_session_id()
        self._exec(
            "start",
            session_id=session_id,
            input_message=prompt,
            persona_agent=persona_agent,
        )
        return session_id

    def say(self, session_id: str, message: str) -> dict:
        """Inject a user turn into an existing session and re-activate it."""
        return self._exec("say", session_id=session_id, input_message=message)

    def stop(self, session_id: str) -> dict:
        """Pause a session (the runner sets status=paused)."""
        return self._exec("stop", session_id=session_id)

    def get_session(self, session_id: str) -> Optional[dict]:
        """Return the session payload (the doc's `value`), with `_id` injected."""
        body = {
            "filters": {"name": SESSION_NAME, "value.session_id": session_id},
            "page_size": 1,
        }
        data = self._pc.post("document/search", body).get("data", [])
        return _payload(data[0]) if data else None

    def list_sessions(self, limit: int = 30) -> list:
        body = {
            "filters": {"name": SESSION_NAME},
            "sorters": ["created", -1],
            "page_size": limit,
        }
        docs = self._pc.post("document/search", body).get("data", [])
        return [_payload(d) for d in docs]


def _payload(doc: dict) -> dict:
    """Workflow-saved docs nest the payload under `value`; lift it and keep `_id`."""
    value = doc.get("value") or doc.get("content") or {}
    return {"_id": doc.get("_id"), **value}
