"""Smoke tests for pm_server.rules (PMSERV-043).

Verifies the new import path works and that pm_server.claudemd remains
a transparent re-export shim. Functional behavior is covered by the
existing tests/test_claudemd.py — kept untouched as the strongest
backward-compatibility guarantee.
"""

from pm_server.rules import (
    BEGIN_MARKER,
    BEGIN_PATTERN,
    CLAUDEMD_TEMPLATE,
    END_MARKER,
    OTHER_SECTION_PATTERN,
    TEMPLATE_VERSION,
    ensure_claudemd,
    get_claudemd_status,
    update_claudemd,
)


class TestRulesModule:
    """pm_server.rules public surface (PMSERV-043)."""

    def test_template_version_is_int(self):
        assert isinstance(TEMPLATE_VERSION, int)
        assert TEMPLATE_VERSION >= 1

    def test_template_version_unchanged_at_v7(self):
        # ADR-008 4th-tier guard: PMSERV-043 keeps v7
        assert TEMPLATE_VERSION == 7

    def test_markers_are_strings(self):
        assert "pm-server:begin" in BEGIN_MARKER
        assert "pm-server:end" in END_MARKER

    def test_template_contains_markers(self):
        assert "<!-- pm-server:begin v={version} -->" in CLAUDEMD_TEMPLATE
        assert "<!-- pm-server:end -->" in CLAUDEMD_TEMPLATE

    def test_begin_pattern_matches_marker(self):
        match = BEGIN_PATTERN.search("<!-- pm-server:begin v=7 -->")
        assert match is not None
        assert match.group(1) == "7"

    def test_other_section_pattern_finds_named_sections(self):
        text = "<!-- foo:begin -->\n<!-- bar:begin -->"
        names = OTHER_SECTION_PATTERN.findall(text)
        assert "foo" in names
        assert "bar" in names

    def test_get_claudemd_status_returns_required_keys(self, tmp_path):
        result = get_claudemd_status(tmp_path)
        for key in ("exists", "has_pm_section", "version", "up_to_date", "other_rule_sections"):
            assert key in result

    def test_ensure_claudemd_creates_file(self, tmp_path):
        message = ensure_claudemd(tmp_path)
        assert (tmp_path / "CLAUDE.md").exists()
        assert "created" in message.lower() or "appended" in message.lower()

    def test_update_claudemd_creates_or_replaces(self, tmp_path):
        message = update_claudemd(tmp_path)
        assert (tmp_path / "CLAUDE.md").exists()
        assert isinstance(message, str)


class TestBackwardCompatShim:
    """pm_server.claudemd is a transparent re-export of pm_server.rules (PMSERV-043)."""

    def test_shim_re_exports_same_function_objects(self):
        import pm_server.claudemd as old_path
        import pm_server.rules as new_path

        assert old_path.ensure_claudemd is new_path.ensure_claudemd
        assert old_path.update_claudemd is new_path.update_claudemd
        assert old_path.get_claudemd_status is new_path.get_claudemd_status

    def test_shim_re_exports_same_constants(self):
        import pm_server.claudemd as old_path
        import pm_server.rules as new_path

        assert old_path.TEMPLATE_VERSION is new_path.TEMPLATE_VERSION
        assert old_path.CLAUDEMD_TEMPLATE is new_path.CLAUDEMD_TEMPLATE
        assert old_path.BEGIN_MARKER is new_path.BEGIN_MARKER
        assert old_path.END_MARKER is new_path.END_MARKER
        assert old_path.BEGIN_PATTERN is new_path.BEGIN_PATTERN
        assert old_path.OTHER_SECTION_PATTERN is new_path.OTHER_SECTION_PATTERN
