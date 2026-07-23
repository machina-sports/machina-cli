"""Scaffold deployable Machina applications."""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import zipfile
from pathlib import Path, PurePosixPath

import httpx
import typer
from rich.console import Console

app = typer.Typer(help="Create projects from official Machina starters")
console = Console()

TEMPLATE_REPOSITORY = "machina-sports/machina-boilerplate"
TEMPLATE_ARCHIVE = "https://github.com/{repository}/archive/refs/heads/{ref}.zip"
TEXT_EXTENSIONS = {
    ".css",
    ".env",
    ".example",
    ".json",
    ".md",
    ".mjs",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not slug:
        raise typer.BadParameter("name must contain at least one letter or number")
    return slug[:63]


def _download_archive(ref: str) -> bytes:
    override = os.environ.get("MACHINA_AI_APP_TEMPLATE_URL")
    url = override or TEMPLATE_ARCHIVE.format(repository=TEMPLATE_REPOSITORY, ref=ref)
    try:
        with httpx.Client(follow_redirects=True, timeout=60) as client:
            response = client.get(url)
            response.raise_for_status()
            return response.content
    except httpx.HTTPError as exc:
        raise RuntimeError(f"could not download {TEMPLATE_REPOSITORY}@{ref}: {exc}") from exc


def _safe_member_path(member: str) -> PurePosixPath | None:
    parts = PurePosixPath(member).parts
    if len(parts) < 2 or any(part in {"", ".", ".."} for part in parts):
        return None
    relative = PurePosixPath(*parts[1:])
    if relative.is_absolute():
        return None
    return relative


def _extract_template(archive: bytes, destination: Path) -> None:
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        for member in bundle.infolist():
            relative = _safe_member_path(member.filename)
            if relative is None:
                continue
            target = destination.joinpath(*relative.parts)
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(bundle.read(member))


def _replace_placeholders(destination: Path, name: str, slug: str) -> None:
    replacements = {
        "{{APP_NAME}}": name,
        "{{APP_SLUG}}": slug,
    }
    for path in destination.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        try:
            original = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rendered = original
        for placeholder, value in replacements.items():
            rendered = rendered.replace(placeholder, value)
        if rendered != original:
            path.write_text(rendered, encoding="utf-8")


def _init_git(destination: Path) -> bool:
    try:
        subprocess.run(
            ["git", "init", "--initial-branch=main"],
            cwd=destination,
            check=True,
            capture_output=True,
            text=True,
        )
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


@app.command("ai-app")
def create_ai_app(
    name: str = typer.Argument(..., help="Application name"),
    directory: Path | None = typer.Option(
        None,
        "--directory",
        "-d",
        help="Output directory (defaults to ./<slug>)",
    ),
    template_ref: str = typer.Option(
        "main",
        "--template-ref",
        help="Branch or tag from the official boilerplate",
    ),
    no_git: bool = typer.Option(False, "--no-git", help="Do not initialize a Git repository"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output machine-readable JSON"),
) -> None:
    """Create a chat app wired to a Machina pod and ready for AWS or Azure."""
    slug = _slugify(name)
    destination = (directory or Path.cwd() / slug).expanduser().resolve()
    if destination.exists() and any(destination.iterdir()):
        message = f"destination is not empty: {destination}"
        if json_output:
            print(json.dumps({"error": message}))
        else:
            console.print(f"[red]{message}[/red]")
        raise typer.Exit(1)

    destination.mkdir(parents=True, exist_ok=True)
    try:
        archive = _download_archive(template_ref)
        _extract_template(archive, destination)
        _replace_placeholders(destination, name=name, slug=slug)
    except (RuntimeError, zipfile.BadZipFile, OSError) as exc:
        if json_output:
            print(json.dumps({"error": str(exc)}))
        else:
            console.print(f"[red]Could not create app:[/red] {exc}")
        raise typer.Exit(1) from exc

    git_initialized = False if no_git else _init_git(destination)
    payload = {
        "name": name,
        "slug": slug,
        "path": str(destination),
        "template": TEMPLATE_REPOSITORY,
        "template_ref": template_ref,
        "git_initialized": git_initialized,
    }
    if json_output:
        print(json.dumps(payload))
        return

    console.print(f"\n[green]Created {name}[/green] at [bold]{destination}[/bold]")
    if not no_git and not git_initialized:
        console.print(
            "[yellow]Git was not initialized; run `git init` when Git is available.[/yellow]"
        )
    console.print("\nNext steps:")
    console.print(f"  cd {destination}")
    console.print("  cp .env.example .env.local")
    console.print("  npm install && npm run dev")
    console.print(
        "\nSet the repository variables documented in DEPLOYMENT.md to enable AWS/Azure Actions."
    )
