"""Self-update logic for machina-cli.

Detects install method and updates accordingly:
- Binary (install.sh): downloads latest binary from GitHub Releases
- pip/pipx: runs pip install --upgrade
- editable (dev): git pull
"""

import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx
from rich.console import Console

from machina_cli import __version__

console = Console()

REPO = "machina-sports/machina-cli"
GITHUB_API = f"https://api.github.com/repos/{REPO}/releases/latest"


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

    os_name = {"linux": "linux", "darwin": "darwin"}.get(system)
    arch = {"x86_64": "amd64", "amd64": "amd64", "arm64": "arm64", "aarch64": "arm64"}.get(machine)

    if not os_name or not arch:
        return ""
    return f"{os_name}-{arch}"


def _detect_install_method() -> str:
    """
    Detect how machina was installed.
    Returns: 'binary' | 'pipx' | 'pip' | 'editable' | 'unknown'
    """
    machina_bin = shutil.which("machina")

    # Check if running in editable/dev mode
    try:
        from importlib.metadata import distribution
        dist = distribution("machina-cli")
        # Check if it's an editable install (contains .egg-link or direct_url with editable)
        direct_url = dist.read_text("direct_url.json")
        if direct_url and "editable" in direct_url:
            return "editable"
    except Exception:
        pass

    # Check for pipx
    if machina_bin and ".local/pipx" in str(machina_bin):
        return "pipx"

    # Check if installed via pip in a venv
    if machina_bin and ("site-packages" in str(machina_bin) or "venv" in str(machina_bin)):
        return "pip"

    # Check if it's a standalone binary (not in a Python path)
    if machina_bin:
        bin_path = Path(machina_bin)
        # Binaries from install.sh go to /usr/local/bin or similar
        if bin_path.parent in (Path("/usr/local/bin"), Path.home() / ".local" / "bin"):
            # If it's NOT a Python script, it's the standalone binary
            try:
                with open(bin_path, "rb") as f:
                    header = f.read(4)
                    # Python scripts start with #! or are text
                    if header[:2] != b"#!":
                        return "binary"
            except Exception:
                pass

    # Fallback: check if pip knows about it
    try:
        from importlib.metadata import distribution
        distribution("machina-cli")
        return "pip"
    except Exception:
        pass

    return "unknown"


def do_update(force: bool = False) -> bool:
    """
    Run the self-update.
    Returns True if updated, False if already latest or failed.
    """
    console.print()
    console.print(f"  [dim]Current version:[/dim] [bold]v{__version__}[/bold]")

    with console.status("Checking for updates..."):
        latest = get_latest_version()

    if not latest:
        console.print("  [yellow]Could not check for updates. Check your internet connection.[/yellow]")
        return False

    console.print(f"  [dim]Latest version:[/dim]  [bold]v{latest}[/bold]")

    if latest == __version__ and not force:
        console.print()
        console.print("  [green]Already up to date.[/green]")
        return False

    method = _detect_install_method()
    console.print(f"  [dim]Install method:[/dim]  {method}")
    console.print()

    if method == "binary":
        return _update_binary(latest)
    elif method == "pipx":
        return _update_pipx()
    elif method == "pip":
        return _update_pip()
    elif method == "editable":
        return _update_editable()
    else:
        console.print("  [yellow]Could not detect install method.[/yellow]")
        console.print("  [dim]Try one of:[/dim]")
        console.print("    pip install --upgrade machina-cli")
        console.print("    pipx upgrade machina-cli")
        console.print(
            "    curl -fsSL https://raw.githubusercontent.com/"
            f"{REPO}/main/install.sh | bash"
        )
        return False


def _update_binary(version: str) -> bool:
    """Update standalone binary from GitHub Releases."""
    plat = _detect_platform()
    if not plat:
        console.print("  [red]Unsupported platform for binary update.[/red]")
        return False

    asset_url = f"https://github.com/{REPO}/releases/download/v{version}/machina-{plat}"
    machina_bin = shutil.which("machina")

    if not machina_bin:
        console.print("  [red]Cannot find machina binary in PATH.[/red]")
        return False

    console.print(f"  Downloading machina v{version}...")

    try:
        with httpx.Client(timeout=60, follow_redirects=True) as client:
            resp = client.get(asset_url)
            if resp.status_code != 200:
                console.print(f"  [red]Download failed (HTTP {resp.status_code}).[/red]")
                return False

            tmp = tempfile.NamedTemporaryFile(delete=False, prefix="machina-")
            tmp.write(resp.content)
            tmp.close()
            os.chmod(tmp.name, 0o755)

            # Replace the binary
            target = Path(machina_bin)
            if target.parent.exists() and os.access(target.parent, os.W_OK):
                shutil.move(tmp.name, str(target))
            else:
                console.print(f"  Need sudo to update {target}")
                subprocess.run(["sudo", "mv", tmp.name, str(target)], check=True)

        console.print(f"  [green]Updated to v{version}[/green]")
        return True
    except Exception as e:
        console.print(f"  [red]Update failed: {e}[/red]")
        return False


def _update_pipx() -> bool:
    """Update via pipx."""
    console.print("  Running pipx upgrade machina-cli...")
    result = subprocess.run(
        ["pipx", "upgrade", "machina-cli"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        console.print(f"  [green]Updated successfully.[/green]")
        return True
    else:
        console.print(f"  [red]pipx upgrade failed:[/red] {result.stderr.strip()}")
        return False


def _update_pip() -> bool:
    """Update via pip."""
    console.print("  Running pip install --upgrade machina-cli...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", "machina-cli"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        console.print(f"  [green]Updated successfully.[/green]")
        return True
    else:
        console.print(f"  [red]pip upgrade failed:[/red] {result.stderr.strip()}")
        return False


def _update_editable() -> bool:
    """Update editable/dev install via git pull."""
    console.print("  [dim]Editable install detected — running git pull...[/dim]")
    # Find the source directory from the package location
    try:
        import machina_cli
        src_dir = Path(machina_cli.__file__).parent.parent.parent  # src/machina_cli/__init__.py -> repo root
        if (src_dir / ".git").exists():
            result = subprocess.run(
                ["git", "pull"], cwd=str(src_dir),
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                console.print(f"  [green]Pulled latest changes.[/green]")
                if result.stdout.strip():
                    console.print(f"  [dim]{result.stdout.strip()}[/dim]")
                return True
            else:
                console.print(f"  [red]git pull failed:[/red] {result.stderr.strip()}")
                return False
        else:
            console.print(f"  [yellow]No .git directory found at {src_dir}[/yellow]")
            return False
    except Exception as e:
        console.print(f"  [red]Failed: {e}[/red]")
        return False
