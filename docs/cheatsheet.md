# PM Server Cheatsheet

> **30 MCP tools** for Claude Code project management.
> Version 0.3.3+ | Python 3.11+ | PyPI: `pm-server`

---

## Quick Start

```bash
pip install pm-server
pm-server install          # Register MCP server in Claude Code
```

Claude Code session:
```
> PM初期化して              → pm_init
> 現在の進捗は？            → pm_status
> 次にやるべきことは？      → pm_next
```

---

## Tool Reference

### Setup & Project

| Tool | Description | Key Params |
|------|-------------|------------|
| `pm_init` | Initialize .pm/ directory, auto-detect project info | `project_path?`, `project_name?` |
| `pm_status` | Project status: phases, tasks, blockers, velocity | `project_path?` |
| `pm_list` | List all registered projects | _(none)_ |
| `pm_discover` | Scan for projects and register them | `scan_path="."` |
| `pm_cleanup` | Health-check registry, remove invalid entries | _(none)_ |
| `pm_update_claudemd` | Update CLAUDE.md rules to latest version | `project_path?` |
| `pm_dashboard` | Generate HTML/text dashboard | `format="html"` |

### Tasks

| Tool | Description | Key Params |
|------|-------------|------------|
| `pm_add_task` | Create a task (ID auto-generated) | `title`, `phase`, `priority="P1"` |
| `pm_update_task` | Update task status/fields | `task_id`, `status?`, `priority?`, `notes?` |
| `pm_tasks` | List/filter tasks | `status?`, `phase?`, `priority?`, `tag?`, `parent_id?` |
| `pm_next` | Recommend next actionable tasks | `count=3` |
| `pm_blockers` | List blocked tasks | `project_path?` |
| `pm_add_issue` | Add child issue to a task | `parent_id`, `title`, `priority="P1"` |

### Memory

| Tool | Description | Key Params |
|------|-------------|------------|
| `pm_remember` | Save a memory (auto-links to active task) | `content`, `type="observation"`, `tags?` |
| `pm_recall` | Recall memories / last session | `query?`, `task_id?`, `limit=5` |
| `pm_memory_search` | Advanced search with filters | `query`, `type?`, `tags?`, `cross_project?` |
| `pm_memory_stats` | Memory DB statistics | `project_path?` |
| `pm_memory_cleanup` | Delete old memories | `older_than_days?`, `keep_latest?`, `dry_run=True` |
| `pm_session_summary` | Save/get/list session summaries | `action="save"`, `summary?` |

### Recording

| Tool | Description | Key Params |
|------|-------------|------------|
| `pm_log` | Add daily log entry (auto-links to active task) | `entry`, `category="progress"` |
| `pm_add_decision` | Record an ADR (ID auto-generated) | `title`, `context`, `decision` |
| `pm_velocity` | Velocity and trend analysis | `weeks=4` |
| `pm_risks` | Auto-detected + manual risks | `project_path?` |

### Knowledge Records

| Tool | Description | Key Params |
|------|-------------|------------|
| `pm_record` | Record structured knowledge | `category`, `title`, `findings?`, `confidence="medium"` |
| `pm_knowledge` | Query/update knowledge records | `action="list"`, `category?`, `status?`, `tag?` |

### Workflow

| Tool | Description | Key Params |
|------|-------------|------------|
| `pm_workflow_start` | Start a workflow from template | `feature`, `template="development"` |
| `pm_workflow_status` | Get workflow progress and guidance | `workflow_id?` (auto-detect) |
| `pm_workflow_advance` | Advance/loop/skip a step | `proceed=True`, `artifacts?`, `skip?` |
| `pm_workflow_list` | List workflow instances | `status?` |
| `pm_workflow_templates` | List available templates | `project_path?` |

---

## Common Patterns

### Task Lifecycle

```
pm_add_task(title="Add auth", phase="phase-1", priority="P0")
  → PROJ-001 created (todo)

pm_update_task(task_id="PROJ-001", status="in_progress")
  → working on it

pm_update_task(task_id="PROJ-001", status="done")
  → completed

pm_log(entry="Auth feature implemented with JWT")
  → daily log recorded
```

### Issue Discovery During Review

```
pm_add_issue(parent_id="PROJ-001", title="JWT token expiry not handled")
  → PROJ-005 created, PROJ-001 reverted to "review"

pm_update_task(task_id="PROJ-005", status="done")
  → all_issues_resolved=True, suggest closing PROJ-001
```

### 3-Layer Knowledge System

```
# Layer 1: Casual — quick notes during work
pm_remember(content="FastMCP v2 requires Python 3.11+", type="observation")

# Layer 2: Structured — research findings, trade-off analyses
pm_record(category="tradeoff", title="JWT vs Session Auth",
          findings="JWT: stateless but larger payload...",
          conclusion="Use JWT for API, session for web",
          confidence="high")

# Layer 3: Formal — architecture decisions
pm_add_decision(title="Use JWT for API auth",
                context="Need stateless auth for microservices",
                decision="JWT with RS256, 15min expiry")
```

### Knowledge Record Categories

| Category | Use Case |
|----------|----------|
| `research` | General research findings |
| `market` | Market analysis, competitor research |
| `spike` | Technical spike / prototype results |
| `requirement` | Requirements definition |
| `constraint` | Technical/business constraints |
| `tradeoff` | Trade-off analysis (A vs B) |
| `risk_analysis` | Risk assessment results |
| `spec` | Feature specification |
| `api_design` | API design documentation |

### Knowledge Record Lifecycle

```
pm_record(category="research", title="Auth options", confidence="low")
  → KR-001 (draft, low confidence)

pm_knowledge(action="update", record_id="KR-001",
             new_status="validated", confidence="high",
             conclusion="JWT is the best option")
  → KR-001 (validated, high confidence)

pm_knowledge(action="update", record_id="KR-001",
             new_status="superseded")
  → KR-001 (superseded — replaced by newer research)
```

---

## Workflow

### Built-in Templates

#### Discovery (5 steps, chains to Development)

```
research ──→ fact_check ──→ proposal ──→ cross_check ──→ confirm
   ↑              ↑             ↑
   └──── brainstorm loop ───────┘
         (proceed=false to loop)
```

- **research**: Investigate the topic (loop)
- **fact_check**: Verify findings (loop)
- **proposal**: Present to user (loop, gate: user_approval)
- **cross_check**: Independent validation
- **confirm**: Finalize direction, record ADR (gate: user_approval)

#### Development (9 steps)

```
decision → tasks → spec → plan → check → implement → test → quality → issues
                                   ↑                          ↑
                              gate: user_approval        gate: user_approval
```

- **decision**: Record ADR
- **tasks**: Break down into tasks
- **spec**: Write specification
- **plan**: Design implementation plan
- **check**: Cross-check (gate: user_approval)
- **implement**: Write code
- **test**: Write and run tests
- **quality**: Final review (gate: user_approval)
- **issues**: Register remaining issues (optional)

### Workflow Usage

```
# Start
pm_workflow_start(feature="user authentication", template="discovery")
  → WF-001 started, step 1: research

# Advance (normal)
pm_workflow_advance(artifacts=["KR-001"])
  → step completed, next: fact_check

# Loop back (brainstorming)
pm_workflow_advance(proceed=False)
  → looped back to research (iteration 2)

# Skip optional step
pm_workflow_advance(skip=True)
  → step skipped, next step activated

# Check status
pm_workflow_status()
  → progress: 3/5, current: proposal, knowledge: {count: 2}

# Chaining: discovery completes → suggests development
pm_workflow_advance()
  → workflow_completed, chain_to: "development"
pm_workflow_start(feature="user authentication", template="development")
  → WF-002 started
```

### Custom Templates

Place YAML files in `.pm/workflow_templates/` to override or add templates:

```yaml
# .pm/workflow_templates/my-workflow.yaml
name: My Custom Workflow
description: Custom workflow for my team
chain_to: development  # optional

steps:
  - id: research
    name: Research
    tool_hint: pm_record
    loop: true
    loop_group: investigate

  - id: review
    name: Review
    gate: user_approval

  - id: implement
    name: Implement
    skill_hint: Use plan mode
    optional: false
```

---

## Session Lifecycle

```
# Session start (auto-executed by CLAUDE.md rules)
pm_status()                    # Current state
pm_next()                      # Recommended tasks
pm_recall()                    # Last session context

# During work
pm_update_task(status="in_progress")   # Start task
pm_remember(content="...")             # Save findings
pm_record(category="...", title="...")  # Record knowledge
pm_workflow_advance()                  # Progress workflow

# Session end
pm_log(entry="Completed auth feature")
pm_session_summary(action="save", summary="...")
```

---

## CLI Commands

```bash
pm-server install              # Register MCP server
pm-server uninstall            # Remove MCP server
pm-server serve                # Start MCP server (stdio)
pm-server status               # Show project status
pm-server discover [path]      # Find and register projects
pm-server update-claudemd      # Update CLAUDE.md rules
pm-server hook post-tool-use   # PostToolUse hook handler
```

---

## Data Storage

```
.pm/
├── project.yaml        # Project metadata
├── tasks.yaml          # All tasks
├── decisions.yaml      # ADRs
├── knowledge.yaml      # Knowledge records
├── workflows.yaml      # Workflow instances
├── risks.yaml          # Manual risks
├── milestones.yaml     # Milestones
├── memory.db           # SQLite + FTS5 memory
├── daily/              # Daily logs
│   └── 2026-04-16.yaml
└── workflow_templates/ # Custom templates (optional)
    └── my-workflow.yaml

~/.pm/
├── registry.yaml       # Global project registry
└── memory.db           # Cross-project memory index
```

---

## Enum Reference

| Type | Values |
|------|--------|
| TaskStatus | `todo`, `in_progress`, `review`, `done`, `blocked` |
| Priority | `P0` (critical), `P1` (important), `P2` (nice-to-have), `P3` (someday) |
| DecisionStatus | `proposed`, `accepted`, `deprecated`, `superseded` |
| LogCategory | `progress`, `decision`, `blocker`, `note`, `milestone` |
| MemoryType | `observation`, `insight`, `lesson` |
| KnowledgeCategory | `research`, `market`, `spike`, `requirement`, `constraint`, `tradeoff`, `risk_analysis`, `spec`, `api_design` |
| KnowledgeStatus | `draft`, `validated`, `superseded` |
| ConfidenceLevel | `high`, `medium`, `low` |
| WorkflowStepStatus | `pending`, `active`, `done`, `skipped` |
| WorkflowStatus | `active`, `completed`, `paused`, `abandoned` |
