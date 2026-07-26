"""Host registry invariants and the two hosts added by PMSERV-165.

Before the registry, a host's identity lived in six unsynchronised literals and
two ``if/elif`` dispatch chains with no ``else``. The failure mode was silence:
a host wired into some of those places and not others produced zero results, no
error, and ``overall_status == "skipped"``. The drift tests here exist to make
that impossible; the Cursor/Grok tests cover the two registration formats.

The cross-host isolation tests are the ones with teeth. pmlens edits files in
``$HOME`` belonging to editors the user actually depends on, and nothing
previously asserted that registering with one host leaves the others alone.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import get_args

import pytest
import tomlkit

from pmlens import installer, rules
from pmlens.hosts import HOSTS, HostId, hosts_reading_both_rule_files
from pmlens.utils import _KNOWN_HOSTS, TARGET_CHOICES

# ─── Registry drift ───────────────────────────────────────────────────────


class TestRegistryDrift:
    def test_host_id_literal_matches_registry(self):
        """A host in the registry but not the Literal is unchecked by the type
        checker; one in the Literal but not the registry is unreachable."""
        assert set(get_args(HostId)) == set(HOSTS)

    def test_known_hosts_derives_from_registry_in_order(self):
        assert _KNOWN_HOSTS == tuple(HOSTS)
        assert TARGET_CHOICES == ("auto", "all", *HOSTS)

    def test_every_host_has_an_installer_and_an_uninstaller(self):
        """The dispatch tables must cover the registry exactly.

        This is the drift the old if/elif chains could not detect: an unhandled
        host simply produced no result at all.
        """
        assert set(installer._INSTALLERS) == set(HOSTS)
        assert set(installer._UNINSTALLERS) == set(HOSTS)

    def test_file_registered_hosts_declare_a_config_file(self):
        for host_id, spec in HOSTS.items():
            if spec.registration == "cli":
                assert spec.config_file is None, f"{host_id} registers via CLI"
            else:
                assert spec.config_file is not None, f"{host_id} needs a config path"
                assert spec.install_marker is not None, f"{host_id} needs an install marker"

    def test_status_keys_are_unique_and_underscored(self):
        keys = [spec.status_key for spec in HOSTS.values()]
        assert len(keys) == len(set(keys))
        assert all("-" not in key for key in keys)

    def test_unhandled_host_fails_loudly_rather_than_silently(self, monkeypatch):
        """A registry entry with no installer must produce a FAILED result.

        The pre-PMSERV-165 chains had no ``else``: the host vanished from the
        results and the summary reported ``skipped``, which reads as success.
        """
        monkeypatch.setitem(installer._INSTALLERS, "codex", None)
        del installer._INSTALLERS["codex"]
        try:
            summary = installer.install(target="codex")
        finally:
            installer._INSTALLERS["codex"] = installer.install_codex

        assert [r.target for r in summary.results] == ["codex"]
        assert summary.results[0].status == "failed"
        assert "no installer wired up" in summary.results[0].message


# ─── Shared AGENTS.md ─────────────────────────────────────────────────────


class TestSharedRuleFile:
    def test_three_hosts_read_agents_md(self):
        assert [h for h, s in HOSTS.items() if s.rule_file == "AGENTS.md"] == [
            "codex",
            "cursor",
            "grok",
        ]

    def test_codex_precedes_the_other_agents_md_hosts(self):
        """Deduplication attributes a shared file to the FIRST host in order.

        If cursor or grok came first, ``target="all"`` would report AGENTS.md as
        written by cursor — changing an existing, asserted result shape for no
        reason.
        """
        order = list(HOSTS)
        assert order.index("codex") < order.index("cursor")
        assert order.index("codex") < order.index("grok")

    def test_target_all_writes_agents_md_exactly_once(self, tmp_path):
        """Three hosts, one file, one write — and one result, not three.

        Iterating hosts would back up and rewrite AGENTS.md three times, and the
        second and third would report "skipped, already current" because the
        first had just written it.
        """
        summary = rules.inject_pm_rules(tmp_path, target="all")

        files = [r.target_file for r in summary.results]
        assert sorted(files) == ["AGENTS.md", "CLAUDE.md"], (
            f"expected one result per FILE, got {files}"
        )
        agents = next(r for r in summary.results if r.target_file == "AGENTS.md")
        assert agents.host == "codex"
        assert agents.hosts == ("codex", "cursor", "grok")
        # A single write means a single created file and no backup litter.
        assert not list(tmp_path.glob("AGENTS.md.bak.*"))

    def test_single_agents_md_host_still_writes_the_file(self, tmp_path):
        summary = rules.inject_pm_rules(tmp_path, target="grok")
        assert [r.target_file for r in summary.results] == ["AGENTS.md"]
        assert (tmp_path / "AGENTS.md").exists()
        assert summary.results[0].hosts == ("grok",)

    def test_status_reports_every_agents_md_host(self, tmp_path):
        rules.inject_pm_rules(tmp_path, target="codex")
        status = rules.get_rules_status(tmp_path)
        assert set(status) == {spec.status_key for spec in HOSTS.values()}
        for key in ("codex", "cursor", "grok"):
            assert status[key]["has_pm_section"] is True, (
                f"{key} reads AGENTS.md, so it really does see the marker"
            )
        assert status["claude_code"]["has_pm_section"] is False


# ─── Grok's double-read warning ───────────────────────────────────────────


class TestDuplicateRuleFileWarning:
    def test_grok_is_the_host_that_reads_both(self):
        assert hosts_reading_both_rule_files() == ["grok"]

    def test_no_warning_when_grok_is_not_installed(self, tmp_path, isolated_home):
        rules.inject_pm_rules(tmp_path, target="all")
        assert rules.duplicate_rule_file_warning(tmp_path) is None

    def test_no_warning_with_only_one_managed_file(self, tmp_path, isolated_home):
        (isolated_home / ".grok").mkdir(parents=True)
        (isolated_home / ".grok" / "config.toml").write_text("", encoding="utf-8")
        rules.inject_pm_rules(tmp_path, target="codex")  # AGENTS.md only
        assert rules.duplicate_rule_file_warning(tmp_path) is None

    def test_warns_when_grok_installed_and_both_files_managed(self, tmp_path, isolated_home):
        (isolated_home / ".grok").mkdir(parents=True)
        (isolated_home / ".grok" / "config.toml").write_text("", encoding="utf-8")
        rules.inject_pm_rules(tmp_path, target="all")

        warning = rules.duplicate_rule_file_warning(tmp_path)
        assert warning is not None
        assert warning["code"] == "duplicate_rule_file_for_host"
        assert "Grok Build" in warning["message"]
        assert "AGENTS.md" in warning["message"] and "CLAUDE.md" in warning["message"]
        assert warning["remediation"]

    def test_pm_status_surfaces_the_warning(self, tmp_path, isolated_home, monkeypatch):
        from pmlens.server import pm_init, pm_status

        (isolated_home / ".grok").mkdir(parents=True)
        (isolated_home / ".grok" / "config.toml").write_text("", encoding="utf-8")
        pm_init(project_path=str(tmp_path), project_name="dup")
        rules.inject_pm_rules(tmp_path, target="all")

        codes = [w["code"] for w in pm_status(project_path=str(tmp_path))["warnings"]]
        assert "duplicate_rule_file_for_host" in codes


# ─── Grok Build registration (TOML) ───────────────────────────────────────


@pytest.fixture
def fake_grok_config(tmp_path, monkeypatch):
    """Redirect installer._grok_config_path at tmp_path (file NOT created)."""
    config_path = tmp_path / ".grok" / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("pmlens.installer._grok_config_path", lambda: config_path)
    return config_path


@pytest.fixture
def resolved_binary(monkeypatch):
    monkeypatch.setattr("pmlens.installer._resolve_pm_server_path", lambda: Path("/usr/bin/pmlens"))
    return Path("/usr/bin/pmlens")


class TestInstallGrok:
    def test_skipped_when_config_absent(self, fake_grok_config):
        result = installer.install_grok()
        assert result.target == "grok"
        assert result.status == "skipped"
        assert "not installed" in result.message
        assert not fake_grok_config.exists()

    def test_registers_under_mcp_servers(self, fake_grok_config, resolved_binary):
        fake_grok_config.write_text('[cli]\ninstaller = "internal"\n', encoding="utf-8")

        result = installer.install_grok()

        assert result.status == "installed"
        doc = tomlkit.parse(fake_grok_config.read_text(encoding="utf-8"))
        assert str(doc["mcp_servers"]["pmlens"]["command"]) == str(resolved_binary)
        assert list(doc["mcp_servers"]["pmlens"]["args"]) == ["serve"]
        # Grok uses the same snake_case key as Codex, not Cursor's camelCase.
        assert "mcpServers" not in doc
        # The user's own settings survive.
        assert str(doc["cli"]["installer"]) == "internal"

    def test_second_install_is_idempotent(self, fake_grok_config, resolved_binary):
        fake_grok_config.write_text("", encoding="utf-8")
        installer.install_grok()
        again = installer.install_grok()
        assert again.status == "already_registered"

    def test_dry_run_writes_nothing(self, fake_grok_config, resolved_binary):
        fake_grok_config.write_text("# stub\n", encoding="utf-8")
        result = installer.install_grok(dry_run=True)
        assert result.is_dry_run is True
        assert "would " in result.message.lower()
        assert fake_grok_config.read_text(encoding="utf-8") == "# stub\n"
        assert not list(fake_grok_config.parent.glob("*.bak.*"))

    def test_uninstall_preserves_user_subtables(self, fake_grok_config, resolved_binary):
        fake_grok_config.write_text(
            textwrap.dedent("""
                [mcp_servers.pmlens]
                command = "/usr/bin/pmlens"
                args = ["serve"]
                startup_timeout_sec = 30

                [mcp_servers.pmlens.tools.pm_init]
                approval_mode = "approve"
            """).lstrip(),
            encoding="utf-8",
        )
        result = installer.uninstall_grok()
        assert result.status == "uninstalled"
        doc = tomlkit.parse(fake_grok_config.read_text(encoding="utf-8"))
        assert "command" not in doc["mcp_servers"]["pmlens"]
        assert doc["mcp_servers"]["pmlens"]["tools"]["pm_init"]["approval_mode"] == "approve"


# ─── Cursor registration (JSON) ───────────────────────────────────────────


@pytest.fixture
def fake_cursor_config(tmp_path, monkeypatch):
    """Redirect Cursor's paths at tmp_path. The DIRECTORY exists, the file does not."""
    config_path = tmp_path / ".cursor" / "mcp.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("pmlens.installer._cursor_config_path", lambda: config_path)
    monkeypatch.setattr("pmlens.installer._cursor_config_dir", lambda: config_path.parent)
    return config_path


class TestInstallCursor:
    def test_skipped_when_cursor_directory_absent(self, tmp_path, monkeypatch):
        missing = tmp_path / "nope" / "mcp.json"
        monkeypatch.setattr("pmlens.installer._cursor_config_path", lambda: missing)
        monkeypatch.setattr("pmlens.installer._cursor_config_dir", lambda: missing.parent)
        result = installer.install_cursor()
        assert result.status == "skipped"
        assert not missing.exists()

    def test_creates_mcp_json_when_directory_exists(self, fake_cursor_config, resolved_binary):
        """An installed Cursor may have ~/.cursor but no mcp.json yet.

        Keying "installed?" on the FILE would refuse to register on a perfectly
        good Cursor install, so the directory is the marker.
        """
        assert not fake_cursor_config.exists()
        result = installer.install_cursor()

        assert result.status == "installed"
        doc = json.loads(fake_cursor_config.read_text(encoding="utf-8"))
        entry = doc["mcpServers"]["pmlens"]
        assert entry["command"] == str(resolved_binary)
        assert entry["args"] == ["serve"]
        # Cursor documents `type` as required for stdio, unlike Claude Code.
        assert entry["type"] == "stdio"

    def test_empty_file_is_not_a_parse_error(self, fake_cursor_config, resolved_binary):
        """A 0-byte mcp.json is a real state on real machines; json.loads('')
        raises, and treating that as corruption would refuse to register."""
        fake_cursor_config.write_text("", encoding="utf-8")
        result = installer.install_cursor()
        assert result.status == "installed"
        assert json.loads(fake_cursor_config.read_text(encoding="utf-8"))["mcpServers"]["pmlens"]

    def test_malformed_json_is_refused_not_overwritten(self, fake_cursor_config, resolved_binary):
        original = '{"mcpServers": {,,,'
        fake_cursor_config.write_text(original, encoding="utf-8")

        result = installer.install_cursor()

        assert result.status == "failed"
        assert "not valid JSON" in result.message
        assert fake_cursor_config.read_text(encoding="utf-8") == original, (
            "a file we could not parse must never be rewritten"
        )

    def test_other_servers_and_user_keys_survive(self, fake_cursor_config, resolved_binary):
        fake_cursor_config.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "other": {"command": "other-server"},
                        "pmlens": {"command": "stale", "myCustomKey": 42},
                    }
                }
            ),
            encoding="utf-8",
        )
        installer.install_cursor()

        doc = json.loads(fake_cursor_config.read_text(encoding="utf-8"))
        assert doc["mcpServers"]["other"] == {"command": "other-server"}
        assert doc["mcpServers"]["pmlens"]["command"] == str(resolved_binary)
        assert doc["mcpServers"]["pmlens"]["myCustomKey"] == 42

    def test_second_install_is_idempotent(self, fake_cursor_config, resolved_binary):
        installer.install_cursor()
        assert installer.install_cursor().status == "already_registered"

    def test_dry_run_writes_nothing(self, fake_cursor_config, resolved_binary):
        result = installer.install_cursor(dry_run=True)
        assert result.is_dry_run is True
        assert "would " in result.message.lower()
        assert not fake_cursor_config.exists()

    def test_uninstall_removes_entry_and_keeps_others(self, fake_cursor_config, resolved_binary):
        fake_cursor_config.write_text(
            json.dumps({"mcpServers": {"other": {"command": "x"}}}), encoding="utf-8"
        )
        installer.install_cursor()

        result = installer.uninstall_cursor()

        assert result.status == "uninstalled"
        doc = json.loads(fake_cursor_config.read_text(encoding="utf-8"))
        assert "pmlens" not in doc["mcpServers"]
        assert doc["mcpServers"]["other"] == {"command": "x"}

    def test_uninstall_preserves_user_added_keys(self, fake_cursor_config, resolved_binary):
        installer.install_cursor()
        doc = json.loads(fake_cursor_config.read_text(encoding="utf-8"))
        doc["mcpServers"]["pmlens"]["myCustomKey"] = 42
        fake_cursor_config.write_text(json.dumps(doc), encoding="utf-8")

        installer.uninstall_cursor()

        after = json.loads(fake_cursor_config.read_text(encoding="utf-8"))
        assert after["mcpServers"]["pmlens"] == {"myCustomKey": 42}


# ─── Cross-host isolation ─────────────────────────────────────────────────


class TestCrossHostIsolation:
    """Registering with one host must not disturb any other host's config.

    Nothing asserted this before PMSERV-165, and it is the invariant with the
    highest cost of being wrong: these are files the user's editors depend on.
    """

    @pytest.fixture
    def all_host_configs(self, tmp_path, monkeypatch):
        codex = tmp_path / ".codex" / "config.toml"
        grok = tmp_path / ".grok" / "config.toml"
        cursor = tmp_path / ".cursor" / "mcp.json"
        for path, body in (
            (codex, '[cli]\nmodel = "gpt-5"\n'),
            (grok, '[cli]\ninstaller = "internal"\n'),
            (cursor, json.dumps({"mcpServers": {"other": {"command": "x"}}})),
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
        monkeypatch.setattr("pmlens.installer._codex_config_path", lambda: codex)
        monkeypatch.setattr("pmlens.installer._grok_config_path", lambda: grok)
        monkeypatch.setattr("pmlens.installer._cursor_config_path", lambda: cursor)
        monkeypatch.setattr("pmlens.installer._cursor_config_dir", lambda: cursor.parent)
        return {"codex": codex, "grok": grok, "cursor": cursor}

    @pytest.mark.parametrize("target", ["codex", "grok", "cursor"])
    def test_installing_one_host_leaves_the_others_byte_identical(
        self, target, all_host_configs, resolved_binary
    ):
        before = {name: path.read_bytes() for name, path in all_host_configs.items()}

        result = installer.install(target=target)
        assert result.results[0].status == "installed"

        for name, path in all_host_configs.items():
            if name == target:
                assert path.read_bytes() != before[name], f"{target} should have been written"
            else:
                assert path.read_bytes() == before[name], (
                    f"installing {target} modified {name}'s config"
                )

    def test_no_host_writes_a_backup_into_another_hosts_directory(
        self, all_host_configs, resolved_binary
    ):
        installer.install(target="grok")
        for name, path in all_host_configs.items():
            strays = list(path.parent.glob(f"{path.name}.bak.*"))
            if name == "grok":
                assert strays, "grok must back up before writing"
            else:
                assert not strays, f"installing grok left a backup in {name}'s directory"
