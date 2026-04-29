"""Tests for Claude Code + Codex MCP installer."""

import subprocess
import textwrap
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest
import tomlkit

from pm_server.installer import (
    InstallResult,
    InstallSummary,
    install,
    install_claude_code,
    install_codex,
    install_mcp,
    uninstall,
    uninstall_codex,
    uninstall_mcp,
)


def _make_result(returncode: int = 0, stderr: str = "") -> CompletedProcess:
    return CompletedProcess(args=[], returncode=returncode, stdout="", stderr=stderr)


@pytest.fixture
def fake_codex_config(tmp_path, monkeypatch):
    """Redirect installer._codex_config_path to a tmp_path location.

    Tests must explicitly create the config file if needed; otherwise
    install_codex / uninstall_codex see a missing config and return
    status="skipped". This isolates tests from the real ~/.codex.
    """
    config_path = tmp_path / ".codex" / "config.toml"
    config_path.parent.mkdir(exist_ok=True)
    monkeypatch.setattr("pm_server.installer._codex_config_path", lambda: config_path)
    return config_path


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

    def test_target_codex_returns_skipped_when_config_not_found(self, fake_codex_config):
        # fake_codex_config does not create the file -> install_codex sees no config
        summary = install(target="codex")
        assert len(summary.results) == 1
        assert summary.results[0].target == "codex"
        assert summary.results[0].status == "skipped"
        assert "not found" in summary.results[0].message.lower()

    def test_target_auto_runs_both(self, fake_codex_config):
        def which(name):
            return "/usr/bin/pm-server" if name == "pm-server" else None

        with patch("pm_server.installer.shutil.which", side_effect=which):
            summary = install(target="auto")
        targets = [r.target for r in summary.results]
        assert "claude-code" in targets
        assert "codex" in targets

    def test_failure_in_one_host_does_not_abort_sibling(self, fake_codex_config):
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

    def test_uninstall_target_codex_returns_skipped_when_config_not_found(self, fake_codex_config):
        summary = uninstall(target="codex")
        assert len(summary.results) == 1
        assert summary.results[0].target == "codex"
        assert summary.results[0].status == "skipped"

    def test_unknown_target_raises_value_error(self):
        with pytest.raises(ValueError, match="unknown target"):
            install(target="banana")

    def test_uninstall_target_claude_code_directly(self):
        """uninstall(target='claude-code') dispatches to uninstall_claude_code (PMSERV-040)."""
        with (
            patch("pm_server.installer.shutil.which", return_value="/usr/bin/claude"),
            patch(
                "pm_server.installer.subprocess.run",
                return_value=_make_result(0),
            ),
        ):
            summary = uninstall(target="claude-code")
        assert len(summary.results) == 1
        assert summary.results[0].target == "claude-code"
        assert summary.results[0].status == "uninstalled"


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

    def test_overall_status_installed_when_skipped_mixed(self):
        """installed + skipped mixture resolves to 'installed' (PMSERV-040)."""
        s = InstallSummary(
            results=[
                InstallResult("claude-code", "installed", "ok"),
                InstallResult("codex", "skipped", "config not found"),
            ]
        )
        assert s.overall_status == "installed"


class TestResolvePmServerPath:
    """Absolute path resolution for sandbox-safe Codex registration (PMSERV-038)."""

    def test_uses_sys_executable_neighbor(self, tmp_path, monkeypatch):
        fake_python = tmp_path / "python"
        fake_pm_server = tmp_path / "pm-server"
        fake_pm_server.write_text("")
        monkeypatch.setattr("pm_server.installer.sys.executable", str(fake_python))
        from pm_server.installer import _resolve_pm_server_path

        path = _resolve_pm_server_path()
        assert path == fake_pm_server.resolve()

    def test_falls_back_to_shutil_which(self, tmp_path, monkeypatch):
        fake_python = tmp_path / "python"
        monkeypatch.setattr("pm_server.installer.sys.executable", str(fake_python))
        fallback = tmp_path / "fallback-pm-server"
        fallback.write_text("")
        monkeypatch.setattr(
            "pm_server.installer.shutil.which",
            lambda name: str(fallback) if name == "pm-server" else None,
        )
        from pm_server.installer import _resolve_pm_server_path

        path = _resolve_pm_server_path()
        assert path == fallback.resolve()

    def test_raises_when_not_found(self, tmp_path, monkeypatch):
        fake_python = tmp_path / "python"
        monkeypatch.setattr("pm_server.installer.sys.executable", str(fake_python))
        monkeypatch.setattr("pm_server.installer.shutil.which", lambda name: None)
        from pm_server.installer import _resolve_pm_server_path

        with pytest.raises(FileNotFoundError, match="pm-server binary not found"):
            _resolve_pm_server_path()


class TestInstallCodex:
    """install_codex against a tmp_path Codex config (PMSERV-038)."""

    @staticmethod
    def _make_pm_server_resolvable(tmp_path, monkeypatch):
        pm = tmp_path / "pm-server"
        pm.write_text("")
        resolved = pm.resolve()
        monkeypatch.setattr("pm_server.installer._resolve_pm_server_path", lambda: resolved)
        return resolved

    def test_skipped_when_config_not_found(self, fake_codex_config):
        result = install_codex()
        assert result.target == "codex"
        assert result.status == "skipped"
        assert "not found" in result.message.lower()
        assert result.backup_path is None

    def test_installed_when_section_new(self, fake_codex_config, tmp_path, monkeypatch):
        pm_path = self._make_pm_server_resolvable(tmp_path, monkeypatch)
        fake_codex_config.write_text(
            textwrap.dedent(
                """\
                [mcp_servers.filesystem]
                command = "npx"
                args = ["-y", "@modelcontextprotocol/server-filesystem"]
                """
            )
        )

        result = install_codex()
        assert result.status == "installed"
        assert "Codex" in result.message
        assert result.backup_path is not None
        doc = tomlkit.parse(fake_codex_config.read_text())
        assert str(doc["mcp_servers"]["pm-server"]["command"]) == str(pm_path)
        assert list(doc["mcp_servers"]["pm-server"]["args"]) == ["serve"]
        assert doc["mcp_servers"]["pm-server"]["startup_timeout_sec"] == 30
        assert "filesystem" in doc["mcp_servers"]

    def test_already_registered_when_command_matches(
        self, fake_codex_config, tmp_path, monkeypatch
    ):
        pm_path = self._make_pm_server_resolvable(tmp_path, monkeypatch)
        fake_codex_config.write_text(
            textwrap.dedent(
                f"""\
                [mcp_servers.pm-server]
                command = "{pm_path}"
                args = ["serve"]
                startup_timeout_sec = 30
                """
            )
        )

        result = install_codex()
        assert result.status == "already_registered"
        assert "already registered" in result.message.lower()
        # No mutation -> no backup created
        assert result.backup_path is None
        backups = list(fake_codex_config.parent.glob("config.toml.bak.*"))
        assert backups == []

    def test_installed_when_command_differs(self, fake_codex_config, tmp_path, monkeypatch):
        pm_path = self._make_pm_server_resolvable(tmp_path, monkeypatch)
        fake_codex_config.write_text(
            textwrap.dedent(
                """\
                [mcp_servers.pm-server]
                command = "/old/path/to/pm-server"
                args = ["serve"]
                startup_timeout_sec = 30
                """
            )
        )

        result = install_codex()
        assert result.status == "installed"
        doc = tomlkit.parse(fake_codex_config.read_text())
        assert str(doc["mcp_servers"]["pm-server"]["command"]) == str(pm_path)

    def test_preserves_subtables(self, fake_codex_config, tmp_path, monkeypatch):
        self._make_pm_server_resolvable(tmp_path, monkeypatch)
        fake_codex_config.write_text(
            textwrap.dedent(
                """\
                [mcp_servers.pm-server]
                command = "/old/path/to/pm-server"
                args = ["serve"]
                startup_timeout_sec = 30

                [mcp_servers.pm-server.tools.pm_init]
                approval_mode = "approve"

                [mcp_servers.pm-server.tools.pm_status]
                approval_mode = "approve"
                """
            )
        )

        result = install_codex()
        assert result.status == "installed"
        doc = tomlkit.parse(fake_codex_config.read_text())
        assert doc["mcp_servers"]["pm-server"]["tools"]["pm_init"]["approval_mode"] == "approve"
        assert doc["mcp_servers"]["pm-server"]["tools"]["pm_status"]["approval_mode"] == "approve"

    def test_preserves_comments_and_other_sections(self, fake_codex_config, tmp_path, monkeypatch):
        self._make_pm_server_resolvable(tmp_path, monkeypatch)
        fake_codex_config.write_text(
            textwrap.dedent(
                """\
                # Top-of-file comment
                [mcp_servers.filesystem]
                command = "npx"
                args = ["-y", "@modelcontextprotocol/server-filesystem"]

                # PM Server section comment
                [mcp_servers.pm-server]
                command = "/old/pm-server"
                args = ["serve"]
                startup_timeout_sec = 30
                """
            )
        )

        install_codex()
        new_text = fake_codex_config.read_text()
        assert "# Top-of-file comment" in new_text
        assert "# PM Server section comment" in new_text
        assert "[mcp_servers.filesystem]" in new_text

    def test_creates_backup(self, fake_codex_config, tmp_path, monkeypatch):
        self._make_pm_server_resolvable(tmp_path, monkeypatch)
        fake_codex_config.write_text('[mcp_servers.filesystem]\ncommand = "npx"\n')
        result = install_codex()
        assert result.backup_path is not None
        backup = Path(result.backup_path)
        assert backup.exists()
        assert backup.name.startswith("config.toml.bak.")
        assert "filesystem" in backup.read_text()

    def test_atomic_write_no_leftover_tmp(self, fake_codex_config, tmp_path, monkeypatch):
        self._make_pm_server_resolvable(tmp_path, monkeypatch)
        fake_codex_config.write_text('[mcp_servers.filesystem]\ncommand = "npx"\n')
        install_codex()
        tmp_file = fake_codex_config.with_name(fake_codex_config.name + ".tmp")
        assert not tmp_file.exists()
        doc = tomlkit.parse(fake_codex_config.read_text())
        assert "pm-server" in doc["mcp_servers"]

    def test_install_codex_twice_second_returns_already_registered(
        self, fake_codex_config, tmp_path, monkeypatch
    ):
        """Second install_codex returns already_registered without extra backup (PMSERV-040)."""
        self._make_pm_server_resolvable(tmp_path, monkeypatch)
        fake_codex_config.write_text(
            textwrap.dedent(
                """\
                [mcp_servers.filesystem]
                command = "npx"
                """
            )
        )

        first = install_codex()
        assert first.status == "installed"
        assert first.backup_path is not None

        second = install_codex()
        assert second.status == "already_registered"
        assert second.backup_path is None

        backups = list(fake_codex_config.parent.glob("config.toml.bak.*"))
        assert len(backups) == 1

    def test_install_codex_preserves_inline_comment_on_other_keys(
        self, fake_codex_config, tmp_path, monkeypatch
    ):
        """tomlkit inline comments on other-server keys survive round-trip (PMSERV-040)."""
        self._make_pm_server_resolvable(tmp_path, monkeypatch)
        fake_codex_config.write_text(
            textwrap.dedent(
                """\
                [mcp_servers.filesystem]
                command = "npx"  # the npx runtime
                args = ["-y", "@modelcontextprotocol/server-filesystem"]
                """
            )
        )

        result = install_codex()
        assert result.status == "installed"
        new_text = fake_codex_config.read_text()
        assert "# the npx runtime" in new_text

    def test_install_codex_when_mcp_servers_section_absent(
        self, fake_codex_config, tmp_path, monkeypatch
    ):
        """install_codex creates [mcp_servers] when the section itself is absent (PMSERV-040)."""
        pm_path = self._make_pm_server_resolvable(tmp_path, monkeypatch)
        fake_codex_config.write_text(
            textwrap.dedent(
                """\
                # User config without any mcp_servers
                model = "gpt-4o"
                """
            )
        )

        result = install_codex()
        assert result.status == "installed"
        doc = tomlkit.parse(fake_codex_config.read_text())
        assert "mcp_servers" in doc
        assert "pm-server" in doc["mcp_servers"]
        assert str(doc["mcp_servers"]["pm-server"]["command"]) == str(pm_path)
        assert str(doc["model"]) == "gpt-4o"

    def test_install_codex_existing_section_without_startup_timeout(
        self, fake_codex_config, tmp_path, monkeypatch
    ):
        """install_codex backfills startup_timeout_sec when missing (PMSERV-040, line 308)."""
        self._make_pm_server_resolvable(tmp_path, monkeypatch)
        fake_codex_config.write_text(
            textwrap.dedent(
                """\
                [mcp_servers.pm-server]
                command = "/old/pm-server"
                args = ["serve"]
                """
            )
        )

        result = install_codex()
        assert result.status == "installed"
        doc = tomlkit.parse(fake_codex_config.read_text())
        assert doc["mcp_servers"]["pm-server"]["startup_timeout_sec"] == 30


class TestUninstallCodex:
    """uninstall_codex against a tmp_path Codex config (PMSERV-038)."""

    def test_skipped_when_config_not_found(self, fake_codex_config):
        result = uninstall_codex()
        assert result.status == "skipped"
        assert "not found" in result.message.lower()
        assert result.backup_path is None

    def test_skipped_when_pm_server_not_registered(self, fake_codex_config):
        fake_codex_config.write_text(
            textwrap.dedent(
                """\
                [mcp_servers.filesystem]
                command = "npx"
                """
            )
        )
        result = uninstall_codex()
        assert result.status == "skipped"
        assert "not registered" in result.message.lower()
        assert result.backup_path is None

    def test_full_removal_when_no_subtables(self, fake_codex_config):
        fake_codex_config.write_text(
            textwrap.dedent(
                """\
                [mcp_servers.pm-server]
                command = "/some/pm-server"
                args = ["serve"]
                startup_timeout_sec = 30
                """
            )
        )
        result = uninstall_codex()
        assert result.status == "uninstalled"
        assert result.backup_path is not None
        doc = tomlkit.parse(fake_codex_config.read_text())
        if "mcp_servers" in doc:
            assert "pm-server" not in doc["mcp_servers"]

    def test_preserves_subtables_with_warning(self, fake_codex_config):
        fake_codex_config.write_text(
            textwrap.dedent(
                """\
                [mcp_servers.pm-server]
                command = "/some/pm-server"
                args = ["serve"]
                startup_timeout_sec = 30

                [mcp_servers.pm-server.tools.pm_init]
                approval_mode = "approve"
                """
            )
        )
        result = uninstall_codex()
        assert result.status == "uninstalled"
        assert "preserved" in result.message.lower() or "manually" in result.message.lower()
        doc = tomlkit.parse(fake_codex_config.read_text())
        section = doc["mcp_servers"]["pm-server"]
        assert "command" not in section
        assert "args" not in section
        assert "startup_timeout_sec" not in section
        assert section["tools"]["pm_init"]["approval_mode"] == "approve"

    def test_creates_backup_when_mutating(self, fake_codex_config):
        fake_codex_config.write_text(
            textwrap.dedent(
                """\
                [mcp_servers.pm-server]
                command = "/some/pm-server"
                args = ["serve"]
                """
            )
        )
        result = uninstall_codex()
        assert result.backup_path is not None
        backup = Path(result.backup_path)
        assert backup.exists()
        assert "pm-server" in backup.read_text()

    def test_uninstall_codex_twice_second_returns_skipped(self, fake_codex_config):
        """Second uninstall_codex skips when pm-server not registered (PMSERV-040)."""
        fake_codex_config.write_text(
            textwrap.dedent(
                """\
                [mcp_servers.pm-server]
                command = "/some/pm-server"
                args = ["serve"]
                """
            )
        )

        first = uninstall_codex()
        assert first.status == "uninstalled"

        second = uninstall_codex()
        assert second.status == "skipped"
        assert "not registered" in second.message.lower()
        assert second.backup_path is None

    def test_uninstall_codex_preserves_top_of_file_comment(self, fake_codex_config):
        """uninstall_codex preserves a top-of-file comment after mutation (PMSERV-040)."""
        fake_codex_config.write_text(
            textwrap.dedent(
                """\
                # Top-of-file comment
                [mcp_servers.pm-server]
                command = "/some/pm-server"
                args = ["serve"]
                """
            )
        )

        uninstall_codex()
        new_text = fake_codex_config.read_text()
        assert "# Top-of-file comment" in new_text

    def test_uninstall_codex_preserves_other_section_comments(self, fake_codex_config):
        """uninstall_codex preserves comments tied to unrelated server sections (PMSERV-040)."""
        fake_codex_config.write_text(
            textwrap.dedent(
                """\
                # Filesystem MCP server
                [mcp_servers.filesystem]
                command = "npx"
                args = ["-y", "@modelcontextprotocol/server-filesystem"]

                [mcp_servers.pm-server]
                command = "/some/pm-server"
                args = ["serve"]
                """
            )
        )

        uninstall_codex()
        new_text = fake_codex_config.read_text()
        assert "# Filesystem MCP server" in new_text
        assert "[mcp_servers.filesystem]" in new_text


class TestCodexLifecycle:
    """install -> uninstall -> install roundtrip state-transition coverage (PMSERV-040)."""

    def test_install_uninstall_install_codex_roundtrip(
        self, fake_codex_config, tmp_path, monkeypatch
    ):
        pm_path = TestInstallCodex._make_pm_server_resolvable(tmp_path, monkeypatch)
        fake_codex_config.write_text(
            textwrap.dedent(
                """\
                [mcp_servers.filesystem]
                command = "npx"
                """
            )
        )

        r1 = install_codex()
        assert r1.status == "installed"
        doc = tomlkit.parse(fake_codex_config.read_text())
        assert "pm-server" in doc["mcp_servers"]

        r2 = uninstall_codex()
        assert r2.status == "uninstalled"
        doc = tomlkit.parse(fake_codex_config.read_text())
        assert "pm-server" not in doc.get("mcp_servers", {})
        assert "filesystem" in doc.get("mcp_servers", {})

        r3 = install_codex()
        assert r3.status == "installed"
        doc = tomlkit.parse(fake_codex_config.read_text())
        assert str(doc["mcp_servers"]["pm-server"]["command"]) == str(pm_path)
        assert "filesystem" in doc["mcp_servers"]

        backups = list(fake_codex_config.parent.glob("config.toml.bak.*"))
        assert len(backups) >= 1
