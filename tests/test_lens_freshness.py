"""A Lens viewer must not go blind to its own project (PMSERV-176).

Two independent mechanisms conspired to freeze the read-only view, and each
needs its own guard because fixing either alone leaves the bug:

**Layer A — the WAL is invisible.** ``_connect_readonly`` opens the DB with
``mode=ro&immutable=1``. ``immutable=1`` tells SQLite the file will not
change, which makes it skip WAL processing entirely: the reader sees only
what has reached the MAIN database file. Nothing on the read path can fix
that — reading a WAL database read-only needs the ``-shm`` sidecar, and
creating one violates the ADR-028 invariant that a Lens host never writes
into another project's ``.pm/``. So the fix lives on the write path, which
owns the DB and may checkpoint (``_checkpoint_passive`` on summary save).

**Layer B — the connection never notices.** ``server._memory_stores`` cached
stores forever, and ``immutable=1`` disables change detection, so a Lens
process was pinned to whatever it first read. Even a checkpoint by the owner
changed nothing until restart. Fixed by re-stamping the file on every read.

Observed in the wild before the fix: default ``wal_autocheckpoint`` is 1000
pages (≈3.9 MiB) and this repo's ``.pm/memory.db`` sat below it for three
weeks, so 16 session summaries and 29 memories were committed, durable, and
completely invisible to ``pm_recall``. A new session restored three-week-old
context and the gap read as data loss.

PM_LENS is read once at import, so the Lens cases run in subprocesses —
same pattern as tests/test_lens_invariant.py.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

from pmlens.memory import MemoryStore
from pmlens.models import Memory, MemoryType, SessionSummary

_PROJECT_YAML = (
    "name: {name}\n"
    "display_name: {name}\n"
    "version: 0.0.1\n"
    "status: development\n"
    "started: 2026-01-01\n"
    "description: lens freshness fixture\n"
    "phases: []\n"
)


def _make_project(tmp_path: Path, name: str, *, with_db: bool) -> Path:
    """A minimal registered project, optionally with a real memory.db.

    The DB is seeded through ``MemoryStore`` rather than raw SQL so it gets
    the full schema (FTS, triggers, migrations) — the Lens path only opens a
    file read-only if it passes the schema guard, and a hand-rolled table
    would silently take the in-memory fallback branch instead.
    """
    root = tmp_path / name
    pm = root / ".pm"
    pm.mkdir(parents=True)
    (pm / "project.yaml").write_text(_PROJECT_YAML.format(name=name), encoding="utf-8")
    if with_db:
        store = MemoryStore(pm / "memory.db")
        store.save(
            Memory(
                session_id="sess-seed",
                type=MemoryType.OBSERVATION,
                content="SEEDED",
                project=name,
            )
        )
        store.close()
    return root


def _run_lens(script: str, *args: str, home: Path) -> dict:
    """Run ``script`` in a child with PM_LENS=1 and return its JSON payload."""
    env = {**os.environ, "HOME": str(home), "PM_LENS": "1"}
    env.pop("PM_DESKTOP_WRITE", None)
    env.pop("VIRTUAL_ENV", None)
    proc = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, f"stderr={proc.stderr!r}\nstdout={proc.stdout!r}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ─── Layer A: the write path publishes to immutable readers ──────────────────


def test_summary_save_is_visible_to_an_immutable_reader(tmp_path: Path):
    """Saving a session summary must land in the MAIN file, not just the WAL.

    The summary is the continuity datum ``pm_recall`` returns at session
    start, so this is the exact contract PMSERV-176 broke.

    The assertion is the user-visible property ("an immutable reader can see
    it"), not the mechanism ("a checkpoint ran"). PMSERV-171 is the reason:
    a test there pinned SQLite behaviour that turned out to be compile-time
    dependent (``secure_delete`` is 2 on Apple's build, 1 on Linux) and went
    red on CI for a non-bug. Asserting the contract keeps this honest on any
    build — if some platform cannot deliver it, that is exactly what we want
    to hear about.

    The writer connection is deliberately left OPEN across the read: closing
    it would checkpoint on its own and the test would pass even with the fix
    reverted.
    """
    db = tmp_path / "memory.db"
    store = MemoryStore(db)
    try:
        store.save_session_summary(
            SessionSummary(session_id="sess-a", summary="PUBLISHED", project="p")
        )
        assert store.last_checkpoint_error is None, (
            f"checkpoint reported an error: {store.last_checkpoint_error}"
        )

        conn = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
        try:
            seen = [r[0] for r in conn.execute("SELECT summary FROM session_summaries")]
        finally:
            conn.close()
    finally:
        store.close()

    assert seen == ["PUBLISHED"], (
        "a saved session summary was not visible to a mode=ro&immutable=1 reader — "
        "it is still stranded in the WAL, which is PMSERV-176 exactly"
    )


def test_checkpoint_failure_does_not_fail_the_save(tmp_path: Path, monkeypatch):
    """A checkpoint is a convenience; losing it must never lose the write.

    Mirrors purge's ``vacuum_error`` contract (PMSERV-171).

    Uses the ``monkeypatch`` fixture rather than saving and restoring the
    module attribute by hand: the substitution is process-global, so a failure
    between the swap and the restore would leak a broken ``_checkpoint_passive``
    into every later test in the same process. The fixture unwinds on teardown
    whatever the outcome.
    """
    import pmlens.memory as mem

    db = tmp_path / "memory.db"
    store = MemoryStore(db)
    try:
        monkeypatch.setattr(mem, "_checkpoint_passive", lambda conn: "OperationalError: simulated")
        sid = store.save_session_summary(
            SessionSummary(session_id="sess-b", summary="SURVIVES", project="p")
        )

        assert isinstance(sid, int)
        assert store.last_checkpoint_error == "OperationalError: simulated"
        got = store.get_latest_summary()
        assert got is not None and got.summary == "SURVIVES"
    finally:
        store.close()


# ─── Layer B: the read path notices the file moved ───────────────────────────


_SEES_LATER_WRITES = """
    import json, sqlite3, sys, time

    import pmlens.server as srv

    assert srv.PM_LENS_ENABLED is True, "PM_LENS not picked up in subprocess"
    proj, db = sys.argv[1], sys.argv[2]

    first = srv.pm_recall(project_path=proj)

    # Stand in for the owning Claude Code session: commit, then checkpoint so
    # the row reaches the main file. A separate connection is the point — the
    # Lens store's immutable connection cannot observe this by itself.
    time.sleep(0.05)
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "INSERT INTO memories (session_id, type, content, project) VALUES (?,?,?,?)",
        ("sess-owner", "observation", "WRITTEN-AFTER-FIRST-READ", "freshproj"),
    )
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()

    second = srv.pm_recall(project_path=proj)
    print(json.dumps({
        "first": [m["content"] for m in first["recent_memories"]],
        "second": [m["content"] for m in second["recent_memories"]],
    }))
"""


def test_lens_reader_sees_later_writes_without_a_restart(tmp_path: Path):
    """The headline regression: no process restart should be required.

    Before the fix the second recall returned the first recall's snapshot
    verbatim, because the cached ``immutable=1`` connection does no change
    detection and the cache was never evicted.
    """
    home = tmp_path / "home"
    home.mkdir()
    root = _make_project(tmp_path, "freshproj", with_db=True)
    db = root / ".pm" / "memory.db"

    out = _run_lens(_SEES_LATER_WRITES, str(root), str(db), home=home)

    assert "SEEDED" in out["first"], f"fixture never loaded: {out['first']}"
    assert "WRITTEN-AFTER-FIRST-READ" not in out["first"], (
        "the fixture leaked the later write into the first read — test is not "
        "measuring what it claims"
    )
    assert "WRITTEN-AFTER-FIRST-READ" in out["second"], (
        "a Lens read did not observe a checkpointed write made after the store "
        f"was cached; the view is frozen at process start (PMSERV-176). got={out['second']}"
    )


_FALLBACK_UNSTICKS = """
    import json, sys
    from pathlib import Path

    import pmlens.server as srv
    from pmlens.memory import MemoryStore
    from pmlens.models import Memory, MemoryType

    assert srv.PM_LENS_ENABLED is True, "PM_LENS not picked up in subprocess"
    proj = sys.argv[1]

    # No memory.db yet -> Lens takes the in-memory fallback branch.
    first = srv.pm_recall(project_path=proj)

    # The owning session initialises the project for the first time.
    store = MemoryStore(Path(proj) / ".pm" / "memory.db")
    store.save(Memory(
        session_id="sess-init", type=MemoryType.OBSERVATION,
        content="APPEARED-LATER", project="lateproj",
    ))
    store.close()

    second = srv.pm_recall(project_path=proj)
    print(json.dumps({
        "first": [m["content"] for m in first["recent_memories"]],
        "first_note": first.get("note"),
        "second": [m["content"] for m in second["recent_memories"]],
        "second_note": second.get("note"),
    }))
"""


def test_lens_fallback_unsticks_once_the_db_appears(tmp_path: Path):
    """The failure mode Codex found while cross-checking PMSERV-176.

    The empty in-memory fallback was cached under the same never-evicted key,
    so a project whose DB did not exist at first touch was reported as having
    no memory at all — permanently, even after ``pm_init``. That reads as
    "this project has nothing", which is worse than reading stale data.
    """
    home = tmp_path / "home"
    home.mkdir()
    root = _make_project(tmp_path, "lateproj", with_db=False)

    out = _run_lens(_FALLBACK_UNSTICKS, str(root), home=home)

    assert out["first"] == [], f"expected the empty fallback, got {out['first']}"
    assert out["first_note"], "the fallback did not explain itself on the first read"
    assert "APPEARED-LATER" in out["second"], (
        "the Lens store stayed pinned to the empty in-memory fallback after the "
        f"real DB was created; a restart should not be required. got={out['second']}"
    )
    assert not out["second_note"], (
        f"still reporting the fallback note after switching to the real DB: {out['second_note']!r}"
    )


# ─── Layer C: what remains invisible is said out loud ────────────────────────


_STALE_HINT = """
    import json, sqlite3, sys

    import pmlens.server as srv

    assert srv.PM_LENS_ENABLED is True, "PM_LENS not picked up in subprocess"
    proj, db = sys.argv[1], sys.argv[2]

    # Commit WITHOUT checkpointing and keep the connection open, so the frames
    # stay in the -wal exactly as they do for a live writing session.
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "INSERT INTO memories (session_id, type, content, project) VALUES (?,?,?,?)",
        ("sess-owner", "observation", "STILL-IN-WAL", "staleproj"),
    )
    conn.commit()

    res = srv.pm_recall(project_path=proj)
    conn.close()
    print(json.dumps({
        "stale_wal_bytes": res.get("stale_wal_bytes"),
        "stale_note": res.get("stale_note"),
        "contents": [m["content"] for m in res["recent_memories"]],
    }))
"""


def test_lens_reports_uncheckpointed_wal(tmp_path: Path):
    """Un-checkpointed frames stay invisible — so say so rather than imply none exist.

    This is the residual risk after layers A and B: a writer that has
    committed but not yet checkpointed is genuinely unreadable from an
    ``immutable=1`` view, and no read-path change can alter that without
    breaking ADR-028. The honest move is to surface it, because the failure
    that made PMSERV-176 expensive was a caller reading "no recent records"
    as fact.
    """
    home = tmp_path / "home"
    home.mkdir()
    root = _make_project(tmp_path, "staleproj", with_db=True)
    db = root / ".pm" / "memory.db"

    out = _run_lens(_STALE_HINT, str(root), str(db), home=home)

    assert out["stale_wal_bytes"], (
        "a Lens read over a DB with un-checkpointed WAL frames reported no "
        "staleness, so a caller cannot tell 'nothing newer exists' from "
        "'newer records are not visible to me'"
    )
    assert out["stale_note"]
    # The invisible row really is invisible — that is the point being disclosed.
    assert "STILL-IN-WAL" not in out["contents"]
