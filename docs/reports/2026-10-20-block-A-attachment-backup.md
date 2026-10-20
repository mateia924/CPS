# 2026-10-20 - Block A: attachments backed up, restore proven, restore identity closed

Shape: per-object encryption (owner decision). Discovery and proposal:
docs/reports/2026-10-20-block-A-attachment-backup-discovery.md.

## The three refinements

### 1. Voided and soft-deleted rows are included

The query, in scripts/backup_attachments.sh:

    SELECT file, sha256, size, status FROM attachments_attachment ORDER BY file

- There is no WHERE clause.
- Attachment has no soft-delete column. Rows are `active` or `voided`, plus
  version chains via `supersedes`, and they are kept forever.
- So every row is included: voided and superseded versions, any scan state,
  archived tenants.
- It runs as $POSTGRES_USER, the table owner pg_dump also uses, so
  row-level security hides nothing.
- Proven: test_every_row_is_backed_up_voided_included_with_the_source_identity
  (a voided row is stored and listed as `voided  new`). On live, the restore
  test downloaded tenant xxx's voided jpeg byte-identical.

### 2. Restore identity, database and attachments

scripts/restore_lib.sh is shared by restore.sh and restore_test.sh. It reads
the named environment's identities live from its running services:
- the cluster's system_identifier;
- MinIO's deploymentID.

It compares them with what the backup recorded:
- the dump's db= field in backups.log;
- the manifest's #minio header;
- the manifest's #pairs header.

restore.sh now requires `--from live|staging|dev`. Restoring into live's own
database also requires `--from live`. Every refusal happens before anything
is created, dropped or written.

Real refusals on this host:

    $ scripts/restore.sh --from live /opt/cps-backups/dev/cps-db-20261020-230409.sql.gz.gpg
    REFUSED: cps-db-20261020-230409.sql.gz.gpg was taken from postgres/cps#7691754161498136610, not from live (postgres/cps#7686947508661833762).
    $ scripts/restore.sh --from staging /opt/cps-backups/dev/cps-db-20261020-230409.sql.gz.gpg
    REFUSED: ... was taken from postgres/cps#7691754161498136610, not from staging (postgres/cps_staging#7691316877294727202).
    $ scripts/restore.sh --from live /opt/cps-backups/cps-db-20260923-112327.sql.gz
    REFUSED: cps-db-20260923-112327.sql.gz has no recorded source (no db= field ...) — its origin cannot be checked against live (...).

Rule 49, backend/tests/test_restore_identity.py, through prove_guard, /opt/cps
untouched each time:

| guard disabled | failing test | proven |
|---|---|---|
| dump identity comparison | test_a_staging_dump_named_as_live_is_refused_by_name | yes |
| no-recorded-source refusal | test_a_dump_with_no_recorded_source_is_refused | yes |
| manifest minio= comparison | test_a_staging_manifest_with_a_live_dump_is_refused_by_name | yes |
| manifest pairs= check | test_a_manifest_paired_with_another_dump_is_refused | yes |
| live database needs a live dump | test_restoring_into_lives_own_database_needs_a_live_dump (restore continued: `gzip: stdin: unexpected end of file`) | yes |

Consequence:
- Dumps from before 2026-10-17 have no db= line: the 46 plaintext dumps and
  the encrypted ones up to 2026-10-17. restore.sh refuses all of them.
- That is the honest state, since their origin cannot be checked.
- A real disaster restore from one of them needs a deliberate path, which
  is not built. See also A below.

### 3. The database dump cannot be failed by the attachment step (built first)

- backup.sh calls the step only after the dump is encrypted, logged and
  pruned, and only as
  `if ! … timeout "${CPS_ATT_TIMEOUT:-1800}" scripts/backup_attachments.sh; then <warning>; fi`.
- A condition is exempt from `set -e`, and timeout bounds a hang.
- The step writes its own backups.log line, FAILED included. A TERM from
  timeout writes FAILED:terminated.

backend/tests/test_backup_attachments.py runs the real backup.sh against a
scratch directory, with a fake docker and real gpg. With MinIO down and with
MinIO hanging (timeout 3 s), backup.sh exits 0, the db= line is written, the
dump decrypts, and the attachment line is FAILED:minio-unreachable or
FAILED:terminated with pairs= set.

Rule 49: with the `if !` wrapper removed, the down and hang tests both FAILED
(`assert 1 == 0`, backup.sh exit 1). The missing-object and mismatch tests
failed too, because every failing attachment step would then abort backup.sh.

## What was built

- scripts/backup_attachments.sh: per-object gpg (AES256, the dump
  passphrase, fd not argv).
  - Every referenced object not yet stored is streamed from MinIO,
    encrypted to objects/<key>.gpg, then decrypted back and its sha256
    checked against the row before it is kept.
  - A mismatch is reported and not stored. An already stored copy is never
    replaced.
  - A missing object is reported by key.
  - One encrypted manifest per run.
  - One backups.log line:
    `minio=minio/<bucket>#<deploymentID> pairs=<dump> refs new kept bytes missing mismatch status`.
  - umask 077.
- scripts/backup.sh: the guarded hook, for live and for --target dev and
  staging. CPS_BACKUP_ROOT is overridable for tests only. The stale
  "Sprint 5.1 adds the attachments bucket here" comment is removed.
- scripts/restore_lib.sh and scripts/restore.sh: as in 2. above, plus
  `--attachments <manifest> --attachments-into <minio-container>`.
- scripts/restore_test.sh, `[--target live|dev|staging]` (default live, as
  in cron):
  1. source checks on the dump and the paired manifest;
  2. the dump into the throwaway cps_restore_test database;
  3. the objects into a THROWAWAY MinIO with fresh credentials;
  4. a THROWAWAY backend, pointed only at those two, downloads every row
     through AttachmentDownloadView with a signed link and compares the
     body with the row's sha256. Rows the app withholds by scan state are
     read through its storage layer.
  5. FAIL on any bad row (named), or if not one row downloaded.

Tests: test_backup_attachments.py (6 tests), test_restore_identity.py (6).
Store permissions are their own proven test (without the umask, a tenant
folder came out 0o40755).

## The deliverable: restore test, file uploaded BEFORE the backup, byte-identical AFTER

Dev:
- 2 attachments created through the public API on smoke-backup-*, one then
  voided;
- then `backup.sh --target dev`: refs=2 new=2 status=OK;
- then `restore_test.sh --target dev`:

      ROW OK   …/66707829-….png [active] 1124 bytes, downloaded through the app, HTTP 200
      ROW OK   …/8522c275-….png [voided] 1124 bytes, downloaded through the app, HTTP 200
      attachments: 2 downloaded byte-identical, 0 verified via storage, 0 bad (restored=2 skipped=0 bad=0)
      OK

Rule 49 on the deliverable, in a copy of the tree (.env linked, not copied).
The copy's restore_lib writes each object under `<key>.lost`, so the
database comes back and its objects do not:

    attachments restored: restored=2 skipped=0 bad=0        <- the restore step itself claims success
    ROW BAD  …/66707829-….png [active] 0 bytes, NOT READABLE: FileNotFoundError: File does not exist: …
    ROW BAD  …/8522c275-….png [voided] 0 bytes, NOT READABLE: FileNotFoundError: File does not exist: …
    FAILED: attachments: 0 downloaded byte-identical, 0 verified via storage, 2 bad
    exit 1

Only the byte check catches the restored-row-with-a-dead-object case; the
restore step's own counts do not.

Live:
- `backup.sh` 23:13: dump 424 K, interim upload OK, then
  `Attachments OK: 4 referenced, 4 new (126029 bytes)`, status=OK, total
  5.5 s.
- `restore_test.sh` 23:14:

      tenants: restored=17 live=17 | posted entries: restored=29 live=29
      attachments restored: restored=4 skipped=0 bad=0
      ROW OK   02efa958…/bank/2026/9552745c….png [active] 707 bytes, downloaded through the app, HTTP 200
      ROW OK   0dec78b2…/legalentity/2026/28983e32….png [active] 90352 bytes, downloaded through the app, HTTP 200
      ROW OK   0dec78b2…/legalentity/2026/b78f7a6d….jpeg [voided] 34263 bytes, downloaded through the app, HTTP 200
      ROW OK   80b8e6df…/bank/2026/634809e2….png [active] 707 bytes, downloaded through the app, HTTP 200
      OK

  restore_tests.log:
  `OK  cps-db-20261020-231336.sql.gz.gpg  17 17 29 29  attachments: 4 downloaded byte-identical, ...`.

The two smoke-storage files and xxx's files were all uploaded before this
backup. No throwaway container and no cps_restore_test database remain.

## Size and runtime (cron NOT touched)

- Bucket today: 4 referenced objects, 126,029 B on live. The 2421 orphans
  are not backed up, by construction.
- Nightly runtime: 4-5 s before, 5.5 s with attachments on the first run (4
  new objects). Later nights only copy new objects.
- Cost grows with new uploads per day, not with bucket size: about two
  docker exec round trips plus gpg per new object (measured 2 objects in
  about 2 s on dev).
- So the window does not change materially at today's volume. If 8.1
  brings hundreds of uploads a day, the per-object exec becomes the cost
  (minutes, not hours), and a batch export would replace it.
- The 03:00 cron line is unchanged. Tonight's 03:00 run will execute this
  step automatically, because it is inside backup.sh, which cron already
  runs. Expected: refs=4, new=0, kept=4.

## Report-only items (no work done)

### A. Off-host: in-Kingdom by default (owner, 2026-10-20)

There is no engineering reason against Jeddah or Riyadh:
- A nightly encrypted upload is not latency-sensitive. From this host Jeddah
  answers in about 0.32 s and Riyadh in about 0.41 s, against Frankfurt's
  0.07 s. At MB scale that is noise. At GB scale, multipart upload (boto3,
  already used by upload_backup_to_s3.py) absorbs it.
- Both are reachable over HTTPS today.
- Both expose the same S3-compatible API backup.sh already speaks. Setting
  CPS_BACKUP_CLOUD_* switches it over.

Volume today:
- live: 86 encrypted dumps, 31 MiB in total, about 0.42 MB per night;
- attachments store: 165 KB;
- steady state at current size (30 daily plus 12 monthly dumps): about 18 MB.

| | OCI Jeddah (me-jeddah-1) | OCI Riyadh (me-riyadh-1) |
|---|---|---|
| storage cost at today's volume | under the Always Free 20 GB object-storage allowance, so $0. Beyond it, OCI prices are the same in every commercial region (about $0.0255/GB-month standard, about $0.0026 archive). | same |
| egress on restore | OCI includes the first 10 TB/month of outbound transfer. A full restore today is about 31 MB, so $0. | same |
| restore path | download dump, manifest and objects over the S3-compatible endpoint `https://<namespace>.compat.objectstorage.me-jeddah-1.oraclecloud.com` (boto3 or the OCI CLI), then restore.sh / restore_test.sh | same, with the `me-riyadh-1` endpoint |
| prerequisites | an OCI tenancy subscribed to the region, a bucket, and a customer secret key (the owner's "M3") | same |

Cost and restore path are identical. The choice is the owner's: which region
her tenancy is subscribed to, and whether two in-Kingdom copies are wanted.

Gap carried into that block: `--from live` reads live's identity from
running services. After host loss there is no live to ask, and a new
database has a new system_identifier, so the check as built would refuse a
genuine disaster restore. The off-host block needs an explicit "restore as
<recorded identity>" path, typed by the operator.

Recorded separately, dated, for the owner's regulatory adviser (DEPLOY.md):
the primary host is not in the Kingdom. It is not an OCI instance, and its
round-trip times put it near Frankfurt.

### B. The 46 unencrypted dumps

- 46 files, 9.9 MB, 2026-09-23 11:23 to 2026-10-01 12:44.
- Encryption arrived in 81ae340 (2026-10-01 14:15). The first encrypted dump
  is 2026-10-01 14:05.
- All 46 were written before encryption existed. None has an encrypted
  dump covering the same point in time: every encrypted dump is later.
- 25 have no backups.log line, because its first entry is 2026-09-29 13:59.

By day:

| day | files | bytes |
|---|---|---|
| 09-23 | 4 | 253,462 |
| 09-24 | 6 | 506,248 |
| 09-25 | 1 | 90,700 |
| 09-26 | 7 | 697,949 |
| 09-27 | 1 | 110,661 |
| 09-28 | 1 | 200,810 |
| 09-29 | 4 | 963,518 |
| 09-30 | 13 | 4,128,690 |
| 10-01 | 9 | 2,969,029 |

Newest per month: cps-db-20260930-220943.sql.gz (Sept) and
cps-db-20261001-124453.sql.gz (Oct). Under the retention policy (30 days
plus newest per month), every file except those two would have expired by
2026-10-31. That is the natural "redundant" set. Each file is still a unique
point in time.

Does a current path still produce plaintext? Not as routine:
- backup.sh, the only pg_dump in CPS, encrypts and removes the raw file.
- staging_refresh.sh and restore_test.sh only read encrypted dumps.
- No plaintext dump exists newer than 2026-10-01 12:44.

**One latent path existed, and is CLOSED in this block** (owner, item 2):
- backup.sh wrote cps-db-<ts>.sql.gz before gpg. A gpg failure or kill left
  plaintext.
- The pruner only matched .gpg.
- The files were 0644.

See "Item 2" below. Not one plaintext file has appeared since encryption
started. The 46 remain as they are, now 0600, listed by the pruner on every
run and never deleted by it.

### C. Alerting: heartbeat, folded into the UptimeRobot item

- Today nothing alerts on anything. Live mail is the dummy backend.
- The failure that matters most writes no line at all: cron not running,
  the host down, or the script dying before its first log line.
- A heartbeat catches it: a check-in URL pinged at the very end of a
  successful backup.sh. UptimeRobot's heartbeat monitors and
  healthchecks.io both offer this. A missing ping inside the window
  (03:00 plus a grace period) alerts.
- Include a separate attachments outcome: ping on DB success always, plus a
  second check for status=OK of the attachment line, so a broken attachment
  step is not hidden behind a healthy dump.

## Item 2 (owner): no plaintext dump, a pruner that sees it, owner-only files

- backup.sh streams `pg_dump | gzip | gpg -o cps-db-<ts>.sql.gz.gpg.part`.
  The output is decrypt-checked for content and renamed when complete.
  Plaintext never touches the disk.
- The EXIT trap removes the encrypted partial on any exit bash survives:
  errors, plus INT/TERM/HUP routed through it.
- A SIGKILL can leave only ciphertext, which the pruner removes after an
  hour.
- The passphrase check now runs before the dump.
- The pruner removes any plaintext cps-db-*.sql.gz newer than 2026-10-01
  14:15:53, when encryption arrived. Older ones are the owner's pending
  item B: listed, never deleted.
- umask 077 in backup.sh and backup_attachments.sh. The 153 existing
  backup files that were group/other-readable are now 0600 (0 left).
- Real runs on dev and live with the new code: no plaintext. The live
  pruner listed 46 and removed 0. Both restore tests OK.

Rule 49, backend/tests/test_backup_plaintext.py, through prove_guard:

| guard disabled | result |
|---|---|
| streaming replaced by the old dump-then-encrypt | SIGKILL and SIGTERM mid-dump: `a plaintext dump survived the kill: ['cps-db-…sql.gz (0 bytes)']`. PROVEN. |
| EXIT trap removed | SIGTERM: `the trap left files behind: ['cps-db-….sql.gz.gpg.part']`. PROVEN. |
| pruner's plaintext removal disabled | the post-encryption plaintext file remains. PROVEN. |
| umask removed from backup.sh | `['cps-db-….sql.gz.gpg 0o100644']`. PROVEN. |

The first attempt at the first proof was NOT PROVEN for SIGKILL. My
detector only looked at contents, and the plaintext file was still empty
at kill time. The detector now also flags plaintext names. Re-proven as
above.

## Item 3 (owner): the rule-50 guard's blind spot

What the guard matches (SECRET_ON_ARGV, test_smoke_sh_credentials.py:81-85),
over scripts/*.sh only:

    --passphrase(?!-file)[ =] | --password[ =] | -e [A-Z_]*(PASSWORD|PASSPHRASE|SECRET|TOKEN|API_KEY|ACCESS_KEY)[A-Z_]*=
    | -d ".*\$[A-Z_]*(PASSWORD|SECRET|TOKEN) | Authorization: Bearer \$

What it cannot see:
1. `(-e|--env)[ =]NAME=<value>` where NAME matches none of those words, but
   the value carries a secret;
2. `[a-z+]+://[^/:@ ]*:[^/@ ]+@`: a URL with inline credentials, literal
   or interpolated, anywhere on a command line;
3. any file outside scripts/*.sh.

Whole-repo search (scripts, Makefile, .github, infra, backend apps/config,
frontend scripts, docs/ops), comments excluded:

| where | what | status |
|---|---|---|
| scripts/restore_test.sh:147, :181 | `-e DATABASE_URL="$TEST_DATABASE_URL"`, live's DB password, monthly cron path | FIXED: by name. ps sampling: 35/200 samples carried it before, 0/193 after. |
| docs/ops/BACKUP.md:44 | `gpg --passphrase "$CPS_BACKUP_ENCRYPTION_PASSPHRASE"` in operator instructions | FIXED: `--passphrase-file <(printf …)` |
| scripts/ci_local.sh:91 | `-e DATABASE_URL=postgres://postgres:postgres@localhost…` | throwaway CI value, same as the declared POSTGRES_PASSWORD=postgres entry |
| scripts/backup_attachments.sh:86, restore_lib.sh:19 | `MC_HOST_m="http://${MINIO_ROOT_USER}:${MINIO_ROOT_PASSWORD}@…"` | safe: the literal `${…}` text crosses into the container unexpanded; only the shell inside sets it as an environment variable |
| infra/docker-compose*.yml | DATABASE_URL with ${POSTGRES_PASSWORD} | container environment, not argv |
| Python subprocess calls, Makefile, workflow run lines | none | none |

So: 2 real instances, both fixed. The guard fix (patterns 1-3) is a dated
open item in DEPLOY.md, not built.

**Incident, my mistake, recorded in DEPLOY.md:**
- My first attempt at the ps measurement ran `grep -F -- "$PW"` about 190
  times over about 20 s.
- That put live's POSTGRES_PASSWORD in grep's own arguments, visible to
  any local user.
- It also made the measurement meaningless: 192/192 matches, all grep
  itself.
- Redone with the pattern read from a file. Rotation is the owner's call.

## A flaky guard found and fixed on the way

- The full suite failed once on test_every_spec_in_the_repo_is_run.
- check_e2e_runners.sh (written this morning) tested
  `grep -v … | grep -qF spec` under pipefail. grep -q exits at the first
  match, the upstream grep dies of SIGPIPE, and pipefail makes the
  pipeline false.
- Measured: 32 false failures in 300 runs. Now one awk process: 0 in 300.
- prove_guard.sh had the same shape twice (`echo "$OUTPUT" | grep -q`).
  Now here-strings.
- docker_firewall_guard.sh has the shape but no pipefail, so its status is
  grep's own. Left untouched (live 2-minute cron).

## Also

- Two smoke tenants left on live: smoke-storage-1792522506 (unreachable;
  its password lived only in one shell) and smoke-storage-1792522563. Now a
  dated open line in DEPLOY.md.
- **Rule 50, found and fixed in this block:**
  - restore_test.sh passed the restore database's URL, password included,
    as `-e DATABASE_URL="$TEST_DATABASE_URL"` on two `docker compose exec`
    command lines: the manage.py check and the posted-entries count. That
    is live's monthly cron path.
  - Both now pass it by name (`DATABASE_URL=… $COMPOSE exec -e DATABASE_URL`),
    the way backup.sh passes its upload keys.
  - The rule-50 guard (test_smoke_sh_credentials.py SECRET_ON_ARGV) could
    not see it: its pattern matches `-e NAME=` only for names containing
    PASSWORD/SECRET/TOKEN/..., never a URL that carries a password.
    Recorded as open; the guard was not widened in this block.
  - The new throwaway backend gets its environment through `--env-file <(…)`.
