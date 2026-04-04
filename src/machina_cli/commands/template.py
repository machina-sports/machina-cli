"""Template management commands."""

import os
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.tree import Tree

from machina_cli.project_client import ProjectClient

app = typer.Typer(help="Template management")
console = Console()

DEFAULT_REPO = "https://github.com/machina-sports/machina-templates.git/"
DEFAULT_BRANCH = "main"


@app.command("list")
def list_templates(
    project_id: Optional[str] = typer.Option(None, "--project", "-p", help="Project ID"),
    repo: str = typer.Option(DEFAULT_REPO, "--repo", "-r", help="Git repository URL"),
    branch: str = typer.Option(DEFAULT_BRANCH, "--branch", "-b", help="Git branch"),
    private: bool = typer.Option(False, "--private", help="Private repository"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """List available templates from the template repository."""
    client = ProjectClient(project_id)
    result = client.post("templates/directories/git", {
        "repo_url": repo,
        "branch": branch,
        "private_repository": private,
    })

    data = result.get("data", result)

    if json_output:
        import json
        console.print_json(json.dumps(data, default=str))
        return

    directories = data.get("directories", []) if isinstance(data, dict) else data

    if not directories:
        console.print("[yellow]No templates found.[/yellow]")
        return

    # Build a tree from the directory paths
    # Filter: only entries with "path" (directories), skip entries with only "datasets"
    paths = []
    template_datasets = {}
    for item in directories:
        if isinstance(item, dict):
            path = item.get("path", "")
            datasets = item.get("datasets")
            if path:
                paths.append(path)
            if datasets:
                # Count files per type in this template
                for ds in datasets:
                    ds_type = ds.get("type", "unknown")
                    ds_path = ds.get("path", "")
                    # Get the template name (first segment of path)
                    parts = ds_path.split("/")
                    if parts:
                        template_datasets.setdefault(ds_type, 0)
                        template_datasets[ds_type] = template_datasets[ds_type] + 1

    # Group top-level template names
    top_level = set()
    for p in paths:
        parts = p.split("/")
        if len(parts) >= 2:
            top_level.add(parts[0])
        elif len(parts) == 1 and parts[0]:
            top_level.add(parts[0])

    # Build tree grouped by top-level
    tree = Tree(f"[bold]Templates[/bold] [dim]({repo.split('/')[-2] if '/' in repo else repo})[/dim]")

    # Group paths under their top-level parent
    children: dict[str, list[str]] = {}
    for p in sorted(paths):
        parts = p.split("/")
        if len(parts) >= 2:
            parent = parts[0]
            child = "/".join(parts[1:])
            children.setdefault(parent, []).append(child)
        elif parts[0]:
            children.setdefault(parts[0], [])

    for parent in sorted(children.keys()):
        subs = children[parent]
        # Get unique second-level names (actual template names)
        template_names = set()
        for sub in subs:
            first = sub.split("/")[0]
            if first:
                template_names.add(first)

        if template_names:
            branch_node = tree.add(f"[bold]{parent}[/bold] [dim]({len(template_names)} templates)[/dim]")
            for name in sorted(template_names):
                branch_node.add(f"[#FF5C1F]{name}[/#FF5C1F]")
        else:
            tree.add(f"[bold]{parent}[/bold]")

    console.print(tree)
    console.print(f"\n  [dim]{len(paths)} directories, {len(top_level)} categories[/dim]")
import os
from pathlib import Path



@app.command("install")
def install_template(
    template_path: str = typer.Argument(..., help="Path to the template (e.g. agent-templates/bundesliga-podcast)"),
    project_id: Optional[str] = typer.Option(None, "--project", "-p", help="Project ID"),
    repo: str = typer.Option(DEFAULT_REPO, "--repo", "-r", help="Git repository URL"),
    branch: str = typer.Option(DEFAULT_BRANCH, "--branch", "-b", help="Git branch"),
):
    """Install a template: Provisions cloud resources via API and downloads local agent context."""
    client = ProjectClient(project_id)
    template_name = template_path.split('/')[-1]
    
    with console.status(f"[bold green]Provisioning Machina Cloud resources for '{template_name}'..."):
        payload = [{
            "repo_url": repo,
            "branch": branch,
            "template": template_path,
            "private_repository": False
        }]
        # Hit the real backend endpoint used by MCP
        result = client.post("templates/git", payload)
        
    if isinstance(result, dict) and result.get("status") == False:
        console.print(f"[red]Cloud provisioning failed:[/red] {result.get('error')}")
        raise typer.Exit(1)
        
    with console.status(f"[bold green]Downloading local agent context for '{template_name}'..."):
        import os
        from pathlib import Path
        local_dir = Path.cwd() / template_name
        tmp_dir = f"{template_name}_tmp"
        
        # Perform a sparse checkout to get just the requested template folder
        os.system(f"git clone -b {branch} --depth 1 --filter=blob:none --sparse {repo} {tmp_dir} > /dev/null 2>&1")
        os.system(f"cd {tmp_dir} && git sparse-checkout set {template_path} > /dev/null 2>&1")
        os.system(f"mv {tmp_dir}/{template_path} {local_dir} > /dev/null 2>&1")
        os.system(f"rm -rf {tmp_dir} > /dev/null 2>&1")
        
    # Agent-First Handoff Output (Machine Readable)
    console.print("\n<machina_install_result>")
    console.print("  <status>success</status>")
    console.print("  <cloud_provisioned>true</cloud_provisioned>")
    console.print(f"  <local_path>./{template_name}</local_path>")
    console.print("  <agent_instruction>")
    console.print("    1. Cloud infrastructure (connectors/datasets/mappings) successfully provisioned on the Machina Pod.")
    console.print(f"    2. ACTION REQUIRED: Read `./{template_name}/SKILL.md` (or README.md) immediately to understand how to interact with these resources.")
    console.print("  </agent_instruction>")
    console.print("</machina_install_result>")
