"""HTTP client for Machina Core API."""

import httpx
from rich.console import Console

from machina_cli.config import get_api_url, get_credential, resolve_auth_token

console = Console(stderr=True)

TIMEOUT = 30.0


class MachinaClient:
    """HTTP client that handles authentication and error formatting."""

    def __init__(self, api_url: str | None = None):
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

    def _handle_response(self, response: httpx.Response, quiet: bool = False) -> dict:
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

        def emit(*args):
            if not quiet:
                console.print(*args)

        if response.status_code == 401:
            emit(f"[red]{error_msg or 'Session expired.'}[/red]")
            emit("[yellow]Run `machina login` to re-authenticate.[/yellow]")
            raise SystemExit(1)
        if response.status_code == 403:
            emit(f"[red]{error_msg or 'Permission denied.'}[/red]")
            raise SystemExit(1)
        if response.status_code == 404:
            emit(f"[red]{error_msg or 'Resource not found.'}[/red]")
            raise SystemExit(1)
        if response.status_code >= 500:
            emit(f"[red]{error_msg or 'Server error. Try again later.'}[/red]")
            raise SystemExit(1)

        if isinstance(data, dict) and data.get("status") == "error":
            emit(f"[red]Error: {error_msg or 'Unknown error'}[/red]")
            raise SystemExit(1)

        return data

    def _request(self, method: str, path: str, **kwargs) -> dict:
        """Execute a request, optionally falling back from API key to session token on 5xx."""
        url = f"{self.api_url}/{path.lstrip('/')}"
        skip_auth = kwargs.pop("skip_auth", False)
        allow_fallback = kwargs.pop("allow_fallback", True)
        quiet = kwargs.pop("quiet", False)
        headers = {"Content-Type": "application/json"} if skip_auth else self._headers()
        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                response = getattr(client, method)(url, headers=headers, **kwargs)

                # A 5xx while sending an API key is ambiguous: the key may be invalid,
                # the endpoint may not accept API-key auth (it 500s instead of 401), or
                # the server may simply be faulting. Fall back to the session token for
                # THIS request only — never delete the stored key on a 5xx (that would
                # silently discard a possibly-valid key, e.g. during `login --api-key`).
                if allow_fallback and response.status_code >= 500 and headers.get("X-Api-Token"):
                    session = get_credential("session_token")
                    if session:
                        retry_headers = {k: v for k, v in headers.items() if k != "X-Api-Token"}
                        retry_headers["X-Session-Token"] = session
                        retry = getattr(client, method)(url, headers=retry_headers, **kwargs)
                        if retry.status_code < 500:
                            if not quiet:
                                console.print(
                                    "[yellow]API key not accepted by the server here; "
                                    "used your session token for this request.[/yellow]"
                                )
                            response = retry

                return self._handle_response(response, quiet=quiet)
        except httpx.ConnectError:
            if not quiet:
                console.print(
                    f"[red]Cannot reach Machina API at {self.api_url}. Check your connection.[/red]"
                )
            raise SystemExit(1)

    def get(
        self,
        path: str,
        params: dict | None = None,
        allow_fallback: bool = True,
        quiet: bool = False,
    ) -> dict:
        return self._request("get", path, params=params, allow_fallback=allow_fallback, quiet=quiet)

    def post(
        self,
        path: str,
        json_data: dict | None = None,
        skip_auth: bool = False,
        allow_fallback: bool = True,
        quiet: bool = False,
    ) -> dict:
        return self._request(
            "post",
            path,
            json=json_data or {},
            skip_auth=skip_auth,
            allow_fallback=allow_fallback,
            quiet=quiet,
        )

    def delete(self, path: str, allow_fallback: bool = True, quiet: bool = False) -> dict:
        return self._request("delete", path, allow_fallback=allow_fallback, quiet=quiet)
