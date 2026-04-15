"""Tests for resolve_project_path guard logic (PMSERV-014)."""

import pytest

from pm_server.models import ProjectNotFoundError
from pm_server.utils import _is_project_pm_dir, resolve_project_path


class TestIsProjectPmDir:
    """Tests for _is_project_pm_dir helper."""

    def test_valid_project_pm_dir(self, tmp_path):
        pm = tmp_path / ".pm"
        pm.mkdir()
        (pm / "project.yaml").write_text("name: test\n")
        assert _is_project_pm_dir(pm) is True

    def test_global_pm_dir_without_project_yaml(self, tmp_path):
        """A .pm/ with registry.yaml but no project.yaml is NOT a project."""
        pm = tmp_path / ".pm"
        pm.mkdir()
        (pm / "registry.yaml").write_text("projects: []\n")
        assert _is_project_pm_dir(pm) is False

    def test_nonexistent_dir(self, tmp_path):
        pm = tmp_path / ".pm"
        assert _is_project_pm_dir(pm) is False

    def test_file_not_dir(self, tmp_path):
        pm = tmp_path / ".pm"
        pm.write_text("not a directory")
        assert _is_project_pm_dir(pm) is False


class TestResolveProjectPathExplicit:
    """Tests for explicit project_path argument (priority 1)."""

    def test_explicit_path_with_pm_dir(self, tmp_path):
        (tmp_path / ".pm").mkdir()
        result = resolve_project_path(str(tmp_path))
        assert result == tmp_path.resolve()

    def test_explicit_path_without_pm_dir(self, tmp_path):
        with pytest.raises(ProjectNotFoundError, match="No .pm/ directory found at"):
            resolve_project_path(str(tmp_path))


class TestResolveProjectPathEnvVar:
    """Tests for PM_PROJECT_PATH env var (priority 2)."""

    def test_env_var_with_pm_dir(self, tmp_path, monkeypatch):
        (tmp_path / ".pm").mkdir()
        monkeypatch.setenv("PM_PROJECT_PATH", str(tmp_path))
        result = resolve_project_path()
        assert result == tmp_path.resolve()

    def test_env_var_without_pm_dir_falls_through(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PM_PROJECT_PATH", str(tmp_path))
        monkeypatch.chdir(tmp_path)  # ensure cwd walk-up also finds nothing
        with pytest.raises(ProjectNotFoundError):
            resolve_project_path()


class TestResolveProjectPathCwdWalkUp:
    """Tests for cwd walk-up (priority 3) — the bug fix target."""

    def test_finds_project_in_cwd(self, tmp_path, monkeypatch):
        pm = tmp_path / ".pm"
        pm.mkdir()
        (pm / "project.yaml").write_text("name: test\n")
        monkeypatch.chdir(tmp_path)

        result = resolve_project_path()
        assert result == tmp_path.resolve()

    def test_finds_project_in_parent(self, tmp_path, monkeypatch):
        pm = tmp_path / ".pm"
        pm.mkdir()
        (pm / "project.yaml").write_text("name: test\n")
        child = tmp_path / "src" / "module"
        child.mkdir(parents=True)
        monkeypatch.chdir(child)

        result = resolve_project_path()
        assert result == tmp_path.resolve()

    def test_skips_global_pm_dir(self, tmp_path, monkeypatch):
        """Core bug fix: .pm/ with registry.yaml but no project.yaml is skipped."""
        home = tmp_path / "fakehome"
        home.mkdir()
        global_pm = home / ".pm"
        global_pm.mkdir()
        (global_pm / "registry.yaml").write_text("projects: []\n")
        (global_pm / "memory.db").write_bytes(b"")

        workdir = home / "projects" / "myproject"
        workdir.mkdir(parents=True)
        monkeypatch.chdir(workdir)

        with pytest.raises(ProjectNotFoundError):
            resolve_project_path()

    def test_skips_global_but_finds_project_below(self, tmp_path, monkeypatch):
        """Walks up past global-only .pm/, finds real project .pm/ lower in tree."""
        home = tmp_path / "fakehome"
        home.mkdir()
        global_pm = home / ".pm"
        global_pm.mkdir()
        (global_pm / "registry.yaml").write_text("projects: []\n")

        project_root = home / "projects" / "myproj"
        project_root.mkdir(parents=True)
        project_pm = project_root / ".pm"
        project_pm.mkdir()
        (project_pm / "project.yaml").write_text("name: myproj\n")

        src = project_root / "src"
        src.mkdir()
        monkeypatch.chdir(src)

        result = resolve_project_path()
        assert result == project_root.resolve()

    def test_home_with_intentional_pm_init(self, tmp_path, monkeypatch):
        """If user ran pm_init at home (project.yaml exists), it works."""
        home = tmp_path / "fakehome"
        home.mkdir()
        pm = home / ".pm"
        pm.mkdir()
        (pm / "project.yaml").write_text("name: home-project\n")
        (pm / "registry.yaml").write_text("projects: []\n")
        monkeypatch.chdir(home)

        result = resolve_project_path()
        assert result == home.resolve()

    def test_no_pm_dir_anywhere(self, tmp_path, monkeypatch):
        workdir = tmp_path / "empty" / "project"
        workdir.mkdir(parents=True)
        monkeypatch.chdir(workdir)

        with pytest.raises(ProjectNotFoundError, match="No .pm/ directory found"):
            resolve_project_path()
