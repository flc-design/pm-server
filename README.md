# pm-server

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)

**[日本語版 README はこちら](README.ja.md)**

**Project management MCP Server for Claude Code.**

Track tasks, visualize progress, record decisions — all through natural language in your Claude Code session.

```
> 進捗は？
✓ Phase 1 "Backend API": 60% complete (12/20 tasks)
  - 3 tasks in progress, 1 blocked
  - Velocity: 8 tasks/week (↑ trending up)

> 次にやること
1. [P0] MYAPP-014: Add user authentication endpoint
2. [P1] MYAPP-015: Implement rate limiting
3. [P1] MYAPP-018: Write integration tests

> MYAPP-014 に着手
✓ MYAPP-014 → in_progress
```

---

## Features

- **16 MCP tools** — task CRUD, status, blockers, velocity, dashboard, ADR, and more
- **Natural language** — say "進捗は？" or "what's next?" instead of memorizing commands
- **Zero configuration** — `pip install` + `pm-server install`, then just say "PM初期化して"
- **Multi-project** — manage all your projects from a global registry with cross-project dashboards
- **Git-friendly** — plain YAML files in `.pm/` directory, trackable with `git diff`
- **Non-invasive** — adds only a `.pm/` directory to your project. `rm -rf .pm/` to remove completely

---

## Quick Start

### Install (once)

```bash
pip install pm-server
pm-server install       # Registers MCP server in Claude Code
# Restart Claude Code
```

### Initialize a project

```
# In Claude Code, cd to your project directory
> PM初期化して
✓ .pm/ created
✓ Registered in global registry
✓ Detected: name=my-app, version=1.2.0 (from package.json)
```

pm-server automatically detects project info from `package.json`, `pyproject.toml`, `Cargo.toml`, `.git/config`, and `README.md`.

### Use it

| You say | What happens |
|---|---|
| `進捗は？` / `status` | Show project progress summary |
| `次にやること` / `what's next` | Recommend next tasks by priority & dependencies |
| `タスク追加：○○を実装` | Add a new task (auto-numbered) |
| `MYAPP-003 完了` | Mark task as done |
| `ブロッカーある？` | List blocked tasks |
| `ダッシュボード見せて` | Generate HTML dashboard (Chart.js, dark theme) |
| `この設計にした理由を記録` | Record an Architecture Decision Record (ADR) |
| `全プロジェクトの状態` | Cross-project portfolio view |

---

## MCP Tools (16 tools)

### Project Management

| Tool | Description |
|---|---|
| `pm_init` | Create `.pm/`, register in global registry, auto-detect project info |
| `pm_status` | Phase progress, task summary, blockers, velocity |
| `pm_tasks` | List tasks with filters (status / phase / priority / tag) |
| `pm_add_task` | Add task with auto-numbered ID (e.g., `MYAPP-001`) |
| `pm_update_task` | Update status, priority, notes, blocked_by |
| `pm_next` | Recommend next tasks (excludes blocked / unmet dependencies) |
| `pm_blockers` | List blocked tasks across projects |

### Records

| Tool | Description |
|---|---|
| `pm_log` | Daily log entry (progress / decision / blocker / note / milestone) |
| `pm_add_decision` | Add ADR with context, decision, and consequences |

### Analysis

| Tool | Description |
|---|---|
| `pm_velocity` | Weekly velocity + trend (up / down / flat) |
| `pm_risks` | Auto-detect risks: overdue, stale, long-blocked tasks |

### Visualization

| Tool | Description |
|---|---|
| `pm_dashboard` | HTML dashboard (single project or portfolio view) |

### Discovery

| Tool | Description |
|---|---|
| `pm_discover` | Scan directories for `.pm/` projects and auto-register |
| `pm_cleanup` | Remove invalid paths from registry |
| `pm_list` | List all registered projects |

### Maintenance

| Tool | Description |
|---|---|
| `pm_update_claudemd` | Update PM Server rules section in CLAUDE.md to latest version |

---

## Data Structure

pm-server stores everything as plain YAML in a `.pm/` directory at your project root:

```
your-project/
└── .pm/
    ├── project.yaml        # Project metadata
    ├── tasks.yaml          # Tasks with status, priority, dependencies
    ├── decisions.yaml      # Architecture Decision Records (ADR)
    ├── milestones.yaml     # Milestone definitions
    ├── risks.yaml          # Risks and blockers
    └── daily/
        └── 2026-04-08.yaml # Auto-generated daily log
```

Global registry at `~/.pm/registry.yaml` indexes all projects.

All files are human-readable and hand-editable. If something goes wrong, you can fix it with a text editor.

---

## CLAUDE.md Integration

Add this to your project's `CLAUDE.md` for automatic PM behavior:

```markdown
## PM Server — Auto-actions (always follow these)

### On session start (before first response)
1. Run pm_status to show current progress
2. Run pm_next to show top 3 recommended tasks
3. Warn about blockers or overdue tasks

### Before starting a task
1. Run pm_update_task to set status to in_progress

### On task completion
1. Run pm_update_task to set status to done
2. Run pm_log to record what was completed
3. Run pm_next to show next recommendations
4. Create an atomic git commit

### On session end
1. Update any in-progress task status
2. Run pm_log to record session results
3. Commit any uncommitted changes
```

---

## CLI Commands

```bash
pm-server install       # Register MCP server in Claude Code
pm-server uninstall     # Unregister MCP server
pm-server serve         # Start MCP server (called by Claude Code automatically)
pm-server discover .    # Scan for projects with .pm/ directories
pm-server status        # Show project status from terminal
pm-server migrate       # Migrate from pm-agent (rename transition)
pm-server update-claudemd  # Update PM Server rules in CLAUDE.md
```

---

## Architecture

```
Claude Code Session
  │
  ├── CLAUDE.md auto-action rules
  │
  └── MCP Server (stdio)
        └── pm-server serve
              │
              ├── server.py    → 16 MCP tools (FastMCP)
              ├── models.py    → Pydantic v2 data models
              ├── storage.py   → YAML read/write
              ├── velocity.py  → Velocity calculation & risk detection
              ├── dashboard.py → HTML/text dashboard (Jinja2)
              ├── discovery.py → Auto-detect project info
              └── installer.py → claude mcp add wrapper
                    │
                    ├── project-A/.pm/
                    ├── project-B/.pm/
                    └── ~/.pm/registry.yaml
```

---

## Migrating from pm-agent

If you were using the earlier `pm-agent` package:

```bash
pip uninstall pm-agent
pip install pm-server
pm-server migrate       # Switches MCP registration from pm-agent to pm-server
# Restart Claude Code
```

The `migrate` command will:
- Remove the old `pm-agent` MCP registration
- Register `pm-server` as the new MCP server
- Verify `~/.pm/registry.yaml` integrity
- Warn about any `CLAUDE.md` files that reference `pm-agent`

Your `.pm/` data directories are **unchanged** — no data migration needed.

---

## Requirements

- Python 3.11+
- Claude Code (with MCP support)

### Dependencies

- [FastMCP](https://github.com/jlowin/fastmcp) — MCP server framework
- [Pydantic](https://docs.pydantic.dev/) v2 — data validation
- [PyYAML](https://pyyaml.org/) — data persistence
- [Click](https://click.palletsprojects.com/) — CLI framework
- [Jinja2](https://jinja.palletsprojects.com/) — dashboard templates

---

## Development

```bash
git clone https://github.com/code-retriever/pm-server.git
cd pm-server
pip install -e ".[dev]"
pytest                  # 115 tests
ruff check src/         # Lint
ruff format src/        # Format
```

---

## Design Principles

1. **Zero Configuration** — `pip install` + one command, done
2. **Auto-everything** — detection, registration, and inference are fully automatic
3. **Git-friendly** — plain text YAML, trackable with `git diff`
4. **Human-readable** — safe to hand-edit, won't break
5. **AI-native** — formats that Claude Code can naturally read and write
6. **Non-invasive** — only adds `.pm/`, never modifies your project

---

## License

MIT — Shinichi Nakazato / FLC design co., ltd.
