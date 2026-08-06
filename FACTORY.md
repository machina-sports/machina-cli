# Machina Factory Integration

This repository is integrated with **Machina Factory**, the automated coding agent runtime designed to streamline software development processes.

## What Machina Factory Does

Machina Factory automates the execution of coding tasks. When a coding task is submitted to Factory, it:
1. Provisions an isolated development environment.
2. Clones the relevant repository.
3. Utilizes AI coding agents to implement the requested changes.
4. Runs verification steps (e.g., tests, linting, type-checking, builds).
5. Creates a dedicated Git branch and pushes the changes.
6. Opens a Pull Request (PR) with the completed work, ready for review.

This process significantly accelerates development cycles by handling routine coding tasks and ensuring code quality through automated verification.

## Example `machina-cli` Commands

The `machina-cli` provides a command-line interface to interact with the Machina platform, including skills, workflows, and agents.

- **Install a skill:**
  ```bash
  machina skills install machina-sports/sports-skills/nba-stats
  ```

- **Run a workflow:**
  ```bash
  machina workflow run my-data-ingestion-workflow source=s3://my-bucket/data.csv
  ```

- **Run an agent:**
  ```bash
  machina agent run code-refactor-agent target-file=src/utils.ts
  ```

## Sample API Call to Factory Endpoint

Machina Factory tasks are typically initiated via the Machina Core API or `machina-cli`. Below is a conceptual example of how a task might be submitted to a Factory endpoint (note: direct interaction with Factory's internal endpoints is usually abstracted by the Machina platform).

```http
POST /api/v1/tasks/submit
Host: factory.machina.gg
Content-Type: application/json
Authorization: Bearer <YOUR_MACHINA_API_KEY>

{
  "repository": "github.com/your-org/your-repo",
  "branch": "machina/feature-branch",
  "taskDescription": "Implement user authentication endpoint",
  "callbackUrl": "https://api.machina.gg/webhook/factory-status"
}
```
