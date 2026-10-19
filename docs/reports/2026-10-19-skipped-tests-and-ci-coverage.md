# The 47 skipped tests, and the 21 files GitHub CI never runs (2026-10-19)

Read-only investigation. Nothing changed.

## The 43 extra skips are not from 8.0

Block 8.0's own files skip nothing:
`tests/test_sprint8_block0.py` and `tests/test_purchasing_defaults_backfill.py` ran
42 of 42 with 0 skipped.

All 47 skips in the dev container come from five files. Each skips for the same kind of
reason: the dev container mounts only `backend/` at `/app`, so `scripts/` (and gpg, git)
are absent. Four of the five were added by the Pre-deploy blocks on 2026-10-17/18, not by
8.0:

| Skips | File | Skip condition (verbatim reason) | Added in |
|---|---|---|---|
| 31 | `test_production_gates.py` | needs the repo's scripts/ (CI and ci_local have it; the dev container mounts only backend/) | 8f9a0e6 Pre-deploy 1, 2026-10-17 |
| 7 | `test_smoke_sh_credentials.py` | same | 907f5e3 Pre-deploy 2, 2026-10-18 |
| 4 | `test_backup_gpg_passphrase.py` | needs gpg and the repo's scripts/ (ci_local installs gnupg; the dev image has neither) | 322560b Pre-deploy 4, 2026-10-18 |
| 1 | `test_backup_upload_credentials.py` | needs the repo's scripts/ (ci_local runs it) | 05b64b8 Pre-deploy 5, 2026-10-18 |
| 4 | `test_deploy_sh_guards.py` | needs the repo root and a git binary (CI does; the dev container does not) | 183030c, 7.0.2, 2026-10-04 |

4 + 31 + 7 + 4 + 1 = 47. The "steady 4" were the `test_deploy_sh_guards.py` tests; the
other 43 arrived in Pre-deploy 1-5. I did not report the skip count in those blocks, so
the jump was first visible in 8.0's run.

`test_attachments.py` and `test_financial_controls.py` can also skip, but they skipped
nothing here. Their marked tests (`clamav`/`minio`) are the 2 *deselected*, not skipped.

## Where each group runs

| Group | dev full suite | ci_local (`scripts/ci_local.sh`) | GitHub CI (`.github/workflows/ci.yml`) |
|---|---|---|---|
| test_production_gates (31) | skips | **runs**, asserts "31 passed" (line 107) | **never**: not in any of the four file lists |
| test_smoke_sh_credentials (7) | skips | **runs**, asserts "7 passed" (line 109) | **never**: not listed |
| test_backup_gpg_passphrase (4) | skips | **runs**, asserts "4 passed" (line 112; installs gnupg) | **never**: not listed (and no gnupg installed) |
| test_backup_upload_credentials (1) | skips | **runs** (line 114) | **never**: not listed |
| test_deploy_sh_guards (4) | skips | **runs**, asserts "4 passed" (line 104) | **never**: not listed |

So none of them skips everywhere. All five run in ci_local, with their pass counts
asserted. The last ci_local run was 2026-10-18 19:52, with every step OK
(`docs/ops/ci-local.log`). ci_local is run by hand, though, and it predates 8.0. None of
them ever runs in GitHub CI.

e2e does not exercise any of them (it drives the dev stack through the browser).

## The larger finding: GitHub CI runs fixed file lists, and 21 test files are in none

GitHub CI's pytest is four steps, each with an explicit list of test files ("accounting",
"assets and treasury", "attachments and permissions", "the rest"). It has no catch-all and
no glob. 78 of the 99 test files are listed. These 21 are in no list, so **GitHub CI has
never run them**:

- the five script tests above;
- `test_accounting_debt_functions.py`, `test_no_manual_posted_filter.py`,
  `test_password_reset.py`, `test_default_approval_rules.py`;
- every sprint-7 block file: `test_sprint7_block0.py`, `_block0_1`, `_block1`, `_block2`,
  `_block2_5`, `_block2_6`, `_block3`, `_block4`, `_block5`, `_block5_followup`;
- both 8.0 files: `test_sprint8_block0.py`, `test_purchasing_defaults_backfill.py`.

They all run in the dev full suite and in ci_local's full-suite step. But "CI green" on
GitHub has said nothing about the inventory engine, password reset, or 8.0 since those
files were added.

Proposed fix (its own block; not done, needs your go-ahead): a fifth CI step that runs
every `test_*.py` not in the other four lists, computed at run time. Plus a structural
test that fails when a test file is in no CI group, so the gap cannot reopen silently.
