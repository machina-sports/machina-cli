"""HTTP client for the Machina Factory (coding-agent runtime).

Factory builds apps from a prompt and opens PRs. The CLI does NOT talk to the
raw Factory API (`/v1/jobs`, `Bearer mf_...`) — that key is a server-side secret
held only by the customers web app. Instead the CLI hits the customer surface
at `https://customers.machina.gg/c/api/*`, which is a thin auth-proxy over the
Factory API. Those routes authenticate the same way the `/c` web UI does.

Two auth modes, in priority order:

1. Studio session (mirrors "logged in to studio"): send the studio session
   cookie `machina_session_key` (= the CLI's `session_token` from `machina login`)
   plus the advisory `machina_project_key` (= the stored `project_token_{id}`).
   This is the interactive path; jobs are owned by the user's `uid`.

2. Project API key (headless / CI): send `X-Api-Token: <api_key>`. Requires the
   customers app to accept api-key auth (resolved via core-api
   `/system/session-check` → org + project). Jobs are scoped to the project.
"""

import json as json_lib
import os
from collections.abc import Iterator

import httpx
from rich.console import Console

from machina_cli.config import (
    _is_jwt_expired,
    get_config,
    get_credential,
)

console = Console(stderr=True)

TIMEOUT = 60.0

DEFAULT_FACTORY_URL = "https://customers.machina.gg"

# Studio cookie names the customers app reads (see machina-factory-customers
# apps/web/app/c/_lib/project-context.ts + factory/auth.ts). The session cookie
# name is environment-specific — core-api sets it from `SESSION_COOKIE_NAME`,
# which production overrides to `machina_production_session_name` (verified
# against a live customers.machina.gg session). Overridable for other deploys.
SESSION_COOKIE = os.environ.get("MACHINA_SESSION_COOKIE_NAME", "machina_production_session_name")
PROJECT_COOKIE = os.environ.get("MACHINA_PROJECT_COOKIE_NAME", "machina_project_key")


def get_factory_url() -> str:
    return (
        os.environ.get("MACHINA_FACTORY_URL") or get_config("factory_url") or DEFAULT_FACTORY_URL
    ).rstrip("/")


def _resolve_session_token() -> str | None:
    """The studio session JWT, if present and unexpired."""
    token = os.environ.get("MACHINA_SESSION_TOKEN") or get_credential("session_token")
    if token and not _is_jwt_expired(token):
        return token
    return None


def _resolve_api_key() -> str | None:
    return os.environ.get("MACHINA_API_KEY") or get_credential("api_key")


def _resolve_project_token(project_id: str | None) -> str | None:
    """Advisory project JWT for the `machina_project_key` cookie.

    Only used to tag a session-mode job with the right studio project. Returns
    the stored project token when valid; never blocks on minting since the
    customers app falls back to core-api when the cookie is absent.
    """
    if not project_id:
        return None
    stored = get_credential(f"project_token_{project_id}")
    if stored and not _is_jwt_expired(stored):
        return stored
    return None


class FactoryClient:
    """HTTP client for the Factory customer surface (`/c/api/*`)."""

    def __init__(self, project_id: str | None = None):
        self.base_url = get_factory_url()
        self.project_id = project_id or get_config("default_project_id")

        self.session_token = _resolve_session_token()
        self.api_key = _resolve_api_key()

        if not (self.session_token or self.api_key):
            console.print(
                "[red]Factory requires a studio session.[/red] "
                "Run [bold]machina login[/bold] (browser) to authenticate."
            )
            raise SystemExit(1)

        # session mode wins when both are present: it carries the real user
        # identity (uid) so jobs are owned by you, not just the project.
        self.mode = "session" if self.session_token else "apikey"
        self.project_token = (
            _resolve_project_token(self.project_id) if self.mode == "session" else None
        )
        # In api-key mode the customers app has no studio JWTs to build the
        # job's pod credentials, so the CLI supplies the client-api URL it
        # already knows (config `client_api_url`). The server pairs it with the
        # api key to form `studioCredentials = {apiKey, clientApiUrl}`.
        self.client_api_url = get_config("client_api_url") if self.mode == "apikey" else None

    # -- auth -----------------------------------------------------------------

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.mode == "apikey":
            headers["X-Api-Token"] = self.api_key
        return headers

    def _cookies(self) -> dict:
        if self.mode != "session":
            return {}
        cookies = {SESSION_COOKIE: self.session_token}
        if self.project_token:
            cookies[PROJECT_COOKIE] = self.project_token
        return cookies

    # -- response handling ----------------------------------------------------

    def _handle_response(self, response: httpx.Response) -> dict:
        data = {}
        try:
            data = response.json()
        except Exception:
            pass

        error_msg = ""
        if isinstance(data, dict):
            err = data.get("error")
            error_msg = (
                err
                if isinstance(err, str)
                else (err or {}).get("message", "")
                if isinstance(err, dict)
                else ""
            )

        if response.status_code == 401:
            if self.mode == "session":
                console.print(
                    "[red]Studio session expired or invalid.[/red] Run [bold]machina login[/bold] to refresh."
                )
            else:
                console.print(
                    "[red]API key rejected by Factory.[/red] The customers app may not accept api-key auth yet, or the key is invalid."
                )
            raise SystemExit(1)
        if response.status_code == 402:
            console.print(f"[red]{error_msg or 'Insufficient credits for this build.'}[/red]")
            raise SystemExit(1)
        if response.status_code == 403:
            console.print(f"[red]{error_msg or 'Permission denied.'}[/red]")
            raise SystemExit(1)
        if response.status_code == 404:
            console.print(f"[red]{error_msg or 'Not found.'}[/red]")
            raise SystemExit(1)
        if response.status_code == 503:
            console.print(f"[red]{error_msg or 'Factory API not configured / unavailable.'}[/red]")
            raise SystemExit(1)
        if response.status_code >= 400:
            console.print(
                f"[red]{error_msg or f'Factory error (HTTP {response.status_code}).'}[/red]"
            )
            raise SystemExit(1)

        return data if isinstance(data, dict) else {"data": data}

    # -- verbs ----------------------------------------------------------------

    def get(self, path: str, params: dict | None = None) -> dict:
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                resp = client.get(
                    url, headers=self._headers(), cookies=self._cookies(), params=params
                )
                return self._handle_response(resp)
        except httpx.ConnectError:
            console.print(f"[red]Cannot reach Factory at {self.base_url}[/red]")
            raise SystemExit(1)

    def post(self, path: str, json_data: dict | None = None) -> dict:
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                resp = client.post(
                    url, headers=self._headers(), cookies=self._cookies(), json=json_data or {}
                )
                return self._handle_response(resp)
        except httpx.ConnectError:
            console.print(f"[red]Cannot reach Factory at {self.base_url}[/red]")
            raise SystemExit(1)

    def stream(self, path: str, params: dict | None = None) -> Iterator[dict]:
        """Yield decoded events from a Server-Sent Events endpoint.

        Used by `factory logs --follow` against `/c/api/stream/{id}`. Yields the
        JSON-decoded `data:` payload of each SSE event (raw string under
        `{"raw": ...}` when not JSON). Closes when the server ends the stream.
        """
        url = f"{self.base_url}/{path.lstrip('/')}"
        headers = {**self._headers(), "Accept": "text/event-stream"}
        try:
            with httpx.Client(timeout=None) as client:  # noqa: SIM117 — separate contexts keep the teardown order explicit
                with client.stream(
                    "GET", url, headers=headers, cookies=self._cookies(), params=params
                ) as resp:
                    if resp.status_code >= 400:
                        resp.read()
                        self._handle_response(resp)
                        return
                    for line in resp.iter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        payload = line[len("data:") :].strip()
                        if not payload or payload == "[DONE]":
                            continue
                        try:
                            yield json_lib.loads(payload)
                        except Exception:
                            yield {"raw": payload}
        except httpx.ConnectError:
            console.print(f"[red]Cannot reach Factory at {self.base_url}[/red]")
            raise SystemExit(1)
