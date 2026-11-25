"""Single source of truth for the human-facing command catalog.

Two surfaces read from here -- the banner you get from bare ``machina`` and the
REPL's ``help`` -- and a third is derived from it: the ``rich_help_panel`` each
command is registered under in ``main.py``, via :data:`PANEL_BY_COMMAND`. That
is deliberate. The two help screens used to carry their own grouping and drifted
apart, so ``machina --help`` and the banner described the same CLI differently.

A spec carries the *complete* action list, which drives tab completion and the
test that keeps this file honest against the registered Typer commands. What the
catalog prints is :attr:`CommandSpec.primary` -- the few actions worth
advertising. Printing all of them is what used to overflow the column and break
the grid; the catalog is a map, and ``<command> --help`` is the manual.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import Console, Group
from rich.table import Table
from rich.text import Text

from machina_cli.theme import ACCENT, DIM, glyph

# Column geometry. Fixed, so every group's grid lines up even though the section
# headers are printed between them.
_CMD_W = 18  # 4 of indent + "context-graph", the longest name
_DESC_W = 38
_ACTIONS_MIN_WIDTH = 92  # below this the actions column is dropped


@dataclass(frozen=True)
class CommandSpec:
    name: str
    actions: tuple[str, ...]
    description: str
    primary: tuple[str, ...] = ()
    usage: str | None = None

    @property
    def shown(self) -> str:
        """The hint column: a few real actions, or a usage string."""
        if self.usage:
            return self.usage
        return " ".join(self.primary or self.actions[:4])

    @property
    def synopsis(self) -> str:
        """Full ``name action|action`` form, kept for docs and error messages."""
        if self.usage:
            return self.usage
        return f"{self.name} {'|'.join(self.actions)}" if self.actions else self.name


COMMAND_GROUPS: tuple[tuple[str, str, tuple[CommandSpec, ...]], ...] = (
    (
        "Session",
        "where you are",
        (
            CommandSpec("login", (), "Authenticate in the browser", usage="--api-key"),
            CommandSpec(
                "auth",
                ("login", "logout", "whoami", "clear-session"),
                "Identity and sign-out",
                primary=("login", "logout", "whoami"),
            ),
            CommandSpec(
                "org",
                ("list", "create", "use", "usage"),
                "Organizations and consumption",
                primary=("list", "use", "usage"),
            ),
            CommandSpec(
                "project",
                ("list", "create", "use", "status"),
                "Projects and the active context",
                primary=("list", "use", "status"),
            ),
            CommandSpec("config", ("list", "get", "set"), "CLI configuration"),
        ),
    ),
    (
        "Resources",
        "what the project holds",
        (
            CommandSpec(
                "workflow",
                ("list", "get", "run", "create", "update", "delete"),
                "Workflows",
                primary=("list", "get", "run", "create"),
            ),
            CommandSpec(
                "agent",
                ("list", "get", "run", "executions", "create", "update", "delete"),
                "Agents and their executions",
                primary=("list", "get", "run", "executions"),
            ),
            CommandSpec("connector", ("list", "get"), "Connectors"),
            CommandSpec("mapping", ("list", "get"), "Mappings"),
            CommandSpec("prompt", ("list", "get"), "Prompts"),
            CommandSpec("document", ("list", "get"), "Documents"),
        ),
    ),
    (
        "Run & watch",
        "make it happen, then see it",
        (
            CommandSpec("execution", ("list", "get"), "Execution history and outcomes"),
            CommandSpec("approvals", ("list", "approve", "reject"), "Human approval checkpoints"),
            CommandSpec(
                "loop",
                ("run", "watch", "say", "stop", "sessions"),
                "Durable agentic turn loop",
                primary=("run", "watch", "say", "stop"),
            ),
            CommandSpec("deploy", ("start", "status", "restart"), "Deployments"),
            CommandSpec("context-graph", ("status", "timeline"), "Self-healing, drift and health"),
        ),
    ),
    (
        "Build",
        "new things",
        (
            CommandSpec("create", ("ai-app",), "Scaffold a deployable app"),
            CommandSpec(
                "factory",
                (
                    "run",
                    "status",
                    "watch",
                    "logs",
                    "follow-up",
                    "cancel",
                    "open-pr",
                    "list",
                    "whoami",
                ),
                "Build with the coding agent",
                primary=("run", "status", "watch", "logs"),
            ),
            CommandSpec(
                "skills",
                (
                    "list",
                    "install",
                    "info",
                    "run",
                    "push",
                    "constructor",
                    "show",
                    "docs",
                    "result",
                ),
                "Install, run and publish skills",
                primary=("list", "install", "run", "push"),
            ),
            CommandSpec("template", ("list", "install", "push"), "Legacy alias for skills"),
        ),
    ),
    (
        "Connect",
        "wire agents in",
        (
            CommandSpec(
                "connect",
                (),
                "Wire an agent to a project's MCP",
                usage="[project] --mint --probe",
            ),
            CommandSpec("mcp", ("url", "tools"), "Inspect an MCP endpoint"),
            CommandSpec("credentials", ("list", "generate", "revoke"), "API keys"),
            CommandSpec("sports", (), "Sports-skills passthrough", usage="<module> <command>"),
        ),
    ),
    (
        "CLI",
        "the tool itself",
        (
            CommandSpec("update", (), "Check for and install updates", usage="--check --force"),
            CommandSpec("version", (), "Show CLI version"),
        ),
    ),
)

# REPL-only verbs: real to the user, invisible to Typer.
REPL_EXTRA_COMMANDS: tuple[CommandSpec, ...] = (
    CommandSpec("clear", (), "Clear the screen"),
    CommandSpec("exit", (), "Exit the session"),
)

ALL_COMMANDS = tuple(spec for _, _, specs in COMMAND_GROUPS for spec in specs)

# Kept for compatibility: every command now lives in COMMAND_GROUPS, so the
# union these names used to add is already covered.
CLI_SESSION_COMMANDS: tuple[CommandSpec, ...] = ()
SESSION_COMMANDS: tuple[CommandSpec, ...] = REPL_EXTRA_COMMANDS

COMMAND_BY_NAME = {spec.name: spec for spec in (*ALL_COMMANDS, *REPL_EXTRA_COMMANDS)}
SUB_COMMANDS = {spec.name: list(spec.actions) for spec in ALL_COMMANDS if spec.actions}

#: Command name -> the help panel it is registered under, so ``machina --help``
#: and the banner cannot drift apart again.
PANEL_BY_COMMAND: dict[str, str] = {
    spec.name: group for group, _, specs in COMMAND_GROUPS for spec in specs
}

#: Panel order for ``main.py`` to register in, so Typer's help reads top-down
#: in the same order the banner does.
PANEL_ORDER: tuple[str, ...] = tuple(group for group, _, _ in COMMAND_GROUPS)

REPL_COMMANDS = tuple(
    dict.fromkeys(
        [
            *(spec.name for spec in ALL_COMMANDS),
            *(spec.name for spec in REPL_EXTRA_COMMANDS),
            "logout",
            "whoami",
            "help",
            "quit",
        ]
    )
)


def command_catalog(
    *,
    width: int = 100,
    extra: tuple[CommandSpec, ...] = (),
) -> Group:
    """Build the command map.

    ``extra`` appends to the trailing CLI group -- the REPL uses it for `clear`
    and `exit`, which Typer never sees.
    """
    show_actions = width >= _ACTIONS_MIN_WIDTH
    renderables: list = []

    for index, (group, purpose, specs) in enumerate(COMMAND_GROUPS):
        if index:
            renderables.append(Text())

        header = Text("  ")
        header.append("▌ ", style=ACCENT)
        header.append(group, style="bold")
        header.append(f"   {purpose}", style=DIM)
        renderables.append(header)

        rows = (*specs, *extra) if group == COMMAND_GROUPS[-1][0] else specs
        grid = Table.grid(padding=(0, 2))
        grid.add_column(style=f"bold {ACCENT}", width=_CMD_W, no_wrap=True)
        grid.add_column(width=_DESC_W, overflow="ellipsis", no_wrap=True)
        if show_actions:
            grid.add_column(style=DIM, overflow="ellipsis", no_wrap=True)
        for spec in rows:
            cells = [Text("    " + spec.name), Text(spec.description)]
            if show_actions:
                cells.append(Text(spec.shown))
            grid.add_row(*cells)
        renderables.append(grid)

    return Group(*renderables)


def print_command_catalog(
    console: Console,
    *,
    extra: tuple[CommandSpec, ...] = (),
) -> None:
    console.print(command_catalog(width=console.width or 100, extra=extra))
    console.print()
    console.print(
        Text.assemble(
            ("  " + glyph("hint") + " ", DIM),
            ("machina <command> --help", "bold"),
            ("  for actions and flags.   Lists accept ", "grey62"),
            ("--limit --page --json", "bold"),
        )
    )
