"""Self-update logic for binary, pip/pipx, and editable installations."""

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

import httpx
from rich.console import Console
from rich.text import Text

from machina_cli import __version__
from machina_cli.versioning import is_newer

console = Console()

REPO = "machina-sports/machina-cli"
GITHUB_API = f"https://api.github.com/repos/{REPO}/releases/latest"
INSTALL_SCRIPT = f"https://raw.githubusercontent.com/{REPO}/main/install.sh"


def _installation_kind() -> str:
    """Return ``binary``, ``python``, or ``editable`` for this process."""
    if getattr(sys, "frozen", False):
        return "binary"
    try:
        direct_url = distribution("machina-cli").read_text("direct_url.json")
        metadata = json.loads(direct_url) if direct_url else {}
        if (metadata.get("dir_info") or {}).get("editable") is True:
            return "editable"
    except (PackageNotFoundError, json.JSONDecodeError, OSError, TypeError, UnicodeError):
        pass
    return "python"


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
                        console.print(Text(f"  {line}", style="dim"))
                    if len(body.split("\n")) > 15:
                        console.print(
                            f"  [dim]... (see full notes at github.com/{REPO}/releases/tag/v{version})[/dim]"
                        )
                    console.print()
    except Exception:
        pass


def _update_python_package(version: str, force: bool) -> bool:
    command = [sys.executable, "-m", "pip", "install", "--upgrade"]
    if force:
        command.append("--force-reinstall")
    command.append(f"machina-cli=={version}")

    console.print(f"  Updating Python package to v{version}...")
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        console.print("  [red]Python package update failed.[/red]")
        if detail:
            console.print(Text(f"  {detail[-1]}", style="dim"))
        console.print("  [dim]If installed with pipx, try:[/dim] pipx upgrade machina-cli")
        return False

    console.print(f"  [green]Updated to v{version}[/green]")
    console.print("  [dim]Restart the CLI to use the new version.[/dim]")
    return True


def _binary_target() -> Path:
    configured_dir = os.environ.get("MACHINA_INSTALL_DIR")
    if configured_dir:
        return Path(configured_dir).expanduser() / "machina"
    return Path(sys.executable).resolve()


def _update_binary(version: str) -> bool:
    plat = _detect_platform()
    if not plat:
        console.print("  [yellow]Unsupported binary platform. Update manually:[/yellow]")
        console.print(f"    curl -fsSL {INSTALL_SCRIPT} | bash")
        return False

    asset_url = f"https://github.com/{REPO}/releases/download/v{version}/machina-{plat}"
    target = _binary_target()
    temporary_path: Path | None = None
    console.print(f"  Downloading machina v{version} ({plat})...")

    try:
        with httpx.Client(timeout=60, follow_redirects=True) as client:
            response = client.get(asset_url)
        if response.status_code == 404:
            console.print(f"  [red]Binary not found for {plat}.[/red]")
            console.print(f"  [dim]Try manually:[/dim] curl -fsSL {INSTALL_SCRIPT} | bash")
            return False
        if response.status_code != 200:
            console.print(f"  [red]Download failed (HTTP {response.status_code}).[/red]")
            return False
        if len(response.content) < 1024:
            console.print("  [red]Downloaded asset is unexpectedly small; update aborted.[/red]")
            return False

        with tempfile.NamedTemporaryFile(delete=False, prefix="machina-update-") as temporary:
            temporary.write(response.content)
            temporary_path = Path(temporary.name)
        temporary_path.chmod(0o755)

        if target.parent.exists() and os.access(target.parent, os.W_OK):
            shutil.move(str(temporary_path), str(target))
        else:
            console.print(f"  [dim]Need sudo to install to {target.parent}[/dim]")
            result = subprocess.run(
                ["sudo", "mv", str(temporary_path), str(target)],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                console.print(f"  [red]Failed: {result.stderr.strip()}[/red]")
                return False
        temporary_path = None

        console.print(f"  [green]Updated to v{version}[/green]")
        console.print(f"  [dim]Installed to {target}[/dim]")
        return True
    except Exception as error:
        console.print(Text(f"  Update failed: {error}", style="red"))
        console.print(f"  [dim]Try manually:[/dim] curl -fsSL {INSTALL_SCRIPT} | bash")
        return False
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def do_update(force: bool = False, check: bool = False) -> bool:
    """
    Update using the installation method that owns the current executable.
    Returns True if updated, False if already latest or failed.
    """
    console.print()
    console.print(f"  [dim]Current version:[/dim] [bold]v{__version__}[/bold]")

    with console.status("  Checking for updates..."):
        latest = get_latest_version()

    if not latest:
        console.print(
            "  [yellow]Could not check for updates. Check your internet connection.[/yellow]"
        )
        return False

    console.print(f"  [dim]Latest version:[/dim]  [bold]v{latest}[/bold]")

    update_available = is_newer(latest, __version__)
    same_version = not is_newer(latest, __version__) and not is_newer(__version__, latest)

    if check:
        console.print()
        if update_available:
            console.print(
                f"  [yellow]Update available:[/yellow] v{__version__} → [bold green]v{latest}[/bold green]"
            )
            console.print("  [dim]Run[/dim] [bold]machina update[/bold] [dim]to install it.[/dim]")
        elif same_version:
            console.print("  [green]Already up to date.[/green]")
        else:
            console.print("  [green]This build is newer than the latest published release.[/green]")
        return False

    if not update_available and not (force and same_version):
        console.print()
        if same_version:
            console.print("  [green]Already up to date.[/green]")
        else:
            console.print("  [green]This build is newer than the latest published release.[/green]")
        return False

    # Show what's new from the GitHub release notes
    _show_release_notes(latest)
    console.print()

    installation = _installation_kind()
    if installation == "editable":
        console.print(
            "  [yellow]Editable development install detected; no files were replaced.[/yellow]"
        )
        console.print(
            "  [dim]Update the repository, then reinstall with:[/dim] uv pip install -e ."
        )
        return False
    if installation == "python":
        return _update_python_package(latest, force)
    return _update_binary(latest)
