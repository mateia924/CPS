# 2026-10-20 - Block A: attachment backup, discovery and proposal (nothing built)

Everything below is read-only:
- `mc` inside each MinIO container, with credentials via MC_HOST_* from the
  container's own environment;
- `BEGIN READ ONLY` SQL;
- code, cron and logs.

Nothing was written, and cron was not touched.

## Step 1 - discovery

### 1. The attachments bucket

| env | bucket | objects | size | referenced by a DB row | orphans |
|---|---|---|---|---|---|
| live (infra-minio-1) | cps-attachments | 2425 | 700 KiB | 4 objects, 126,029 B | 2421 objects, 590,989 B |
| staging | cps-attachments-staging | 0 | 0 | 0 | 0 |
| dev | cps-attachments | 2808 | 646 KiB | (test tenants) | most |

Live's 2421 orphans:
- they belong to no live tenant and have no attachment row;
- every one was uploaded between 2026-09-23 and 2026-09-30, across 2306
  tenant prefixes;
- that is pytest's throwaway tenants, from test runs inside the live
  backend container before the dev stack existed. The rows went with the
  test database flush and the objects stayed.

All 4 live rows have their object, and no row's object is missing.

Dev's bucket fills the same way today, because pytest runs with dev's S3
settings. That is about 150-400 objects a day of test litter.

Growth over 30 days, live real content: 2 objects (tenant xxx, 2026-09-23)
plus my 2 smoke files (2026-10-20). Effectively zero, because fatma has
never uploaded. Growth starts when 8.1's mandatory attachments go live. The
upload cap is ATTACHMENT_DEFAULT_MAX_FILE_MB=20. I have no real volume
estimate; any projection would be invented.

### 2. Where backups physically live: everything is on one disk

- Live database: Docker volume infra_postgres_data, under
  /var/lib/docker/volumes.
- Live MinIO: infra_minio_data, in the same place.
- Database dumps: /opt/cps-backups (84 MB, plus dev/ and staging/
  subfolders).
- The "off-server" upload: MinIO bucket `cps-backups-interim`, inside the
  same live MinIO. backup.sh labels it so itself: "ليست حماية off-site
  حقيقية — نفس الخادم" ("not real off-site protection — same server").
- All of it is one filesystem: /dev/mapper/ol-home mounted at /, 384 G, 19%
  used.
- CPS_BACKUP_CLOUD_* (OCI, "M3") are empty in live's .env.
- No cron job, rsync or other process copies anything off the host. The
  only off-host artefact is the git repository, which holds code and logs,
  not data.

**Losing this host loses the database, the attachments and every backup of
the database at once. No copy of any data exists anywhere else.** That is
bigger than the finding we started with. Backing up the attachments onto the
same disk closes the deletion, corruption and DB-file mismatch risks. It does
not close host loss.

### 3. Retention

- prune_backups.sh keeps every backup from the last 30 days, plus the newest
  per calendar month for the 12 months before that. backup.sh runs it on each
  directory.
- It matches only `cps-db-*.sql.gz.gpg`. The 46 UNENCRYPTED live dumps
  `cps-db-*.sql.gz` (2026-09-23 to 2026-10-01, from before encryption) are
  never pruned. Plaintext copies of the live database will stay indefinitely
  (the directory is root 700).
- `cps-backups-interim` has no lifecycle rule and nothing prunes it: 78
  objects, 28 MiB, growing nightly.
- Current counts: live 85 encrypted plus 46 plaintext, staging 13, dev 6.

### 4. Runtime and schedule

- root crontab: `0 3 * * * /opt/cps/scripts/backup.sh >> /var/log/cps-backup.log 2>&1`.
- The last 7 nights took 4-5 s end to end: dump about 412 KB encrypted, then
  the interim upload.
- restore_test.sh runs monthly (`0 4 1 * *`). Its last run was 2026-10-04,
  OK.

### 5. Is the store append-only?

At the application layer, yes:
- there is no DELETE endpoint (`http_method_names` is get/post/head/options);
- a void is a status update (views.py:129-137);
- archive_smoke_tenants changes the tenant's status only;
- no code calls a storage delete, and there are no delete signals;
- there is no admin registration for Attachment;
- keys are `<tenant>/<type>/<year>/<uuid>.<ext>`, so two uploads never share
  a key and nothing overwrites.

The orphans also show that removing rows never removes objects.

At the storage layer, no:
- the backend uses the MinIO root credentials (its MINIO_ACCESS_KEY is the
  root user);
- there are no other users and no restrictive policy;
- versioning is off, and object lock is not supported on this bucket.

Anything holding those credentials, or an operator with `mc`, can delete or
overwrite any object, including the interim database backups. So an
incremental copy is safe against the application's own behaviour. It must
never propagate deletions or overwrites from the source, or one mistake on
the source would be copied into the backup.

### 6. Identity: MinIO's deploymentID

MinIO writes a deployment ID into `<data>/.minio.sys/format.json` (`id`) the
first time a data directory is initialised. It stays with the volume, and
`mc admin info` reports it as `deploymentID`. This is the equivalent of
pg_control_system's system_identifier:
- live    9b9652d0-35a2-4f1b-b397-96e28a574aa5
- staging 515d69d6-7ef7-4103-acc7-617a33e3584e
- dev     bbd8c048-b8ed-4c3d-a4e5-552a8e09ab9f

Proposed field: `minio=<service>/<bucket>#<deploymentID>`, for example
`minio=minio/cps-attachments#9b9652d0-35a2-4f1b-b397-96e28a574aa5`.

Also found: **restore.sh checks no identity today, not even the database
one.** The db=...#id field is read only by the migrate guard. restore.sh
restores whatever file it is given, into a side database, and accepts
unencrypted .sql.gz. "A restore cannot be fed the wrong source" is not true
for the database either, yet.

## Step 2 - proposal (for your decision)

### Shapes, costed with today's numbers

Let N be the bytes the database references; today N is 126 KB on live.

1. **Nightly full copy:** tar the bucket, gzip and gpg it into one artifact,
   exactly the database's shape.
   - Window: N per night. Trivial today. About 1-3 min at 10 GB.
   - Storage: N × (30 dailies + 12 monthlies) = 42 N. At 10 GB that is
     420 GB, more than the 298 G free. It fails on its own growth.
2. **Incremental mirror** (`mc mirror`, no --remove/--overwrite).
   - Window: only new objects, so seconds.
   - Storage: 1 × N.
   - The copies are plaintext, so it does not meet the dumps' encryption bar.
3. **Per-object encryption of new objects only.** RECOMMENDED, with two
   additions:
   - Each night, take the attachment keys referenced by the dump just taken,
     straight from that dump's database state, not a bucket listing. Encrypt
     each object not already in the backup store with gpg (same passphrase,
     AES256), to `/opt/cps-backups/attachments/<key>.gpg`.
   - Write an encrypted manifest per night (`attachments-<ts>.manifest.gpg`)
     listing every referenced key with its sha256 (from the row), its size,
     and the paired database dump's file name.
   - Window: only new objects, plus one manifest. Seconds.
   - Storage: 1 × N, plus small manifests.
   - Orphans are skipped by construction.
   - Nothing on the source can remove a backed-up copy. An object whose bytes
     no longer match its row's sha256 is NOT copied over the backed-up one:
     it is reported, and the old copy is kept.

### Encryption

One gpg file per object, symmetric AES256, with the database dump's passphrase
passed the same way (`--passphrase-file <(printf …)`, rule 50). The manifest
is one gpg file per night. A growing store does not fit a single artifact,
but per-object encryption fits a store that only ever adds.

### backups.log line, one per night, after the database line

    <ts>  <git>  attachments-<ts>.manifest.gpg  <reason>  minio=minio/cps-attachments#9b9652d0-35a2-4f1b-b397-96e28a574aa5  pairs=cps-db-<ts>.sql.gz.gpg  refs=<n> new=<k> bytes=<b> status=OK

On failure: `status=FAILED:<reason>` with the counts reached. Unreachable
storage, a referenced object missing, or a sha256 mismatch on a new object.

### The database dump must never fail because of this

- The attachment step runs only after the database line is written, the
  upload is attempted, and pruning is done. backup.sh's database work is
  complete before it starts.
- It is a separate script, called as
  `if ! timeout 1800 scripts/backup_attachments.sh …; then echo WARNING …; fi`.
  An `if !` condition is exempt from `set -e`, and timeout bounds it.
- That script writes its own backups.log line, FAILED included. Its exit
  status never reaches the database part.
- Rule 49 proof: break MinIO access (a wrong endpoint in a copy) and show
  the database line still written and the dump still decryptable.

### restore.sh / restore_test.sh

- restore.sh gains `--attachments <manifest>`. It restores into a clean
  target bucket by decrypting every key in the manifest.
  - It refuses unless the manifest's `minio=` deploymentID equals the source
    the operator names (`--expect-source <id>`).
  - It gains the same check for the dump's `db=` system_identifier, which is
    missing today.
  - It refuses a manifest whose `pairs=` is not the dump being restored.
- restore_test.sh runs in throwaway containers only:
  - a clean MinIO plus the existing cps_restore_test database;
  - it restores the latest dump and its paired manifest, then starts a
    throwaway backend on both and downloads through the app's signed link.
  - It PASSES only if every attachment row in the restored database downloads
    with bytes equal to the row's sha256.
  - It also checks a canary: a known file uploaded before the backup, on a
    dedicated smoke tenant, must come back byte-identical.
  - A row whose object is missing is a FAIL, with the row named.

### Failure modes, and which are silent

| failure | detected | silent? |
|---|---|---|
| MinIO unreachable or wrong credentials | step fails, FAILED line | **silent in practice**: it lands only in /var/log/cps-backup.log and backups.log, which nobody is alerted on. The database backup has the same gap today. |
| referenced object missing from the bucket | FAILED line, key named | silent in practice, as above |
| object overwritten in place (bytes ≠ row sha256) | reported, old copy kept | silent in practice |
| object deleted at source after backup | not propagated; restore still has it | n/a, protected |
| bit rot or corruption in the backup store | only at restore test (monthly) | silent for up to a month |
| passphrase lost | only at restore | silent until needed, same as the dumps today |
| disk full | step fails | silent in practice |
| host loss | everything gone, including all backups | **silent until needed: there is no off-host copy** |
| uploads after the dump, before the step | picked up the next night | by design |

The common thread: no failure alerts anyone. Each one is written to a file
nobody watches. An alert channel is not in this block's scope. I am naming
it because it decides how silent "silent" is.

## Also found (recorded, not acted on)

- 46 plaintext live database dumps never pruned (§3).
- The interim backup bucket is never pruned (§3).
- The backend holds MinIO root credentials (§5).
- 2421 orphan test objects in live's bucket, plus ongoing test litter in
  dev's (§1).
- restore.sh checks no identity (§6).
