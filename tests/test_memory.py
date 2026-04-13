"""Tests for memory.py — SQLite MemoryStore + FTS5 search."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from pm_server.memory import MemoryStore, _sanitize_fts_query, _str_to_tags, _tags_to_str
from pm_server.models import Memory, MemoryType, SessionSummary

# ─── Tag conversion helpers ────────────────────────────


class TestTagConversion:
    def test_tags_to_str(self):
        assert _tags_to_str(["auth", "api"]) == "auth,api"

    def test_tags_to_str_empty(self):
        assert _tags_to_str([]) == ""

    def test_str_to_tags(self):
        assert _str_to_tags("auth,api") == ["auth", "api"]

    def test_str_to_tags_with_spaces(self):
        assert _str_to_tags(" auth , api ") == ["auth", "api"]

    def test_str_to_tags_empty(self):
        assert _str_to_tags("") == []

    def test_str_to_tags_none(self):
        assert _str_to_tags("") == []

    def test_roundtrip(self):
        tags = ["memory", "sqlite", "fts5"]
        assert _str_to_tags(_tags_to_str(tags)) == tags


# ─── FTS5 query sanitization ─────────────────────────────


class TestSanitizeFtsQuery:
    def test_plain_words_unchanged(self):
        assert _sanitize_fts_query("memory search") == "memory search"

    def test_hyphenated_word_quoted(self):
        assert _sanitize_fts_query("pm-server") == '"pm-server"'

    def test_colon_word_quoted(self):
        assert _sanitize_fts_query("col:value") == '"col:value"'

    def test_already_quoted_preserved(self):
        assert _sanitize_fts_query('"exact phrase"') == '"exact phrase"'

    def test_mixed_tokens(self):
        result = _sanitize_fts_query('memory "exact phrase" pm-server')
        assert result == 'memory "exact phrase" "pm-server"'

    def test_empty_query(self):
        assert _sanitize_fts_query("") == ""

    def test_multiple_hyphens(self):
        assert _sanitize_fts_query("a-b-c") == '"a-b-c"'


# ─── MemoryStore initialization ────────────────────────


class TestMemoryStoreInit:
    def test_creates_db_file(self, tmp_path: Path):
        db_path = tmp_path / "subdir" / "memory.db"
        store = MemoryStore(db_path)
        assert db_path.exists()
        store.close()

    def test_schema_is_idempotent(self, memory_store: MemoryStore):
        # Calling _ensure_schema again should not raise
        memory_store._ensure_schema()

    def test_tables_exist(self, memory_store: MemoryStore):
        cur = memory_store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row["name"] for row in cur.fetchall()}
        assert "memories" in tables
        assert "session_summaries" in tables
        assert "memories_fts" in tables


# ─── Memory CRUD ───────────────────────────────────────


class TestMemorySave:
    def test_save_returns_id(self, memory_store: MemoryStore):
        mem = Memory(
            session_id="sess-test-001",
            content="Test memory",
            project="testproj",
        )
        mem_id = memory_store.save(mem)
        assert isinstance(mem_id, int)
        assert mem_id >= 1

    def test_save_multiple(self, memory_store: MemoryStore):
        ids = []
        for i in range(3):
            mem = Memory(
                session_id="sess-test-001",
                content=f"Memory {i}",
                project="testproj",
            )
            ids.append(memory_store.save(mem))
        assert len(set(ids)) == 3  # all unique

    def test_save_with_task_id(self, memory_store: MemoryStore):
        mem = Memory(
            session_id="sess-test-001",
            content="Auth implementation notes",
            task_id="TEST-001",
            project="testproj",
        )
        mem_id = memory_store.save(mem)
        results = memory_store.get_by_task("TEST-001")
        assert len(results) == 1
        assert results[0].id == mem_id
        assert results[0].task_id == "TEST-001"

    def test_save_with_decision_id(self, memory_store: MemoryStore):
        mem = Memory(
            session_id="sess-test-001",
            content="JWT decision rationale",
            decision_id="ADR-001",
            project="testproj",
        )
        memory_store.save(mem)
        results = memory_store.get_by_decision("ADR-001")
        assert len(results) == 1
        assert results[0].decision_id == "ADR-001"

    def test_save_with_tags(self, memory_store: MemoryStore):
        mem = Memory(
            session_id="sess-test-001",
            content="Tagged memory",
            tags=["auth", "api"],
            project="testproj",
        )
        memory_store.save(mem)
        recent = memory_store.get_recent(limit=1)
        assert recent[0].tags == ["auth", "api"]

    def test_save_all_types(self, memory_store: MemoryStore):
        for mtype in MemoryType:
            mem = Memory(
                session_id="sess-test-001",
                type=mtype,
                content=f"Memory of type {mtype.value}",
                project="testproj",
            )
            memory_store.save(mem)
        recent = memory_store.get_recent(limit=3)
        types = {m.type for m in recent}
        assert types == {MemoryType.OBSERVATION, MemoryType.INSIGHT, MemoryType.LESSON}


# ─── FTS5 Search ───────────────────────────────────────


class TestFTS5Search:
    @pytest.fixture(autouse=True)
    def _seed_memories(self, memory_store: MemoryStore):
        memories = [
            ("User authentication API implemented with JWT tokens", "auth,jwt"),
            ("Database migration script for user table", "database,migration"),
            ("Refactored error handling to use custom exceptions", "refactor,error"),
            ("Performance optimization for search queries", "performance,search"),
            ("Added unit tests for storage module", "test,storage"),
        ]
        for content, tags in memories:
            mem = Memory(
                session_id="sess-seed",
                content=content,
                tags=tags.split(","),
                project="testproj",
            )
            memory_store.save(mem)

    def test_search_single_word(self, memory_store: MemoryStore):
        results = memory_store.search("authentication")
        assert len(results) >= 1
        assert any("authentication" in r.content.lower() for r in results)

    def test_search_multiple_words(self, memory_store: MemoryStore):
        results = memory_store.search("database migration")
        assert len(results) >= 1

    def test_search_no_results(self, memory_store: MemoryStore):
        results = memory_store.search("nonexistent_term_xyz")
        assert len(results) == 0

    def test_search_with_type_filter(self, memory_store: MemoryStore):
        # Save an insight
        mem = Memory(
            session_id="sess-seed",
            type=MemoryType.INSIGHT,
            content="JWT tokens need short expiry for security",
            project="testproj",
        )
        memory_store.save(mem)

        results = memory_store.search("JWT", type="insight")
        assert all(r.type == MemoryType.INSIGHT for r in results)

    def test_search_limit(self, memory_store: MemoryStore):
        results = memory_store.search("user", limit=1)
        assert len(results) <= 1

    def test_search_japanese(self, memory_store: MemoryStore):
        """FTS5 unicode61 tokenizes CJK characters individually."""
        mem = Memory(
            session_id="sess-jp",
            content="ユーザー認証APIの実装を完了した",
            tags=["認証", "API"],
            project="testproj",
        )
        memory_store.save(mem)
        results = memory_store.search("認証")
        assert len(results) >= 1
        assert any("認証" in r.content for r in results)

    def test_search_hyphenated_term(self, memory_store: MemoryStore):
        """Hyphenated terms must not crash FTS5 with column-filter error."""
        mem = Memory(
            session_id="sess-hyp",
            content="Deployed pm-server to staging environment",
            tags=["deploy"],
            project="testproj",
        )
        memory_store.save(mem)
        results = memory_store.search("pm-server")
        assert len(results) >= 1
        assert any("pm-server" in r.content for r in results)

    def test_search_hyphenated_no_match(self, memory_store: MemoryStore):
        """Hyphenated term that doesn't match should return empty, not error."""
        results = memory_store.search("no-such-term")
        assert len(results) == 0

    def test_search_japanese_tags(self, memory_store: MemoryStore):
        mem = Memory(
            session_id="sess-jp",
            content="リファクタリングを実施",
            tags=["リファクタ", "改善"],
            project="testproj",
        )
        memory_store.save(mem)
        results = memory_store.search("リファクタ")
        assert len(results) >= 1


# ─── get_by_task / get_by_decision ─────────────────────


class TestGetByAssociation:
    def test_get_by_task_multiple(self, memory_store: MemoryStore):
        for i in range(3):
            mem = Memory(
                session_id="sess-test",
                content=f"Task note {i}",
                task_id="TEST-001",
                project="testproj",
            )
            memory_store.save(mem)
        results = memory_store.get_by_task("TEST-001")
        assert len(results) == 3

    def test_get_by_task_empty(self, memory_store: MemoryStore):
        results = memory_store.get_by_task("NONEXIST-999")
        assert results == []

    def test_get_by_decision_empty(self, memory_store: MemoryStore):
        results = memory_store.get_by_decision("ADR-999")
        assert results == []


# ─── get_recent ────────────────────────────────────────


class TestGetRecent:
    def test_get_recent_order(self, memory_store: MemoryStore):
        for i in range(5):
            mem = Memory(
                session_id="sess-test",
                content=f"Memory {i}",
                project="testproj",
            )
            memory_store.save(mem)
        recent = memory_store.get_recent(limit=5)
        # Most recent first (highest ID = most recent by created_at default)
        ids = [m.id for m in recent]
        assert ids == sorted(ids, reverse=True)

    def test_get_recent_limit(self, memory_store: MemoryStore):
        for i in range(10):
            mem = Memory(
                session_id="sess-test",
                content=f"Memory {i}",
                project="testproj",
            )
            memory_store.save(mem)
        recent = memory_store.get_recent(limit=3)
        assert len(recent) == 3

    def test_get_recent_empty_db(self, memory_store: MemoryStore):
        recent = memory_store.get_recent()
        assert recent == []


# ─── Session Summaries ─────────────────────────────────


class TestSessionSummaries:
    def test_save_and_get_latest(self, memory_store: MemoryStore):
        summary = SessionSummary(
            session_id="sess-001",
            summary="Implemented auth module",
            goals="Complete JWT auth",
            tasks_done=["TEST-001"],
            decisions=["ADR-001"],
            pending=["Review needed"],
            project="testproj",
        )
        sid = memory_store.save_session_summary(summary)
        assert isinstance(sid, int)

        latest = memory_store.get_latest_summary()
        assert latest is not None
        assert latest.session_id == "sess-001"
        assert latest.summary == "Implemented auth module"
        assert latest.tasks_done == ["TEST-001"]
        assert latest.decisions == ["ADR-001"]
        assert latest.pending == ["Review needed"]

    def test_get_latest_returns_most_recent(self, memory_store: MemoryStore):
        for i in range(3):
            summary = SessionSummary(
                session_id=f"sess-{i:03d}",
                summary=f"Session {i}",
                project="testproj",
            )
            memory_store.save_session_summary(summary)
            # Small delay to ensure different created_at
            time.sleep(0.01)

        latest = memory_store.get_latest_summary()
        assert latest is not None
        assert latest.session_id == "sess-002"

    def test_get_latest_empty_db(self, memory_store: MemoryStore):
        assert memory_store.get_latest_summary() is None

    def test_list_summaries(self, memory_store: MemoryStore):
        for i in range(5):
            summary = SessionSummary(
                session_id=f"sess-{i:03d}",
                summary=f"Session {i}",
                project="testproj",
            )
            memory_store.save_session_summary(summary)
        summaries = memory_store.list_summaries(limit=3)
        assert len(summaries) == 3

    def test_list_summaries_empty_db(self, memory_store: MemoryStore):
        assert memory_store.list_summaries() == []

    def test_save_replaces_existing_session(self, memory_store: MemoryStore):
        """INSERT OR REPLACE should update if session_id exists."""
        s1 = SessionSummary(
            session_id="sess-same",
            summary="First version",
            project="testproj",
        )
        memory_store.save_session_summary(s1)

        s2 = SessionSummary(
            session_id="sess-same",
            summary="Updated version",
            project="testproj",
        )
        memory_store.save_session_summary(s2)

        summaries = memory_store.list_summaries()
        assert len(summaries) == 1
        assert summaries[0].summary == "Updated version"

    def test_summary_with_empty_lists(self, memory_store: MemoryStore):
        summary = SessionSummary(
            session_id="sess-empty",
            summary="Minimal session",
            project="testproj",
        )
        memory_store.save_session_summary(summary)
        latest = memory_store.get_latest_summary()
        assert latest is not None
        assert latest.tasks_done == []
        assert latest.decisions == []
        assert latest.pending == []


# ─── Server tool integration ───────────────────────────


class TestServerToolIntegration:
    """Test pm_remember / pm_recall / pm_session_summary via server functions."""

    @pytest.fixture(autouse=True)
    def _setup_project(self, tmp_project: Path, monkeypatch):
        """Set up a project with project.yaml for server tool calls."""
        from pm_server.models import Project
        from pm_server.storage import save_project

        pm_path = tmp_project / ".pm"
        project = Project(name="testproj", display_name="Test")
        save_project(pm_path, project)
        monkeypatch.chdir(tmp_project)

        # Clear cached memory stores between tests
        import pm_server.server

        pm_server.server._memory_stores.clear()

    def test_remember_and_recall(self):
        from pm_server.server import pm_recall, pm_remember

        result = pm_remember(content="JWT tokens expire in 15 minutes", type="insight")
        assert result["status"] == "saved"
        assert "memory_id" in result

        recall_result = pm_recall(query="JWT")
        assert len(recall_result["results"]) >= 1
        assert any("JWT" in r["content"] for r in recall_result["results"])

    def test_recall_default_no_args(self):
        from pm_server.server import pm_recall, pm_remember

        pm_remember(content="Some observation")
        result = pm_recall()
        assert "last_session" in result
        assert "recent_memories" in result
        assert len(result["recent_memories"]) >= 1

    def test_recall_default_with_type_filter(self):
        from pm_server.server import pm_recall, pm_remember

        pm_remember(content="An observation", type="observation")
        pm_remember(content="A lesson learned", type="lesson")
        pm_remember(content="An insight gained", type="insight")

        result = pm_recall(type="lesson")
        assert all(m["type"] == "lesson" for m in result["recent_memories"])
        assert len(result["recent_memories"]) == 1

    def test_recall_by_task_id(self):
        from pm_server.server import pm_recall, pm_remember

        pm_remember(content="Task note", task_id="TEST-001")
        result = pm_recall(task_id="TEST-001")
        assert len(result["results"]) == 1
        assert result["results"][0]["task_id"] == "TEST-001"

    def test_recall_cross_project_requires_query(self):
        from pm_server.server import pm_recall

        result = pm_recall(cross_project=True)
        assert result["status"] == "error"

    def test_recall_cross_project_with_query(self):
        from pm_server.server import pm_recall, pm_remember

        pm_remember(content="Cross project test data")
        result = pm_recall(query="Cross project", cross_project=True)
        assert result["cross_project"] is True
        assert "results" in result

    def test_session_summary_save_get(self):
        from pm_server.server import pm_session_summary

        save_result = pm_session_summary(
            action="save",
            summary="Completed auth module implementation",
            goals="JWT auth working",
            pending="Code review,Deploy",
        )
        assert save_result["status"] == "saved"

        get_result = pm_session_summary(action="get")
        assert get_result["summary"] == "Completed auth module implementation"
        assert get_result["pending"] == ["Code review", "Deploy"]

    def test_session_summary_list(self):
        from pm_server.server import pm_session_summary

        pm_session_summary(action="save", summary="Session 1")
        result = pm_session_summary(action="list")
        assert result["count"] >= 1

    def test_session_summary_save_requires_summary(self):
        from pm_server.server import pm_session_summary

        result = pm_session_summary(action="save")
        assert result["status"] == "error"

    def test_session_summary_get_empty(self):
        from pm_server.server import pm_session_summary

        result = pm_session_summary(action="get")
        assert result["status"] == "empty"

    def test_session_summary_invalid_action(self):
        from pm_server.server import pm_session_summary

        result = pm_session_summary(action="invalid")
        assert result["status"] == "error"
