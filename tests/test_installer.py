"""Tests for Claude Code MCP installer."""

import subprocess
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

from pm_server.installer import (
    InstallResult,
    InstallSummary,
    install,
    install_claude_code,
    install_mcp,
    uninstall,
    uninstall_mcp,
)


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


class TestInstallClaudeCode:
    """Structured install_claude_code (PMSERV-037)."""

    def test_pm_server_not_found_returns_failed(self):
        with patch("pm_server.installer.shutil.which", return_value=None):
            r = install_claude_code()
            assert r.target == "claude-code"
            assert r.status == "failed"
            assert "pm-server command not found" in r.message

    def test_claude_not_found_returns_skipped(self):
        def which(name):
            return "/usr/bin/pm-server" if name == "pm-server" else None

        with patch("pm_server.installer.shutil.which", side_effect=which):
            r = install_claude_code()
            assert r.status == "skipped"
            assert "claude command not found" in r.message

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
            r = install_claude_code()
            assert r.status == "already_registered"

    def test_install_success(self):
        def which(name):
            return f"/usr/bin/{name}"

        call_count = 0

        def mock_run(cmd, **kwargs):
            nonlocal call_count
            call_count += 1
            return _make_result(1) if call_count == 1 else _make_result(0)

        with (
            patch("pm_server.installer.shutil.which", side_effect=which),
            patch("pm_server.installer.subprocess.run", side_effect=mock_run),
        ):
            r = install_claude_code()
            assert r.status == "installed"
            assert "user scope" in r.message.lower()


class TestInstallOrchestrator:
    """install / uninstall orchestrators (PMSERV-037)."""

    def test_target_claude_code_returns_one_result(self):
        def which(name):
            return "/usr/bin/pm-server" if name == "pm-server" else None

        with patch("pm_server.installer.shutil.which", side_effect=which):
            summary = install(target="claude-code")
        assert len(summary.results) == 1
        assert summary.results[0].target == "claude-code"

    def test_target_codex_returns_skipped_stub(self):
        summary = install(target="codex")
        assert len(summary.results) == 1
        assert summary.results[0].target == "codex"
        assert summary.results[0].status == "skipped"
        assert "PMSERV-038" in summary.results[0].message

    def test_target_auto_runs_both(self):
        def which(name):
            return "/usr/bin/pm-server" if name == "pm-server" else None

        with patch("pm_server.installer.shutil.which", side_effect=which):
            summary = install(target="auto")
        targets = [r.target for r in summary.results]
        assert "claude-code" in targets
        assert "codex" in targets

    def test_failure_in_one_host_does_not_abort_sibling(self):
        def which(name):
            return f"/usr/bin/{name}"

        def mock_run(cmd, **kwargs):
            raise RuntimeError("kaboom")

        with (
            patch("pm_server.installer.shutil.which", side_effect=which),
            patch("pm_server.installer.subprocess.run", side_effect=mock_run),
        ):
            summary = install(target="auto")

        cc = next(r for r in summary.results if r.target == "claude-code")
        codex = next(r for r in summary.results if r.target == "codex")
        assert cc.status == "failed"
        assert "kaboom" in cc.message
        assert codex.status == "skipped"

    def test_uninstall_target_codex_returns_skipped_stub(self):
        summary = uninstall(target="codex")
        assert len(summary.results) == 1
        assert summary.results[0].target == "codex"
        assert summary.results[0].status == "skipped"

    def test_unknown_target_raises_value_error(self):
        with pytest.raises(ValueError, match="unknown target"):
            install(target="banana")


class TestInstallSummary:
    """InstallSummary aggregation (PMSERV-037)."""

    def test_overall_status_failed_takes_priority(self):
        s = InstallSummary(
            results=[
                InstallResult("a", "failed", "x"),
                InstallResult("b", "installed", "y"),
            ]
        )
        assert s.overall_status == "failed"

    def test_overall_status_installed_when_no_failure(self):
        s = InstallSummary(
            results=[
                InstallResult("a", "installed", "x"),
                InstallResult("b", "skipped", "y"),
            ]
        )
        assert s.overall_status == "installed"

    def test_overall_status_skipped_when_all_skipped(self):
        s = InstallSummary(
            results=[
                InstallResult("a", "skipped", "x"),
                InstallResult("b", "skipped", "y"),
            ]
        )
        assert s.overall_status == "skipped"

    def test_message_aggregation(self):
        s = InstallSummary(
            results=[
                InstallResult("a", "installed", "hello"),
                InstallResult("b", "skipped", "world"),
            ]
        )
        assert "[a] hello" in s.message
        assert "[b] world" in s.message

    def test_message_when_empty(self):
        s = InstallSummary()
        assert s.message == "no targets processed"
