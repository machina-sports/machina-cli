# sports

The full [sports-skills](https://pypi.org/project/sports-skills/) CLI is bundled with `machina-cli` and mounted dynamically under `machina sports`. Every module and command that `sports-skills` exposes is delegated live — there is no hand-written allow-list, so new `sports-skills` releases surface automatically without a `machina-cli` upgrade.

## Usage

```bash
machina sports                         # list every module + command
machina sports --help                  # sports-skills' own argparse help
machina sports catalog                 # JSON catalog of modules
machina sports <module> schema         # JSON Schema tool definitions for a module
machina sports <module> <command> [--key=value ...]
```

Output is identical to running `sports-skills <module> <command> …` directly.

## Examples

One per domain that `sports-skills` documents:

```bash
machina sports football get_team_schedule --team_id=6273
machina sports f1 get_race_schedule --year=2025
machina sports nfl get_scoreboard
machina sports nba get_standings --season=2025
machina sports wnba get_scoreboard
machina sports nhl get_standings --season=2025
machina sports mlb get_scoreboard
machina sports tennis get_scoreboard
machina sports cfb get_scoreboard
machina sports cbb get_scoreboard
machina sports golf get_leaderboard --tour=pga
machina sports volleyball get_scoreboard
machina sports polymarket get_sports_markets --limit=20
machina sports kalshi get_markets --series_ticker=KXNBA
machina sports betting convert_odds --american=-150
machina sports markets get_todays_markets
machina sports metadata search_teams --query=Arsenal
machina sports news fetch_items --query=Arsenal --limit=5
```

::: tip
Run `machina sports catalog` for the machine-readable module list, or `machina sports <module> schema` for the JSON Schema tool definitions — handy when wiring sports data into an agent.
:::
