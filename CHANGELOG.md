# Changelog

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
- GitHub repository moved to `code-retriever/pm-server`
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
