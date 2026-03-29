"""Browser-based authentication flow for Clerk magic link login.

Flow:
1. CLI starts a temporary HTTP server on localhost
2. Opens browser to Machina session auth page with callback to localhost
3. User authenticates via Clerk (email magic link, Google SSO, etc.)
4. After auth, machina-session redirects to localhost with the session token
5. CLI captures the token and stores it
"""

import socket
import threading
import time
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional
from urllib.parse import urlencode, urlparse, parse_qs

from rich.console import Console

console = Console(stderr=True)

# Result holder for cross-thread communication
_auth_result: dict = {}


def _find_free_port() -> int:
    """Find a free port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _AuthCallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler that captures the auth callback with the session token."""

    def do_GET(self):
        global _auth_result
        parsed = urlparse(self.path)

        # Only process requests to /callback — ignore favicon, etc.
        if parsed.path != "/callback":
            self.send_response(204)
            self.end_headers()
            return

        params = parse_qs(parsed.query)

        token = params.get("token", [None])[0]
        error = params.get("error", [None])[0]

        if token:
            _auth_result = {"status": True, "token": token}
            self._respond_success()
        elif error:
            _auth_result = {"status": False, "error": error}
            self._respond_error(error)
        else:
            _auth_result = {"status": False, "error": "No token received"}
            self._respond_error("No token received")

    def _respond_success(self):
        html = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Machina CLI</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            display: flex; justify-content: center; align-items: center;
            min-height: 100vh; margin: 0;
            background: #0a0a0a; color: #f2eff3;
        }
        .card {
            text-align: center; padding: 3rem;
            border: 1px solid #FF5C1F; border-radius: 12px;
            background: #111;
        }
        .star { color: #FF5C1F; font-size: 2rem; }
        h1 { margin: 1rem 0 0.5rem; }
        p { color: #888; }
    </style>
</head>
<body>
    <div class="card">
        <div class="star">✦</div>
        <h1>Authentication successful</h1>
        <p>You can close this tab and return to the terminal.</p>
    </div>
</body>
</html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(html.encode())

    def _respond_error(self, error: str):
        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Machina CLI - Error</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            display: flex; justify-content: center; align-items: center;
            min-height: 100vh; margin: 0;
            background: #0a0a0a; color: #f2eff3;
        }}
        .card {{
            text-align: center; padding: 3rem;
            border: 1px solid #dc2626; border-radius: 12px;
            background: #111;
        }}
        h1 {{ color: #dc2626; }}
        p {{ color: #888; }}
    </style>
</head>
<body>
    <div class="card">
        <h1>Authentication failed</h1>
        <p>{error}</p>
        <p>Please try again in the terminal.</p>
    </div>
</body>
</html>"""
        self.send_response(400)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(html.encode())

    def log_message(self, format, *args):
        """Suppress default HTTP server logging."""
        pass


def browser_login(session_url: str, timeout: int = 120) -> Optional[str]:
    """
    Run the browser-based auth flow.

    Args:
        session_url: Base URL of machina-session (e.g. https://session.machina.gg)
        timeout: Max seconds to wait for auth callback

    Returns:
        Session token string on success, None on failure
    """
    global _auth_result
    _auth_result = {}

    port = _find_free_port()
    callback_url = f"http://localhost:{port}/callback"

    # Primary flow: /cli/auth page that works even if user is already logged in.
    # It calls /api/auth/cli-token (server-side) and redirects to localhost with token.
    # If user is NOT logged in with Clerk, Clerk middleware will redirect to sign-in first.
    params = urlencode({"callback": callback_url})
    auth_url = f"{session_url}/cli/auth?{params}"

    # Start local server
    server = HTTPServer(("127.0.0.1", port), _AuthCallbackHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    try:
        console.print()
        console.print("  [bold]Opening browser to authenticate...[/bold]")
        console.print("  [dim]If the browser doesn't open, visit:[/dim]")
        console.print(f"  [link={auth_url}]{auth_url}[/link]")
        console.print()

        webbrowser.open(auth_url)

        # Wait for callback
        elapsed = 0
        with console.status("[bold]  Waiting for authentication...", spinner="dots"):
            while elapsed < timeout:
                if _auth_result:
                    break
                time.sleep(0.5)
                elapsed += 0.5

        if not _auth_result:
            console.print()
            console.print("  [yellow]Browser authentication timed out.[/yellow]")
            console.print()
            console.print("  [dim]This can happen if:[/dim]")
            console.print("  [dim]  • You were already logged in and got redirected to Studio[/dim]")
            console.print("  [dim]  • The session server doesn't support CLI auth yet[/dim]")
            console.print()
            console.print("  [bold]Alternative ways to authenticate:[/bold]")
            console.print()
            console.print("  1. Generate an API key in Studio → Settings → API Keys, then:")
            console.print("     [bold #FF5C1F]machina login --api-key <your-key>[/bold #FF5C1F]")
            console.print()
            console.print("  2. Use username/password:")
            console.print("     [bold #FF5C1F]machina login --with-credentials[/bold #FF5C1F]")
            console.print()
            return None

        if _auth_result.get("status"):
            return _auth_result["token"]
        else:
            error = _auth_result.get('error', 'Unknown error')
            console.print(f"  [red]Authentication failed: {error}[/red]")
            console.print()
            console.print("  [dim]Try:[/dim] [bold]machina login --api-key <key>[/bold] [dim]or[/dim] [bold]machina login --with-credentials[/bold]")
            return None

    finally:
        server.shutdown()
