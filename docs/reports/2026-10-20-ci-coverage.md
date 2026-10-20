# CI coverage: every test file runs, a guard proves it, failures go red, skips are capped (2026-10-20)

This closes clause (أ) of the start-condition exception (b2b56e3): "GitHub CI does not run 21 test files".
No deploy in this block.

## 1. Why each file never ran (diagnosed, not guessed)

**The mechanism is the same for every file: an explicit allowlist.**

- `.github/workflows/ci.yml` ran pytest four times, and each step named its files one by one.
- pytest collects only the paths it is given, so a file named in no step was never collected. No marker,
  path rule, missing `__init__.py` or naming problem was involved:
  - `backend/pyproject.toml` collects `test_*.py` under `tests`;
  - no file skips at module level;
  - the marker filter deselects only the clamav/minio tests.
- The lists last changed in **2ca1422 (2026-10-04)**. Every file below was added on or after that day and
  never appended.
- The record said 21 files; by today it was **24** (test_email_backend_setting, test_sprint8_block1,
  test_create_test_user joined since).

| File | Added | Mechanism |
|---|---|---|
| test_accounting_debt_functions.py | 485c051 2026-10-04 | not named in any of ci.yml's four file lists |
| test_backup_gpg_passphrase.py | 322560b 2026-10-18 | same |
| test_backup_upload_credentials.py | 05b64b8 2026-10-18 | same |
| test_create_test_user.py | a82a6df 2026-10-20 | same |
| test_default_approval_rules.py | b240087 2026-10-14 | same |
| test_deploy_sh_guards.py | 183030c 2026-10-04 | same |
| test_email_backend_setting.py | 9bace75 2026-10-19 | same |
| test_no_manual_posted_filter.py | 485c051 2026-10-04 | same |
| test_password_reset.py | f82aded 2026-10-10 | same |
| test_production_gates.py | 8f9a0e6 2026-10-17 | same |
| test_purchasing_defaults_backfill.py | bd16dff 2026-10-19 | same |
| test_smoke_sh_credentials.py | 907f5e3 2026-10-18 | same |
| test_sprint7_block0.py | 268b137 2026-10-04 | same |
| test_sprint7_block0_1.py | 3a49065 2026-10-04 | same |
| test_sprint7_block1.py | db555ec 2026-10-05 | same |
| test_sprint7_block2.py | 5194729 2026-10-05 | same |
| test_sprint7_block2_5.py | da73791 2026-10-05 | same |
| test_sprint7_block2_6.py | eb6aad2 2026-10-05 | same |
| test_sprint7_block3.py | e243230 2026-10-13 | same |
| test_sprint7_block4.py | 5b7f2fa 2026-10-14 | same |
| test_sprint7_block5.py | efe6b40 2026-10-14 | same |
| test_sprint7_block5_followup.py | 66e1830 2026-10-15 | same |
| test_sprint8_block0.py | bd16dff 2026-10-19 | same |
| test_sprint8_block1.py | 1065a3d 2026-10-20 | same |

## 2. The fix

- `scripts/ci_test_groups.sh` is the one definition of the split.
  - Three named groups are kept, because they narrow which part of the suite a run died in (CI #62/#63).
  - The fourth group is not a list. It is every file under `backend/tests` minus the three groups, so a new
    file runs by default.
- `.github/workflows/ci.yml`'s four pytest steps read their group from that file.

**The fix immediately exposed real breakage.** The first CI run with all files collected (run 199) was RED:
4 tests in `test_production_gates.py` failed on GitHub's runner. That file had never run in CI. The secrets
preflight requires the secret file to be owned by uid 0, and the runner is uid 1001, so a file the test
creates can never be root-owned.

- **Fix (c260e05):** only the test's own copy of the script expects the running uid, the same way it
  already rewrites the secrets path. `production_gates.sh` still requires root.
- Verified: 34/34 as uid 1001 locally.

## 3. The durable guard: scripts/check_ci_collection.sh

It runs as a CI step before the tests (no continue-on-error, so it fails the job) and in `ci_local.sh`.

**Check (a): the Gate covers every pytest step.** Every step whose `run` invokes pytest must have an `id`, and
the Gate must read `steps.<id>.outcome` for it. Each such step must also run exactly one group from
ci_test_groups.sh, and each group exactly once. A step the Gate does not read is invisible: with
`continue-on-error: true` it looks green whatever happened.

**Check (b): collected files equal present files.** The test files those steps collect must equal the test
files present under `backend/`, each collected exactly once. It fails with the names.

Rule 49, check (b): a throwaway `backend/apps/purchasing/tests_rule49/test_throwaway_rule49.py`. The fixed
config collects only `backend/tests`. It was removed by a trap afterwards.

    check_ci_collection: 4 pytest steps in ci.yml, all read by the Gate
    check_ci_collection: 103 test files present, 102 collected by the CI steps
    FAIL: test file(s) present but collected by no CI step:
      apps/purchasing/tests_rule49/test_throwaway_rule49.py
    exit=1
    [cleanup] throwaway removed

Rule 49, check (a): a throwaway pytest step added to a copy of ci.yml (`CI_YML=` points the guard at it, so
the real workflow could not be left modified). The Gate does not read the new step.

    FAIL: ci.yml pytest steps and the Gate do not match:
      pytest step not covered by the Gate (steps.test_throwaway.outcome missing): Tests (pytest) — throwaway rule-49 step
      group $CI_GROUP_ACCOUNTING is run by 2 pytest steps, expected 1

On the real tree: `4 pytest steps in ci.yml, all read by the Gate` / `102 test files present, 102 collected` /
`every test file is collected exactly once`.

## 4. How a failing pytest step turns the workflow red

- Each pytest step has `continue-on-error: true` (ci.yml lines 175, 202, 228, 254). A failing step, even with
  an explicit `exit 1`, does not fail the job by itself.
- **What does:** the step `Gate — fail the job if any pytest group actually failed` (ci.yml:283).
  - `if: always()` (ci.yml:284), so it runs even after a failure.
  - It reads each step's `steps.<id>.outcome`, which is the result *before* continue-on-error overrides it
    (ci.yml:287-290).
  - It exits 1 if any outcome is not `success`. The backend job fails, `e2e` (which `needs: [backend,
    frontend]`) is skipped, and the workflow run is red.
- The Gate's list of step ids is hand-maintained. Check (a) above makes a step it misses fail CI.
- **Required status check on main: there is none.** The public API reports main `protected: false`, required
  status checks `enforcement_level: off`, no contexts. A red run marks the commit red but blocks nothing.
  Enabling protection (requiring `backend`, `frontend`, `e2e`) needs repository admin rights. This session has
  no GitHub credentials, so it is **open for the owner**.

**Proof from GitHub, not a local run:** branch `ci-red-proof` = the fixed CI plus one test that fails on
purpose (`backend/tests/test_ci_red_proof.py`, `assert 1 == 2`). See section 6 for the run, the annotations,
the branch's deletion, and main's green run.

## 5. Skips

**In CI: 0 skipped.** Two things show it:

- A CI-like full run (repo mounted, git and gpg installed, which is what the runner has) gave
  **987 passed, 0 skipped, 2 deselected**.
- The first green CI run with every file collected: section 6.

**In the dev container: 59 skipped, all environmental.** That container mounts only `backend/` and has
neither git nor gpg. Every reason string below is still true for the dev container:

| Skips | File | Reason (verbatim) | Still true? |
|---|---|---|---|
| 34 | test_production_gates.py | needs the repo's scripts/ (CI and ci_local have it; the dev container mounts only backend/) | yes, for the dev container |
| 13 | test_deploy_sh_guards.py | needs the repo root and a git binary (CI does; the dev container does not) | yes |
| 7 | test_smoke_sh_credentials.py | needs the repo's scripts/ (CI and ci_local have it; ...) | yes |
| 4 | test_backup_gpg_passphrase.py | needs gpg and the repo's scripts/ (ci_local installs gnupg; the dev image has neither) | yes |
| 1 | test_backup_upload_credentials.py | needs the repo's scripts/ (ci_local runs it) | yes |

Total 59.

One correction: four of these reasons say "CI has it". That was literally true (CI had `scripts/`) but
meaningless until today, because CI never collected those files. From c260e05 on they run in CI. No skip
lacks a reason, and no reason has stopped being true.

**The skip ceiling, per CI step,** recorded today in `scripts/ci_test_groups.sh`:

| Step | Ceiling |
|---|---|
| accounting | 0 |
| assets and treasury | 0 |
| attachments and permissions | 0 |
| the rest | 0 |

The Gate fails if any step's skip count rises above its ceiling. A new skip needs a deliberate bump there,
plus a dated line in this report, like any accepted exception.

Each step also posts its `SKIPPED` lines as a notice annotation. **That annotation is truncated at 60 lines
per step** (its title says "first 60 lines only"), so a short list there is not proof of a complete one. The
count in the step's summary line is authoritative.

## 6. Tests actually executed in CI (from the runs' own annotations)

Read through the public check-run annotations API. Raw logs need credentials this session does not have, so
commit b05909b made every step post its own pytest summary line as an annotation. Nothing else changed in
that commit.

| Run | Commit | accounting | assets+treasury | attachments+permissions | rest | Executed | Skipped | Result |
|---|---|---|---|---|---|---|---|---|
| **198, BEFORE** | b05909b (old lists) | 245 | 193 | 111 | 157 | **706** | 0 | green, on a false signal |
| 199 | fc8183e (all files collected) | 245 | 193 | 111 | 434 + **4 failed** | 987 | 0 | **RED**: production-gates x4 (section 2) |
| **201, AFTER** | c260e05 | 245 | 193 | 111 | 438 | **987** | **0** | green |
| 202, red proof | 2cf0fd1 (c260e05 + throwaway failing test) | 245 | 193 | 111 | 438 + **1 failed** | 988 | 0 | **RED**, by design |

- **281 more tests now run in CI per push** (706 -> 987).
- 2 deselected in every run: the clamav/minio-marked tests, run on dev/staging by `make test-integration`.

**The red proof (run 202, https://github.com/mateia924/CPS/actions/runs/39413860630):**

- backend job: failure. e2e: skipped. Workflow: failure.
- Annotations:

      FAILED test_ci_red_proof.py::test_deliberate_failure_for_the_ci_gate - AssertionError: deliberate failure: the CI Gate must turn this run red
      assert 1 == 2
      ============ 1 failed, 438 passed, 2 warnings in 253.90s (0:04:13) =============
      Pytest group(s) failed: the-rest — see each group's own annotation above.

- Branch `ci-red-proof` was deleted (remote and local) right after. Main's own run on the merged commits:
  **run 203, 2d848af: success** (https://github.com/mateia924/CPS/actions/runs/39416902540). The only remote
  branch is `main`.
