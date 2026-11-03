"""HTTP client for Machina Client API (per-project resources).

The Client API serves project-level resources (workflows, agents, templates, etc.)
and lives at a per-project URL like: https://{org}-{project}.org.machina.gg

Authentication requires both:
- X-Session-Token: user session (from machina login)
- X-Project-Token: project session (from POST /login/project on Core API)
"""

import mimetypes
import os

import httpx
from rich.console import Console

from machina_cli.client import MachinaClient
from machina_cli.config import (
    _clear_credential,
    get_api_url,
    get_config,
    get_credential,
    resolve_auth_token,
    store_credential,
)

console = Console(stderr=True)

TIMEOUT = 30.0

# Project sessions cached in memory for one CLI invocation, keyed on
# (project, endpoint): a session resolved for one project/Core endpoint (or one
# direct client-api URL) is never served for another.
_project_cache: dict = {}


def _direct_client_api_url(project_id: str) -> str | None:
    """The configured direct client-api URL, if it belongs to `project_id`.

    `client_api_url` + an API key (Factory sandbox, CI/CD) describe ONE project:
    the configured default. A different explicitly selected project must not be
    silently served from that URL — it resolves through Core like any other.
    """
    client_api_url = get_config("client_api_url")
    api_key = get_credential("api_key") or os.environ.get("MACHINA_API_KEY")
    if not (client_api_url and api_key):
        return None
    default_project = get_config("default_project_id")
    if default_project and default_project != project_id:
        return None
    return client_api_url


def _cache_key(project_id: str) -> tuple:
    direct = _direct_client_api_url(project_id)
    return (project_id, direct or get_api_url())


def _get_project_session(project_id: str) -> dict:
    """
    Login to a project via Core API and get project token + client API URL.
    Caches the result for repeated calls within the same CLI invocation.

    Returns: {"token": "jwt...", "api_url": "https://org-proj.org.machina.gg"}
    """
    key = _cache_key(project_id)
    if key in _project_cache:
        return _project_cache[key]

    # Direct client-api mode: use API key directly against client-api URL
    # This allows Factory sandbox and CI/CD to use project API keys without core-api login
    client_api_url = _direct_client_api_url(project_id)
    if client_api_url:
        api_key = get_credential("api_key") or os.environ.get("MACHINA_API_KEY")
        result = {"token": api_key, "api_url": client_api_url, "direct_api_key": True}
        _project_cache[key] = result
        return result

    # Check if we have a stored project token
    stored = get_credential(f"project_token_{project_id}")
    if stored:
        # Decode JWT to get the api URL (without verification)
        import base64
        import json

        try:
            payload_b64 = stored.split(".")[1]
            # Add padding
            payload_b64 += "=" * (4 - len(payload_b64) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))

            # Check if expired
            import time

            if payload.get("exp", 0) > time.time():
                result = {"token": stored, "api_url": payload.get("api", "")}
                _project_cache[key] = result
                return result
            else:
                # Clear expired project token
                _clear_credential(f"project_token_{project_id}")
        except Exception:
            pass

    # Login to project via Core API
    core_client = MachinaClient()
    result = core_client.post("login/project", {"project_id": project_id})

    data = result.get("data", {})
    token = data.get("token") or data.get("project_key")

    if not token:
        console.print("[red]Failed to get project session. Check project ID.[/red]")
        raise SystemExit(1)

    # Decode JWT to get the Client API URL
    import base64
    import json

    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (4 - len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        api_url = payload.get("api", "")
    except Exception:
        api_url = ""

    if not api_url:
        console.print("[red]Project token missing API URL.[/red]")
        raise SystemExit(1)

    # Store for reuse
    store_credential(f"project_token_{project_id}", token)

    cached = {"token": token, "api_url": api_url}
    _project_cache[key] = cached
    return cached


_STATUS_MESSAGES = {403: "Permission denied.", 404: "Resource not found."}
_ERROR_CODES = {
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    400: "invalid_request",
    422: "invalid_request",
}


def _body_failed(status) -> bool:
    if status in ("error", False):
        return True
    return isinstance(status, int) and not isinstance(status, bool) and status >= 400


class ProjectAPIError(SystemExit):
    """A rejected Client API request.

    Subclasses SystemExit(1) so every existing caller keeps exiting non-zero;
    commands that emit machine output catch it and print `to_payload()`.
    """

    def __init__(self, message: str, http_status: int, details=None):
        super().__init__(1)
        self.message = message
        self.http_status = http_status
        self.details = details
        if http_status >= 500:
            self.code = "server_error"
        elif http_status >= 400:
            self.code = _ERROR_CODES.get(http_status, "request_rejected")
        else:
            self.code = "rejected"  # HTTP 2xx with status false in the body

    def to_payload(self) -> dict:
        payload = {"error": self.message, "error_code": self.code, "http_status": self.http_status}
        if self.details:
            payload["details"] = self.details
        return payload


class ProjectClient:
    """HTTP client for per-project Client API resources."""

    def __init__(self, project_id: str | None = None):
        self.project_id = project_id or get_config("default_project_id")

        if not self.project_id:
            # Login comes before project selection in onboarding, so check auth
            # first: an unauthenticated user sent to `machina project use` just
            # hits the login error one command later. resolve_auth_token covers
            # every mode (env API key, stored API key, session token).
            _, token = resolve_auth_token()
            if not token:
                console.print("[red]Not authenticated. Run `machina login` first.[/red]")
                raise SystemExit(1)
            console.print("[red]No project selected. Run `machina project use <id>` first.[/red]")
            raise SystemExit(1)

        session = _get_project_session(self.project_id)
        self.api_url = session["api_url"].rstrip("/")
        self.project_token = session["token"]
        self.direct_api_key = session.get("direct_api_key", False)

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.direct_api_key:
            headers["X-Api-Token"] = self.project_token
        else:
            header_name, session_token = resolve_auth_token()
            if header_name and session_token:
                headers["X-Session-Token"] = session_token
            headers["X-Project-Token"] = self.project_token
        return headers

    def _handle_response(self, response: httpx.Response) -> dict:
        data = {}
        try:
            data = response.json()
        except Exception:
            pass

        error_msg = ""
        details = None
        if isinstance(data, dict):
            error = data.get("error", {})
            if isinstance(error, dict):
                error_msg = error.get("message", "")
                details = error or None
            elif isinstance(error, str):
                error_msg = error
            elif isinstance(error, list):
                details = error
            error_msg = error_msg or (
                data.get("message", "") if _body_failed(data.get("status")) else ""
            )

        status = response.status_code
        if status == 401:
            # Clear cached and stored project token
            _project_cache.pop(_cache_key(self.project_id), None)
            _clear_credential(f"project_token_{self.project_id}")
            console.print(f"[red]{error_msg or 'Project session expired.'}[/red]")
            console.print(
                "[yellow]Run the command again to re-authenticate, or `machina login` to refresh your session.[/yellow]"
            )
            raise ProjectAPIError(error_msg or "project session expired", status, details)
        if status >= 400:
            fallback = _STATUS_MESSAGES.get(status) or (
                "Client API error." if status >= 500 else f"Request rejected (HTTP {status})."
            )
            console.print(f"[red]{error_msg or fallback}[/red]")
            raise ProjectAPIError(error_msg or fallback.rstrip("."), status, details)

        # A 200 whose body says it failed is a failure: the legacy controllers
        # return {"status": false, "error": {...}} with HTTP 200 (and the agent
        # executor's not-found is {"status": 404, "message": ...}).
        if isinstance(data, dict) and _body_failed(data.get("status")):
            console.print(f"[red]Error: {error_msg or 'Unknown error'}[/red]")
            raise ProjectAPIError(error_msg or "request failed", status, details)

        return data

    def get(self, path: str, params: dict | None = None) -> dict:
        url = f"{self.api_url}/{path.lstrip('/')}"
        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                response = client.get(url, headers=self._headers(), params=params)
                return self._handle_response(response)
        except httpx.ConnectError:
            console.print(f"[red]Cannot reach Client API at {self.api_url}[/red]")
            raise SystemExit(1)

    def post(self, path: str, json_data: dict | None = None) -> dict:
        url = f"{self.api_url}/{path.lstrip('/')}"
        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                response = client.post(url, headers=self._headers(), json=json_data or {})
                return self._handle_response(response)
        except httpx.ConnectError:
            console.print(f"[red]Cannot reach Client API at {self.api_url}[/red]")
            raise SystemExit(1)

    def put(self, path: str, json_data: dict | None = None) -> dict:
        url = f"{self.api_url}/{path.lstrip('/')}"
        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                response = client.put(url, headers=self._headers(), json=json_data or {})
                return self._handle_response(response)
        except httpx.ConnectError:
            console.print(f"[red]Cannot reach Client API at {self.api_url}[/red]")
            raise SystemExit(1)

    def delete(self, path: str) -> dict:
        url = f"{self.api_url}/{path.lstrip('/')}"
        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                response = client.delete(url, headers=self._headers())
                return self._handle_response(response)
        except httpx.ConnectError:
            console.print(f"[red]Cannot reach Client API at {self.api_url}[/red]")
            raise SystemExit(1)

    def post_file(self, path: str, file_path: str, data: dict | None = None) -> dict:
        url = f"{self.api_url}/{path.lstrip('/')}"
        mime_type, _ = mimetypes.guess_type(file_path)
        mime_type = mime_type or "application/octet-stream"

        # Multipart uploads must NOT carry the JSON Content-Type from
        # _headers(): an explicit header overrides the multipart boundary
        # httpx generates for `files=`, Flask never sees request.files, and
        # every upload dies as "No file uploaded". Auth headers stay.
        headers = {k: v for k, v in self._headers().items() if k.lower() != "content-type"}
        try:
            with httpx.Client(timeout=60.0) as client:
                with open(file_path, "rb") as f:
                    files = {"file": (os.path.basename(file_path), f, mime_type)}
                    response = client.post(url, headers=headers, data=data, files=files)
                return self._handle_response(response)
        except httpx.ConnectError:
            console.print(f"[red]Cannot reach Client API at {self.api_url}[/red]")
            raise SystemExit(1)
