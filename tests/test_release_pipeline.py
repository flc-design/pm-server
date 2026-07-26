"""Half-release guardrail for the two-workflow release pipeline (PMSERV-173).

A `v*` tag fires TWO independent workflow runs — `release.yml` (publishes
`pmlens`) and `publish-wrapper.yml` (publishes the `pm-server` compatibility
metapackage) — and each stops at its own manual approval in the `pypi`
environment. Until PMSERV-173 both approval prompts were named
``Publish … to PyPI (Trusted Publisher)`` and neither run knew the other
existed, so:

* **approving only the first** published pmlens, attached the ``.mcpb`` and
  created a ``--latest`` GitHub Release, while ``uvx pm-server@X.Y.Z`` — the pin
  committed in ``plugin/.mcp.json`` — stayed unresolvable for every plugin user.
  Nothing anywhere went red.
* **approving the wrapper first** published a metapackage requiring
  ``pmlens>=X.Y.Z`` before that pmlens existed. If the pmlens run's ``verify``
  then failed, the window was **permanent** — PyPI never allows re-uploading a
  filename.

Both are now loud: each publish path polls PyPI for its counterpart and fails.
``skip-existing: true`` on both uploads means a job's exit status is *not*
evidence that anything was published, so these gates are the only mechanism that
can distinguish "released" from "half-released".

This file exists for the same reason ``test_workflow_pins.py`` does: without it,
deleting a gate or renaming a job back to an ambiguous label leaves CI green and
the regression only surfaces during a release, which is the worst possible time
to find it.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
RELEASE_YML = WORKFLOWS_DIR / "release.yml"
WRAPPER_YML = WORKFLOWS_DIR / "publish-wrapper.yml"
RUNBOOK = REPO_ROOT / "docs" / "RELEASING.md"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _steps(job: dict) -> list[dict]:
    return [s for s in job.get("steps", []) if isinstance(s, dict)]


def _index_of_step_containing(job: dict, needle: str) -> int:
    """Index of the first step whose `run` or `uses` mentions `needle`, else -1."""
    for i, step in enumerate(_steps(job)):
        blob = f"{step.get('run', '')}\n{step.get('uses', '')}"
        if needle in blob:
            return i
    return -1


def _environment_name(job: dict) -> str | None:
    env = job.get("environment")
    if isinstance(env, dict):
        return env.get("name")
    return env if isinstance(env, str) else None


# ─── The approvals must be distinguishable ────────────────────────────────────


def test_exactly_two_jobs_gate_on_the_pypi_environment():
    """A third publish path would mean a third approval nobody is told about."""
    gated = [
        f"{path.name}:{job_id}"
        for path in (RELEASE_YML, WRAPPER_YML)
        for job_id, job in _load(path)["jobs"].items()
        if _environment_name(job) == "pypi"
    ]
    assert sorted(gated) == ["publish-wrapper.yml:publish", "release.yml:publish"], (
        f"jobs behind the `pypi` approval changed: {sorted(gated)}. Every one of "
        "these is a separate manual approval a maintainer must click — update "
        "docs/RELEASING.md §2 and the job names before changing this set."
    )


def test_publish_job_names_state_the_approval_order():
    """Two identically-named prompts is how a maintainer approves one and stops.

    The names are load-bearing UI, not decoration: the Actions list is where the
    ordering rule (pmlens before wrapper) is actually enforced, by a human.
    """
    pmlens_name = _load(RELEASE_YML)["jobs"]["publish"]["name"]
    wrapper_name = _load(WRAPPER_YML)["jobs"]["publish"]["name"]

    assert "1 of 2" in pmlens_name, (
        f"release.yml publish job is named {pmlens_name!r}; it must say it is the "
        "FIRST of two approvals (PMSERV-173)"
    )
    assert "2 of 2" in wrapper_name, (
        f"publish-wrapper.yml publish job is named {wrapper_name!r}; it must say "
        "it is the SECOND of two approvals (PMSERV-173)"
    )
    assert pmlens_name != wrapper_name


# ─── The ordering gates ───────────────────────────────────────────────────────


def test_github_release_waits_for_the_wrapper_on_pypi():
    """Do not announce a version whose committed plugin pin cannot resolve."""
    job = _load(RELEASE_YML)["jobs"]["github-release"]
    gate = _index_of_step_containing(job, "pypi.org/pypi/pm-server/")
    announce = _index_of_step_containing(job, "gh release create")

    assert gate != -1, (
        "release.yml's github-release job no longer polls PyPI for the pm-server "
        "wrapper. Without it, approving only the pmlens run creates a `--latest` "
        "Release for a version whose `uvx pm-server@X.Y.Z` plugin pin is "
        "unresolvable, with no job red anywhere (PMSERV-173)."
    )
    assert announce != -1, "expected a `gh release create` step in github-release"
    assert gate < announce, (
        "the PyPI presence gate must run BEFORE the Release is created — "
        f"gate at step {gate}, `gh release create` at step {announce}"
    )


def test_wrapper_publish_waits_for_pmlens_on_pypi():
    """The wrapper's floor must be satisfiable at the moment it is published.

    This is the gate that closes the *permanent* window: a wrapper published
    ahead of pmlens cannot be withdrawn or replaced.
    """
    job = _load(WRAPPER_YML)["jobs"]["publish"]
    gate = _index_of_step_containing(job, "pypi.org/pypi/pmlens/")
    upload = _index_of_step_containing(job, "gh-action-pypi-publish")

    assert gate != -1, (
        "publish-wrapper.yml's publish job no longer verifies that pmlens is "
        "already on PyPI. Publishing the wrapper first ships `pmlens>=X.Y.Z` "
        "against a version that does not exist (PMSERV-173)."
    )
    assert upload != -1, "expected the pypa publish action in the wrapper publish job"
    assert gate < upload, (
        "the pmlens presence gate must run BEFORE the upload — PyPI filenames "
        f"are immutable (gate at step {gate}, upload at step {upload})"
    )


def test_wrapper_version_is_passed_from_build_not_derived_from_the_ref():
    """The gate must also work on a `workflow_dispatch` backfill.

    On a dispatch, `github.ref_name` is a branch and carries no version, so
    deriving it from the ref would silently skip the gate on exactly the manual
    path a half-release recovery uses.
    """
    build = _load(WRAPPER_YML)["jobs"]["build"]
    assert "version" in (build.get("outputs") or {}), (
        "publish-wrapper.yml's build job must export the wrapper version as an "
        "output so the publish gate does not depend on the ref shape"
    )


# ─── Re-runs must not race an upload ──────────────────────────────────────────


def test_release_workflows_never_cancel_an_in_flight_run():
    """A run that may already have uploaded to PyPI must never be cancelled."""
    for path in (RELEASE_YML, WRAPPER_YML):
        concurrency = _load(path).get("concurrency")
        assert isinstance(concurrency, dict), (
            f"{path.name} has no `concurrency:` block; a re-tagged correction can "
            "then stack duplicate approval prompts alongside the original run"
        )
        assert concurrency.get("cancel-in-progress") is False, (
            f"{path.name} sets cancel-in-progress={concurrency.get('cancel-in-progress')!r}; "
            "cancelling a release run mid-upload leaves PyPI in an unknown state"
        )


# ─── The runbook is part of the mechanism ─────────────────────────────────────


def test_runbook_exists_and_states_the_two_approval_rule():
    """PMSERV-173's acceptance criterion: the fact must be written down.

    Before this, "a tag needs two approvals" lived only in a task description.
    The pipeline gates make a mistake loud; the runbook is what stops it being
    made.
    """
    assert RUNBOOK.is_file(), "docs/RELEASING.md is missing (PMSERV-173)"
    body = RUNBOOK.read_text(encoding="utf-8")
    for phrase in ("approval 1 of 2", "approval 2 of 2", "release.yml", "publish-wrapper.yml"):
        assert phrase in body, f"docs/RELEASING.md no longer mentions {phrase!r}"
    assert "docs/RELEASING.md" in (REPO_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8"), (
        "CONTRIBUTING.md must link the release runbook — an unlinked runbook is "
        "one nobody reads before their first release"
    )
