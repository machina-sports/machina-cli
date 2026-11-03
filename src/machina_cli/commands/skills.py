"""Skills-first command surface built on top of template plumbing."""

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from machina_cli import mcp_session
from machina_cli.commands import agent as agent_cmd
from machina_cli.commands import template
from machina_cli.commands import workflow as workflow_cmd

app = typer.Typer(help="Skills management")
console = Console()

CONSTRUCTOR_SKILL_PATH = "skills/mkn-constructor"
CONSTRUCTOR_LOCAL_DIR = "mkn-constructor"


def _download_template_files(template_path: str, repo: str, branch: str):
    """Download local package files from GitHub without requiring project context."""
    import urllib.parse

    import httpx

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
    project_id: str | None = typer.Option(None, "--project", "-p", help="Project ID"),
    repo: str = typer.Option(template.DEFAULT_REPO, "--repo", "-r", help="Git repository URL"),
    branch: str = typer.Option(template.DEFAULT_BRANCH, "--branch", "-b", help="Git branch"),
    private: bool = typer.Option(False, "--private", help="Private repository"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """List available skills from the template repository (read-only: installs nothing)."""
    return template.list_templates(
        project_id=project_id,
        repo=repo,
        branch=branch,
        private=private,
        json_output=json_output,
    )


@app.command("install")
def install_skill(
    skill_path: str = typer.Argument(
        ...,
        help="Path to the skill/template (e.g. skills/mkn-constructor or connectors/polymarket)",
    ),
    project_id: str | None = typer.Option(None, "--project", "-p", help="Project ID"),
    repo: str = typer.Option(template.DEFAULT_REPO, "--repo", "-r", help="Git repository URL"),
    branch: str = typer.Option(template.DEFAULT_BRANCH, "--branch", "-b", help="Git branch"),
    json_output: bool = typer.Option(
        False, "--json", "-j", help="Output raw JSON for agent ingestion"
    ),
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
    target_dir: str = typer.Argument(
        ..., help="Path to local folder containing your custom skill/template"
    ),
    project_id: str | None = typer.Option(None, "--project", "-p", help="Project ID"),
    json_output: bool = typer.Option(
        False, "--json", "-j", help="Output raw JSON for agent ingestion"
    ),
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
        Path.cwd() / skill_name / "skill.yml",
        Path.cwd() / "skills" / skill_name / "skill.yml",
        Path.cwd() / f"{skill_name}.yml",
    ]
    for path in candidates:
        if path.exists():
            with open(path, "r") as f:
                data = yaml.safe_load(f) or {}
            return path, data.get("skill", {})
    return None, None


@app.command("info")
def skill_info(
    skill_path: str = typer.Argument(
        ..., help="Path to the skill/template (e.g. skills/mkn-constructor)"
    ),
):
    """Show a local skill's manifest (skill.yml). For an installed project Skill use `skills show`."""
    manifest_path, skill = _load_skill_manifest(Path(skill_path).name)
    if manifest_path and skill:
        console.print(
            Panel.fit(
                f"[bold]Name:[/bold] {skill.get('name', 'N/A')}\n"
                f"[bold]Title:[/bold] {skill.get('title', 'N/A')}\n"
                f"[bold]Description:[/bold] {skill.get('description', 'N/A')}\n"
                f"[bold]Version:[/bold] {skill.get('version', 'N/A')}\n"
                f"[bold]Manifest:[/bold] {manifest_path}",
                title="Skill Info",
                border_style="#FF5C1F",
            )
        )
        return

    p = Path(skill_path)
    console.print(f"[bold]Skill path:[/bold] {skill_path}")
    console.print(f"[dim]Expected manifest:[/dim] {p / 'skill.yml'}")
    console.print(f"[dim]Expected guide:[/dim] {p / 'SKILL.md'}")
    console.print("[dim]Install via:[/dim] machina skills install <path>")


@app.command("run")
def run_skill(
    skill_name: str = typer.Argument(..., help="Installed skill name"),
    params: list[str] | None = typer.Argument(None, help="Parameters as key=value pairs"),
    entrypoint: str | None = typer.Option(
        None, "--entrypoint", "-e", help="Specific workflow or agent entrypoint name"
    ),
    project_id: str | None = typer.Option(None, "--project", "-p", help="Project ID"),
    sync: bool = typer.Option(True, "--sync/--async", help="Sync (wait) or async (schedule)"),
    watch: bool = typer.Option(False, "--watch", "-w", help="Watch async execution progress"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    remote: bool = typer.Option(
        False, "--remote", help="Execute the installed project Skill (by name or id) via MCP"
    ),
    message: str | None = typer.Option(
        None, "--message", "-m", help="--remote: user message for the skill's agent context"
    ),
    timeout: float = typer.Option(30.0, "--timeout", help="--remote: MCP timeout in seconds"),
):
    """Run a skill: --remote executes the installed project Skill via the pod's MCP
    (submit-only — prints a skill_run_id for `skills result`); otherwise resolves a
    local skill.yml entrypoint into the agent/workflow runtime."""
    if remote:
        return _run_remote(skill_name, params, message, project_id, json_output, timeout)
    manifest_path, skill = _load_skill_manifest(skill_name)
    if not skill:
        console.print(f"[red]Skill manifest not found for:[/red] {skill_name}")
        console.print(
            "[dim]Expected a local skill.yml. Install or bootstrap the skill first.[/dim]"
        )
        raise typer.Exit(1)

    workflows = skill.get("workflows", []) or []
    agents = skill.get("agents", []) or []
    choices = []
    for wf in workflows:
        if isinstance(wf, dict) and wf.get("name"):
            choices.append(("workflow", wf.get("name")))
    for ag in agents:
        if isinstance(ag, dict) and ag.get("name"):
            choices.append(("agent", ag.get("name")))

    if not choices:
        console.print(
            f"[red]No runnable entrypoints found in skill:[/red] {skill.get('name', skill_name)}"
        )
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

    if kind == "workflow":
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
    install: bool = typer.Option(
        True, "--install/--no-install", help="Install the constructor skill package first"
    ),
    project_id: str | None = typer.Option(None, "--project", "-p", help="Project ID"),
    repo: str = typer.Option(template.DEFAULT_REPO, "--repo", "-r", help="Git repository URL"),
    branch: str = typer.Option(template.DEFAULT_BRANCH, "--branch", "-b", help="Git branch"),
):
    """Use mkn-constructor as the built-in authoring bridge for new skills/templates/connectors."""
    if install:
        _ensure_constructor_installed(repo=repo, branch=branch)

    console.print(
        Panel.fit(
            f"[bold]Constructor skill:[/bold] {CONSTRUCTOR_SKILL_PATH}\n"
            "[bold]Purpose:[/bold] Build new skills, templates, and connectors in the canonical Machina format\n"
            "[bold]Next action:[/bold] Read the installed SKILL.md and use the init/create/validate/install references as the authoring workflow",
            title="mkn-constructor bridge",
            border_style="#FF5C1F",
        )
    )


# --- Installed project Skills (remote, through the pod's MCP tools) ----------
#
# Discovery (show/docs/result) is read-only. Only `run --remote` executes, and it
# is submit-only: registration/acceptance is never reported as a completed run.

SKILL_SCHEMA = "machina.skill/v1"
_SKILL_FIELDS = ("name", "title", "description", "version", "status", "category", "domain")
_TERMINAL = {"executed": "completed", "completed": "completed", "failed": "failed"}
_EXIT = {"completed": 0, "failed": 1, "partial": 2}


def _is_object_id(value: str) -> bool:
    return len(value) == 24 and all(c in "0123456789abcdef" for c in value.lower())


async def _get_skill(session, ref: str) -> dict:
    if _is_object_id(ref):
        skill = await mcp_session.call(session, "get_skill", {"item_id": ref})
    else:
        skill = await mcp_session.call(session, "get_skill_by_name", {"name": ref})
    if not isinstance(skill, dict) or not skill.get("_id"):
        raise mcp_session.MCPConnectError("not_found", f"skill '{ref}' not found")
    return skill


def _skill_view(skill: dict) -> dict:
    """Identity + supplied metadata only. Fields the server didn't supply are
    listed in `missing`, never synthesised. `instruction_only` is read from the
    supplied entrypoints (workflows/agents), not from the name."""
    workflows = skill.get("workflows") or []
    agents = skill.get("agents") or []
    view = {"id": skill.get("_id")}
    view.update({field: skill.get(field) for field in _SKILL_FIELDS})
    view.update(
        {
            "workflows": workflows,
            "agents": agents,
            "documents": [
                {"id": doc.get("_id"), "name": doc.get("name"), "title": doc.get("title")}
                for doc in skill.get("documents") or []
                if isinstance(doc, dict)
            ],
            "instruction_only": not workflows and not agents,
            "missing": [field for field in _SKILL_FIELDS if skill.get(field) in (None, "", [])],
        }
    )
    return view


def _remote(project_id, json_output, timeout, work):
    from machina_cli.commands.mcp import fail, resolve_base_url
    from machina_cli.config import resolve_auth_token

    project_id, base_url = resolve_base_url(project_id, json_output)
    try:
        _, result = mcp_session.run(base_url, resolve_auth_token(), work, timeout)
    except mcp_session.MCPConnectError as error:
        fail(error, json_output)
    return project_id, result


def _print_json(payload: dict):
    import json

    print(json.dumps(payload, default=str))


@app.command("show")
def show_skill(
    skill: str = typer.Argument(..., help="Installed project Skill name or id"),
    project_id: str | None = typer.Option(None, "--project", "-p", help="Project ID"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    timeout: float = typer.Option(30.0, "--timeout", help="MCP timeout in seconds"),
):
    """Show an installed project Skill: identity, entrypoints, ordered documents (read-only)."""
    project_id, record = _remote(project_id, json_output, timeout, lambda s: _get_skill(s, skill))
    view = _skill_view(record)
    if json_output:
        _print_json({"schema": SKILL_SCHEMA, "project_id": project_id, "skill": view})
        return

    def show(value):
        return value if value not in (None, "", []) else "[dim]not supplied[/dim]"

    console.print(
        Panel.fit(
            f"[bold]Id:[/bold] {view['id']}\n"
            f"[bold]Name:[/bold] {show(view['name'])}\n"
            f"[bold]Title:[/bold] {show(view['title'])}\n"
            f"[bold]Version:[/bold] {show(view['version'])}\n"
            f"[bold]Source:[/bold] {show(view['domain'])}\n"
            f"[bold]Registry status:[/bold] {show(view['status'])}\n"
            f"[bold]Description:[/bold] {show(view['description'])}",
            title=f"Skill · {project_id}",
            border_style="#FF5C1F",
        )
    )
    if view["instruction_only"]:
        console.print("[yellow]Instruction-only:[/yellow] no workflow/agent entrypoints supplied.")
    for kind in ("workflows", "agents"):
        for entry in view[kind]:
            label = entry.get("name") if isinstance(entry, dict) else entry
            console.print(f"  [bold]{kind[:-1]}:[/bold] {label}")
    for index, doc in enumerate(view["documents"], 1):
        console.print(f"  [bold]doc {index}:[/bold] {doc['name']}  [dim]{doc['id']}[/dim]")
    if view["documents"]:
        console.print(f"[dim]Read them with[/dim] machina skills docs {skill}")


@app.command("docs")
def skill_docs(
    skill: str = typer.Argument(..., help="Installed project Skill name or id"),
    name: str | None = typer.Option(None, "--name", "-n", help="Only the document with this name"),
    project_id: str | None = typer.Option(None, "--project", "-p", help="Project ID"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    timeout: float = typer.Option(30.0, "--timeout", help="MCP timeout in seconds"),
):
    """Read an installed Skill's linked documents (instructions/references), in order."""

    async def work(session):
        record = await _get_skill(session, skill)
        refs = _skill_view(record)["documents"]
        if name:
            refs = [doc for doc in refs if doc["name"] == name]
        documents = []
        for ref in refs:
            try:
                doc = await mcp_session.call(session, "get_document", {"item_id": ref["id"]})
            except mcp_session.MCPConnectError as error:
                if error.code not in ("not_found", "tool_failed"):
                    raise  # auth denials are not a "missing reference"
                documents.append({**ref, "error": error.message})
                continue
            documents.append(
                {
                    **ref,
                    "filetype": doc.get("filetype") if isinstance(doc, dict) else None,
                    "value": doc.get("value") if isinstance(doc, dict) else doc,
                }
            )
        return record, documents

    project_id, (record, documents) = _remote(project_id, json_output, timeout, work)
    missing = [doc for doc in documents if "error" in doc]
    if json_output:
        _print_json(
            {
                "schema": SKILL_SCHEMA,
                "project_id": project_id,
                "skill": {"id": record.get("_id"), "name": record.get("name")},
                "documents": documents,
            }
        )
    else:
        for doc in documents:
            console.rule(f"{doc['name']} · {doc['id']}")
            if "error" in doc:
                console.print(f"[red]Unavailable:[/red] {doc['error']}")
            elif isinstance(doc["value"], str):
                console.print(Text(doc["value"]))
            else:
                console.print_json(data=doc["value"])
    if not documents:
        if not json_output:
            console.print(
                "[yellow]No linked documents"
                + (f" named '{name}'" if name else "")
                + " — this Skill supplies none.[/yellow]"
            )
        raise typer.Exit(1)
    if missing:
        # A missing reference is a non-success outcome, never an empty success.
        raise typer.Exit(1)


def _params_to_context(params: list[str] | None) -> dict:
    context = {}
    for item in params or []:
        if "=" not in item:
            console.print(f"[red]Invalid parameter (expected key=value):[/red] {item}")
            raise typer.Exit(1)
        key, value = item.split("=", 1)
        context[key] = value
    return context


def _run_remote(skill, params, message, project_id, json_output, timeout):
    context_agent = _params_to_context(params)
    messages = [{"role": "user", "content": message}] if message else []
    if messages:
        context_agent["messages"] = messages
    state = {"submitted": False}

    async def work(session):
        record = await _get_skill(session, skill)
        if _skill_view(record)["instruction_only"]:
            raise mcp_session.MCPConnectError(
                "instruction_only",
                f"skill '{record.get('name')}' supplies no workflow/agent entrypoint to execute; "
                f"read it with `machina skills docs {skill}`",
            )
        state["submitted"] = True
        args = {
            "skill_id": record["_id"],
            "messages": messages,
            "context": {"context-agent": context_agent},
        }
        is_error, data, text = mcp_session.tool_payload(
            await session.call_tool("execute_skill", args)
        )
        if is_error:
            raise mcp_session.tool_error("execute_skill", text)
        run_id = data.get("skill_run_id") if isinstance(data, dict) else None
        inner = mcp_session.unwrap("execute_skill", data)
        run_id = run_id or (inner.get("skill_run_id") if isinstance(inner, dict) else None)
        return record, run_id, inner

    from machina_cli.commands.mcp import fail, resolve_base_url
    from machina_cli.config import resolve_auth_token

    project_id, base_url = resolve_base_url(project_id, json_output)
    try:
        _, (record, run_id, inner) = mcp_session.run(base_url, resolve_auth_token(), work, timeout)
    except mcp_session.MCPConnectError as error:
        if state["submitted"] and error.code == "endpoint_unavailable":
            # The request may have reached the server: never resubmit blindly.
            error = mcp_session.MCPConnectError(
                "submission_unknown",
                "submission may have run — check `machina execution` / Studio before retrying; "
                "it was not resubmitted",
            )
        fail(error, json_output)

    if not run_id:
        fail(
            mcp_session.MCPConnectError(
                "submission_unknown", "execute_skill returned no skill_run_id; outcome unknown"
            ),
            json_output,
        )
    payload = {
        "schema": "machina.skill.run/v1",
        "project_id": project_id,
        "skill": {"id": record.get("_id"), "name": record.get("name")},
        "outcome": "accepted",
        "skill_run_id": run_id,
        "task_id": inner.get("task_id") if isinstance(inner, dict) else None,
        "result_command": f"machina skills result {run_id}",
    }
    if json_output:
        _print_json(payload)
        return
    console.print(f"[bold]Skill:[/bold] {record.get('name')}  [dim]{record.get('_id')}[/dim]")
    console.print(f"[yellow]Accepted (not completed):[/yellow] skill_run_id {run_id}")
    console.print(f"[dim]Retrieve the outcome with[/dim] {payload['result_command']}")


def _skill_outcome(run: dict) -> str:
    """Normalise a skill run onto accepted/running/completed/failed/partial/unknown.
    A server-supplied `outcome` wins; otherwise map the run record's own status."""
    if run.get("outcome"):
        return str(run["outcome"])
    status = str(run.get("status") or "").lower()
    outcome = _TERMINAL.get(status)
    if outcome == "completed":
        done, total = run.get("completed_workflows"), run.get("total_workflows")
        if isinstance(done, int) and isinstance(total, int) and done < total:
            return "partial"
        return "completed"
    if outcome:
        return outcome
    return {"scheduled": "accepted", "executing": "running"}.get(status, "unknown")


@app.command("result")
def skill_result(
    skill_run_id: str = typer.Argument(..., help="skill_run_id returned by `skills run --remote`"),
    project_id: str | None = typer.Option(None, "--project", "-p", help="Project ID"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    timeout: float = typer.Option(30.0, "--timeout", help="MCP timeout in seconds"),
):
    """Retrieve a remote skill run's persisted outcome (read-only, never resubmits).

    Exit codes: 0 completed, 1 failed, 2 partial, 3 not finished yet / unknown.
    """

    async def work(session):
        return await mcp_session.call(
            session, "get_skill_execution", {"skill_run_id": skill_run_id, "compact": False}
        )

    project_id, run = _remote(project_id, json_output, timeout, work)
    if not isinstance(run, dict) or not run:
        from machina_cli.commands.mcp import fail

        fail(mcp_session.MCPConnectError("not_found", f"no skill run {skill_run_id}"), json_output)
    outcome = _skill_outcome(run)
    if json_output:
        _print_json(
            {
                "schema": "machina.skill.result/v1",
                "project_id": project_id,
                "skill_run_id": skill_run_id,
                "outcome": outcome,
                "status": run.get("status"),
                "error": run.get("error"),
                "execution": run,
            }
        )
    else:
        style = {"completed": "green", "failed": "red", "partial": "yellow"}.get(outcome, "cyan")
        console.print(f"[bold]Run:[/bold] {skill_run_id}  [{style}]{outcome}[/{style}]")
        console.print(f"[bold]Status:[/bold] {run.get('status')}")
        if run.get("error"):
            console.print(f"[red]Error:[/red] {run['error']}")
        if outcome in ("completed", "partial", "failed") and run.get("response") is not None:
            console.print_json(data=run["response"], default=str)
    raise typer.Exit(_EXIT.get(outcome, 3))
