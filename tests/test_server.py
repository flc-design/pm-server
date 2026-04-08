"""Tests for MCP server tools."""

from unittest.mock import patch

import pytest

from pm_server.server import (
    pm_add_decision,
    pm_add_task,
    pm_blockers,
    pm_cleanup,
    pm_dashboard,
    pm_discover,
    pm_init,
    pm_list,
    pm_log,
    pm_next,
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
