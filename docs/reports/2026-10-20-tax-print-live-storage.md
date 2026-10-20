# 2026-10-20 - Printed tax invoice, live attachment storage, ClamAV consequences, CI-env parity

## 1. Printed tax invoice: tax-by-code table vs the server, to the cent

Demonstration setup:
- A fresh dev smoke tenant. Everything was created through the public API,
  and the print page was read in a real browser.
- The spec was never committed. It is kept in the scratchpad as
  97-invoice-tax-print-demo.spec.ts.
- The invoice had 72 lines: 6 products at 0.10 / 0.07 / 33.33 / 0.01 / 1.15
  / 19.99, times quantities 1 / 3 / 7 / 0.33 / 11 / 0.07, twice, spread over
  S (15%) and Z (0%).
- "Server" means the server's own line_subtotal / line_tax, summed in
  integer cents, plus the invoice's subtotal / tax_total.

Before the change (browser parseFloat sum):

    TAX Z: printed base 844.02 tax 0.00     | server base 844.02 tax 0.00     | AGREE | browser float before formatting: base 844.0200000000002 tax 0
    TAX S: printed base 1,604.28 tax 240.67 | server base 1604.28 tax 240.67  | AGREE | browser float before formatting: base 1604.2799999999997 tax 240.67
    TAX sum of printed rows: base 2448.30 tax 240.67 | server invoice subtotal 2448.30 tax_total 240.67 | AGREE
    TAX mismatching rows: 0

They agreed to the cent. The server rounds tax per line and sums those
rounded values (apps/sales/services.py:38-44), so the browser's method was
the same method. Only float representation differed, and display rounding
to 2 places hid it: 844.0200000000002 and 1604.2799999999997.

Moved to the server anyway, as instructed:
- InvoiceSerializer.tax_summary sums in Decimal from the lines' own rounded
  figures, grouped by (code, rate) in line order. The viewset prefetches
  lines__tax_code.
- print/invoices/[id] renders `invoice.tax_summary` as is. No parseFloat is
  left on the page.
- Grouping is now by (code, rate). The browser grouped by code alone and
  labelled the row with the first line's rate, so a rate change between
  line snapshots would have merged into one mislabelled row.

After the change, the same demonstration:

    TAX Z: printed base 844.02 tax 0.00     | server base 844.02 tax 0.00    | AGREE
    TAX S: printed base 1,604.28 tax 240.67 | server base 1604.28 tax 240.67 | AGREE
    TAX sum of printed rows: base 2448.30 tax 240.67 | server invoice subtotal 2448.30 tax_total 240.67 | AGREE

Screenshot: docs/uat/screens/8.2.1-tax-print/print-invoice.png.

Guards:
- backend/tests/test_invoice_tax_summary.py. On the same 72-line invoice,
  every row must equal the Decimal sum of its lines as an exact string, the
  rows must add up to subtotal and tax_total, and the totals must be
  2448.30 / 240.67. A second test: one code at two rates gives two rows.
- Rule 49, through prove_guard, /opt/cps untouched:
  - float sum in the serializer:
    `AssertionError: {'code': 'Z', ... 'base': '844.0200000000002'}` /
    `assert '844.0200000000002' == '844.02'`;
  - grouping by code only: both tests FAILED (`{('S','None'),('Z','None')}`,
    `[('None','20.00')]`).
- frontend/scripts/check-money.sh (prebuild) gains: no `parseFloat(`,
  `Number(` or `+ x.line_*/amount*/debit*/credit*` on any page under
  src/app/print/. Proven against HEAD's print page:
  `49: existing.base += parseFloat(line.line_subtotal);`,
  `50: existing.tax += parseFloat(line.line_tax);`, FAIL.

Found while checking: opening-balances (list and [id]) also sum money with
parseFloat, for the on-screen debit/credit balance check. That is not a
printed or legal document. Recorded, not changed.

### The before-fix number and the document history (owner questions)

The measurement was taken against the unmodified print page before any code
changed, but I changed the code in the same stretch of work instead of
reporting the number first. On the test invoice the old parseFloat table did
NOT disagree: 0 mismatching rows, float error about 1e-13, hidden by display
rounding.

Live history, read-only. I replayed the browser's exact arithmetic over
every invoice on live:
- IEEE doubles; parseFloat of each line string; lines in the order the
  database returns them;
- each per-code sum rounded half-up to 2 places, as Intl.NumberFormat does;
- each table's rows compared against the invoice's own subtotal and
  tax_total.

Results:
- 18 invoices: 7 draft, 6 cancelled, 5 issued. The issued ones are fatma 4
  and acme 1.
- Largest float error: 3.4e-15.
- Figures that would have printed differently from the server's: 0.

There is no document history to chase. A flip needs half a cent of
accumulated float error, which takes invoice totals in the billions with
thousands of lines.

Server computation, apps/sales/services.py `recalculate_invoice`:
- :39 rounds each line's tax to the cent (ROUND_HALF_UP);
- :44 `tax_total += line_tax` adds the rounded values;
- :49 `invoice.tax_total = tax_total`.

So tax_total is the SUM OF THE ROUNDED per-line taxes, not the round of a
sum. tax_summary adds the same stored line_tax values, so its rows add
exactly to tax_total.

The qualifier matters, and it is recorded. ":49 is the only assignment in
APP code" leaves migrations, management commands and direct SQL outside it.
The new test pins one invoice, not the invariant. Open item recorded in
docs/prompts/sprint-8.md under D14, 2026-10-20: a reconciliation check that
every invoice's tax_total equals the sum of its lines' line_tax (and
subtotal the sum of line_subtotal), across all rows, in the shape of
check_chart_health. Not built.

## 2a. Live attachment storage: verified end to end

- 2026-10-20 18:56 UTC, live (port 3000).
- smoke-storage-1792522563, registered through the public API with a fresh
  password via stdin.
- A bank was created through the API, and a unique 707-byte PNG was uploaded
  through the bank screen's attachment panel in a real browser.

| check | result |
|---|---|
| upload, POST /api/attachments/ | 201 |
| server record | sha256 96ec7bf8c518641d11ae9c8044f6aa9c1b6450207eae7f6a6746486989f19fb7, scan_status clean |
| object in live MinIO, bucket cps-attachments, key 80b8e6df-e4fe-461c-ae46-21bd516dbac1/bank/2026/634809e2-d742-419d-9264-078f1174b13f.png | present: 707 B, image/png, 2026-10-20 18:56:09 UTC |
| sha256 of the object as stored (mc cat inside infra-minio-1, credentials via MC_HOST_*) | 96ec7bf8...9fb7 |
| read back through the app's signed download link | HTTP 200, 707 bytes, sha256 96ec7bf8...9fb7 |
| file on disk before upload | sha256 96ec7bf8...9fb7, 707 bytes |

So the same bytes went in, are stored, and come back.

Live ClamAV also answered: scan_status went pending -> clean within seconds.
A clean verdict means clamd replied; an exception would have recorded
"error". Signature database: ClamAV 1.5.4/28158, dated 19 Oct 2026, and
freshclam is running.

Live smoke tenants left behind (archiving needs manage.py on live, which is
not mine to run):
- smoke-storage-1792522506: first attempt. It also has one bank and one
  clean attachment, sha256 11da4843..., and it IS in MinIO with the same
  hash. Its app read-back returned 409 "still scanning" before the scan
  finished. Its password lived only in that shell, by design, so the
  read-back was redone on a second tenant.
- smoke-storage-1792522563: the run above.

Screenshot: docs/uat/screens/8.2.1-live-storage/bank-attachment.png.

### Found while doing it (not built)

- **Attachments are not in any backup.** scripts/backup.sh:175 still says
  "Sprint 5.1 adds the MinIO attachments bucket here ... not yet, so there is
  nothing to sync today." The bucket has existed since Sprint 5.1 and nothing
  copies it. Live today holds 2 attachments for tenant xxx (2026-09-23) and my
  2 smoke files; fatma has none. Once 8.1's mandatory attachments are live,
  every supporting document for a posted entry will exist in exactly one
  place: live's MinIO volume.
- **The mandatory-attachment rule ignores the scan.**
  apps/approvals/services.py `_check_mandatory_attachments` asks only for an
  ACTIVE attachment of the right category. It never checks scan_status. A
  file that is pending, infected, or `error` (ClamAV unreachable) satisfies
  the rule, and the document posts with a file nobody can download (the
  download returns 409). A failed storage write is not silent: the upload
  request itself fails and no row is created. A failed scan is silent.

## 2b. What an EICAR upload on live would trigger (nothing uploaded)

In the application, in order:
1. The upload stores the file in live MinIO first (bucket cps-attachments,
   key <tenant>/<type>/<year>/<uuid>.<ext>). The scan is asynchronous, so the
   EICAR bytes land in live storage before anything checks them.
2. An AuditLog row for the upload (log_action in attachments/services.py).
   AuditLog is protected by a database trigger: it cannot be deleted.
3. The Celery task scan_attachment streams the file to infra-clamav-1. On
   FOUND it sets scan_status=infected. No file is moved; the code comment
   calls quarantine a "documented simplification".
4. Downloads are refused with 409 "الملف مرفوض." The row stays visible in
   the attachment list.
5. No notification to anyone. The code notes the INFECTED alert as debt, and
   live mail goes to the dummy backend anyway.

On the host:
- infra-clamav-1 writes one line to its stdout, e.g.
  `stream(...): Eicar-Test-Signature FOUND`. Docker keeps it in the
  container's json-file log, with no rotation configured, until the
  container is recreated.
- There is no host-level antivirus: the clamav packages are not installed,
  and the three clamd processes are the dev, staging and live containers.
  auditd has no rules. fail2ban watches only sshd and recidive.
- Nothing on the host would alert, quarantine or block.
- Provider-side (Oracle Cloud) scanning of volume contents: unknown to me.
  I see no agent for it on the host.
- Backups: none, because the attachments bucket is not backed up. Backups
  go to a separate MinIO bucket and are gpg-encrypted.

Cleanup afterwards:
- The app cannot delete an attachment. Rule 6 forbids deleting the object,
  and the UI only voids it with a reason.
- The EICAR object, its row and the audit row would stay on live permanently
  unless the owner approves a manual `mc rm` of that one object in live MinIO.
  That is outside the application, and against rule 6's spirit. The rows
  stay regardless.
- The smoke tenant stays until someone archives it with manage.py on live.

Lower-impact alternative, for your decision: stream the EICAR string
straight to live's clamd with INSTREAM, from a throwaway container on the
infra network.
- That proves the same signature detection without touching storage, the
  database or the audit log.
- Its only trace is the one FOUND line in infra-clamav-1's log.
- It does not exercise the app's scan task, but the clean upload above
  already showed that the task reaches clamd and records its verdict.

## 2c. Deploy gate: proposed, not built (it follows the 2b decision)

The deploy.sh gate, after migrate and before smoke:
- storage: upload one small unique file through the API as a dedicated live
  smoke account, wait for scan_status, read it back through the signed link,
  compare sha256. Fail the deploy on any mismatch, 409 or error.
- scanning: whichever of the two forms you choose in 2b. The INSTREAM form
  writes nothing.

Each deploy would leave one attachment on live, permanently (rule 6). That
needs the dedicated live smoke tenant, which DEPLOY.md already lists as open
before the first gated live deploy. smoke.sh still logs in as a user inside
fatma.

## 3. Dev/CI parity: the four-group runner, CPS_ENVIRONMENT, injected secrets

scripts/ci_groups_local.sh (committed) runs the four CI groups as ci.yml
does, then ci_gate_counts.sh.
- Default mode: the template's whole environment, the same as pytest_run.sh.
- --ci-env: only ci.yml's backend env block, read from ci.yml, with
  DATABASE_URL / REDIS_URL pointed at dev's services.

CPS_ENVIRONMENT branches in app code, three places:
- the migrate backup guard. It returns early on any test_ database, before
  reading the variable;
- anonymize_staging_users refuses unless "staging";
- seed_perf refuses on staging and production.

The tests that cover them set the variable themselves (monkeypatch). Neither
"dev" nor "ci" reaches a branch that differs between the two.

Measured with `scripts/ci_groups_local.sh --ci-env`, at the working tree of
this commit (8ab75ea plus the tax_summary change and its 2 tests):

    [accounting] 245 passed
    [assets-treasury] 193 passed
    [attachments-permissions] 111 passed, 2 deselected
    [rest] 478 passed
    ::notice title=pytest total::1027 passed, 0 skipped, 2 deselected      (ci_gate_counts.sh: pass)

That is 1025 plus the 2 new tests, all passing:
- with CPS_ENVIRONMENT=ci;
- with local attachment storage and scanning off;
- with none of the 45 dev variables, including every dev secret.

So no test passes because a real secret, or any dev-only setting, is
present. The attachment tests pass on both paths (S3 against dev MinIO by
default, filesystem under --ci-env), so neither path hides a failure in the
other.

The other differences remain:
- service versions and lifetimes (Postgres, Redis);
- OS and Python build;
- the platform-DB alias.

They can't be closed from this host, only measured, and this runner is now
the instrument for that. Verdict: partial, with the two high-risk
differences measured clean.
