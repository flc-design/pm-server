# Changelog

## [0.4.0] - 2026-04-17

### Added
- Workflow Engine: template-based state machine with 5 MCP tools (`pm_workflow_start`, `pm_workflow_advance`, `pm_workflow_status`, `pm_workflow_list`, `pm_workflow_templates`)
- Built-in workflow templates: `discovery` (research/brainstorm) and `development` (implementation)
- Workflow chaining support (e.g., discovery → development)
- Loops, gates (`user_approval`), and optional steps for workflow flexibility
- Knowledge Records: structured knowledge between casual Memory and formal ADR
- `pm_record` and `pm_knowledge` MCP tools with 3 enums (KnowledgeCategory, KnowledgeStatus, ConfidenceLevel)
- Super Research skill + dashboard extensions (Phase 7)
- `pm_add_issue` severity parameter (`defect` | `enhancement`) — gates parent auto-revert
- Structured `warnings[]` array in MCP tool responses: `{level, code, message, remediation}`
- `Task.severity` field persists the issue classification
- CLAUDE.md template v7: documents severity selection, warnings[] relay, workflow rules

### Fixed
- `pm_add_issue` silent parent-revert UX issue (ADR-006): Claude now explicitly relays auto-revert side-effects via structured warnings
- `enhancement` severity issues no longer unexpectedly revert parent tasks from `done`

### Changed
- MCP tool count: 23 → 30
- Pydantic model count: 14 → 17
- Enum count: 10 → 15
- Test count: 305 → 413
- `pm_add_issue` default severity is `defect` (backward-compatible with v0.3.x behavior)
- Legacy fields `parent_reverted` and `message` remain in responses (slated for removal in 0.5.0)

## [0.3.3] - 2026-04-16

### Added
- Child issue (sub-task) support: `pm_add_issue` tool for creating issues linked to parent tasks via `parent_id`
- `pm_tasks` filter by `parent_id` to list child issues
- Auto-revert parent task from `done` to `review` when a child issue is added
- `all_issues_resolved` flag in `pm_update_task` when all sibling issues are done
- PostToolUse hooks: auto-remind PM actions after `git commit` via Claude Code hooks
- `pm-server hook post-tool-use` CLI command for hook handler
- Auto-install hooks from `pm_status` if not configured
- Generic detection of other MCP rule sections in CLAUDE.md (Open-Closed Principle)
- `other_rule_sections` in `pm_status` response for cross-MCP coordination
- CLAUDE.md template v5 with instruction to execute other rule sections

### Fixed
- **Critical**: `resolve_project_path` no longer matches global `~/.pm/` as a project directory (ADR-004)
- Added `_is_project_pm_dir()` guard to distinguish project `.pm/` from global registry
- `pm_cleanup` now detects orphan project files (tasks.yaml, decisions.yaml) in `~/.pm/`
- `pm_log` and `pm_remember` auto-link to active in-progress task when `task_id` is omitted

### Changed
- MCP tool count: 16 → 23
- Pydantic model count: 12 → 14
- Enum count: 9 → 10
- Test count: 136 → 305

## [0.3.2] - 2026-04-15

### Changed
- Updated README.md with Memory Layer documentation
- PyPI package rebuild (v0.3.1 had stale README)

## [0.3.1] - 2026-04-15

### Added
- Memory Layer: `pm_remember`, `pm_recall`, `pm_session_summary` tools
- `pm_memory_search` for advanced full-text search with filters
- `pm_memory_stats` and `pm_memory_cleanup` for memory operations
- SQLite + FTS5 based memory storage with cross-project global index
- Session continuity via `ContextBuilder` (Progressive Disclosure)
- `pm-server context-inject` CLI command
- CLAUDE.md template v2-v4 with memory layer rules

## [0.3.0] - 2026-04-08

### Added
- CLAUDE.md auto-management: `pm_init` automatically adds PM Server rules with version markers
- `pm_update_claudemd` MCP tool (16th tool) for updating PM Server rules section
- `pm-server update-claudemd` CLI command with `--all` flag for batch updates
- `claudemd.py` module with marker-based section management

### Fixed
- storage.py YAML header showing "PM Agent" instead of "PM Server"
- dashboard_portfolio.html title showing old name
- pm_discover MCP tool default scan path changed from "~" to "." (security)
- uninstall_mcp() missing --scope user flag
- migrate_from_pm_agent() now uses shutil.which() and timeout
- Case-insensitive detection of "PM Agent" references in migrate command
- `PmAgentError` renamed to `PmServerError`

### Changed
- Removed internal development prompts from docs/
- Added `.claude/` and `.pm/` to .gitignore
- pyproject.toml: added classifiers and dev extras
- MCP tool count: 15 → 16

## [0.2.0] - 2026-04-08

### Changed
- Package renamed from `pm-agent` to `pm-server` (PyPI name conflict with existing `PMAgent`)
- GitHub repository moved to `flc-design/pm-server`
- Added `pm-server migrate` command for transitioning from pm-agent

### Added
- `README.ja.md` — Japanese README
- `migrate` CLI command for pm-agent → pm-server transition

## [0.1.0] - 2026-04-07

### Added
- 15 MCP tools for project management
- YAML-based task, decision, and log storage
- HTML dashboard with Chart.js (single + portfolio view)
- Text dashboard fallback
- Velocity tracking and risk detection
- Project discovery and auto-registration
- CLI interface (install, uninstall, serve, discover, status)
- Claude Code integration via `claude mcp add --scope user`

### Fixed
- installer.py: use `claude mcp add` instead of writing to wrong settings file
- Template path resolution for packaged installations
- Test isolation: prevent tests from polluting `~/.pm/registry.yaml`

### Documentation
- Development workflow guide (docs/workflow.md)
- Design document (docs/design.md)
- Project status report (docs/status.md)
