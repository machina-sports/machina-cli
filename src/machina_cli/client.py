"""HTTP client for Machina Core API."""

from typing import Optional

import httpx
from rich.console import Console

from machina_cli.config import _clear_credential, get_api_url, get_credential, resolve_auth_token

console = Console(stderr=True)

TIMEOUT = 30.0


class MachinaClient:
    """HTTP client that handles authentication and error formatting."""

    def __init__(self, api_url: Optional[str] = None):
        self.api_url = (api_url or get_api_url()).rstrip("/")

    def _headers(self) -> dict:
        header_name, token = resolve_auth_token()
        headers = {"Content-Type": "application/json"}
        if header_name and token:
            headers[header_name] = token
        else:
            console.print("[red]Not authenticated. Run `machina login` first.[/red]")
            raise SystemExit(1)
        return headers

    def _handle_response(self, response: httpx.Response) -> dict:
        data = {}
        try:
            data = response.json()
        except Exception:
            pass

        # Extract error message from response body if available
        error_msg = ""
        if isinstance(data, dict):
            error = data.get("error", {})
            if isinstance(error, dict):
                error_msg = error.get("message", "")

        if response.status_code == 401:
            console.print(f"[red]{error_msg or 'Session expired.'}[/red]")
            console.print("[yellow]Run `machina login` to re-authenticate.[/yellow]")
            raise SystemExit(1)
        if response.status_code == 403:
            msg = error_msg or "Permission denied."
            console.print(f"[red]{msg}[/red]")
            raise SystemExit(1)
        if response.status_code == 404:
            msg = error_msg or "Resource not found."
            console.print(f"[red]{msg}[/red]")
            raise SystemExit(1)
        if response.status_code >= 500:
            msg = error_msg or "Server error. Try again later."
            console.print(f"[red]{msg}[/red]")
            raise SystemExit(1)

        if isinstance(data, dict) and data.get("status") == "error":
            console.print(f"[red]Error: {error_msg or 'Unknown error'}[/red]")
            raise SystemExit(1)

        return data

    def _request(self, method: str, path: str, **kwargs) -> dict:
        """Execute request with automatic API key fallback on 500."""
        url = f"{self.api_url}/{path.lstrip('/')}"
        skip_auth = kwargs.pop("skip_auth", False)
        headers = {"Content-Type": "application/json"} if skip_auth else self._headers()
        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                response = getattr(client, method)(url, headers=headers, **kwargs)

                # If API key returns 500, it may be invalid/missing from Redis.
                # Clear it and retry with session token if available.
                if response.status_code >= 500 and headers.get("X-Api-Token"):
                    if get_credential("session_token"):
                        console.print(
                            "[yellow]API key rejected by server. "
                            "Falling back to session token...[/yellow]"
                        )
                        _clear_credential("api_key")
                        headers = self._headers()
                        response = getattr(client, method)(url, headers=headers, **kwargs)

                return self._handle_response(response)
        except httpx.ConnectError:
            console.print(f"[red]Cannot reach Machina API at {self.api_url}. Check your connection.[/red]")
            raise SystemExit(1)

    def get(self, path: str, params: Optional[dict] = None) -> dict:
        return self._request("get", path, params=params)

    def post(self, path: str, json_data: Optional[dict] = None, skip_auth: bool = False) -> dict:
        return self._request("post", path, json=json_data or {}, skip_auth=skip_auth)

    def delete(self, path: str) -> dict:
        return self._request("delete", path)
