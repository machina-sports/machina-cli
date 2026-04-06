"""Skills-first command surface built on top of template plumbing."""

from pathlib import Path
from typing import Optional, List

import typer
from rich.console import Console
from rich.panel import Panel

from machina_cli.commands import template, agent as agent_cmd, workflow as workflow_cmd

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

    def download_dir(remote_path: str, local_dir: Path, http_client):
        api_url = f"https://api.github.com/repos/{owner_repo}/contents/{urllib.parse.quote(remote_path)}?ref={branch}"
        resp = http_client.get(api_url, headers={"Accept": "application/vnd.github.v3+json"})
        resp.raise_for_status()
        files = resp.json()
        if isinstance(files, list):
            for file_info in files:
                file_type = file_info.get("type")
                file_name = file_info.get("name")
                if not file_name:
                    continue
                if file_type == "file":
                    download_url = file_info.get("download_url")
                    if download_url:
                        file_resp = http_client.get(download_url)
                        file_resp.raise_for_status()
                        with open(local_dir / file_name, "wb") as f:
                            f.write(file_resp.content)
                elif file_type == "dir":
                    sub_local = local_dir / file_name
                    sub_local.mkdir(parents=True, exist_ok=True)
                    download_dir(f"{remote_path}/{file_name}", sub_local, http_client)

    with httpx.Client(timeout=30.0) as http_client:
        download_dir(template_path, target_dir, http_client)


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


def _load_skill_manifest(skill_name: str):
    import yaml

    candidates = [
        Path.cwd() / skill_name / 'skill.yml',
        Path.cwd() / 'skills' / skill_name / 'skill.yml',
        Path.cwd() / f'{skill_name}.yml',
    ]
    for path in candidates:
        if path.exists():
            with open(path, 'r') as f:
                data = yaml.safe_load(f) or {}
            return path, data.get('skill', {})
    return None, None


@app.command("info")
def skill_info(
    skill_path: str = typer.Argument(..., help="Path to the skill/template (e.g. skills/mkn-constructor)"),
):
    """Show skill metadata and manifest location when available."""
    _ensure_constructor_installed()
    manifest_path, skill = _load_skill_manifest(Path(skill_path).name)
    if manifest_path and skill:
        console.print(Panel.fit(
            f"[bold]Name:[/bold] {skill.get('name', 'N/A')}\n"
            f"[bold]Title:[/bold] {skill.get('title', 'N/A')}\n"
            f"[bold]Description:[/bold] {skill.get('description', 'N/A')}\n"
            f"[bold]Version:[/bold] {skill.get('version', 'N/A')}\n"
            f"[bold]Manifest:[/bold] {manifest_path}",
            title='Skill Info',
            border_style='#FF5C1F',
        ))
        return

    p = Path(skill_path)
    console.print(f"[bold]Skill path:[/bold] {skill_path}")
    console.print(f"[dim]Expected manifest:[/dim] {p / 'skill.yml'}")
    console.print(f"[dim]Expected guide:[/dim] {p / 'SKILL.md'}")
    console.print("[dim]Install via:[/dim] machina skills install <path>")


@app.command("run")
def run_skill(
    skill_name: str = typer.Argument(..., help="Installed skill name"),
    params: Optional[List[str]] = typer.Argument(None, help="Parameters as key=value pairs"),
    entrypoint: Optional[str] = typer.Option(None, "--entrypoint", "-e", help="Specific workflow or agent entrypoint name"),
    project_id: Optional[str] = typer.Option(None, "--project", "-p", help="Project ID"),
    sync: bool = typer.Option(True, "--sync/--async", help="Sync (wait) or async (schedule)"),
    watch: bool = typer.Option(False, "--watch", "-w", help="Watch async execution progress"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Resolve a skill entrypoint into the existing agent/workflow runtime."""
    _ensure_constructor_installed()
    manifest_path, skill = _load_skill_manifest(skill_name)
    if not skill:
        console.print(f"[red]Skill manifest not found for:[/red] {skill_name}")
        console.print("[dim]Expected a local skill.yml. Install or bootstrap the skill first.[/dim]")
        raise typer.Exit(1)

    workflows = skill.get('workflows', []) or []
    agents = skill.get('agents', []) or []
    choices = []
    for wf in workflows:
        if isinstance(wf, dict) and wf.get('name'):
            choices.append(('workflow', wf.get('name')))
    for ag in agents:
        if isinstance(ag, dict) and ag.get('name'):
            choices.append(('agent', ag.get('name')))

    if not choices:
        console.print(f"[red]No runnable entrypoints found in skill:[/red] {skill.get('name', skill_name)}")
        raise typer.Exit(1)

    selected = None
    if entrypoint:
        for kind, name in choices:
            if name == entrypoint:
                selected = (kind, name)
                break
        if not selected:
            console.print(f"[red]Entrypoint not found:[/red] {entrypoint}")
            raise typer.Exit(1)
    elif len(choices) == 1:
        selected = choices[0]
    else:
        console.print("[yellow]Multiple entrypoints found. Use --entrypoint with one of:[/yellow]")
        for kind, name in choices:
            console.print(f"  - {kind}: {name}")
        raise typer.Exit(1)

    kind, name = selected
    console.print(f"[bold]Resolved skill:[/bold] {skill.get('name', skill_name)}")
    console.print(f"[bold]Entrypoint:[/bold] {kind} → {name}")
    console.print(f"[dim]Manifest:[/dim] {manifest_path}")

    if kind == 'workflow':
        return workflow_cmd.run_workflow(
            name=name,
            params=params,
            project_id=project_id,
            sync=sync,
            watch=watch,
            json_output=json_output,
        )

    return agent_cmd.run_agent(
        name=name,
        params=params,
        project_id=project_id,
        sync=sync,
        watch=watch,
        json_output=json_output,
    )


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
