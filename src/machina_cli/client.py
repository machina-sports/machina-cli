"""HTTP client for Machina Core API."""

from typing import Any, Optional

import httpx
from rich.console import Console

from machina_cli.config import get_api_url, resolve_auth_token

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
            msg = error_msg or "Session expired. Run `machina login` to re-authenticate."
            console.print(f"[red]{msg}[/red]")
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

    def get(self, path: str, params: Optional[dict] = None) -> dict:
        url = f"{self.api_url}/{path.lstrip('/')}"
        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                response = client.get(url, headers=self._headers(), params=params)
                return self._handle_response(response)
        except httpx.ConnectError:
            console.print(f"[red]Cannot reach Machina API at {self.api_url}. Check your connection.[/red]")
            raise SystemExit(1)

    def post(self, path: str, json_data: Optional[dict] = None, skip_auth: bool = False) -> dict:
        url = f"{self.api_url}/{path.lstrip('/')}"
        headers = {"Content-Type": "application/json"} if skip_auth else self._headers()
        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                response = client.post(url, headers=headers, json=json_data or {})
                return self._handle_response(response)
        except httpx.ConnectError:
            console.print(f"[red]Cannot reach Machina API at {self.api_url}. Check your connection.[/red]")
            raise SystemExit(1)

    def delete(self, path: str) -> dict:
        url = f"{self.api_url}/{path.lstrip('/')}"
        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                response = client.delete(url, headers=self._headers())
                return self._handle_response(response)
        except httpx.ConnectError:
            console.print(f"[red]Cannot reach Machina API at {self.api_url}. Check your connection.[/red]")
            raise SystemExit(1)
