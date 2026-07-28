"""PMSERV-156 / ADR-045: physical ingest of auto-memory into the global index.

The v1 overlay (ADR-040) only reaches the CURRENT project, and `pm_recall`'s
cross_project branch returns before any overlay runs — so auto-memory
knowledge was structurally invisible to cross-project search. These tests pin
the ingest that closes that gap, plus the guardrails ADR-045 attaches to it.
"""

from __future__ import annotations

import sqlite3

import pytest

from pmlens import auto_memory
from pmlens.memory import AUTO_MEMORY_SOURCE, MemoryStore
from pmlens.models import Memory


def write_note(home, project_path, name: str, body: str, note_type: str = "reference") -> None:
    """Create a Claude Code auto-memory note for `project_path` under `home`."""
    d = home / ".claude" / "projects" / auto_memory.encode_project_dirname(project_path) / "memory"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(
        f"---\nname: {name.removesuffix('.md')}\n"
        f"description: test note\nmetadata:\n  type: {note_type}\n---\n\n{body}\n",
        encoding="utf-8",
    )


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Two projects, an isolated HOME, and a store wired to a global index."""
    home = tmp_path / "home"
    (home / ".claude" / "projects").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    proj_a, proj_b = tmp_path / "proj-a", tmp_path / "proj-b"
    for p in (proj_a, proj_b):
        (p / ".pm").mkdir(parents=True)
    store = MemoryStore(proj_a / ".pm" / "memory.db", global_db_path=home / ".pm" / "memory.db")
    yield home, proj_a, proj_b, store
    store.close()


def collect(project_path, home, scope="project"):
    entries, scanned, _diag = auto_memory.collect_ingest_entries(
        str(project_path), scope=scope, home=home
    )
    return entries, scanned


class TestCollect:
    def test_project_scope_sees_only_this_repo(self, env):
        home, a, b, _ = env
        write_note(home, a, "a1.md", "ALPHATOKEN lives here")
        write_note(home, b, "b1.md", "BETATOKEN lives here")
        entries, dirs = collect(a, home)
        assert [e["source_file"] for e in entries] == ["a1.md"]
        assert len(dirs) == 1

    def test_all_scope_sweeps_every_store(self, env):
        home, a, b, _ = env
        write_note(home, a, "a1.md", "ALPHATOKEN")
        write_note(home, b, "b1.md", "BETATOKEN")
        entries, dirs = collect(a, home, scope="all")
        assert sorted(e["source_file"] for e in entries) == ["a1.md", "b1.md"]
        assert len(dirs) == 2

    def test_content_is_not_truncated_for_ingest(self, env):
        """The overlay excerpts at 500 chars; indexing that excerpt would make
        anything said later in a note permanently unsearchable."""
        home, a, _b, _ = env
        tail = "NEEDLETOKEN"
        write_note(home, a, "long.md", ("x" * 2000) + " " + tail)
        entries, _ = collect(a, home)
        assert tail in entries[0]["content"]
        assert "content_truncated" not in entries[0]

    def test_memory_md_index_is_never_ingested(self, env):
        """MEMORY.md is the reverse bridge's own output — ingesting it would
        close the loop ADR-040 keeps structurally open."""
        home, a, _b, _ = env
        write_note(home, a, "real.md", "REALTOKEN")
        d = home / ".claude" / "projects" / auto_memory.encode_project_dirname(a) / "memory"
        (d / "MEMORY.md").write_text("- [Real](real.md) — pointer\n", encoding="utf-8")
        entries, _ = collect(a, home)
        assert [e["source_file"] for e in entries] == ["real.md"]

    def test_rejects_an_unknown_scope(self, env):
        home, a, _b, _ = env
        with pytest.raises(ValueError):
            auto_memory.collect_ingest_entries(str(a), scope="everything", home=home)


class TestIngest:
    def test_ingested_notes_become_cross_project_searchable(self, env):
        home, a, _b, store = env
        write_note(home, a, "a1.md", "ZEBRAFISHALPHA runbook")
        assert store.search_global_ex("ZEBRAFISHALPHA")[0] == []  # the PMSERV-156 blind spot
        entries, dirs = collect(a, home)
        result = store.ingest_auto_memory(entries, dirs)
        assert result["ingested"] == 1
        hits, _strategy = store.search_global_ex("ZEBRAFISHALPHA")
        assert len(hits) == 1
        assert hits[0]["source"] == AUTO_MEMORY_SOURCE
        assert hits[0]["source_path"].endswith("a1.md")

    def test_dry_run_reports_without_writing(self, env):
        home, a, _b, store = env
        write_note(home, a, "a1.md", "DRYTOKEN")
        entries, dirs = collect(a, home)
        assert store.ingest_auto_memory(entries, dirs, dry_run=True)["ingested"] == 1
        assert store.search_global_ex("DRYTOKEN")[0] == []

    def test_reingest_is_idempotent_by_content_hash(self, env):
        home, a, _b, store = env
        write_note(home, a, "a1.md", "STABLETOKEN")
        entries, dirs = collect(a, home)
        store.ingest_auto_memory(entries, dirs)
        again = store.ingest_auto_memory(*collect(a, home))
        assert (again["ingested"], again["unchanged"]) == (0, 1)
        assert len(store.search_global_ex("STABLETOKEN")[0]) == 1

    def test_edited_note_replaces_the_row_and_the_fts_entry(self, env):
        """Re-ingest must DELETE+INSERT: the global FTS5 table is
        external-content with only after-insert / after-delete triggers, so an
        UPDATE would leave the old text searchable and the new text missing —
        silently, with no error anywhere."""
        home, a, _b, store = env
        write_note(home, a, "a1.md", "OLDTOKEN here")
        store.ingest_auto_memory(*collect(a, home))
        write_note(home, a, "a1.md", "NEWTOKEN here")
        result = store.ingest_auto_memory(*collect(a, home))
        assert result["ingested"] == 1
        assert len(store.search_global_ex("NEWTOKEN")[0]) == 1
        assert store.search_global_ex("OLDTOKEN")[0] == [], "stale FTS row survived the re-ingest"

    def test_deleted_note_is_pruned(self, env):
        home, a, _b, store = env
        write_note(home, a, "gone.md", "GONETOKEN")
        store.ingest_auto_memory(*collect(a, home))
        d = home / ".claude" / "projects" / auto_memory.encode_project_dirname(a) / "memory"
        (d / "gone.md").unlink()
        result = store.ingest_auto_memory(*collect(a, home))
        assert result["pruned"] == 1
        assert store.search_global_ex("GONETOKEN")[0] == []

    def test_project_scoped_ingest_never_prunes_another_project(self, env):
        """Pruning is scoped to the directories actually scanned. Without that,
        a project-scoped run would see every other project's rows as 'files no
        longer present' and delete them."""
        home, a, b, store = env
        write_note(home, a, "a1.md", "ALPHATOKEN")
        write_note(home, b, "b1.md", "BETATOKEN")
        store.ingest_auto_memory(*collect(a, home, scope="all"))
        assert len(store.search_global_ex("BETATOKEN")[0]) == 1
        store.ingest_auto_memory(*collect(a, home))  # project scope only
        assert len(store.search_global_ex("BETATOKEN")[0]) == 1

    def test_ledger_rows_are_untouched_by_ingest_and_purge(self, env):
        """PMSERV-111: the project ledger stays the source of truth. Ingest
        adds derived rows beside it and purge removes only those."""
        home, a, _b, store = env
        store.save(Memory(session_id="s1", content="LEDGERTOKEN from pm_remember", project="a"))
        write_note(home, a, "a1.md", "AUTOTOKEN")
        store.ingest_auto_memory(*collect(a, home))
        assert len(store.search_global_ex("LEDGERTOKEN")[0]) == 1
        purged = store.purge_auto_memory(None)
        assert purged["purged"] == 1
        assert store.search_global_ex("AUTOTOKEN")[0] == []
        assert len(store.search_global_ex("LEDGERTOKEN")[0]) == 1
        # The project's own ledger table is never written by ingest.
        assert store.get_stats()["total_memories"] == 1

    def test_purge_can_be_limited_to_one_project(self, env):
        home, a, b, store = env
        write_note(home, a, "a1.md", "ALPHATOKEN")
        write_note(home, b, "b1.md", "BETATOKEN")
        store.ingest_auto_memory(*collect(a, home, scope="all"))
        _entries, dirs_a = collect(a, home)
        assert store.purge_auto_memory(dirs_a)["purged"] == 1
        assert store.search_global_ex("ALPHATOKEN")[0] == []
        assert len(store.search_global_ex("BETATOKEN")[0]) == 1


class TestMigration:
    def test_ingest_migrates_a_pre_pmserv156_global_index(self, env):
        """Existing global indexes have no provenance columns. Ingest must add
        them without disturbing the rows already there."""
        home, a, _b, store = env
        store.save(Memory(session_id="s1", content="EXISTINGTOKEN", project="a"))
        gdb = home / ".pm" / "memory.db"
        conn = sqlite3.connect(gdb)
        for col in ("source", "source_path", "content_hash"):
            conn.execute(f"ALTER TABLE memory_index DROP COLUMN {col}")
        conn.commit()
        cols = {r[1] for r in conn.execute("PRAGMA table_info(memory_index)")}
        conn.close()
        assert "source" not in cols  # genuinely un-migrated

        # A read on the un-migrated DB must not raise (ingest is what migrates).
        assert len(store.search_global_ex("EXISTINGTOKEN")[0]) == 1

        write_note(home, a, "a1.md", "NEWLYINDEXED")
        store.ingest_auto_memory(*collect(a, home))
        hits, _ = store.search_global_ex("EXISTINGTOKEN")
        assert hits[0]["source"] == "pm", "pre-existing rows must default to the ledger source"
        assert len(store.search_global_ex("NEWLYINDEXED")[0]) == 1


class TestServerTool:
    def _setup(self, tmp_path, monkeypatch, home):
        from pmlens.models import Project
        from pmlens.storage import _save_project

        pm_path = tmp_path / ".pm"
        pm_path.mkdir(parents=True, exist_ok=True)
        (pm_path / "daily").mkdir(exist_ok=True)
        _save_project(pm_path, Project(name="proj", display_name="proj"))
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.chdir(tmp_path)

    def test_tool_defaults_to_project_scope_and_dry_run(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        (home / ".claude" / "projects").mkdir(parents=True)
        self._setup(tmp_path / "proj", monkeypatch, home)
        from pmlens.server import pm_memory_ingest

        write_note(home, tmp_path / "proj", "n.md", "TOOLTOKEN")
        result = pm_memory_ingest()
        assert result["scope"] == "project"
        assert result["dry_run"] is True
        assert result["notes_found"] == 1
        assert "warnings" not in result

    def test_all_scope_warns_about_the_blast_radius(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        (home / ".claude" / "projects").mkdir(parents=True)
        self._setup(tmp_path / "proj", monkeypatch, home)
        from pmlens.server import pm_memory_ingest

        write_note(home, tmp_path / "proj", "n.md", "TOOLTOKEN")
        write_note(home, tmp_path / "other", "o.md", "OTHERTOKEN")
        result = pm_memory_ingest(scope="all")
        codes = [w["code"] for w in result.get("warnings", [])]
        assert "auto_memory_ingest_blocked_foreign" in codes
        assert result["would_block"] is True
        assert result["notes_found"] == 2

    def test_unknown_scope_is_rejected(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        (home / ".claude" / "projects").mkdir(parents=True)
        self._setup(tmp_path / "proj", monkeypatch, home)
        from pmlens.server import pm_memory_ingest

        assert pm_memory_ingest(scope="everything")["status"] == "error"

    def test_ingest_tool_is_hidden_from_the_lens_viewer(self):
        """Ingest writes, so it must never register under PM_LENS=1 (RO
        invariant, PMSERV-144)."""
        from pmlens.server import RO_ALLOWLIST

        assert "pm_memory_ingest" not in RO_ALLOWLIST


# ─── Adversarial-review regressions (PMSERV-156 hardening) ───────────────


class TestForeignGate:
    """The safety boundary is what was COLLECTED, not the scope parameter:
    an auto_memory_path override kept scope="project" while ingesting an
    arbitrary directory, and the scope-keyed warning never fired."""

    def _setup(self, tmp_path, monkeypatch):
        from pmlens.models import Project
        from pmlens.storage import _save_project

        home = tmp_path / "home"
        (home / ".claude" / "projects").mkdir(parents=True)
        proj = tmp_path / "proj"
        pm_path = proj / ".pm"
        pm_path.mkdir(parents=True)
        (pm_path / "daily").mkdir()
        _save_project(pm_path, Project(name="proj", display_name="proj"))
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.chdir(proj)
        return home, proj

    def test_scope_all_real_run_is_blocked_without_force(self, tmp_path, monkeypatch):
        home, proj = self._setup(tmp_path, monkeypatch)
        from pmlens.server import pm_memory_ingest

        write_note(home, proj, "mine.md", "MINETOKEN")
        write_note(home, tmp_path / "other", "theirs.md", "THEIRSTOKEN")
        result = pm_memory_ingest(scope="all", dry_run=False)
        assert result["blocked"] is True
        assert result["ingested"] == 0
        assert result["foreign_projects"]
        codes = [w["code"] for w in result["warnings"]]
        assert codes == ["auto_memory_ingest_blocked_foreign"]
        # All-or-nothing: even this project's own note was not written.
        assert not (home / ".pm" / "memory.db").exists()

    def test_force_executes_and_keeps_the_post_hoc_warning(self, tmp_path, monkeypatch):
        home, proj = self._setup(tmp_path, monkeypatch)
        from pmlens.server import pm_memory_ingest

        write_note(home, tmp_path / "other", "theirs.md", "THEIRSTOKEN")
        result = pm_memory_ingest(scope="all", dry_run=False, force=True)
        assert result.get("blocked") is not True
        assert result["ingested"] == 1
        codes = [w["code"] for w in result["warnings"]]
        assert "auto_memory_ingested_foreign" in codes
        assert "auto_memory_ingest_blocked_foreign" not in codes

    def test_auto_memory_path_override_is_gated(self, tmp_path, monkeypatch):
        """The confirmed bypass: scope="project" + auto_memory_path pointing
        at an arbitrary directory ingested it with no warning at all."""
        home, proj = self._setup(tmp_path, monkeypatch)
        from pmlens.server import pm_memory_ingest

        outside = tmp_path / "private-notes"
        outside.mkdir()
        (outside / "secret.md").write_text("---\nname: s\n---\n\nSECRETTOKEN\n", encoding="utf-8")
        result = pm_memory_ingest(scope="project", dry_run=False, auto_memory_path=str(outside))
        assert result["blocked"] is True
        assert result["ingested"] == 0
        assert not (home / ".pm" / "memory.db").exists()

    def test_own_project_content_is_never_gated(self, tmp_path, monkeypatch):
        """scope="all" with only this project's own store present collects
        nothing foreign — fact-based gating must not fire on scope alone."""
        home, proj = self._setup(tmp_path, monkeypatch)
        from pmlens.server import pm_memory_ingest

        write_note(home, proj, "mine.md", "MINETOKEN")
        result = pm_memory_ingest(scope="all", dry_run=False)
        assert result.get("blocked") is not True
        assert result["ingested"] == 1
        assert "warnings" not in result

    def test_dry_run_predicts_the_block_without_writing(self, tmp_path, monkeypatch):
        home, proj = self._setup(tmp_path, monkeypatch)
        from pmlens.server import pm_memory_ingest

        write_note(home, tmp_path / "other", "theirs.md", "THEIRSTOKEN")
        result = pm_memory_ingest(scope="all")  # dry_run default
        assert result["would_block"] is True
        assert not (home / ".pm" / "memory.db").exists()
        forced = pm_memory_ingest(scope="all", force=True)
        assert forced.get("would_block") is not True
        assert [w["code"] for w in forced["warnings"]] == ["auto_memory_ingested_foreign"]


class TestDryRunPurity:
    def test_dry_run_does_not_create_the_global_db(self, env):
        """The old dry_run created the DB, flipped it to WAL and ALTERed the
        schema before ever checking the flag (adversarial review, two lenses
        independently)."""
        home, a, _b, store = env
        write_note(home, a, "a1.md", "PUREDRYTOKEN")
        result = store.ingest_auto_memory(*collect(a, home), dry_run=True)
        assert result["ingested"] == 1
        assert not (home / ".pm" / "memory.db").exists()

    def test_dry_run_does_not_migrate_an_old_schema(self, env):
        home, a, _b, store = env
        store.save(Memory(session_id="s1", content="OLDROW", project="a"))
        gdb = home / ".pm" / "memory.db"
        conn = sqlite3.connect(gdb)
        for col in ("source", "source_path", "content_hash"):
            conn.execute(f"ALTER TABLE memory_index DROP COLUMN {col}")
        conn.commit()
        conn.close()
        write_note(home, a, "a1.md", "MIGRATIONTOKEN")
        result = store.ingest_auto_memory(*collect(a, home), dry_run=True)
        assert result["ingested"] == 1  # counted as new — no provenance rows exist
        cols = {r[1] for r in sqlite3.connect(gdb).execute("PRAGMA table_info(memory_index)")}
        assert "source" not in cols, "dry_run migrated the schema"


class TestScanFailureSafety:
    def test_unreadable_dir_is_skipped_not_pruned(self, env):
        """pathlib's glob() swallows PermissionError and returns [] — the old
        collector then listed the directory as scanned, and every previously
        indexed row under it was pruned as stale (confirmed: 2 rows -> 0,
        no error). os.listdir raises honestly; the dir must leave scanning
        as UNREADABLE, not as empty."""
        import os as _os

        home, a, _b, store = env
        write_note(home, a, "keep.md", "KEEPTOKEN")
        store.ingest_auto_memory(*collect(a, home))
        assert len(store.search_global_ex("KEEPTOKEN")[0]) == 1
        d = home / ".claude" / "projects" / auto_memory.encode_project_dirname(a) / "memory"
        mode = d.stat().st_mode
        _os.chmod(d, 0o000)
        try:
            entries, scanned, diag = auto_memory.collect_ingest_entries(str(a), home=home)
            assert entries == []
            assert scanned == []
            assert diag["unreadable_dirs"]
            result = store.ingest_auto_memory(entries, scanned)
            assert result["pruned"] == 0
        finally:
            _os.chmod(d, mode)
        assert len(store.search_global_ex("KEEPTOKEN")[0]) == 1

    def test_one_pathological_file_does_not_abort_the_sweep(self, env, monkeypatch):
        home, a, _b, _store = env
        write_note(home, a, "good.md", "GOODTOKEN")
        write_note(home, a, "bad.md", "BADTOKEN")

        real_parse = auto_memory.parse_auto_memory_file

        def exploding(path, **kwargs):
            if path.name == "bad.md":
                raise RecursionError("billion laughs")
            return real_parse(path, **kwargs)

        monkeypatch.setattr(auto_memory, "parse_auto_memory_file", exploding)
        entries, _scanned, diag = auto_memory.collect_ingest_entries(str(a), home=home)
        assert [e["source_file"] for e in entries] == ["good.md"]
        assert len(diag["skipped_files"]) == 1


class TestSymlinkedRoot:
    def test_symlinked_project_root_stays_idempotent(self, tmp_path, monkeypatch):
        """Claude Code encodes the path as IT sees it (possibly through a
        symlink); the store compared resolved scan dirs against unresolved
        stored paths, so every re-ingest duplicated every note and pruning
        never fired (adversarial review, confirmed via /var vs /private/var)."""
        home = tmp_path / "home"
        (home / ".claude" / "projects").mkdir(parents=True)
        monkeypatch.setenv("HOME", str(home))
        real = tmp_path / "real-proj"
        (real / ".pm").mkdir(parents=True)
        link = tmp_path / "link-proj"
        link.symlink_to(real, target_is_directory=True)

        # CC created the store under the SYMLINK spelling of the root.
        d = home / ".claude" / "projects" / auto_memory.encode_project_dirname(link) / "memory"
        d.mkdir(parents=True)
        (d / "n.md").write_text("---\nname: n\n---\n\nSYMLINKTOKEN\n", encoding="utf-8")

        store = MemoryStore(real / ".pm" / "memory.db", global_db_path=home / ".pm" / "memory.db")
        try:

            def run():
                entries, scanned, _diag = auto_memory.collect_ingest_entries(str(link), home=home)
                return store.ingest_auto_memory(entries, scanned)

            first = run()
            assert first["ingested"] == 1, "locator missed the symlink-spelled store"
            second = run()
            assert (second["ingested"], second["unchanged"]) == (0, 1)
            assert len(store.search_global_ex("SYMLINKTOKEN")[0]) == 1
            (d / "n.md").unlink()
            third = run()
            assert third["pruned"] == 1
            assert store.search_global_ex("SYMLINKTOKEN")[0] == []
        finally:
            store.close()


class TestPurgeContract:
    def test_purge_reports_projects_and_supports_dry_run(self, env):
        home, a, b, store = env
        write_note(home, a, "a1.md", "ALPHATOKEN")
        write_note(home, b, "b1.md", "BETATOKEN")
        store.ingest_auto_memory(*collect(a, home, scope="all"))
        preview = store.purge_auto_memory(None, dry_run=True)
        assert preview["would_purge"] == 2
        assert len(preview["projects"]) == 2
        assert len(store.search_global_ex("ALPHATOKEN")[0]) == 1  # nothing deleted
        real = store.purge_auto_memory(None)
        assert real["purged"] == 2

    def test_purge_by_project_root_survives_a_vanished_dir(self, env):
        """The source directory can disappear (encoding drift, deleted repo);
        rows still carry project_path, so a project-scoped purge must keep
        working instead of returning purged:0 as success (two lenses
        independently)."""
        import shutil as _shutil

        home, a, _b, store = env
        write_note(home, a, "a1.md", "VANISHTOKEN")
        store.ingest_auto_memory(*collect(a, home))
        d = home / ".claude" / "projects" / auto_memory.encode_project_dirname(a) / "memory"
        _shutil.rmtree(d.parent)
        entries, scanned = collect(a, home)
        assert scanned == []  # the dir is gone — dir-based targeting finds nothing
        result = store.purge_auto_memory(scanned, project_root=a)
        assert result["purged"] == 1
        assert store.search_global_ex("VANISHTOKEN")[0] == []

    def test_purge_tool_reports_scope_all_removal(self, tmp_path, monkeypatch):
        from pmlens.models import Project
        from pmlens.storage import _save_project

        home = tmp_path / "home"
        (home / ".claude" / "projects").mkdir(parents=True)
        proj = tmp_path / "proj"
        (proj / ".pm" / "daily").mkdir(parents=True)
        _save_project(proj / ".pm", Project(name="proj", display_name="proj"))
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.chdir(proj)
        from pmlens.server import pm_memory_ingest

        write_note(home, proj, "mine.md", "MINETOKEN")
        write_note(home, tmp_path / "other", "theirs.md", "THEIRSTOKEN")
        pm_memory_ingest(scope="all", dry_run=False, force=True)
        result = pm_memory_ingest(scope="all", purge=True, dry_run=False)
        assert result["purged"] == 2
        assert len(result["projects"]) == 2
        codes = [w["code"] for w in result.get("warnings", [])]
        assert "auto_memory_purged_all_projects" in codes


#: A note body large enough to spill onto SQLite overflow pages. That is the
#: whole condition under which purged text survives — measured, not assumed:
#: a row that fits in one page is rewritten in place and the WAL checkpoint
#: copies the post-delete version over it, leaving nothing. Overflow pages are
#: released to the freelist WITHOUT being rewritten, so their contents stay in
#: the file. Free-form auto-memory notes routinely clear this bar.
_BIG_NOTE_FILLER = "residue-payload-" * 4096  # ~64 KB


class TestPurgeVacuum:
    """PMSERV-171: purge can reclaim the bytes, but only when asked.

    Scope, stated precisely because the imprecise version is tempting: a
    DELETE does not generally leave readable text behind in this store. In WAL
    mode the modified page is checkpointed over the original, so small rows
    vanish for free. What survives is the *overflow* content of large rows,
    which is freed without being rewritten — and that is exactly the shape of
    an auto-memory note someone pasted a secret into.
    """

    def _residue_blocks(self, store) -> int:
        """How many payload blocks are still readable in the index file + WAL."""
        blob = b""
        for suffix in ("", "-wal"):
            path = store.global_db_path.with_name(store.global_db_path.name + suffix)
            if path.exists():
                blob += path.read_bytes()
        return blob.count(b"residue-payload-" * 64)

    def test_default_purge_leaves_the_overflow_bytes_and_says_nothing(self, env):
        """No vacuum key at all unless asked — the response shape is unchanged
        for every existing caller — and the residue this feature exists for is
        asserted rather than assumed."""
        home, a, _b, store = env
        write_note(home, a, "a1.md", _BIG_NOTE_FILLER)
        store.ingest_auto_memory(*collect(a, home))

        result = store.purge_auto_memory(None)
        assert result["purged"] == 1
        assert "vacuumed" not in result
        assert "vacuum_error" not in result
        assert store.search_global_ex("residue")[0] == []  # gone from the index
        assert self._residue_blocks(store) > 0, (
            "a large purged note left no residue at all — if SQLite's behaviour "
            "changed, vacuum=True may no longer be solving anything and this "
            "feature's justification should be re-checked, not the assert relaxed"
        )

    def test_vacuum_removes_the_residual_plaintext(self, env):
        home, a, _b, store = env
        write_note(home, a, "a1.md", _BIG_NOTE_FILLER)
        store.ingest_auto_memory(*collect(a, home))

        result = store.purge_auto_memory(None, vacuum=True)
        assert result["purged"] == 1
        assert result["vacuumed"] is True
        assert "vacuum_error" not in result
        assert store.search_global_ex("residue")[0] == []
        assert self._residue_blocks(store) == 0, (
            "vacuum=True must leave no readable copy in the index file or its "
            "WAL sidecar — truncating the WAL is the half that is easy to omit"
        )

    def test_dry_run_never_vacuums(self, env):
        """dry_run is a pure preview (PMSERV-156). vacuum must not break that:
        VACUUM rewrites the file, which is the least pure thing here."""
        home, a, _b, store = env
        write_note(home, a, "a1.md", _BIG_NOTE_FILLER)
        store.ingest_auto_memory(*collect(a, home))

        result = store.purge_auto_memory(None, dry_run=True, vacuum=True)
        assert result["would_purge"] == 1
        assert "vacuumed" not in result
        # Nothing was deleted, so the row must still be there.
        assert len(store.search_global_ex("residue")[0]) == 1

    def test_no_match_does_not_take_an_exclusive_lock(self, env):
        """Nothing was deleted, so there is nothing to reclaim. Running VACUUM
        anyway would rewrite the whole file for no reason and could fail on a
        concurrent session."""
        home, a, _b, store = env
        result = store.purge_auto_memory(None, vacuum=True)
        assert result["purged"] == 0
        assert "vacuumed" not in result

    def test_tool_exposes_vacuum(self, tmp_path, monkeypatch):
        from pmlens.models import Project
        from pmlens.storage import _save_project

        home = tmp_path / "home"
        (home / ".claude" / "projects").mkdir(parents=True)
        proj = tmp_path / "proj"
        (proj / ".pm" / "daily").mkdir(parents=True)
        _save_project(proj / ".pm", Project(name="proj", display_name="proj"))
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.chdir(proj)
        from pmlens.server import pm_memory_ingest

        write_note(home, proj, "mine.md", "TOOLVACUUMTOKEN")
        pm_memory_ingest(dry_run=False)
        result = pm_memory_ingest(purge=True, dry_run=False, vacuum=True)
        assert result["purged"] == 1
        assert result["vacuumed"] is True


#: A syntactically valid AWS access key id. Fake, but it matches the anchored
#: `AKIA[0-9A-Z]{16}` pattern, which is the point.
_FAKE_AWS_KEY = "AKIAIOSFODNN7EXAMPLE"


class TestSecretRedactionGate:
    """PMSERV-168: the content half of the ingest gate.

    ADR-045's fact-based gate asks WHOSE notes are being published. It says
    nothing about what is in them — so a credential pasted into one repo's
    auto-memory became searchable from every other repo the moment ingest ran.
    """

    def test_secrets_are_scrubbed_before_indexing(self, env):
        home, a, _b, store = env
        write_note(home, a, "creds.md", f"deploy runbook, key={_FAKE_AWS_KEY} rotate quarterly")
        entries, scanned, diagnostics = auto_memory.collect_ingest_entries(
            str(a), scope="project", home=home
        )
        assert _FAKE_AWS_KEY not in entries[0]["content"]
        assert "<REDACTED:secret>" in entries[0]["content"]
        assert diagnostics["redacted_files"][0]["by_category"] == {"secret": 1}

        store.ingest_auto_memory(entries, scanned)
        assert store.search_global_ex("AKIAIOSFODNN7EXAMPLE")[0] == [], (
            "the credential is searchable from every project — the exact "
            "cross-project exposure this gate exists to prevent"
        )
        # The surrounding note stays useful; this is a scrub, not a drop.
        assert len(store.search_global_ex("runbook")[0]) == 1

    def test_the_report_never_echoes_the_secret(self, env):
        """A report that quotes the match to prove it found one has published
        it again — in a field that gets pasted into chat."""
        home, a, _b, _store = env
        write_note(home, a, "creds.md", f"key={_FAKE_AWS_KEY}")
        _entries, _scanned, diagnostics = auto_memory.collect_ingest_entries(
            str(a), scope="project", home=home
        )
        assert _FAKE_AWS_KEY not in repr(diagnostics)

    def test_scrub_happens_before_the_content_hash(self, env):
        """Hash the raw body and the idempotency key describes something other
        than what was stored, so a re-ingest looks changed forever."""
        home, a, _b, store = env
        write_note(home, a, "creds.md", f"key={_FAKE_AWS_KEY}")
        store.ingest_auto_memory(*collect(a, home))
        again = store.ingest_auto_memory(*collect(a, home))
        assert (again["ingested"], again["unchanged"]) == (0, 1)

    def test_ordinary_identifiers_survive(self, env):
        """Only the `secret` category is scrubbed. An index on the user's own
        machine that has lost its paths and ticket refs returns hits nobody can
        act on — and those patterns match ordinary prose."""
        home, a, _b, _store = env
        write_note(
            home,
            a,
            "notes.md",
            "PMSERV-168 in /Users/dev/proj, host 10.0.0.1, ping dev@example.com",
        )
        entries, _scanned, diagnostics = auto_memory.collect_ingest_entries(
            str(a), scope="project", home=home
        )
        body = entries[0]["content"]
        for keep in ("PMSERV-168", "/Users/dev/proj", "10.0.0.1", "dev@example.com"):
            assert keep in body, f"{keep!r} was scrubbed — the index loses its usefulness"
        assert diagnostics["redacted_files"] == []

    def test_redaction_can_be_turned_off(self, env):
        home, a, _b, _store = env
        write_note(home, a, "creds.md", f"key={_FAKE_AWS_KEY}")
        entries, _scanned, diagnostics = auto_memory.collect_ingest_entries(
            str(a), scope="project", home=home, redact_secrets_enabled=False
        )
        assert _FAKE_AWS_KEY in entries[0]["content"]
        assert diagnostics["redacted_files"] == []

    def test_tool_warns_and_defaults_to_redacting(self, tmp_path, monkeypatch):
        from pmlens.models import Project
        from pmlens.storage import _save_project

        home = tmp_path / "home"
        (home / ".claude" / "projects").mkdir(parents=True)
        proj = tmp_path / "proj"
        (proj / ".pm" / "daily").mkdir(parents=True)
        _save_project(proj / ".pm", Project(name="proj", display_name="proj"))
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.chdir(proj)
        from pmlens.server import pm_memory_ingest

        write_note(home, proj, "creds.md", f"key={_FAKE_AWS_KEY}")
        result = pm_memory_ingest(dry_run=False)
        codes = [w["code"] for w in result.get("warnings", [])]
        assert "auto_memory_secrets_redacted" in codes
        assert _FAKE_AWS_KEY not in repr(result)


class TestSizeCaps:
    """PMSERV-169: bound what one note, and one sweep, can pull in.

    The caps are deliberately SKIP-not-truncate. A truncated note indexes as a
    row that looks complete and silently loses whatever came after the cut,
    which is the same class of failure ingest exists to fix.
    """

    def _big_note(self, home, project, name, marker):
        """A note comfortably over the per-note cap."""
        write_note(home, project, name, marker + " " + ("x" * (auto_memory._MAX_NOTE_BYTES + 1)))

    def test_oversized_note_is_skipped_and_reported(self, env):
        home, a, _b, _store = env
        write_note(home, a, "small.md", "SMALLTOKEN")
        self._big_note(home, a, "huge.md", "HUGETOKEN")

        entries, _scanned, diagnostics = auto_memory.collect_ingest_entries(
            str(a), scope="project", home=home
        )
        assert [e["source_file"] for e in entries] == ["small.md"]
        assert len(diagnostics["oversized_files"]) == 1
        assert diagnostics["oversized_files"][0]["path"].endswith("huge.md")
        assert diagnostics["oversized_files"][0]["bytes"] > auto_memory._MAX_NOTE_BYTES

    def test_oversized_note_is_never_truncated_into_the_index(self, env):
        home, a, _b, store = env
        self._big_note(home, a, "huge.md", "HUGETOKEN")
        store.ingest_auto_memory(*collect(a, home))
        assert store.search_global_ex("HUGETOKEN")[0] == [], (
            "an over-cap note must be absent, not partially indexed — a partial "
            "row looks complete and hides everything after the cut"
        )

    def test_sweep_budget_stops_reading_and_reports_the_remainder(self, env, monkeypatch):
        home, a, _b, _store = env
        monkeypatch.setattr(auto_memory, "_MAX_INGEST_BYTES", 4096)
        for i in range(6):
            write_note(home, a, f"n{i}.md", "PAYLOAD" + ("y" * 1500))

        entries, _scanned, diagnostics = auto_memory.collect_ingest_entries(
            str(a), scope="project", home=home
        )
        assert diagnostics["over_budget_files"], "the budget never engaged"
        assert len(entries) + len(diagnostics["over_budget_files"]) == 6
        assert diagnostics["bytes_read"] <= 4096

    def test_skipped_note_does_not_lose_its_existing_index_row(self, env, monkeypatch):
        """The trap this feature would otherwise walk into.

        Pruning treats "absent from entries" as "the file was deleted". A note
        skipped for size is absent from entries but very much still on disk, so
        without the protection a size cap would DELETE the good row it already
        had — a resource guard causing data loss.
        """
        home, a, _b, store = env
        write_note(home, a, "grows.md", "GROWSTOKEN and some content")
        store.ingest_auto_memory(*collect(a, home))
        assert len(store.search_global_ex("GROWSTOKEN")[0]) == 1

        # The same note, now over the cap.
        self._big_note(home, a, "grows.md", "GROWSTOKEN")
        entries, scanned, diagnostics = auto_memory.collect_ingest_entries(
            str(a), scope="project", home=home
        )
        assert entries == []
        result = store.ingest_auto_memory(
            entries, scanned, present_but_skipped=diagnostics["present_but_skipped"]
        )
        assert result["pruned"] == 0, "a size-skipped note must not be pruned"
        assert len(store.search_global_ex("GROWSTOKEN")[0]) == 1, (
            "the previously indexed row was deleted because the file grew past "
            "the cap — the guard destroyed the data it was meant to protect"
        )

    def test_a_genuinely_deleted_note_is_still_pruned(self, env):
        """The protection must not blunt the real prune."""
        home, a, _b, store = env
        write_note(home, a, "gone.md", "GONETOKEN")
        store.ingest_auto_memory(*collect(a, home))
        d = home / ".claude" / "projects" / auto_memory.encode_project_dirname(a) / "memory"
        (d / "gone.md").unlink()

        entries, scanned, diagnostics = auto_memory.collect_ingest_entries(
            str(a), scope="project", home=home
        )
        result = store.ingest_auto_memory(
            entries, scanned, present_but_skipped=diagnostics["present_but_skipped"]
        )
        assert result["pruned"] == 1
        assert store.search_global_ex("GONETOKEN")[0] == []

    def test_tool_warns_about_oversized_notes(self, tmp_path, monkeypatch):
        from pmlens.models import Project
        from pmlens.storage import _save_project

        home = tmp_path / "home"
        (home / ".claude" / "projects").mkdir(parents=True)
        proj = tmp_path / "proj"
        (proj / ".pm" / "daily").mkdir(parents=True)
        _save_project(proj / ".pm", Project(name="proj", display_name="proj"))
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.chdir(proj)
        from pmlens.server import pm_memory_ingest

        write_note(home, proj, "huge.md", "H" * (auto_memory._MAX_NOTE_BYTES + 1))
        result = pm_memory_ingest(dry_run=False)
        codes = [w["code"] for w in result.get("warnings", [])]
        assert "auto_memory_notes_oversized" in codes, (
            "skipping silently leaves a hole in cross-project search that looks "
            "exactly like a topic nobody wrote about"
        )
        assert result["oversized_files"]

    def test_overlay_read_is_also_bounded(self, env):
        """parse_auto_memory_file's own guard protects the read-time overlay,
        which reads whole files too even though it excerpts the output."""
        home, a, _b, _store = env
        d = home / ".claude" / "projects" / auto_memory.encode_project_dirname(a) / "memory"
        d.mkdir(parents=True, exist_ok=True)
        big = d / "huge.md"
        big.write_text("x" * (auto_memory._MAX_NOTE_BYTES + 1), encoding="utf-8")
        assert auto_memory.parse_auto_memory_file(big) is None
        # …and the cap is opt-out for callers that have already measured.
        assert auto_memory.parse_auto_memory_file(big, max_bytes=None) is not None


class TestUnregisteredDisplayName:
    """PMSERV-170: the encoded dir name must not be the user-facing label.

    ``project`` is quoted back in cross-project search results and in
    warnings[] project lists. Defaulting it to the encoded directory name
    published the directory layout — client names and all — independently of
    anything the notes contained.
    """

    def test_known_root_uses_the_real_basename_not_the_encoding(self):
        name = auto_memory.unregistered_display_name(
            "-Users-alice-clients-acme-portal", "/Users/alice/clients/acme_portal"
        )
        assert name == "acme_portal", (
            "when the real project root is known the basename is exact — no "
            "reason to fall back to a guess, let alone to the encoded path"
        )

    def test_unknown_root_is_marked_and_trimmed(self):
        name = auto_memory.unregistered_display_name("-Users-alice-clients-acme-portal")
        assert name == "unregistered:acme-portal"
        # The point of the exercise: the rest of the path is gone.
        assert "alice" not in name
        assert "clients" not in name

    def test_degenerate_encodings_do_not_crash(self):
        assert auto_memory.unregistered_display_name("-") == "unregistered"
        assert auto_memory.unregistered_display_name("") == "unregistered"
        assert auto_memory.unregistered_display_name("solo") == "unregistered:solo"

    def test_project_scope_labels_rows_with_the_repo_name(self, env):
        """The un-overridden project scope always knows its own root, so an
        unregistered repo still gets a readable label."""
        home, a, _b, store = env
        write_note(home, a, "a1.md", "LABELTOKEN")
        entries, scanned = collect(a, home)
        assert entries[0]["project"] == a.name
        assert "-Users-" not in entries[0]["project"]
        # project_path stays exact — a project-scoped purge targets it.
        assert entries[0]["project_path"] == str(a)

    def test_foreign_store_in_scope_all_is_labelled_unregistered(self, env):
        home, a, b, store = env
        write_note(home, a, "a1.md", "MINETOKEN")
        write_note(home, b, "b1.md", "THEIRSTOKEN")
        entries, _scanned = collect(a, home, scope="all")
        labels = {e["project"] for e in entries}
        assert all(
            not label.startswith("-Users") and not label.startswith("-private") for label in labels
        ), f"an encoded absolute path is still used as a display name: {labels}"
        foreign = [e for e in entries if "THEIRSTOKEN" in (e.get("content") or "")]
        assert foreign and foreign[0]["project"].startswith("unregistered:")
        # …while the exact identity survives where purge needs it: project_path
        # still names the store's own directory, so a targeted purge resolves.
        assert foreign[0]["project_path"].endswith(auto_memory.encode_project_dirname(b)), (
            "project_path must keep identifying the store exactly — rounding it "
            f"would break purge targeting (got {foreign[0]['project_path']!r})"
        )


class TestIndexRowShape:
    def test_created_at_matches_ledger_format_and_is_not_future(self, env):
        """Ledger rows use SQLite datetime('now') — UTC, space-separated. The
        local isoformat mtime ('T'-separated) sorted AFTER every ledger value
        in the LIKE fallback's ORDER BY created_at (confirmed: 'T' > ' ')."""
        home, a, _b, store = env
        store.save(Memory(session_id="s1", content="LEDGERROW", project="a"))
        write_note(home, a, "ts.md", "AUTOROW")
        store.ingest_auto_memory(*collect(a, home))
        conn = sqlite3.connect(home / ".pm" / "memory.db")
        auto_ts = conn.execute(
            "SELECT created_at FROM memory_index WHERE source='auto_memory'"
        ).fetchone()[0]
        now_utc = conn.execute("SELECT datetime('now') AS n").fetchone()[0]
        conn.close()
        assert "T" not in auto_ts
        assert auto_ts <= now_utc

    def test_typeless_note_gets_unknown_not_the_source_literal(self, env):
        """type='auto_memory' invented a fake category colliding with the
        source column; the overlay honestly returns None for such notes."""
        home, a, _b, store = env
        d = home / ".claude" / "projects" / auto_memory.encode_project_dirname(a) / "memory"
        d.mkdir(parents=True, exist_ok=True)
        (d / "untyped.md").write_text("---\nname: u\n---\n\nUNTYPEDTOKEN\n", encoding="utf-8")
        store.ingest_auto_memory(*collect(a, home))
        hit = store.search_global_ex("UNTYPEDTOKEN")[0][0]
        assert hit["type"] == "unknown"
        assert hit["source"] == AUTO_MEMORY_SOURCE

    def test_drift_duplicate_dirs_dedup_to_one_row(self, env):
        """One repo can own several encoded dirs (encoding drift); the overlay
        dedups by basename but ingest did not, so one logical note became N
        searchable rows."""
        home, a, _b, store = env
        raw = str(a)
        current = home / ".claude" / "projects" / auto_memory.encode_project_dirname(raw)
        legacy = home / ".claude" / "projects" / raw.replace("/", "-")
        for base in (current, legacy):
            (base / "memory").mkdir(parents=True, exist_ok=True)
            (base / "memory" / "same.md").write_text(
                "---\nname: s\n---\n\nDRIFTTOKEN\n", encoding="utf-8"
            )
        # Register the project so both encodings resolve to one identity.
        (home / ".pm").mkdir(exist_ok=True)
        (home / ".pm" / "registry.yaml").write_text(
            f"projects:\n- path: {raw}\n  name: proj-a\n  registered: '2026-01-01'\n",
            encoding="utf-8",
        )
        entries, _scanned, _diag = auto_memory.collect_ingest_entries(
            str(a), scope="all", home=home
        )
        drift_entries = [e for e in entries if "DRIFTTOKEN" in e["content"]]
        assert len(drift_entries) == 1


class TestLensGlobalRead:
    def test_lens_searches_ingested_rows_but_cannot_ingest(self, env):
        """CHANGELOG/design.md promise the Lens viewer can SEARCH ingested
        rows; the old wiring nulled global_db_path on every readonly store,
        so Lens cross-project search always returned [] (confirmed). Writes
        must still be refused by the store itself (defense-in-depth under
        RO_ALLOWLIST)."""
        home, a, _b, store = env
        write_note(home, a, "a1.md", "LENSREADTOKEN")
        store.ingest_auto_memory(*collect(a, home))
        # The WRITER legitimately created WAL sidecars; its connection is
        # closed (auto-checkpoint), so drop them to observe what the RO read
        # itself touches.
        for suffix in ("-wal", "-shm"):
            sidecar = home / ".pm" / f"memory.db{suffix}"
            if sidecar.exists():
                sidecar.unlink()

        ro = MemoryStore(
            a / ".pm" / "memory.db",
            global_db_path=home / ".pm" / "memory.db",
            readonly=True,
        )
        try:
            hits, _ = ro.search_global_ex("LENSREADTOKEN")
            assert len(hits) == 1
            assert hits[0]["source"] == AUTO_MEMORY_SOURCE
            refused = ro.ingest_auto_memory(*collect(a, home))
            assert "error" in refused
            purged = ro.purge_auto_memory(None)
            assert "error" in purged
        finally:
            ro.close()
        # The read created no sidecars in ~/.pm (RO invariant, ADR-028).
        assert not (home / ".pm" / "memory.db-wal").exists()
        assert not (home / ".pm" / "memory.db-shm").exists()
