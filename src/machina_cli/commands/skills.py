"""Skills-first command surface built on top of template plumbing."""

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel

from machina_cli.commands import template

app = typer.Typer(help="Skills management")
console = Console()

CONSTRUCTOR_SKILL_PATH = "skills/mkn-constructor"
CONSTRUCTOR_LOCAL_DIR = "mkn-constructor"


def _download_template_files(template_path: str, repo: str, branch: str):
    """Download local package files from GitHub without requiring project context."""
    import httpx
    import urllib.parse

    target_dir = Path.cwd() / Path(template_path).name
    target_dir.mkdir(parents=True, exist_ok=True)

    repo_cleaned = repo.replace(".git", "").replace(".git/", "").rstrip("/")
    if "github.com/" in repo_cleaned:
        owner_repo = repo_cleaned.split("github.com/")[1]
    else:
        owner_repo = "machina-sports/machina-templates"

    api_url = f"https://api.github.com/repos/{owner_repo}/contents/{urllib.parse.quote(template_path)}?ref={branch}"

    with httpx.Client(timeout=30.0) as http_client:
        resp = http_client.get(api_url, headers={"Accept": "application/vnd.github.v3+json"})
        resp.raise_for_status()
        files = resp.json()
        if isinstance(files, list):
            for file_info in files:
                if file_info.get("type") == "file":
                    download_url = file_info.get("download_url")
                    file_name = file_info.get("name")
                    if download_url and file_name:
                        file_resp = http_client.get(download_url)
                        file_resp.raise_for_status()
                        with open(target_dir / file_name, "wb") as f:
                            f.write(file_resp.content)


def _ensure_constructor_installed(
    repo: str = template.DEFAULT_REPO,
    branch: str = template.DEFAULT_BRANCH,
):
    """Best-effort local bootstrap of mkn-constructor into the current workspace."""
    local_dir = Path.cwd() / CONSTRUCTOR_LOCAL_DIR
    if local_dir.exists():
        return

    console.print(f"[dim]Bootstrapping constructor skill locally:[/dim] {CONSTRUCTOR_SKILL_PATH}")
    _download_template_files(CONSTRUCTOR_SKILL_PATH, repo=repo, branch=branch)


@app.command("list")
def list_skills(
    project_id: Optional[str] = typer.Option(None, "--project", "-p", help="Project ID"),
    repo: str = typer.Option(template.DEFAULT_REPO, "--repo", "-r", help="Git repository URL"),
    branch: str = typer.Option(template.DEFAULT_BRANCH, "--branch", "-b", help="Git branch"),
    private: bool = typer.Option(False, "--private", help="Private repository"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """List available skills from the template repository."""
    _ensure_constructor_installed(repo=repo, branch=branch)
    return template.list_templates(
        project_id=project_id,
        repo=repo,
        branch=branch,
        private=private,
        json_output=json_output,
    )


@app.command("install")
def install_skill(
    skill_path: str = typer.Argument(..., help="Path to the skill/template (e.g. skills/mkn-constructor or connectors/polymarket)"),
    project_id: Optional[str] = typer.Option(None, "--project", "-p", help="Project ID"),
    repo: str = typer.Option(template.DEFAULT_REPO, "--repo", "-r", help="Git repository URL"),
    branch: str = typer.Option(template.DEFAULT_BRANCH, "--branch", "-b", help="Git branch"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output raw JSON for agent ingestion"),
):
    """Install a skill/package from the registry."""
    _ensure_constructor_installed(repo=repo, branch=branch)
    return template.install_template(
        template_path=skill_path,
        project_id=project_id,
        repo=repo,
        branch=branch,
        json_output=json_output,
    )


@app.command("push")
def push_skill(
    target_dir: str = typer.Argument(..., help="Path to local folder containing your custom skill/template"),
    project_id: Optional[str] = typer.Option(None, "--project", "-p", help="Project ID"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output raw JSON for agent ingestion"),
):
    """Push a local skill/package to the Machina pod."""
    _ensure_constructor_installed()
    return template.push_template(
        target_dir=target_dir,
        project_id=project_id,
        json_output=json_output,
    )


@app.command("info")
def skill_info(
    skill_path: str = typer.Argument(..., help="Path to the skill/template (e.g. skills/mkn-constructor)"),
):
    """Show the expected local manifest files for a skill/package."""
    _ensure_constructor_installed()
    p = Path(skill_path)
    console.print(f"[bold]Skill path:[/bold] {skill_path}")
    console.print(f"[dim]Expected manifest:[/dim] {p / 'skill.yml'}")
    console.print(f"[dim]Expected guide:[/dim] {p / 'SKILL.md'}")
    console.print("[dim]Install via:[/dim] machina skills install <path>")


@app.command("run")
def run_skill(
    skill_name: str = typer.Argument(..., help="Installed skill name"),
):
    """Placeholder skills-first run surface.

    Current behavior: instruct the user/operator to use the skill entrypoint from Studio or
    the installed local guide until backend runtime dispatch is formalized.
    """
    _ensure_constructor_installed()
    console.print(f"[bold]Skill:[/bold] {skill_name}")
    console.print("[yellow]Direct skill runtime dispatch is not formalized in machina-cli yet.[/yellow]")
    console.print("[dim]For now, install the package and follow the skill's SKILL.md or use the Studio Skills run surface.[/dim]")


@app.command("constructor")
def constructor_bridge(
    install: bool = typer.Option(True, "--install/--no-install", help="Install the constructor skill package first"),
    project_id: Optional[str] = typer.Option(None, "--project", "-p", help="Project ID"),
    repo: str = typer.Option(template.DEFAULT_REPO, "--repo", "-r", help="Git repository URL"),
    branch: str = typer.Option(template.DEFAULT_BRANCH, "--branch", "-b", help="Git branch"),
):
    """Use mkn-constructor as the built-in authoring bridge for new skills/templates/connectors."""
    if install:
        _ensure_constructor_installed(repo=repo, branch=branch)

    console.print(Panel.fit(
        f"[bold]Constructor skill:[/bold] {CONSTRUCTOR_SKILL_PATH}\n"
        "[bold]Purpose:[/bold] Build new skills, templates, and connectors in the canonical Machina format\n"
        "[bold]Next action:[/bold] Read the installed SKILL.md and use the init/create/validate/install references as the authoring workflow",
        title="mkn-constructor bridge",
        border_style="#FF5C1F",
    ))
