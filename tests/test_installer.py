"""Tests for Claude Code MCP installer."""

import subprocess
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from pm_server.installer import install_mcp, uninstall_mcp


def _make_result(returncode: int = 0, stderr: str = "") -> CompletedProcess:
    return CompletedProcess(args=[], returncode=returncode, stdout="", stderr=stderr)


class TestInstallMcp:
    def test_pm_server_not_found(self):
        with patch("pm_server.installer.shutil.which", return_value=None):
            msg = install_mcp()
            assert "pm-server command not found" in msg

    def test_claude_not_found(self):
        def which(name):
            return "/usr/bin/pm-server" if name == "pm-server" else None

        with patch("pm_server.installer.shutil.which", side_effect=which):
            msg = install_mcp()
            assert "claude command not found" in msg

    def test_already_registered(self):
        def which(name):
            return f"/usr/bin/{name}"

        with (
            patch("pm_server.installer.shutil.which", side_effect=which),
            patch(
                "pm_server.installer.subprocess.run",
                return_value=_make_result(0),
            ),
        ):
            msg = install_mcp()
            assert "already registered" in msg.lower()

    def test_install_success(self):
        def which(name):
            return f"/usr/bin/{name}"

        call_count = 0

        def mock_run(cmd, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # mcp get -> not found
                return _make_result(1)
            # mcp add -> success
            return _make_result(0)

        with (
            patch("pm_server.installer.shutil.which", side_effect=which),
            patch("pm_server.installer.subprocess.run", side_effect=mock_run),
        ):
            msg = install_mcp()
            assert "registered" in msg.lower()
            assert "user scope" in msg.lower()

    def test_install_failure(self):
        def which(name):
            return f"/usr/bin/{name}"

        def mock_run(cmd, **kwargs):
            if "get" in cmd:
                return _make_result(1)
            return _make_result(1, stderr="some error")

        with (
            patch("pm_server.installer.shutil.which", side_effect=which),
            patch("pm_server.installer.subprocess.run", side_effect=mock_run),
        ):
            msg = install_mcp()
            assert "failed to register" in msg.lower()


class TestUninstallMcp:
    def test_claude_not_found(self):
        with patch("pm_server.installer.shutil.which", return_value=None):
            msg = uninstall_mcp()
            assert "claude command not found" in msg

    def test_uninstall_success(self):
        with (
            patch("pm_server.installer.shutil.which", return_value="/usr/bin/claude"),
            patch(
                "pm_server.installer.subprocess.run",
                return_value=_make_result(0),
            ),
        ):
            msg = uninstall_mcp()
            assert "unregistered" in msg.lower()

    def test_uninstall_not_registered(self):
        with (
            patch("pm_server.installer.shutil.which", return_value="/usr/bin/claude"),
            patch(
                "pm_server.installer.subprocess.run",
                return_value=_make_result(1, stderr="not found"),
            ),
        ):
            msg = uninstall_mcp()
            assert "not registered" in msg.lower() or "removal failed" in msg.lower()


class TestMigrateFromPmAgent:
    def test_migrate_from_pm_agent(self, tmp_path, monkeypatch):
        """migrate コマンドが旧 pm-agent を解除して pm-server を登録する。"""
        calls = []

        def mock_run(cmd, **kwargs):
            calls.append(cmd)
            result = subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            return result

        monkeypatch.setattr(subprocess, "run", mock_run)

        # registry を用意
        registry_dir = tmp_path / ".pm"
        registry_dir.mkdir()
        (registry_dir / "registry.yaml").write_text("projects: []")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        from pm_server.installer import migrate_from_pm_agent

        migrate_from_pm_agent()

        # remove pm-agent が呼ばれたこと
        assert any("pm-agent" in str(c) for c in calls)
        # add pm-server が呼ばれたこと
        assert any("pm-server" in str(c) for c in calls)
