"""Search command for unified project resource discovery."""

import json as json_lib
import concurrent.futures
from typing import Optional, Dict, Any, List

import typer
from rich.console import Console
from rich.table import Table

from machina_cli.project_client import ProjectClient

console = Console()

RESOURCE_TYPES = {
    "workflow": {"icon": "⚡", "endpoint": "workflow/search", "label": "Workflow"},
    "agent": {"icon": "🤖", "endpoint": "agent/search", "label": "Agent"},
    "connector": {"icon": "🔌", "endpoint": "connector/search", "label": "Connector"},
    "mapping": {"icon": "🔄", "endpoint": "mapping/search", "label": "Mapping"},
    "prompt": {"icon": "💬", "endpoint": "prompt/search", "label": "Prompt"},
    "document": {"icon": "📄", "endpoint": "document/search", "label": "Document"},
}

def fetch_resource(client: ProjectClient, res_type: str, info: dict) -> List[dict]:
    """Fetch all resources of a given type."""
    try:
        result = client.post(info["endpoint"], {
            "filters": {},
            "page": 1,
            "page_size": 1000,
            "sorters": ["name", 1],
        })
        data = result.get("data", [])
        # Append resource type to each item
        for item in data:
            item["_type"] = res_type
            item["_icon"] = info["icon"]
            item["_label"] = info["label"]
        return data
    except Exception:
        # If one fails, don't break the whole search
        return []

def do_search(
    query: str,
    resource_type: Optional[str] = None,
    limit: int = 20,
    json_output: bool = False,
    project_id: Optional[str] = None,
):
    """Search across all project resources."""
    client = ProjectClient(project_id)
    query_lower = query.lower()

    types_to_fetch = RESOURCE_TYPES
    if resource_type:
        rt_lower = resource_type.lower()
        if rt_lower in RESOURCE_TYPES:
            types_to_fetch = {rt_lower: RESOURCE_TYPES[rt_lower]}
        else:
            console.print(f"[red]Unknown resource type: {resource_type}[/red]")
            raise typer.Exit(1)

    all_resources = []
    
    # Query endpoints in parallel
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(types_to_fetch)) as executor:
        future_to_type = {
            executor.submit(fetch_resource, client, rtype, info): rtype
            for rtype, info in types_to_fetch.items()
        }
        for future in concurrent.futures.as_completed(future_to_type):
            data = future.result()
            all_resources.extend(data)

    # Client-side filtering
    matches = []
    for item in all_resources:
        name = item.get("name", "") or ""
        desc = item.get("description", "") or ""
        
        name_lower = name.lower()
        desc_lower = desc.lower()
        
        # Calculate relevance
        score = 0
        if query_lower == name_lower:
            score = 100
        elif query_lower in name_lower:
            score = 50
        elif query_lower in desc_lower:
            score = 10
            
        if score > 0:
            item["_score"] = score
            matches.append(item)

    # Sort by relevance (desc) then name (asc)
    matches.sort(key=lambda x: (-x.get("_score", 0), x.get("name", "").lower()))
    
    # Apply limit
    results = matches[:limit]

    if json_output:
        # Strip internal fields for JSON output
        clean_results = []
        for r in results:
            clean = dict(r)
            clean.pop("_score", None)
            clean.pop("_icon", None)
            clean.pop("_label", None)
            clean_results.append(clean)
        console.print_json(json_lib.dumps(clean_results, default=str))
        return

    if not results:
        console.print(f"  [yellow]No resources found matching '{query}'.[/yellow]")
        return

    console.print()
    table = Table(title=f"Search Results for '{query}'", box=None, show_edge=False)
    table.add_column("Type", style="dim")
    table.add_column("Name", style="bold #FF5C1F")
    table.add_column("Description", style="dim", max_width=60, no_wrap=False)

    for item in results:
        desc = item.get("description") or ""
        # Truncate description if too long
        if len(desc) > 80:
            desc = desc[:77] + "..."
            
        table.add_row(
            f"{item['_icon']} {item['_label']}",
            item.get("name", ""),
            desc
        )

    console.print(table)
    
    if len(matches) > limit:
        console.print(f"  [dim]Showing {limit} of {len(matches)} matches. Use --limit to show more.[/dim]")
    console.print()

