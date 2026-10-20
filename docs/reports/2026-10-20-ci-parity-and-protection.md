# Copy-vs-real script, branch protection behaviour, dev/CI parity cost (2026-10-20)

## 1. test_production_gates.py runs a copy of the script; is the real root check guarded?

**It was not.** It is now.

**What differs between the copy and the real script:**

- the secrets path, always (the fixed `/etc/cps-secrets` points at a temp dir; this was already so before
  today);
- since c260e05, `[ "$owner" != "0" ]` becomes `[ "$owner" != "<running uid>" ]`, only when the test is not
  running as root.

Nothing else differs.

**Proof that it was unguarded** (prove_guard `--repo`, as root): the owner check was deleted from the REAL
`scripts/production_gates.sh`.

    -        if [ "$owner" != "0" ] || [ $((8#$mode & 8#077)) -ne 0 ]; then
    +        if [ $((8#$mode & 8#077)) -ne 0 ]; then
    34 passed, 2 warnings in 17.71s
    [prove_guard] NOT PROVEN: every test passed with the guard disabled.

On a non-root runner (CI) the same deletion would have failed every test that uses the copy. That failure
comes only from the copy's `assert text.count(owner_check) == 1` ("the preflight's owner check moved"). It is
a tripwire on the text, not a test that the check refuses anything, and the fix it invites is to "update the
test".

**Fix (fc63f66):** `test_secrets_preflight_refuses_a_smoke_password_file_not_owned_by_root`.

- Its copy rewrites ONLY the path and keeps the real `[ "$owner" != "0" ]`.
- As root the file is chowned to 65534; as non-root it is the runner's own. Either way it is not uid 0, and
  the run must stop at the preflight with "is owned by uid N with mode 600".
- 35/35 as uid 0 and as uid 1001.

Rule 49, with the real check deleted:

    FAILED tests/test_production_gates.py::test_secrets_preflight_refuses_a_smoke_password_file_not_owned_by_root
    1 failed, 34 passed, 2 warnings in 17.86s
    E       assert 0 == 1      (the run went through all 9 gates: "gate 9/9: smoke ... failed gate: ")
    [prove_guard] PROVEN ... restored: scripts/production_gates.sh is byte-identical to its saved copy.

Not proven by a mutation run as non-root: prove_guard's containers run as root. The new test was run as uid
1001 and passes there.

## 2. "Require status checks to pass" on main: what happens to commit-on-main-and-push

**Short answer.** Commits pushed directly from this server would be **rejected** by GitHub, unless they
already carry passing required checks, which a new commit never does at push time. The owner's own pushes
would **go through** by default (admin exemption).

From GitHub's documentation (fetched 2026-10-20):

- docs.github.com, "Troubleshooting required status checks": "If required status checks have not passed,
  pushing to a protected branch returns an error similar to this:"

      remote: error: GH006: Protected branch update failed for refs/heads/main.
      remote: error: Required status check "ci-build" is failing

- docs.github.com, "About protected branches": "After all required status checks pass, any commits must
  either be pushed to another branch and then merged or pushed directly to the protected branch."
- The same page: "By default, the restrictions of a branch protection rule don't apply to people with admin
  permissions to the repository ... You can optionally apply the restrictions to administrators and roles
  with the 'bypass branch protections' permission, too" (the "Do not allow bypassing the above settings"
  option).

Applied to this repository:

- **This server pushes with a deploy key.** an SSH test against GitHub (`ssh -T` to its git host) answers "Hi mateia924/CPS!", which is a
  repository key, not a user. A deploy key is not an admin. GitHub's bypass lists name roles, teams, apps and
  Dependabot, not deploy keys.
- Our checks run *after* the push (`on: push`). So a commit pushed directly has no passing check at push time
  and would be refused with GH006. That is every commit this server makes: "commit on main, push" would stop
  working.
- **The workable shape with required checks:** push to a branch, let CI pass, then fast-forward main to the
  same commit. That is exactly what was done today for ci-coverage. Pushing main to an already-checked SHA is
  allowed.
- **The owner's pushes as admin go through** unless "Do not allow bypassing" is ticked. GitHub records them
  as a bypass.

**What I could not verify from the docs:** how GitHub treats a deploy key under classic branch protection,
and whether the GH006 text for a not-yet-run check says "is expected" rather than "is failing". To settle it
empirically without touching main: the owner adds a protection rule with required checks on a scratch branch
pattern (e.g. `protection-test`). I push a fresh commit there and paste GitHub's reply, then the rule and the
branch are removed. About 10 minutes.

Block force pushes and Restrict deletions on main do not affect our flow: we never force-push or delete main.
Today's force-push went to the throwaway branch only.

## 3. Cost of giving the dev container scripts/, git and gpg (not built)

**Why local is not a preview of CI today.** There are four differences, not three:

| | CI runner | dev container |
|---|---|---|
| Repo around backend/ | yes (checkout) | no: `../backend:/app` only (infra/docker-compose.dev.yml:49, 63) |
| git | yes | no (backend/Dockerfile:9 installs libpq5 gettext gosu libmagic1 only) |
| gpg | yes | no |
| uid | 1001 | 0 (root) |

The skipping tests find the repo as `Path(__file__).parents[2]`, which in the container is `/`. They look for
`/scripts`, `/.git` and `/docs`.

The fourth row is what actually hid the production_gates failures: the dev container runs as root, so the
ownership check could never fail there even with `scripts/` present.

**Option A: change the dev container itself.**

- Add `git gnupg` to the Dockerfile's `dev` stage (1 line, about +40 MB, one rebuild).
- Add read-only mounts for `../scripts:/scripts`, `../.git:/.git` and `../docs:/docs` in docker-compose.dev.yml.
- Add `git config --system safe.directory '*'` (the mounted repo is owned by another uid).
- It still runs as root, so it does not close the fourth difference unless the test command runs as a
  non-root user.
- Cost: ~1 hour plus a dev backend/celery recreate (seconds of dev downtime). It mounts `.git` into a
  long-running dev server, which I'd rather not.

**Option B (recommended): a test container per run, the shape used all day today.**

- `scripts/pytest_run.sh` runs pytest in a throwaway container:
  - from a `test` image target (dev + `git gnupg` + safe.directory);
  - with the whole repo mounted read-only at `/workspace`;
  - as uid 1001, like CI.
- The dev server stays as it is.
- Cost: ~1-2 hours.
  - A Dockerfile `test` target.
  - pytest_run.sh changes, keeping the one-run-at-a-time lock.
  - Test-DB ownership/permissions for a non-root user, to be checked: the RLS role setup assumes a superuser
    connection, the same as CI's postgres user.
  - One full-suite run to confirm 987 collected, 0 skipped.
- After that, `pytest_run.sh` locally and CI collect the same set with the same skips. The check_ci_collection
  guard can run in it too.

Either way, the remaining difference is the database service (CI uses a fresh postgres:16-alpine; local uses
the dev postgres's `test_cps`). That is acceptable.
