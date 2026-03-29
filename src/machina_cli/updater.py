"""Self-update logic for machina-cli.

Simple approach: always download the latest binary from GitHub Releases.
This matches how install.sh works and is the most reliable update method.
"""

import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

import httpx
from rich.console import Console

from machina_cli import __version__

console = Console()

REPO = "machina-sports/machina-cli"
GITHUB_API = f"https://api.github.com/repos/{REPO}/releases/latest"
INSTALL_SCRIPT = f"https://raw.githubusercontent.com/{REPO}/main/install.sh"


def get_latest_version() -> str | None:
    """Fetch the latest release tag from GitHub."""
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(GITHUB_API, headers={"Accept": "application/vnd.github.v3+json"})
            if resp.status_code == 200:
                return resp.json().get("tag_name", "").lstrip("v")
    except Exception:
        pass
    return None


def _detect_platform() -> str:
    """Detect OS-arch string matching release asset names."""
    system = platform.system().lower()
    machine = platform.machine().lower()

    os_map = {"linux": "linux", "darwin": "darwin"}
    arch_map = {"x86_64": "amd64", "amd64": "amd64", "arm64": "arm64", "aarch64": "arm64"}

    os_name = os_map.get(system)
    arch = arch_map.get(machine)

    if not os_name or not arch:
        return ""
    return f"{os_name}-{arch}"


def _show_release_notes(version: str):
    """Fetch and display release notes from GitHub."""
    try:
        url = f"https://api.github.com/repos/{REPO}/releases/tags/v{version}"
        with httpx.Client(timeout=10) as client:
            resp = client.get(url, headers={"Accept": "application/vnd.github.v3+json"})
            if resp.status_code == 200:
                body = resp.json().get("body", "").strip()
                if body:
                    console.print(f"  [bold]What's new in v{version}:[/bold]")
                    # Show first ~15 lines of release notes
                    lines = body.split("\n")[:15]
                    for line in lines:
                        console.print(f"  [dim]{line}[/dim]")
                    if len(body.split("\n")) > 15:
                        console.print(f"  [dim]... (see full notes at github.com/{REPO}/releases/tag/v{version})[/dim]")
                    console.print()
    except Exception:
        pass


def do_update(force: bool = False) -> bool:
    """
    Run the self-update by downloading the latest binary from GitHub Releases.
    Returns True if updated, False if already latest or failed.
    """
    console.print()
    console.print(f"  [dim]Current version:[/dim] [bold]v{__version__}[/bold]")

    with console.status("  Checking for updates..."):
        latest = get_latest_version()

    if not latest:
        console.print("  [yellow]Could not check for updates. Check your internet connection.[/yellow]")
        return False

    console.print(f"  [dim]Latest version:[/dim]  [bold]v{latest}[/bold]")

    if latest == __version__ and not force:
        console.print()
        console.print("  [green]Already up to date.[/green]")
        return False

    # Show what's new from the GitHub release notes
    _show_release_notes(latest)
    console.print()

    plat = _detect_platform()

    if not plat:
        console.print("  [yellow]Unsupported platform. Update manually:[/yellow]")
        console.print(f"    curl -fsSL {INSTALL_SCRIPT} | bash")
        return False

    # Download the binary directly
    asset_url = f"https://github.com/{REPO}/releases/download/v{latest}/machina-{plat}"

    # Always install to the system bin path (not venv)
    install_dir = Path(os.environ.get("MACHINA_INSTALL_DIR", "/usr/local/bin"))
    target = install_dir / "machina"

    console.print(f"  Downloading machina v{latest} ({plat})...")

    try:
        with httpx.Client(timeout=60, follow_redirects=True) as client:
            resp = client.get(asset_url)

            if resp.status_code == 404:
                console.print(f"  [red]Binary not found for {plat}.[/red]")
                console.print(f"  [dim]Try manually:[/dim] curl -fsSL {INSTALL_SCRIPT} | bash")
                return False

            if resp.status_code != 200:
                console.print(f"  [red]Download failed (HTTP {resp.status_code}).[/red]")
                return False

            # Write to temp file
            tmp = tempfile.NamedTemporaryFile(delete=False, prefix="machina-update-")
            tmp.write(resp.content)
            tmp.close()
            os.chmod(tmp.name, 0o755)

            # Replace the binary
            if target.parent.exists() and os.access(target.parent, os.W_OK):
                shutil.move(tmp.name, str(target))
            else:
                console.print(f"  [dim]Need sudo to install to {target.parent}[/dim]")
                result = subprocess.run(
                    ["sudo", "mv", tmp.name, str(target)],
                    capture_output=True, text=True,
                )
                if result.returncode != 0:
                    console.print(f"  [red]Failed: {result.stderr.strip()}[/red]")
                    os.unlink(tmp.name)
                    return False

        console.print(f"  [green]Updated to v{latest}[/green]")
        console.print(f"  [dim]Installed to {target}[/dim]")
        console.print()

        # Verify
        try:
            verify = subprocess.run(
                [str(target), "version"],
                capture_output=True, text=True, timeout=5,
            )
            if verify.returncode == 0:
                console.print(f"  {verify.stdout.strip()}")
        except Exception:
            pass

        return True

    except Exception as e:
        console.print(f"  [red]Update failed: {e}[/red]")
        console.print(f"  [dim]Try manually:[/dim] curl -fsSL {INSTALL_SCRIPT} | bash")
        return False
