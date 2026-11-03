"""Create / update / delete for agent and workflow configurations (DX-02).

Thin wrappers over the existing Client API REST routes — no new contract:

    create  POST   /<kind>             body = the file, as-is
    read    GET    /<kind>/id/<id>     (by name: GET /<kind>/<name>)
    update  PUT    /<kind>/<id>        server applies `$set`: omitted fields are kept
    delete  DELETE /<kind>/<id>

Every write is read back and the persisted record printed, so the caller sees
the exact stored state instead of an optimistic echo. A rejected write (any
4xx/5xx, or `status: false` in an HTTP 200 body) exits non-zero with a
structured error.

Configuration is kept apart from lifecycle: `update` never writes `status`,
`scheduled`, `processing` or `last_execution`. A file that carries them with
their persisted value round-trips fine (they are dropped); a file that would
change them is refused — activation and scheduling are separate operations.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from machina_cli.project_client import ProjectAPIError, ProjectClient
from machina_cli.ui import console

SCHEMA = "machina.config/v1"

# Lifecycle/runtime state: never written by a configuration update.
LIFECYCLE_FIELDS = ("status", "scheduled", "processing", "last_execution")
# Server-managed bookkeeping, dropped from update bodies.
SERVER_FIELDS = ("created", "updated")


class ConfigError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def to_payload(self) -> dict:
        return {"error": self.message, "error_code": self.code}


def _is_object_id(value: str) -> bool:
    return len(value) == 24 and all(c in "0123456789abcdef" for c in value.lower())


def load_file(path: str) -> dict:
    file = Path(path)
    if not file.is_file():
        raise ConfigError("invalid_file", f"file not found: {path}")
    try:
        body = json.loads(file.read_text())
    except ValueError as exc:
        raise ConfigError("invalid_file", f"{path} is not valid JSON ({exc})") from None
    if not isinstance(body, dict) or not body:
        raise ConfigError("invalid_file", f"{path} must hold a non-empty JSON object")
    return body


def read(client: ProjectClient, kind: str, ref: str) -> dict:
    """Fetch one record by id (24-hex) or name; raises on absence."""
    path = f"{kind}/id/{ref}" if _is_object_id(ref) else f"{kind}/{ref}"
    record = client.get(path).get("data")
    if not isinstance(record, dict) or not record.get("_id"):
        raise ConfigError("not_found", f"{kind} '{ref}' not found")
    return record


def update_body(kind: str, current: dict, body: dict) -> dict:
    """The `$set` body for an update, with the lifecycle guard applied."""
    if "_id" in body and str(body["_id"]) != str(current["_id"]):
        raise ConfigError("id_mismatch", f"file _id {body['_id']} is not {kind} {current['_id']}")
    changed = [
        field for field in LIFECYCLE_FIELDS if field in body and body[field] != current.get(field)
    ]
    if changed:
        raise ConfigError(
            "lifecycle_change_refused",
            f"update would change {', '.join(changed)} — activation/scheduling is a separate "
            "operation; remove these fields (or keep their current values) and retry",
        )
    payload = {
        key: value
        for key, value in body.items()
        if key not in LIFECYCLE_FIELDS and key not in SERVER_FIELDS and key != "_id"
    }
    if not payload:
        raise ConfigError("invalid_file", "nothing to update: the file only has lifecycle fields")
    return payload


def agent_references(body: dict) -> list[dict]:
    """Workflows/skills an agent definition calls by name, in order, deduplicated."""
    refs, seen = [], set()
    for step in body.get("workflows") or []:
        if not isinstance(step, dict) or not isinstance(step.get("name"), str) or not step["name"]:
            continue
        ref = ("skill" if step.get("type") == "skill" else "workflow", step["name"])
        if ref not in seen:
            seen.add(ref)
            refs.append({"type": ref[0], "name": ref[1]})
    return refs


def _exists(client: ProjectClient, kind: str, name: str) -> bool:
    """Quiet existence check (no stderr noise for an expected miss)."""
    import httpx

    with httpx.Client(timeout=30) as http:
        response = http.get(
            f"{client.api_url}/{kind}/{name}",
            params={"fields": "_id,name"},
            headers=client._headers(),
        )
    if response.status_code in (401, 403):
        raise ProjectAPIError("not authorized to read references", response.status_code)
    try:
        body = response.json()
    except ValueError:
        return False
    data = body.get("data") if isinstance(body, dict) else None
    return response.status_code == 200 and isinstance(data, dict) and bool(data.get("_id"))


def check_references(client: ProjectClient, kind: str, body: dict) -> None:
    """Refuse an agent whose workflows[] call names that don't exist in the project.

    The REST API stores agents as given (Studio and template installs rely on
    that), so the CLI checks before writing, like the MCP adapter does.
    """
    if kind != "agent" or "workflows" not in body:
        return
    missing = [
        ref for ref in agent_references(body) if not _exists(client, ref["type"], ref["name"])
    ]
    if missing:
        names = ", ".join(f"{ref['type']} '{ref['name']}'" for ref in missing)
        raise ConfigError(
            "invalid_reference",
            f"the agent calls {names}, which do not exist in this project; create them first",
        )


def _emit(json_output: bool, kind: str, operation: str, record: dict | None, ref_id: str):
    if json_output:
        print(
            json.dumps(
                {
                    "schema": SCHEMA,
                    "resource": kind,
                    "operation": operation,
                    "id": ref_id,
                    "record": record,
                },
                default=str,
            )
        )
        return
    name = (record or {}).get("name", "")
    console.print(f"[green]{kind.capitalize()} {operation}:[/green] {name} [dim]{ref_id}[/dim]")
    if record is not None:
        console.print_json(json.dumps(record, default=str))


def _guard(json_output: bool, action):
    """Run a CRUD action, turning rejections into one structured, non-zero exit."""
    try:
        return action()
    except ConfigError as error:
        if json_output:
            print(json.dumps({"schema": SCHEMA, **error.to_payload()}))
        else:
            console.print(f"[red]{error.message}[/red]")
        raise typer.Exit(1) from None
    except ProjectAPIError as error:
        # The human message already went to stderr from the client.
        if json_output:
            print(json.dumps({"schema": SCHEMA, **error.to_payload()}, default=str))
        raise typer.Exit(1) from None


def create(kind: str, file: str, project_id: str | None, json_output: bool):
    def action():
        body = load_file(file)
        if not body.get("name"):
            raise ConfigError("invalid_file", f"a {kind} needs a 'name'")
        client = ProjectClient(project_id)
        check_references(client, kind, body)
        result = client.post(kind, body)
        new_id = (result.get("data") or {}).get("id")
        if not new_id:
            # The write may have happened: report it, never retry it blindly.
            raise ConfigError(
                "outcome_unknown",
                f"create returned no id; check `machina {kind} get {body['name']}` before retrying",
            )
        _emit(json_output, kind, "created", read(client, kind, new_id), new_id)

    _guard(json_output, action)


def update(kind: str, ref: str, file: str, project_id: str | None, json_output: bool):
    def action():
        body = load_file(file)
        client = ProjectClient(project_id)
        current = read(client, kind, ref)
        payload = update_body(kind, current, body)
        check_references(client, kind, payload)
        client.put(f"{kind}/{current['_id']}", payload)
        _emit(json_output, kind, "updated", read(client, kind, current["_id"]), current["_id"])

    _guard(json_output, action)


def delete(kind: str, ref: str, project_id: str | None, json_output: bool, yes: bool):
    def action():
        client = ProjectClient(project_id)
        current = read(client, kind, ref)
        if not yes:
            if json_output:
                raise ConfigError("confirmation_required", "pass --yes to delete non-interactively")
            typer.confirm(f"Delete {kind} '{current.get('name')}' ({current['_id']})?", abort=True)
        client.delete(f"{kind}/{current['_id']}")
        _emit(json_output, kind, "deleted", None, current["_id"])

    _guard(json_output, action)
