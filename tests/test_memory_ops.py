"""Tests for pm_memory_stats and pm_memory_cleanup tools."""

from __future__ import annotations

from pm_server.memory import MemoryStore
from pm_server.models import Memory, MemoryType

# ─── MemoryStore.get_stats ────────────────────────────


class TestMemoryStats:
    def test_stats_empty_db(self, memory_store: MemoryStore):
        stats = memory_store.get_stats()
        assert stats["total_memories"] == 0
        assert stats["by_type"] == {}
        assert stats["sessions"] == 0
        assert stats["session_summaries"] == 0
        assert stats["oldest"] is None
        assert stats["newest"] is None
        assert stats["db_size_bytes"] > 0  # DB file exists even when empty

    def test_stats_with_memories(self, memory_store: MemoryStore):
        for i in range(3):
            memory_store.save(
                Memory(
                    session_id="sess-001",
                    type=MemoryType.OBSERVATION,
                    content=f"Obs {i}",
                    project="testproj",
                )
            )
        memory_store.save(
            Memory(
                session_id="sess-001",
                type=MemoryType.INSIGHT,
                content="Insight 1",
                project="testproj",
            )
        )
        memory_store.save(
            Memory(
                session_id="sess-002",
                type=MemoryType.LESSON,
                content="Lesson 1",
                project="testproj",
            )
        )

        stats = memory_store.get_stats()
        assert stats["total_memories"] == 5
        assert stats["by_type"]["observation"] == 3
        assert stats["by_type"]["insight"] == 1
        assert stats["by_type"]["lesson"] == 1
        assert stats["sessions"] == 2
        assert stats["oldest"] is not None
        assert stats["newest"] is not None


# ─── MemoryStore.cleanup ──────────────────────────────


class TestMemoryCleanup:
    def _seed(self, store: MemoryStore, count: int = 10) -> list[int]:
        ids = []
        for i in range(count):
            mid = store.save(
                Memory(
                    session_id=f"sess-{i % 3:03d}",
                    content=f"Memory {i}",
                    project="testproj",
                )
            )
            ids.append(mid)
        return ids

    def test_cleanup_no_criteria(self, memory_store: MemoryStore):
        self._seed(memory_store)
        result = memory_store.cleanup()
        assert "error" in result

    def test_cleanup_dry_run(self, memory_store: MemoryStore):
        self._seed(memory_store, 10)
        result = memory_store.cleanup(keep_latest=3, dry_run=True)
        assert result["dry_run"] is True
        assert result["would_delete"] == 7
        # Verify nothing actually deleted
        assert memory_store.get_stats()["total_memories"] == 10

    def test_cleanup_keep_latest(self, memory_store: MemoryStore):
        self._seed(memory_store, 10)
        result = memory_store.cleanup(keep_latest=3, dry_run=False)
        assert result["deleted"] == 7
        assert result["dry_run"] is False
        assert memory_store.get_stats()["total_memories"] == 3

    def test_cleanup_by_session(self, memory_store: MemoryStore):
        self._seed(memory_store, 9)  # 3 sessions × 3 each
        result = memory_store.cleanup(session_id="sess-000", dry_run=False)
        assert result["deleted"] == 3
        assert memory_store.get_stats()["total_memories"] == 6

    def test_cleanup_older_than_days(self, memory_store: MemoryStore):
        self._seed(memory_store, 5)
        # All memories are "now", so older_than_days=0 deletes nothing meaningful
        # Use a large window to verify the mechanism works
        result = memory_store.cleanup(older_than_days=0, dry_run=True)
        # All memories are from "now", so 0 days ago = now, nothing is older
        assert result["would_delete"] == 0

    def test_cleanup_empty_db(self, memory_store: MemoryStore):
        result = memory_store.cleanup(keep_latest=5, dry_run=False)
        # count==0 triggers the early return with would_delete key
        assert result["would_delete"] == 0


# ─── Server tool integration ─────────────────────────


class TestServerToolMemoryStats:
    def _setup_project(self, tmp_path, monkeypatch):
        from pm_server.models import Project
        from pm_server.storage import save_project

        pm_path = tmp_path / ".pm"
        pm_path.mkdir(exist_ok=True)
        (pm_path / "daily").mkdir(exist_ok=True)
        project = Project(name="statsproj", display_name="Stats Test")
        save_project(pm_path, project)
        monkeypatch.chdir(tmp_path)

        import pm_server.server

        pm_server.server._memory_stores.clear()

    def test_stats_returns_db_size(self, tmp_path, monkeypatch):
        self._setup_project(tmp_path, monkeypatch)
        from pm_server.server import pm_memory_stats, pm_remember

        pm_remember(content="Test memory for stats")
        result = pm_memory_stats()
        assert result["total_memories"] >= 1
        assert "db_size" in result
        assert "db_size_bytes" in result

    def test_stats_type_breakdown(self, tmp_path, monkeypatch):
        self._setup_project(tmp_path, monkeypatch)
        from pm_server.server import pm_memory_stats, pm_remember

        pm_remember(content="Observation 1", type="observation")
        pm_remember(content="Insight 1", type="insight")
        pm_remember(content="Lesson 1", type="lesson")

        result = pm_memory_stats()
        assert result["by_type"].get("observation", 0) >= 1
        assert result["by_type"].get("insight", 0) >= 1
        assert result["by_type"].get("lesson", 0) >= 1


class TestServerToolMemoryCleanup:
    def _setup_project(self, tmp_path, monkeypatch):
        from pm_server.models import Project
        from pm_server.storage import save_project

        pm_path = tmp_path / ".pm"
        pm_path.mkdir(exist_ok=True)
        (pm_path / "daily").mkdir(exist_ok=True)
        project = Project(name="cleanupproj", display_name="Cleanup Test")
        save_project(pm_path, project)
        monkeypatch.chdir(tmp_path)

        import pm_server.server

        pm_server.server._memory_stores.clear()

    def test_cleanup_default_dry_run(self, tmp_path, monkeypatch):
        self._setup_project(tmp_path, monkeypatch)
        from pm_server.server import pm_memory_cleanup, pm_remember

        for i in range(5):
            pm_remember(content=f"Memory {i}")

        result = pm_memory_cleanup(keep_latest=2)
        assert result["dry_run"] is True
        assert result["would_delete"] == 3

    def test_cleanup_actual_delete(self, tmp_path, monkeypatch):
        self._setup_project(tmp_path, monkeypatch)
        from pm_server.server import pm_memory_cleanup, pm_memory_stats, pm_remember

        for i in range(5):
            pm_remember(content=f"Memory {i}")

        pm_memory_cleanup(keep_latest=2, dry_run=False)
        stats = pm_memory_stats()
        assert stats["total_memories"] == 2
