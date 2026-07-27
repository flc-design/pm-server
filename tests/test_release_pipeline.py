"""Half-release guardrail for the release pipeline (PMSERV-173, PMSERV-174).

A `v*` tag used to fire TWO independent workflow runs — `release.yml`
(publishes `pmlens`) and `publish-wrapper.yml` (publishes the `pm-server`
compatibility metapackage) — each stopping at its own manual approval in the
`pypi` environment. Approving one and not the other shipped a half-release:

* **approving only pmlens** published it, attached the ``.mcpb`` and created a
  ``--latest`` GitHub Release, while ``uvx pm-server@X.Y.Z`` — the pin committed
  in ``plugin/.mcp.json`` — stayed unresolvable for every plugin user. Nothing
  anywhere went red.
* **approving the wrapper first** published a metapackage requiring
  ``pmlens>=X.Y.Z`` before that pmlens existed. If the pmlens run's ``verify``
  then failed, the window was **permanent** — PyPI never allows re-uploading a
  filename.

PMSERV-173 made both orderings loud. PMSERV-174 (ADR-050 Phase 3) removed the
choice: one job now uploads pmlens and then the wrapper behind a **single**
approval, so ordering is step order rather than a rule a human follows. The
`v*` trigger was removed from ``publish-wrapper.yml``, which survives as the
dispatch-only rollback path.

Two properties therefore need locking, and they pull in opposite directions:
the tag path must gate exactly **once** (or the two-approval hole is back under
a new name), and within that one job pmlens must upload **before** the wrapper
(or the permanent window reopens). Both are asserted below, along with the
PyPI presence poll that still guards the announcement — ``skip-existing: true``
means a green publish step is *not* evidence anything was uploaded, so asking
PyPI directly remains the only way to tell "released" from "no-op'd".

This file exists for the same reason ``test_workflow_pins.py`` does: without it,
deleting a gate or splitting the publish back into two approvals leaves CI green
and the regression only surfaces during a release, which is the worst possible
time to find it.
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
    """Index of the first UNCONDITIONAL step whose `run`/`uses` mentions `needle`.

    Steps carrying an ``if:`` are skipped deliberately. A gate behind
    ``if: false`` — or behind any condition — is not a gate, and matching on
    ``run`` alone would let a disabled guardrail satisfy every ordering
    assertion here. The gates these tests protect must always run.
    """
    for i, step in enumerate(_steps(job)):
        if "if" in step:
            continue
        blob = f"{step.get('run', '')}\n{step.get('uses', '')}"
        if needle in blob:
            return i
    return -1


def _step_containing(job: dict, needle: str) -> dict | None:
    index = _index_of_step_containing(job, needle)
    return _steps(job)[index] if index != -1 else None


def _environment_name(job: dict) -> str | None:
    env = job.get("environment")
    if isinstance(env, dict):
        return env.get("name")
    return env if isinstance(env, str) else None


# ─── The approvals must be distinguishable ────────────────────────────────────


def _triggers(path: Path) -> dict:
    """The `on:` block. PyYAML parses a bare ``on:`` key as the boolean True."""
    wf = _load(path)
    return wf.get("on") if "on" in wf else wf[True]


def test_a_tag_push_requires_exactly_one_approval():
    """The whole point of PMSERV-174. Two gated jobs on the tag path = the hole.

    GitHub creates a pending deployment per JOB, so a second job on the `pypi`
    environment is a second prompt — whether it lives in this workflow or
    another one. Chaining it with ``needs:`` does not help; it makes the two
    prompts sequential rather than batchable, which is strictly worse for the
    maintainer who has to sit through both.
    """
    gated_on_tag_push = [
        f"{path.name}:{job_id}"
        for path in (RELEASE_YML, WRAPPER_YML)
        for job_id, job in _load(path)["jobs"].items()
        if _environment_name(job) == "pypi" and "push" in _triggers(path)
    ]
    assert gated_on_tag_push == ["release.yml:publish"], (
        f"jobs requiring approval on a tag push: {sorted(gated_on_tag_push)}. "
        "A v* tag must stop at exactly ONE approval (PMSERV-174 / ADR-050 "
        "Phase 3). Adding a second returns the half-release hole PMSERV-173 "
        "existed to close — update docs/RELEASING.md §2 and §6 first."
    )


def test_wrapper_workflow_is_dispatch_only():
    """The rollback path must not re-arm itself on a tag.

    ``publish-wrapper.yml`` is kept deliberately (docs/RELEASING.md §6 step 3:
    do not delete the file) so a failed OIDC migration can be reverted by
    restoring this trigger. Until then it must never fire from a tag, or the
    single approval silently becomes two again.
    """
    triggers = _triggers(WRAPPER_YML)
    assert "workflow_dispatch" in triggers, (
        "publish-wrapper.yml lost its workflow_dispatch trigger; it is the "
        "manual recovery/backfill path and must stay runnable"
    )
    assert "push" not in triggers, (
        "publish-wrapper.yml fires on a push again. A v* tag would then start a "
        "second approval-gated run alongside release.yml's, which is exactly "
        "the two-approval state PMSERV-174 removed."
    )


def test_both_version_assertions_run_before_the_approval():
    """A stale wrapper version must fail while stopping is still free.

    Once the single approval is granted, pmlens uploads immediately — after
    that, "the wrapper is stale" can no longer be fixed at this version, since
    PyPI filenames are immutable. So both tag-vs-version checks belong in
    `verify`, which runs before anything is gated.
    """
    verify = _load(RELEASE_YML)["jobs"]["verify"]
    blob = "\n".join(f"{s.get('name', '')}\n{s.get('run', '')}" for s in _steps(verify))

    assert 'tomllib.load(open("pyproject.toml"' in blob, (
        "release.yml's verify job no longer asserts the tag matches pyproject"
    )
    assert "packaging/pm-server-wrapper/pyproject.toml" in blob, (
        "release.yml's verify job must also assert the tag matches the WRAPPER "
        "version (moved here from publish-wrapper.yml by PMSERV-174). Without "
        "it a stale wrapper is only discovered after pmlens has been published."
    )


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


def test_pmlens_uploads_before_the_wrapper_in_the_single_publish_job():
    """The permanent window, now closed by step order rather than by a poll.

    The wrapper declares ``pmlens>=X.Y.Z``. Published first, it leaves
    ``uvx pm-server@X.Y.Z`` unresolvable — and if the pmlens upload then fails,
    that state is permanent, because PyPI never allows re-uploading a filename.

    Step order is the entire enforcement mechanism inside one job, which is
    *stronger* than the ``needs:`` chain it replaced: ``needs:`` only requires
    the prior job to succeed, and ``skip-existing: true`` means success is not
    evidence of an upload. A failed pmlens step here is never followed by a
    wrapper step at all.
    """
    job = _load(RELEASE_YML)["jobs"]["publish"]
    uploads = [
        (i, step)
        for i, step in enumerate(_steps(job))
        if "gh-action-pypi-publish" in step.get("uses", "") and "if" not in step
    ]
    assert len(uploads) == 2, (
        f"expected exactly two unconditional PyPI uploads in release.yml's "
        f"publish job (pmlens then the wrapper), found {len(uploads)}"
    )

    (first_index, first), (second_index, second) = uploads
    first_dir = (first.get("with") or {}).get("packages-dir", "dist/")
    second_dir = (second.get("with") or {}).get("packages-dir", "dist/")

    assert "wrapper" not in first_dir, (
        f"the FIRST upload publishes {first_dir!r}. pmlens must go first — a "
        "wrapper published ahead of it cannot be withdrawn or replaced."
    )
    assert "wrapper-dist" in second_dir, (
        f"the SECOND upload publishes {second_dir!r}; expected the wrapper's "
        "wrapper-dist/. If the wrapper is no longer published here, the tag "
        "path ships pmlens alone and the plugin pin breaks."
    )
    assert first_index < second_index

    # Both artifacts must actually be present, or an upload silently publishes
    # nothing while the step still goes green.
    for artifact in ("dist", "wrapper-dist"):
        assert _index_of_step_containing(job, "download-artifact") != -1
        assert any(
            (s.get("with") or {}).get("name") == artifact
            for s in _steps(job)
            if "download-artifact" in s.get("uses", "")
        ), f"release.yml's publish job never downloads the {artifact!r} artifact"


def test_recovery_path_still_waits_for_pmlens_on_pypi():
    """The dispatch-only wrapper run has no step ordering to protect it.

    On the rollback/backfill path the wrapper is published alone, so the poll
    that release.yml no longer needs is the only thing standing between a
    manual run and a permanently unresolvable metapackage.
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
    wf = _load(WRAPPER_YML)
    build = wf["jobs"]["build"]
    assert "version" in (build.get("outputs") or {}), (
        "publish-wrapper.yml's build job must export the wrapper version as an "
        "output so the publish gate does not depend on the ref shape"
    )

    # Exporting the output is worthless if the gate does not consume it. This
    # is the half that actually prevents the regression the docstring names.
    gate = _step_containing(wf["jobs"]["publish"], "pypi.org/pypi/pmlens/")
    assert gate is not None, "expected the pmlens presence gate in the publish job"
    version_source = (gate.get("env") or {}).get("VERSION", "")
    assert "needs.build.outputs.version" in version_source, (
        f"the gate derives its version from {version_source!r}; it must read "
        "needs.build.outputs.version. github.ref_name is a BRANCH on a "
        "workflow_dispatch run, which would silently skip the gate on exactly "
        "the manual path a half-release recovery uses."
    )
    assert "github.ref_name" not in version_source

    # The gate must also refuse to poll a blank version rather than requesting
    # https://pypi.org/pypi/pmlens//json and treating the 404 as "not published".
    assert 'if [ -z "${VERSION:-}" ]' in gate["run"], (
        "the gate must fail closed when the build output is empty"
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


def test_runbook_states_the_single_approval_rule_and_the_rollback():
    """PMSERV-173's acceptance criterion, updated for PMSERV-174.

    The pipeline gates make a mistake loud; the runbook is what stops it being
    made. Two facts have to survive there: that a tag now stops at one
    approval, and that ``publish-wrapper.yml`` is the rollback and must not be
    deleted (nor its pypi.org publisher entry removed) until a real release has
    shipped through the merged workflow.
    """
    assert RUNBOOK.is_file(), "docs/RELEASING.md is missing (PMSERV-173)"
    body = RUNBOOK.read_text(encoding="utf-8")
    for phrase in ("single approval", "release.yml", "publish-wrapper.yml", "rollback"):
        assert phrase in body, f"docs/RELEASING.md no longer mentions {phrase!r}"
    assert "approval 1 of 2" not in body, (
        "docs/RELEASING.md still describes the two-approval flow removed by "
        "PMSERV-174. A runbook that contradicts the pipeline is worse than no "
        "runbook — it is what a maintainer follows under time pressure."
    )
    assert "docs/RELEASING.md" in (REPO_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8"), (
        "CONTRIBUTING.md must link the release runbook — an unlinked runbook is "
        "one nobody reads before their first release"
    )
