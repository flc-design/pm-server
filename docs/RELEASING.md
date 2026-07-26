# Releasing PM Lens

How a version of `pmlens` (and its `pm-server` compatibility wrapper) reaches
PyPI, the GitHub Release page, and the Claude Code plugin.

> **The one thing to remember.** Pushing a `vX.Y.Z` tag starts **two** GitHub
> Actions runs, each with its **own** manual approval. **Approve
> "Release to PyPI" first, then "Release wrapper (pm-server) to PyPI".**
> Approving only one used to ship a broken plugin with every job green.

---

## 1. Pre-flight (on `main`, before tagging)

`pyproject.toml [project].version` is the single source of truth. Everything
below repeats that number and must move in the same commit.

1. **Bump `pyproject.toml`**, then bump every surface:

   | File | What to change |
   |---|---|
   | `src/pmlens/__init__.py` | `__version__` |
   | `manifest.json` | `version` (the `.mcpb` bundle) |
   | `.claude-plugin/marketplace.json` | `metadata.version` |
   | `plugin/.claude-plugin/plugin.json` | `version` |
   | `plugin/.mcp.json` | the `pm-server@X.Y.Z` uvx pin |
   | `plugin/README.md` | three pins: prerequisite, committed pin, floor form |
   | `packaging/pm-server-wrapper/pyproject.toml` | `project.version` **and** the `pmlens>=X.Y.Z` floor (plus the version in its header comments) |
   | `uv.lock` | run `uv lock` — do **not** hand-edit |
   | `docs/cheatsheet.md`, `docs/cheatsheet.ja.md` | the `> Version X.Y.Z \|` header |
   | `docs/architecture.html` | three stamps (header, tool-count caption, footer). **Leave the dates alone** — `Generated` is frozen; `counts refreshed` moves only when counts are actually re-derived |
   | `docs/README.md` | the `architecture.html は vX.Y.Z 時点` clause **only**. The `user-guide / workflow-guide は v0.12.0` clause on the same line is deliberately frozen |

2. **Let the guard check you** rather than the table above:

   ```bash
   pytest tests/test_version_lockstep.py -q
   ```

   It owns the authoritative registry, asserts an exact pin *count* per file so
   a newly added pin cannot hide, and scans the whole release surface for
   version strings that disagree. If you add a version pin to a new file, add
   that file to `SCOPE_FILES` there. (This guard is `tests/test_version_lockstep.py`;
   it replaced `test_plugin.py::TestPluginVersionSync` in PMSERV-172.)

3. **`CHANGELOG.md`** — move `[Unreleased]` to `[X.Y.Z] - YYYY-MM-DD`. *No test
   asserts this.* Re-read the entries against the code as it is **now**: an
   entry written months ago can have been made false by a later design change —
   the 0.13.0 CHANGELOG advertised a warning code that had since been deleted.
   The CHANGELOG goes out on the Release page, so it is public.

4. **Full suite + lint green on `main`**: `pytest -q`, `ruff check src/ tests/`,
   `ruff format --check src/ tests/`. `ci.yml` does not run on tags, so `main`
   being green is the only pre-tag signal you get from CI (the `verify` job
   re-runs both on the tagged commit — see below).

5. **Commit, then tag with an *annotated* tag.** The Release page's title and
   body come from the tag message:

   ```bash
   git tag -a vX.Y.Z -m "vX.Y.Z — one-line title" -m "Body that becomes the release notes."
   git push origin main --follow-tags
   ```

   A **lightweight** tag is detected and falls back to a CHANGELOG pointer —
   without that detection, `git tag --format=%(contents:*)` silently resolves to
   the *commit* message and would publish its `Co-Authored-By` trailers as your
   public release notes.

---

## 2. The two approvals

Pushing `vX.Y.Z` fires two workflows in parallel:

| Run | Workflow | Publishes | Approval |
|---|---|---|---|
| **Release to PyPI** | `.github/workflows/release.yml` | `pmlens` | **approval 1 of 2** |
| **Release wrapper (pm-server) to PyPI** | `.github/workflows/publish-wrapper.yml` | `pm-server` | **approval 2 of 2** |

Both stop at the `pypi` GitHub environment. **Approve 1 first.** The
job names carry the ordering so the two prompts are distinguishable in the
Actions UI.

Why the order matters: the wrapper is a metapackage declaring
`pmlens>=X.Y.Z`. Publishing it first creates a window where
`uvx pm-server@X.Y.Z` cannot resolve — and if the pmlens run's `verify` then
fails, that window is **permanent**, because PyPI never allows re-uploading a
filename.

Since PMSERV-173 both orderings fail loudly instead of silently:

- **Approve 1 only** → the `github-release` job polls PyPI for `pm-server X.Y.Z`
  for ~14 minutes and then fails. No Release page is created. Approve run 2,
  then *Re-run failed jobs*.
- **Approve 2 first** → the wrapper's `publish` job polls PyPI for
  `pmlens X.Y.Z` and fails **before uploading anything**. Approve run 1, then
  re-run.
- **Approve 1, then 2** → green.

---

## 3. Job graph and what each red means

**`release.yml`**: `verify` → `build` → (`publish` ∥ `pack-mcpb`) → `github-release`

| Gate | Red means |
|---|---|
| `verify` › *Tag name must match the tagged tree's version* | The tag says `vX.Y.Z` but the tagged tree's `pyproject.toml` says something else — the version bump is probably uncommitted. Delete the tag, fix, re-tag. |
| `verify` › ruff + pytest | The **tagged commit** is broken. This job exists because `ci.yml` has no tag trigger, so before it nothing tested what was actually being published. |
| `pack-mcpb` › `scripts/build_mcpb.py` | `manifest.json` disagrees with `pyproject.toml`, or the MCPB v0.4 shape is violated. |
| `github-release` › *Require the pm-server wrapper on PyPI* | See §2. |

**`publish-wrapper.yml`**: `build` → `publish`

| Gate | Red means |
|---|---|
| `build` › *Tag name must match the wrapper's version* | `packaging/pm-server-wrapper/pyproject.toml` was not bumped. This is the v0.12.1 incident. |
| `publish` › *Require pmlens on PyPI* | See §2. |

---

## 4. Recovery

- **PyPI filenames are immutable.** You cannot replace an uploaded artifact.
- **A green publish job is not evidence that anything was uploaded.** Both use
  `skip-existing: true`, so re-firing a tag republishes nothing and still goes
  green. Confirm on pypi.org, not in the Actions UI.
- **Wrapper-only miss** (pmlens published, wrapper not): tag
  `vX.Y.Z-wrapper.N`. Both workflows accept it (`${TAG#v}` then `%%-*` strips
  the suffix), the pmlens side no-ops on `skip-existing`, and `github-release`
  correctly skips it — its `if:` excludes any tag containing a hyphen.
- **`workflow_dispatch` on `publish-wrapper.yml`** is advertised as a backfill
  path, but the `pypi` environment is understood to restrict deployments to
  `v*` tags — a dispatch from `main` would build successfully and then be
  rejected at the environment gate. Verify the environment's protection rules on
  github.com before relying on it; otherwise use the `-wrapper.N` tag above.

---

## 5. Known gaps (deliberate, documented rather than fixed)

- **Pre-release tags publish as final.** Both version checks strip everything
  after the first hyphen, so `v0.14.0-rc1` on a 0.14.0 tree passes `verify` and
  publishes a *real* 0.14.0 — while silently skipping the Release page. Do not
  use `-rc` style tags until this is handled.
- **The tagged commit is tested on one Python only.** `verify` runs 3.12;
  `ci.yml`'s 3.11/3.13 matrix never sees the tag.
- **`pack-mcpb` runs parallel to `publish`, not before it.** A bundle-packing
  failure can therefore land *after* PyPI already has the artifacts.
- **Two runs, two approvals** — structural, not yet fixed. The permanent fix is
  to move the wrapper publish into `release.yml` (one run, one approval,
  ordering guaranteed by `needs:`), which requires the PyPI-side change in §6
  first. Tracked as the follow-up to PMSERV-173.

---

## 6. PyPI trusted publishers

No PyPI API token exists anywhere in this project — publishing is OIDC-only.
The bindings, which must be kept in sync with the workflow filenames:

| PyPI project | Owner | Repository | Workflow | Environment |
|---|---|---|---|---|
| `pmlens` | `flc-design` | `pmlens` | `release.yml` | `pypi` |
| `pm-server` | `flc-design` | `pmlens` | `publish-wrapper.yml` | `pypi` |

**Renaming or moving a workflow file breaks publishing**, because the workflow
filename is part of the OIDC claim.

**To consolidate the wrapper into `release.yml`** (the fix for the two-approval
gap), do it **between releases**, in this order. PyPI allows a project to have
several trusted publishers at once, so this is add-then-verify-then-remove with
no window in which the wrapper is unpublishable:

1. On pypi.org → `pm-server` → *Manage* → *Publishing* → add a second GitHub
   publisher: `flc-design` / `pmlens` / `release.yml` / `pypi`. **Leave the
   `publish-wrapper.yml` entry in place.**
2. In the repo, add a wrapper-publish job to `release.yml` with
   `needs: publish` (so pmlens is on PyPI first by construction), move the
   wrapper's tag↔version assertion into `verify`, and point `github-release` at
   both publish jobs. Drop the now-redundant pmlens-presence poll from the
   wrapper path; keep the `pm-server` presence poll before `github-release`.
3. Change `publish-wrapper.yml`'s trigger to `workflow_dispatch:` only — this
   removes the second automatic run and the second approval while preserving a
   manual recovery path. Do not delete the file.
4. Ship one real release through the merged workflow. Confirm on pypi.org that
   **both** projects show the new version with provenance attestations.
5. Only *after* that success, remove the `publish-wrapper.yml` publisher entry.
   If step 4 fails for OIDC reasons, revert step 3 — the old path still works
   because its publisher entry was never removed.
