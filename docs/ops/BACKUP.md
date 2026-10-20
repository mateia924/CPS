# النسخ الاحتياطي والاستعادة (سبرنت 6.6.4)

## أين تعيش النسخ

- **القرص المحلي**: `/opt/cps-backups/cps-db-<YYYYMMDD-HHMMSS>.sql.gz.gpg`
  على هذا الخادم نفسه — جذر 700، مملوك لـroot فقط. كل نسخة **مُعمَّاة**
  (gpg symmetric، AES256) فور إنتاجها مباشرة؛ النسخة الصِّرفة (`.sql.gz`
  بلا `.gpg`) لا تبقى على القرص لحظة واحدة بعد التعمية.
- **السحابة (OCI Object Storage، S3-متوافقة) — الهدف النهائي**: نفس
  الملف المُعمَّى يُرفَع تلقائيًا من كل تشغيلة `scripts/backup.sh`،
  **بشرط** ضبط أربعة متغيرات في `.env` (القسم أدناه) — وهذا بند **M3**
  الذي يلزم المالك توفيره (`docs/prompts/sprint-6.6.md` §4)، وغير
  مضبوط على هذا الخادم اليوم.
- **MinIO — الهدف المؤقت («الخيار 1»، سبرنت 6.6.4، `sprint-6.6.md`
  v1.1 §6.1)**: إلى أن يُضبَط M3، يُرفَع نفس الملف إلى MinIO (الموجود
  أصلًا، بمفاتيح حقيقية في كل بيئة) تلقائيًا — بادلة `cps-backups-interim`
  تُنشأ تلقائيًا عند أول استخدام. **هذا ليس حماية off-site حقيقية** (نفس
  الخادم، نفس عطل القرص يأخذ الاثنين معًا) — غرضه تشغيل مسار الرفع
  فعليًا بدل بقائه بلا اختبار حتى وصول M3، وحماية فقط من حذف
  `/opt/cps-backups` بالخطأ تحديدًا.
- **الشدّة بحسب البيئة**: غياب كليهما أو فشل الرفع → تحذير واضح في
  `dev`/`staging` (لا يُفشِل `backup.sh` نفسه، انظر أدناه)، **لكن فشل
  حقيقي (exit غير صفري) في `production`** (`CPS_ENVIRONMENT=production`
  — القيمة نفسها التي يضبطها `infra/docker-compose.prod.yml` فعليًا) —
  متانة النسخة الاحتياطية ليست اختيارية هناك.

## التعمية — المفتاح

`CPS_BACKUP_ENCRYPTION_PASSPHRASE` في `.env` (وليس `.env.staging` —
النسخ التي يُنتجها `backup.sh` هي نسخ القرص/الحي دائمًا، لا staging).
**فقدان هذا المفتاح يجعل كل نسخة موجودة غير قابلة للقراءة للأبد** —
عامله كأي سرّ آخر يُولَّد محليًا في هذا المشروع (نفس فئة
`DJANGO_SECRET_KEY`)، واحتفظ بنسخة منه في مكان آمن خارج هذا الخادم
نفسه (وإلا فقدان القرص = فقدان كل النسخ الاحتياطية معه، وهو ما تحاول
السحابة أصلًا الحماية منه).

توليد مفتاح جديد:
```
openssl rand -base64 48
```

فك تعمية ملف يدويًا (مثلًا لفحصه، أو لاستعادة طارئة بلا سكربت):
```
gpg --batch --yes --passphrase-file <(printf '%s' "$CPS_BACKUP_ENCRYPTION_PASSPHRASE") \
  --decrypt cps-db-20261001-030000.sql.gz.gpg | gunzip -c > restored.sql
```
(Rule 50, corrected 2026-10-20: this line used to read `--passphrase "$CPS_BACKUP_ENCRYPTION_PASSPHRASE"`,
which puts the passphrase in `ps` for every user on the host while gpg runs. `printf` is a bash builtin, so
`<(printf …)` hands it over without any process carrying it as an argument. Never replace it with `echo`
from /bin or any external command.)

## الرفع السحابي — المتغيرات (M3، بيانات المالك)

في `.env`:
```
CPS_BACKUP_CLOUD_BUCKET=
CPS_BACKUP_CLOUD_ENDPOINT_URL=
CPS_BACKUP_CLOUD_ACCESS_KEY=
CPS_BACKUP_CLOUD_SECRET_KEY=
CPS_BACKUP_CLOUD_REGION=us-ashburn-1
```
الأربعة الأولى يجب أن تكون كلها مضبوطة معًا (لا رفع جزئي) — الرفع نفسه
يتم عبر صورة `backend` (مكتبة `boto3` الموجودة أصلًا لمرفقات MinIO/S3،
لا حاجة لأداة جديدة على الخادم) عبر `docker compose exec`، فيحتاج
الحاوية الحية (`infra-backend-1`) تثبيت `/opt/cps-backups` فيها للقراءة
فقط — موجود في `infra/docker-compose.yml` منذ هذا السبرنت، **يحتاج
تشغيلة `deploy.sh` واحدة بعد ضبط M3 لتفعيله فعليًا** (التحميل الجديد
للحاوية هو ما يُنشئ هذا الـmount، لا إعادة تشغيل عادية).

فشل الرفع (بيانات ناقصة أو خطأ شبكة/صلاحية) **لا يُفشِل `backup.sh`
نفسه في `dev`/`staging`** — فقط تحذير واضح في السجل؛ `scripts/
deploy.sh` يعتمد على نجاح `backup.sh` قبل كل migration، ونسخة سحابية
معطوبة/غائبة يجب أن لا تمنع نشرًا روتينيًا أبدًا بينما النسخة المحلية
المُعمَّاة سليمة — **في `production` فقط، نفس الفشل يُسقِط `backup.sh`
نفسه (exit 1)**.

## سياسة الاحتفاظ

**30 يومًا يوميًا + 12 شهرًا شهريًا** (`scripts/prune_backups.sh`،
يُستدعى من `backup.sh` في نهاية كل تشغيلة):
- كل نسخة من آخر 30 يومًا تُحفَظ كاملة.
- لكل شهر تقويمي أقدم من 30 يومًا (حتى 12 شهرًا للخلف): تُحفَظ أحدث نسخة
  فيه فقط؛ البقية تُحذف.
- أي نسخة أقدم من 12 شهرًا كاملة تُحذف.

التاريخ يُستخرج من **اسم الملف نفسه** (`cps-db-YYYYMMDD-HHMMSS...`) لا
من `mtime` — نسخ/استعادة الملف لا يُفسِد حساب السياسة.

## Attachments and restore identity (Block A, 2026-10-20)

**Attachments are backed up.** From 2026-10-20 every `backup.sh` run, nightly or manual, ends with
`scripts/backup_attachments.sh`:

- Every row of `attachments_attachment` is covered, voided and superseded included (no WHERE clause).
- Each object not yet stored is copied from MinIO into `<backup dir>/attachments/objects/<key>.gpg`.
  It is gpg AES256-encrypted with the dumps' passphrase, decrypted back, and checked against the row's
  sha256 before it is kept.
- A stored copy is never replaced.
- One encrypted manifest per run goes to `attachments/manifests/attachments-<ts>.manifest.gpg`. It is
  paired with that run's dump, and its header records the source `minio=minio/<bucket>#<deploymentID>`.
- One `backups.log` line per run, FAILED included.
- The step runs inside `if ! timeout …`, after the dump is written and logged. Whatever it does,
  the database backup and backup.sh's exit code are unaffected
  (`backend/tests/test_backup_attachments.py`).

**No plaintext dump touches the disk.** `pg_dump | gzip | gpg` streams into `cps-db-<ts>.sql.gz.gpg.part`,
which is renamed when complete.

- An EXIT trap removes the partial.
- `prune_backups.sh` removes partials older than an hour, and any plaintext `cps-db-*.sql.gz` newer than
  2026-10-01 14:15:53 (when encryption arrived).
- The 46 pre-encryption plaintext dumps are kept and listed on every run until the owner decides.
- Everything is created owner-only (umask 077). Existing backups were set to 0600/0700 on 2026-10-20.

**Restore checks where a backup came from.** `scripts/restore.sh --from live|staging|dev <dump> [target-db]
[--attachments <manifest> --attachments-into <minio-container>]` refuses, by name and before writing
anything, in four cases:

- the dump's recorded `db=` identity (backups.log) is not the named environment's current
  `system_identifier`;
- the manifest's `minio=` is not that environment's MinIO `deploymentID`;
- the manifest's `pairs=` is not the dump being restored;
- the target is live's own database and `--from` is not `live`.

Dumps with no recorded `db=` (everything before 2026-10-17) are refused. After host loss there is no
running source to compare with, so a disaster-recovery path that names the recorded identity explicitly
is still open (the off-host block).

**The restore test needs the bytes back.** `restore_test.sh [--target live|dev|staging]` also restores the
paired manifest into a throwaway MinIO. A throwaway backend, pointed only at the restored database and
that MinIO, downloads every attachment through the app's signed-link view and compares each body with the
row's sha256. A missing manifest, a missing object or a mismatch is FAIL, with the row named.

## اختبار الاستعادة الآلي (`scripts/restore_test.sh`)

يُشغَّل شهريًا عبر crontab الجذر (`0 4 1 * * /opt/cps/scripts/
restore_test.sh`) — **لا Celery beat**: عامل Celery يعمل داخل حاوية
بلا وصول لنظام ملفات الخادم (`/opt/cps-backups`) ولا لـ`docker compose`
نفسه؛ منحه ذلك يحتاج تغييرًا معماريًا أكبر (mount لمقبس Docker أو
القرص بالكامل داخل الحاوية) لا يستحقه هذا البند — crontab الجذر هو
نفس النمط الذي يشغِّل `backup.sh` نفسه فعليًا، لا استثناء جديد.

الخطوات: يجد آخر نسخة `.sql.gz.gpg`، يفكّ تعميتها، يستعيدها في قاعدة
مؤقتة (`cps_restore_test`، تُحذف دائمًا في النهاية — نجح أو فشل)، يشغّل
`manage.py check` ضدها، ثم يعدّ المستأجرين والقيود المرحَّلة فيها
ويسجّلهما جنبًا إلى جنب مع عدّهما في القاعدة الحية — **السجلّان يُكتبان
دائمًا، حتى عند التطابق التام**، في `docs/ops/restore_tests.log`.

**القرار على النتيجة ليس "تطابق تام بالحي":** النسخة لقطة زمنية —
القاعدة الحية عادة تُظهر أرقامًا أعلى بحلول وقت الاختبار (عمل حقيقي
استمر بعد أخذ النسخة)؛ اعتبار هذا الفرق الطبيعي فشلًا يجعل التنبيه
يُطلَق في كل تشغيلة بصرف النظر عن صحة النسخة فعليًا — النتيجة الأسوأ
الممكنة لتنبيه صحة. القرار الفعلي: `manage.py check` نظيف + الاستعادة
نفسها بلا خطأ + عدد المستأجرين المُستعاد ليس منخفضًا بشكل مريب قياسًا
بالحي (أقل من 50% منه) — أي مما سبق يفشل يُسجَّل `FAILED` صريحًا.

**تنبيه الفشل:** بريد معاملاتي (سبرنت 6.6.8) غير موجود بعد — حتى ذلك
الحين، سطر `FAILED` صريح في `docs/ops/restore_tests.log` **و**stderr
(يصل لـ`/var/log/cps-restore-test.log` عبر crontab) هو التنبيه الوحيد؛
راجع هذا الملف يدويًا دوريًا حتى يُضاف البريد.

### التحقق المحاسبي (لا العددي فقط) — مؤجَّل من إغلاق سبرنت 6، نُفِّذ 2026-10-04

`restore_test.sh` نفسه يتحقق عدديًا فقط (عدد المستأجرين/القيود). هذا
لا يكفي محاسبيًا: عدّان متطابقان لا يثبتان أن *قيمهما* المالية صحيحة
(سجلّ تالف قد يحافظ على عدد الصفوف ويُفسِد الأرقام). التحقق الإضافي
التالي نُفِّذ فعليًا (لا افتراضًا) لإغلاق هذا البند المؤجَّل من سبرنت 6:

- **التاريخ:** 2026-10-04T20:4x+03:00 (بعد نشر الكتلة 7.0.1 مباشرة).
- **ملف النسخة:** `cps-db-20261004-203557.sql.gz.gpg` (نُسخة `deploy.sh`
  الآلية قبل خطوة migrate/add_missing_system_accounts لتلك الكتلة).
- **الخطوات:** استعادة النسخة كاملة (نفس آلية `restore_test.sh` —
  `dropdb`/`createdb` فارغة ثم `psql` يستعيد دمب `pg_dump --no-owner
  --no-privileges` كاملًا) في قاعدة مؤقتة منفصلة، ثم استعلام SQL مباشر
  يجمع **كل** سطور القيود المرحَّلة (`accounting_journalline` المرتبطة
  بـ`accounting_journalentry` بحالة `posted`) عبر كل المستأجرين معًا —
  لا عدّ صفوف، بل جمع القيم المالية الفعلية (مدين/دائن) — ونفس الاستعلام
  حرفيًا على القاعدة الحية في نفس اللحظة.
- **الأعداد:**

  | | المستعادة | الحية |
  |---|---|---|
  | المستأجرون | 49 | 49 |
  | القيود المرحَّلة | 82 | 82 |
  | **إجمالي المدين** | **734405.43** | **734405.43** |
  | **إجمالي الدائن** | **734405.43** | **734405.43** |

- **النتيجة: تطابق تام بالقرش** على إجمالي المدين والدائن معًا، لا
  على عدّ الصفوف فقط — هذا هو الدليل المحاسبي الذي يخصّ محاسبًا
  (استعادة بعدد صفوف صحيح لكنها تُحرِّف قيمة سطر واحد كانت ستُظهر هذا
  الفرق فورًا؛ عدّ الصفوف وحده كان سيُخفيه تمامًا).

## استعادة فعلية على سيرفر إنتاج جديد (خطوة بخطوة)

يُختبر فعليًا في سبرنت 6.6.8 — الخطوات المتوقَّعة:

1. نسخ `cps-db-<أحدث>.sql.gz.gpg` من حاوية OCI Object Storage (أو من
   `/opt/cps-backups` إن كانت النسخة محلية) إلى السيرفر الجديد.
2. `CPS_BACKUP_ENCRYPTION_PASSPHRASE` نفسه (من مكان تخزينه الآمن، **لا**
   من هذا الخادم القديم إن كان هو سبب الحاجة للاستعادة) في `.env`
   السيرفر الجديد.
3. `docker compose up -d postgres` (القاعدة فقط أولًا، فارغة).
4. فكّ التعمية + استعادة (نفس نمط `scripts/staging_refresh.sh` خطوة 4،
   أو `scripts/restore_test.sh` كمرجع — كلاهما بـ`gpg --decrypt |
   gunzip -c | psql`).
   **Attachments (2026-10-20):** copy `attachments/` (objects plus manifests) together with the dump, then
   restore the manifest paired with that dump into the new MinIO. `restore.sh --attachments` does this
   on a host where the source environment is still running. On a new host its identity check has nothing
   to compare with, which is an open item.
5. `manage.py setup_rls` (سبرنت 6.6.3b) — `pg_dump --no-privileges`
   يُسقط كل GRANT/سياسة RLS، فالقاعدة المُستعادة بلا هذه الخطوة تعمل
   بصلاحيات `cps_app` الكاملة (RLS متوقف فعليًا من منظور ذلك الدور)
   بلا أي خطأ ظاهر — راجع `docs/ops/RLS.md` للقاعدة الكاملة وفحص عدّ
   السياسات الإلزامي بعدها.
6. `scripts/deploy.sh` (بناء الصور + migrate + تشغيل + `make smoke`).
