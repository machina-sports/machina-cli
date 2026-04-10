"""HTTP client for Machina Client API (per-project resources).

The Client API serves project-level resources (workflows, agents, templates, etc.)
and lives at a per-project URL like: https://{org}-{project}.org.machina.gg

Authentication requires both:
- X-Session-Token: user session (from machina login)
- X-Project-Token: project session (from POST /login/project on Core API)
"""

import mimetypes
import os
from typing import Optional

import httpx
from rich.console import Console

from machina_cli.client import MachinaClient
from machina_cli.config import (
    _clear_credential,
    get_config,
    get_credential,
    resolve_auth_token,
    store_credential,
)

console = Console(stderr=True)

TIMEOUT = 30.0

# Cache project token in memory for the session
_project_cache: dict = {}


def _get_project_session(project_id: str) -> dict:
    """
    Login to a project via Core API and get project token + client API URL.
    Caches the result for repeated calls within the same CLI invocation.

    Returns: {"token": "jwt...", "api_url": "https://org-proj.org.machina.gg"}
    """
    if project_id in _project_cache:
        return _project_cache[project_id]

    # Check if we have a stored project token
    stored = get_credential(f"project_token_{project_id}")
    if stored:
        # Decode JWT to get the api URL (without verification)
        import json
        import base64
        try:
            payload_b64 = stored.split(".")[1]
            # Add padding
            payload_b64 += "=" * (4 - len(payload_b64) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))

            # Check if expired
            import time
            if payload.get("exp", 0) > time.time():
                result = {"token": stored, "api_url": payload.get("api", "")}
                _project_cache[project_id] = result
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
    import json
    import base64
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
    _project_cache[project_id] = cached
    return cached


class ProjectClient:
    """HTTP client for per-project Client API resources."""

    def __init__(self, project_id: Optional[str] = None):
        self.project_id = project_id or get_config("default_project_id")

        if not self.project_id:
            console.print("[red]No project selected. Run `machina project use <id>` first.[/red]")
            raise SystemExit(1)

        session = _get_project_session(self.project_id)
        self.api_url = session["api_url"].rstrip("/")
        self.project_token = session["token"]

    def _headers(self) -> dict:
        header_name, session_token = resolve_auth_token()
        headers = {"Content-Type": "application/json"}
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
        if isinstance(data, dict):
            error = data.get("error", {})
            if isinstance(error, dict):
                error_msg = error.get("message", "")
            elif isinstance(error, str):
                error_msg = error

        if response.status_code == 401:
            # Clear cached and stored project token
            _project_cache.pop(self.project_id, None)
            _clear_credential(f"project_token_{self.project_id}")
            console.print(f"[red]{error_msg or 'Project session expired.'}[/red]")
            console.print("[yellow]Run the command again to re-authenticate, or `machina login` to refresh your session.[/yellow]")
            raise SystemExit(1)
        if response.status_code == 403:
            console.print(f"[red]{error_msg or 'Permission denied.'}[/red]")
            raise SystemExit(1)
        if response.status_code == 404:
            console.print(f"[red]{error_msg or 'Resource not found.'}[/red]")
            raise SystemExit(1)
        if response.status_code >= 500:
            console.print(f"[red]{error_msg or 'Client API error.'}[/red]")
            raise SystemExit(1)

        if isinstance(data, dict) and data.get("status") == "error":
            console.print(f"[red]Error: {error_msg or 'Unknown error'}[/red]")
            raise SystemExit(1)

        return data

    def get(self, path: str, params: Optional[dict] = None) -> dict:
        url = f"{self.api_url}/{path.lstrip('/')}"
        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                response = client.get(url, headers=self._headers(), params=params)
                return self._handle_response(response)
        except httpx.ConnectError:
            console.print(f"[red]Cannot reach Client API at {self.api_url}[/red]")
            raise SystemExit(1)

    def post(self, path: str, json_data: Optional[dict] = None) -> dict:
        url = f"{self.api_url}/{path.lstrip('/')}"
        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                response = client.post(url, headers=self._headers(), json=json_data or {})
                return self._handle_response(response)
        except httpx.ConnectError:
            console.print(f"[red]Cannot reach Client API at {self.api_url}[/red]")
            raise SystemExit(1)

    def post_file(self, path: str, file_path: str, data: dict = None) -> dict:
        url = f"{self.api_url}/{path.lstrip('/')}"
        mime_type, _ = mimetypes.guess_type(file_path)
        mime_type = mime_type or 'application/octet-stream'
        
        try:
            with httpx.Client(timeout=60.0) as client:
                with open(file_path, "rb") as f:
                    files = {"file": (os.path.basename(file_path), f, mime_type)}
                    response = client.post(url, headers=self._headers(), data=data, files=files)
                return self._handle_response(response)
        except httpx.ConnectError:
            console.print(f"[red]Cannot reach Client API at {self.api_url}[/red]")
            raise SystemExit(1)
