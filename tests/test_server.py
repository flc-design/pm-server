"""Tests for MCP server tools."""

from unittest.mock import patch

import pytest

from pm_server.server import (
    pm_add_decision,
    pm_add_issue,
    pm_add_task,
    pm_blockers,
    pm_cleanup,
    pm_dashboard,
    pm_discover,
    pm_init,
    pm_list,
    pm_log,
    pm_next,
    pm_remember,
    pm_risks,
    pm_status,
    pm_tasks,
    pm_update_claudemd,
    pm_update_task,
    pm_velocity,
)
from pm_server.storage import (
    init_pm_directory,
    save_project,
    save_tasks,
)


@pytest.fixture
def initialized_project(tmp_path, sample_project, sample_tasks):
    """Create a fully initialized project with data."""
    pm_path = init_pm_directory(tmp_path)
    save_project(pm_path, sample_project)
    save_tasks(pm_path, sample_tasks)
    return tmp_path


class TestPmInit:
    def test_init_creates_pm_dir(self, tmp_path):
        result = pm_init(project_path=str(tmp_path))
        assert result["status"] == "initialized"
        assert (tmp_path / ".pm").is_dir()
        assert (tmp_path / ".pm" / "project.yaml").exists()

    def test_init_with_custom_name(self, tmp_path):
        result = pm_init(project_path=str(tmp_path), project_name="custom")
        assert result["project"]["name"] == "custom"


class TestPmStatus:
    def test_returns_status(self, initialized_project):
        result = pm_status(project_path=str(initialized_project))
        assert result["project"]["name"] == "testproj"
        assert result["tasks"]["total"] == 4
        assert result["tasks"]["done"] == 1
        assert result["tasks"]["blocked"] == 1

    def test_phase_progress(self, initialized_project):
        result = pm_status(project_path=str(initialized_project))
        phases = result["phases"]
        phase0 = next(p for p in phases if p["id"] == "phase-0")
        assert phase0["progress"] == "1/1"
        assert phase0["progress_pct"] == 100


class TestPmTasks:
    def test_all_tasks(self, initialized_project):
        result = pm_tasks(project_path=str(initialized_project))
        assert len(result) == 4

    def test_filter_by_status(self, initialized_project):
        result = pm_tasks(project_path=str(initialized_project), status="todo")
        assert len(result) == 2

    def test_filter_by_priority(self, initialized_project):
        result = pm_tasks(project_path=str(initialized_project), priority="P0")
        assert len(result) == 2

    def test_filter_by_tag(self, initialized_project):
        result = pm_tasks(project_path=str(initialized_project), tag="core")
        assert len(result) == 1
        assert result[0]["id"] == "TEST-002"


class TestPmAddTask:
    def test_add_task(self, initialized_project):
        result = pm_add_task(
            title="New feature",
            phase="phase-1",
            priority="P0",
            project_path=str(initialized_project),
            tags=["feature"],
        )
        assert result["status"] == "created"
        assert result["task"]["priority"] == "P0"

        # Verify persisted
        tasks = pm_tasks(project_path=str(initialized_project))
        assert len(tasks) == 5


class TestPmUpdateTask:
    def test_update_status(self, initialized_project):
        result = pm_update_task(
            task_id="TEST-002",
            status="in_progress",
            project_path=str(initialized_project),
        )
        assert result["status"] == "updated"
        assert result["task"]["status"] == "in_progress"

    def test_update_nonexistent(self, initialized_project):
        with pytest.raises(Exception):
            pm_update_task(
                task_id="NOPE-999",
                status="done",
                project_path=str(initialized_project),
            )


class TestPmNext:
    def test_recommends_actionable(self, initialized_project):
        result = pm_next(project_path=str(initialized_project))
        # TEST-002 is todo with no deps — should be first
        # TEST-003 depends on TEST-002 (not done) — should NOT appear
        ids = [t["id"] for t in result]
        assert "TEST-002" in ids
        assert "TEST-003" not in ids

    def test_respects_count(self, initialized_project):
        result = pm_next(project_path=str(initialized_project), count=1)
        assert len(result) <= 1


class TestPmBlockers:
    def test_lists_blocked(self, initialized_project):
        result = pm_blockers(project_path=str(initialized_project))
        assert len(result) == 1
        assert result[0]["id"] == "TEST-004"
        assert "days_blocked" in result[0]


class TestPmLog:
    def test_add_log(self, initialized_project):
        result = pm_log(
            entry="Completed setup",
            category="progress",
            project_path=str(initialized_project),
        )
        assert result["status"] == "logged"
        assert result["entries_today"] == 1


class TestPmAddDecision:
    def test_add_decision(self, initialized_project):
        result = pm_add_decision(
            title="Use SQLite",
            context="Need faster queries",
            decision="Switch to SQLite",
            consequences_positive=["Faster"],
            consequences_negative=["Binary format"],
            project_path=str(initialized_project),
        )
        assert result["status"] == "recorded"
        assert result["decision_id"] == "ADR-001"


class TestPmList:
    def test_list_with_registered(self, initialized_project, tmp_path):
        from pm_server.storage import register_project

        # Create a temp registry
        registry_dir = tmp_path / "reg"
        registry_dir.mkdir()
        register_project(initialized_project, "testproj", registry_dir)

        # pm_list uses the global registry; we patch it
        with patch("pm_server.server.load_registry") as mock_reg:
            from pm_server.models import Registry, RegistryEntry

            mock_reg.return_value = Registry(
                projects=[
                    RegistryEntry(
                        path=str(initialized_project),
                        name="testproj",
                    )
                ]
            )
            result = pm_list()
            assert len(result) == 1
            assert result[0]["name"] == "testproj"
            assert result[0]["tasks_total"] == 4


class TestPmInitIdempotent:
    def test_init_does_not_overwrite_existing(self, tmp_path):
        # First init
        pm_init(project_path=str(tmp_path), project_name="original")
        # Second init should not overwrite
        result = pm_init(project_path=str(tmp_path), project_name="overwritten")
        assert result["project"]["name"] == "original"


class TestPmDiscover:
    def test_discover_finds_projects(self, tmp_path):
        # Create two projects with .pm/
        for name in ["proj-a", "proj-b"]:
            pm = tmp_path / name / ".pm"
            pm.mkdir(parents=True)
            (pm / "project.yaml").write_text(f"name: {name}\n")
        result = pm_discover(scan_path=str(tmp_path))
        assert result["found"] == 2

    def test_discover_empty(self, tmp_path):
        result = pm_discover(scan_path=str(tmp_path))
        assert result["found"] == 0


class TestPmCleanup:
    def test_cleanup_removes_invalid(self, tmp_path, initialized_project):
        from pm_server.models import Registry, RegistryEntry

        with (
            patch("pm_server.server.load_registry") as mock_reg,
            patch("pm_server.server.save_registry"),
        ):
            mock_reg.return_value = Registry(
                projects=[
                    RegistryEntry(path=str(initialized_project), name="valid"),
                    RegistryEntry(path="/nonexistent/path", name="invalid"),
                ]
            )
            result = pm_cleanup()
            assert result["valid"] == 1
            assert result["removed"] == 1


class TestPmRisks:
    def test_risks_returns_list(self, initialized_project):
        result = pm_risks(project_path=str(initialized_project))
        assert isinstance(result, list)
        # sample_tasks has a blocked task → should detect it
        blocked_risks = [r for r in result if r.get("type") == "blocked_task"]
        assert len(blocked_risks) >= 1


class TestPmVelocity:
    def test_velocity_returns_dict(self, initialized_project):
        result = pm_velocity(project_path=str(initialized_project))
        assert "average" in result
        assert "trend" in result
        assert "weeks" in result


class TestPmUpdateClaudemd:
    def test_pm_update_claudemd_creates_new(self, initialized_project):
        """pm_update_claudemd creates CLAUDE.md when it doesn't exist."""
        # Remove CLAUDE.md if pm_init created it
        claude_md = initialized_project / "CLAUDE.md"
        if claude_md.exists():
            claude_md.unlink()
        result = pm_update_claudemd(project_path=str(initialized_project))
        assert result["status"] == "updated"
        assert "created" in result["message"]
        assert claude_md.exists()

    def test_pm_update_claudemd_updates_existing(self, initialized_project):
        """pm_update_claudemd updates existing CLAUDE.md."""
        # 初回
        pm_update_claudemd(project_path=str(initialized_project))
        # 2回目
        result = pm_update_claudemd(project_path=str(initialized_project))
        assert result["status"] == "updated"
        assert result["after"]["up_to_date"] is True


class TestPmDashboard:
    def test_html_dashboard(self, initialized_project):
        html = pm_dashboard(project_path=str(initialized_project), format="html")
        assert "<!DOCTYPE html>" in html

    def test_text_dashboard(self, initialized_project):
        text = pm_dashboard(project_path=str(initialized_project), format="text")
        assert "testproj" in text.lower() or "Test Project" in text


class TestPmAddIssue:
    def test_add_issue_basic(self, initialized_project):
        """pm_add_issue creates a child task linked to the parent."""
        result = pm_add_issue(
            parent_id="TEST-002",
            title="Fix validation bug",
            project_path=str(initialized_project),
        )
        assert result["status"] == "created"
        assert result["task"]["parent_id"] == "TEST-002"
        assert result["task"]["phase"] == "phase-1"  # inherited from parent

    def test_add_issue_inherits_phase(self, initialized_project):
        """Child task inherits phase from parent automatically."""
        result = pm_add_issue(
            parent_id="TEST-001",
            title="Phase-0 issue",
            project_path=str(initialized_project),
        )
        assert result["task"]["phase"] == "phase-0"

    def test_add_issue_reverts_done_parent_to_review(self, initialized_project):
        """When parent is 'done', adding an issue moves it to 'review'."""
        result = pm_add_issue(
            parent_id="TEST-001",  # status: done
            title="Found a problem",
            project_path=str(initialized_project),
        )
        assert result["parent_reverted"] is True
        assert "review" in result["message"]

        # Verify parent status actually changed
        tasks = pm_tasks(project_path=str(initialized_project))
        parent = next(t for t in tasks if t["id"] == "TEST-001")
        assert parent["status"] == "review"

    def test_add_issue_no_revert_when_parent_not_done(self, initialized_project):
        """When parent is not 'done', no automatic status change."""
        result = pm_add_issue(
            parent_id="TEST-002",  # status: todo
            title="New issue",
            project_path=str(initialized_project),
        )
        assert "parent_reverted" not in result

    def test_add_issue_nonexistent_parent(self, initialized_project):
        """Adding an issue to a nonexistent parent raises an error."""
        with pytest.raises(Exception):
            pm_add_issue(
                parent_id="NOPE-999",
                title="Orphan issue",
                project_path=str(initialized_project),
            )

    def test_add_issue_with_priority_and_tags(self, initialized_project):
        """pm_add_issue accepts priority and tags."""
        result = pm_add_issue(
            parent_id="TEST-002",
            title="Critical fix",
            priority="P0",
            tags=["bugfix", "urgent"],
            project_path=str(initialized_project),
        )
        assert result["task"]["priority"] == "P0"
        assert "bugfix" in result["task"]["tags"]


class TestPmTasksParentFilter:
    def test_filter_by_parent_id(self, initialized_project):
        """pm_tasks(parent_id=...) returns only child issues."""
        # Add two issues to TEST-002
        pm_add_issue(
            parent_id="TEST-002",
            title="Issue A",
            project_path=str(initialized_project),
        )
        pm_add_issue(
            parent_id="TEST-002",
            title="Issue B",
            project_path=str(initialized_project),
        )
        # Add one issue to TEST-001
        pm_add_issue(
            parent_id="TEST-001",
            title="Issue C",
            project_path=str(initialized_project),
        )

        children = pm_tasks(
            project_path=str(initialized_project),
            parent_id="TEST-002",
        )
        assert len(children) == 2
        assert all(c["parent_id"] == "TEST-002" for c in children)

    def test_filter_parent_id_no_children(self, initialized_project):
        """pm_tasks with parent_id returns empty list when no children."""
        children = pm_tasks(
            project_path=str(initialized_project),
            parent_id="TEST-003",
        )
        assert children == []


class TestPmUpdateTaskIssueCompletion:
    def test_all_issues_resolved_notification(self, initialized_project):
        """When all child issues are done, result includes completion hint."""
        # Add two issues
        pm_add_issue(
            parent_id="TEST-002",
            title="Issue 1",
            project_path=str(initialized_project),
        )
        pm_add_issue(
            parent_id="TEST-002",
            title="Issue 2",
            project_path=str(initialized_project),
        )

        # Complete first child
        children = pm_tasks(
            project_path=str(initialized_project),
            parent_id="TEST-002",
        )
        pm_update_task(
            task_id=children[0]["id"],
            status="done",
            project_path=str(initialized_project),
        )

        # Complete second child → should trigger notification
        result = pm_update_task(
            task_id=children[1]["id"],
            status="done",
            project_path=str(initialized_project),
        )
        assert result["all_issues_resolved"] is True
        assert result["parent_id"] == "TEST-002"

    def test_no_notification_when_issues_remain(self, initialized_project):
        """No notification when some child issues are still open."""
        pm_add_issue(
            parent_id="TEST-002",
            title="Issue 1",
            project_path=str(initialized_project),
        )
        pm_add_issue(
            parent_id="TEST-002",
            title="Issue 2",
            project_path=str(initialized_project),
        )

        children = pm_tasks(
            project_path=str(initialized_project),
            parent_id="TEST-002",
        )
        # Complete only one
        result = pm_update_task(
            task_id=children[0]["id"],
            status="done",
            project_path=str(initialized_project),
        )
        assert "all_issues_resolved" not in result

    def test_no_notification_for_top_level_task(self, initialized_project):
        """No notification when completing a task with no parent."""
        result = pm_update_task(
            task_id="TEST-002",
            status="done",
            project_path=str(initialized_project),
        )
        assert "all_issues_resolved" not in result


class TestPmStatusExtended:
    """Tests for active_tasks, hooks, and next_pm_actions in pm_status."""

    def test_active_tasks_included(self, initialized_project):
        # Set a task to in_progress first
        pm_update_task(
            task_id="TEST-002", status="in_progress",
            project_path=str(initialized_project),
        )
        result = pm_status(project_path=str(initialized_project))
        assert "active_tasks" in result
        assert any(t["id"] == "TEST-002" for t in result["active_tasks"])

    def test_active_tasks_empty(self, initialized_project):
        result = pm_status(project_path=str(initialized_project))
        assert result["active_tasks"] == []

    def test_hooks_status_included(self, initialized_project):
        result = pm_status(project_path=str(initialized_project))
        assert "hooks" in result
        assert "installed" in result["hooks"]

    def test_next_pm_actions_with_active(self, initialized_project):
        pm_update_task(
            task_id="TEST-002", status="in_progress",
            project_path=str(initialized_project),
        )
        result = pm_status(project_path=str(initialized_project))
        actions = result["next_pm_actions"]
        assert any("pm_update_task" in a for a in actions)
        assert any("pm_remember" in a for a in actions)

    def test_next_pm_actions_without_active(self, initialized_project):
        result = pm_status(project_path=str(initialized_project))
        actions = result["next_pm_actions"]
        assert any("pm_log" in a for a in actions)
        assert any("pm_session_summary" in a for a in actions)


class TestPmLogAutoLink:
    """Tests for pm_log task_id auto-inference."""

    def test_auto_links_single_active_task(self, initialized_project):
        pm_update_task(
            task_id="TEST-002", status="in_progress",
            project_path=str(initialized_project),
        )
        result = pm_log(
            entry="Completed feature",
            project_path=str(initialized_project),
        )
        assert result["auto_linked_task"] == "TEST-002"

    def test_no_auto_link_without_active(self, initialized_project):
        result = pm_log(
            entry="General note",
            project_path=str(initialized_project),
        )
        assert "auto_linked_task" not in result

    def test_explicit_task_id_used(self, initialized_project):
        pm_update_task(
            task_id="TEST-002", status="in_progress",
            project_path=str(initialized_project),
        )
        result = pm_log(
            entry="Specific task log",
            task_id="TEST-001",
            project_path=str(initialized_project),
        )
        # explicit task_id should override auto-link
        assert "auto_linked_task" not in result

    def test_no_auto_link_multiple_active(self, initialized_project):
        """No auto-link when multiple tasks are in_progress."""
        pm_update_task(
            task_id="TEST-002", status="in_progress",
            project_path=str(initialized_project),
        )
        pm_update_task(
            task_id="TEST-003", status="in_progress",
            project_path=str(initialized_project),
        )
        result = pm_log(
            entry="Ambiguous",
            project_path=str(initialized_project),
        )
        assert "auto_linked_task" not in result


class TestPmRememberAutoLink:
    """Tests for pm_remember task_id auto-inference."""

    def test_auto_links_single_active_task(self, initialized_project):
        pm_update_task(
            task_id="TEST-002", status="in_progress",
            project_path=str(initialized_project),
        )
        result = pm_remember(
            content="Important finding",
            project_path=str(initialized_project),
        )
        assert result["auto_linked_task"] == "TEST-002"

    def test_no_auto_link_when_task_id_provided(self, initialized_project):
        pm_update_task(
            task_id="TEST-002", status="in_progress",
            project_path=str(initialized_project),
        )
        result = pm_remember(
            content="Linked to specific task",
            task_id="TEST-001",
            project_path=str(initialized_project),
        )
        assert "auto_linked_task" not in result

    def test_no_auto_link_when_decision_id_provided(self, initialized_project):
        pm_update_task(
            task_id="TEST-002", status="in_progress",
            project_path=str(initialized_project),
        )
        result = pm_remember(
            content="Decision context",
            decision_id="ADR-001",
            project_path=str(initialized_project),
        )
        assert "auto_linked_task" not in result

    def test_no_auto_link_multiple_active(self, initialized_project):
        pm_update_task(
            task_id="TEST-002", status="in_progress",
            project_path=str(initialized_project),
        )
        pm_update_task(
            task_id="TEST-003", status="in_progress",
            project_path=str(initialized_project),
        )
        result = pm_remember(
            content="Ambiguous context",
            project_path=str(initialized_project),
        )
        assert "auto_linked_task" not in result
