# النشر — الأدلة والملفات (سبرنت 6.6.0)

هذا المستند يشرح كل ملف compose على هذا الخادم، ومتى يُستخدم كل واحد،
ولماذا. القاعدة الوحيدة التي لا تُكسَر أبدًا: **لا تغيير على ما يخدمه
المنفذ 3000 إلا عبر `scripts/deploy.sh`** — لا `docker compose ... up
-d --build` يدويًا ضد `docker-compose.local.yml`، ولا استثناء.

## الملفات الخمسة

| الملف | الغرض | المشروع (project) | المنفذ | من يشغّله |
|---|---|---|---|---|
| `infra/docker-compose.yml` | التعريفات المشتركة (لا يُشغَّل بمفرده أبدًا) | — | — | — |
| `infra/docker-compose.local.yml` | **الحي** — ما يخدمه هذا الخادم فعليًا الآن، بلا إعادة تحميل، من صورة مبنية | `infra` | 3000 | `scripts/deploy.sh` فقط |
| `infra/docker-compose.dev.yml` | صندوق التطوير التفاعلي — إعادة تحميل + bind-mount، للكتابة والتجربة على مستأجرات `smoke-*` فقط | `cps-dev` | 3002 | `make dev-up` |
| `infra/docker-compose.ci.yml` | طبقة إضافية فوق `dev.yml` (سبرنت 7.0، CI #61) — تحذف خدمة `minio` نهائيًا (عمال GitHub لا يصلون إلى `quay.io`) | `cps-dev` | 3002 | `make dev-up CI_OVERLAY=1` فقط (مهمة e2e في CI، و`make ci-local`) — لا يُستخدَم أبدًا بلا `CI_OVERLAY=1` |
| `infra/docker-compose.staging.yml` | staging — نسخة مستقلة كاملة، حيث يُنفَّذ كل UAT بشري من الآن | `cps-staging` | 3001 | `make staging-up` / `scripts/staging_refresh.sh` |
| `infra/docker-compose.prod.yml` | سيرفر الإنتاج المستقل المستقبلي (6.6.8) — لا يُشغَّل على هذا الخادم أبدًا | — | 80/443 | — |

كل مشروع (project) مستقل تمامًا: قاعدته وحاوياته وأحجامه الخاصة، تحت
اسم compose project مختلف — `docker compose down` في أحدهما لا يمسّ
الآخرين أبدًا.

## `scripts/deploy.sh` — الطريق الوحيد لتغيير الحي (3000)

الاستثناء الوحيد المسجَّل: أمر إدارة لمرة واحدة بالشروط السبعة في «حالة الحي — 2026-10-14» أدناه، وكلها مجتمعة.

```
scripts/deploy.sh
```

الخطوات، بالترتيب، وتتوقف عند أول فشل:

1. **بناء الصور** من الشيفرة الحالية (`docker compose build`).
2. **بوابات الإنتاج** — معرَّفة مرة واحدة في `scripts/production_gates.sh`،
   ويشغّلها `scripts/staging_refresh.sh` (البروفة، بنمطيها) بالتعريف نفسه
   (القاعدة 32؛ Pre-deploy 1، 2026-10-17):
   `backup` (`scripts/backup.sh --target live`) ← `migrate` (حاوية مؤقتة؛ الحارس
   يطابق حقل `db=` في سطر النسخة بقاعدته هو، لا الوقت وحده) ← `setup_rls` ←
   `verify_rls` (عدد سياسات `tenant_isolation` = عدد الجداول) ←
   `add_missing_system_accounts` ← `check_chart_health --fail-on-findings` ←
   `start` (وسم الصور الحالية `:rollback-<وقت>`، `up -d`، إعادة تشغيل nginx) ←
   `ready` (انتظار فعلي حتى يردّ الخادم الخلفي، 180 ثانية) ← `smoke`.

`scripts/backup.sh --target dev|staging|live` (الافتراضي live): كل هدف يدمب
قاعدته هو، وكل سطر في `backups.log` ينتهي بـ`db=<host>/<name>#<system_identifier>`.
`CPS_SKIP_BACKUP_GUARD` و`CPS_BACKUPS_LOG_PATH` مرفوضان خارج `CPS_ENVIRONMENT=dev`.

**حالة 2026-10-17:** البوابات المشتركة لم تُنفَّذ بعد ولو مرة؛ `tests/test_production_gates.py` يثبت النص لا التشغيل؛ وأول تنفيذ حقيقي سيكون `scripts/staging_refresh.sh --full` على staging.

**حالة 2026-10-18 — البروفة الأمينة على staging:** أول تنفيذ فعلي للبوابات المشتركة، تشغيلان:
1. **بروفة فشل** (`--full`، 13:46–13:48): `check_chart_health` (6/9) أُسقطت عمدًا — البوابة الحقيقية جرت (`0 findings`) ثم أُفشلت — في **نسخة من الشجرة** (`production_gates.sh` الحقيقي يقرؤه `deploy.sh` الحي، فلا يحمل بوابة مخرَّبة ولو دقيقة). الإخفاء سبق البوابات: بعد الفشل 0 بريد خارج `*.staging.test` (85 مستخدمًا، 50 نطاقًا)، والقاعدة لم تُحذف.
2. **تشغيل نظيف** (`--full`، 14:19:21–14:21:05، exit 0): البوابات 1–9 خضراء بالترتيب، `smoke` → `ALL CHECKS PASSED`. **`ready` احتاج ~9 ثوانٍ**: حاوية الباك-إند بدأت 14:20:49.99، gunicorn استمع 14:20:58، البوابة 8 بدأت 14:20:51 والبوابة 9 بدأت 14:21:00 (دقة الطوابع ثانية، وpoll كل ثانيتين). مهلة الـ180 أكبر بنحو 20 مرة مما قيس — على صور مبنية من الذاكرة المؤقتة؛ أول استيراد بارد على الحي لم يُقَس.
- الوسيط الخاطئ `--code-onyl` رُفض (exit 2) في المرتين، **بلا أي أمر docker** ولقطة staging/live متطابقة قبله وبعده.
- live: قراءة فقط. مصدر الاستعادة ملف (`/opt/cps-backups/cps-db-20261018-030001.sql.gz.gpg`، نسخة cron)؛ كل أوامر docker في التشغيلين (17 و46، مسجَّلة بوسيط أمام `docker`) على `cps-staging` وحده؛ حاويات `infra-*` وصورها وchecksum الملف مطابقة قبل وبعد.
- live متأخر **6 هجرات** عن HEAD (طُبِّقت على نسخته): `accounting.0043`، `accounts.0005`، `inventory.0007`–`0010` — هذا ما سيطبّقه أول نشر حي.
- **نسخ البروفة:** أنتجت بروفة الفشل نسختين في `/opt/cps-backups/staging` (`cps-db-20261018-134733.sql.gz.gpg` قبل المسح، `cps-db-20261018-134835.sql.gz.gpg` قبل الهجرة) بهوية `db=postgres/cps_staging#7691316877294727202`؛ **سطراهما في `docs/ops/backups.log` لنسخة البروفة** (`/tmp/claude-0/-opt-cps/bf5ac544-253a-47e7-a102-a93dc730b148/scratchpad/rehearsal-repo/docs/ops/backups.log`، ملف مؤقت) **لا في السجل** — عن قصد: سطر يكتبه إنسان في سجل تكتبه الأداة تزوير، حتى لو كان مضمونه صحيحًا. نسختا التشغيل النظيف في السجل كالمعتاد.
- **أُغلق في Pre-deploy 3 (2026-10-18):** `start` كان يَسِم بـ`:rollback-<وقت>` **كل** صورة في المشروع، ومنها الخارجية المشتركة مع live (`postgres:16-alpine`، `nginx:1.27-alpine`، `redis:7-alpine`، clamav، minio)، وأمر التراجع يعيد وسمها — أي وسومًا يقرؤها live. الآن يَسِم **الصور التي يبنيها المشروع فقط** (`<project>-<service>`: backend، celery_worker، frontend)، فكل وسم تراجع يحمل اسم مشروعه (`cps-staging-backend:rollback-…` لا يقرؤه live، و`infra-backend:rollback-…` لا تقرؤه staging)؛ الخارجية مثبّتة بوسمها ولا تُمسّ (`test_start_on_staging_changes_no_image_tag_that_live_reads`). الوسوم الخمسة `rollback-20261018-142046` على الصور الخارجية (من التشغيل الذي سبق الإصلاح) لم تعد موجودة (تحقّق 2026-10-19: كل صورة خارجية تحمل وسمها وحده)؛ الثلاثة على `cps-staging-*` باقية أهداف تراجع لـstaging. إثبات حي 2026-10-19 13:09: `staging_refresh.sh --code-only` على 05b64b8 — `docker images` قبل/بعد لم يتغيّر فيه إلا `cps-staging-*` (`:latest` و`:rollback-20261019-130957`)، والسجل: «not tagged (external …): clamav … minio … nginx … postgres … redis».
  - Live proof record (2026-10-19 13:09, `scripts/staging_refresh.sh --code-only` at 05b64b8, exit 0, gates 1-9 passed). External image tags, `docker images` before and after (identical, `cmp` clean):
    ```
    clamav/clamav:1.5.4-debian 02253321874d
    nginx:1.27-alpine 6769dc3a703c
    postgres:16-alpine 81bd698b4594
    quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z 69b2ec208575
    redis:7-alpine f84b0c467801
    ```
    Complete before/after diff of `docker images` (tagged images only); nothing outside `cps-staging-*` changed, `infra-*` included:
    ```
    - cps-staging-backend:latest 9154845dcf49
    + cps-staging-backend:latest 82f0e7a7db66
    + cps-staging-backend:rollback-20261019-130957 9154845dcf49
    - cps-staging-celery_worker:latest 14b2a1191d01
    + cps-staging-celery_worker:latest 7f0a1a4ef5da
    + cps-staging-celery_worker:rollback-20261019-130957 14b2a1191d01
    - cps-staging-frontend:latest 78b5e053af00
    + cps-staging-frontend:latest ce3e4cc541a4
    + cps-staging-frontend:rollback-20261019-130957 78b5e053af00
    ```
  - The stale tag `rollback-20261018-142046` disappeared from the external images by an unknown hand at an unknown time; it was already absent when checked on 2026-10-19. No cause is recorded.

### أدلة `ps`: لا سرّ في سطر أوامر (2026-10-18) — وحدّ هذا الدليل

مِعيان (`ps -eo pid,args` كل 0.2 ثانية) يعدّ الأسطر التي تحمل القيمة دون أن يطبعها، ويسجّل اسم البرنامج (argv[0]) وحده لأي ظهور:

| التشغيل | العيّنات | كلمة سر staging | عبارة مرور النسخ | ملاحظة |
|---|---|---|---|---|
| `--full` رقم 3 (Pre-deploy 3، قبل إصلاح smoke.sh) | 443 | **3** — من `curl -d` في `smoke.sh` | 1 | |
| `--full` رقم 4 (بعد إصلاح smoke.sh) | 449 | **0** | 2 — argv[0] = `gpg`: تشفير `backup.sh` (`--passphrase`)؛ gpg فكّ التشفير في العيّنات نفسها ظهر بـ`--passphrase-file /dev/fd/63` نظيفًا | سطر الإخفاء في 229 عيّنة: `… run --rm -e STAGING_UAT_PASSWORD … anonymize_staging_users` |
| `backup.sh --target live` يدويًا (Pre-deploy 4، بالسطر الجديد) | 17 | 0 | 0 | **gpg لم يُلتقَط في أي عيّنة** — انتهى في أقل من 0.2 ثانية |
| `backup.sh --target live` يدويًا (Pre-deploy 5، مفتاحا الرفع بالاسم؛ **عيّنة كل 0.05 ثانية**) | 47 | — | 0 | مفتاحا MinIO (السري ومفتاح الوصول): **0 و0**. هذه المرة رُئيت العمليتان: gpg في 3 عيّنات (`--passphrase-file /dev/fd/63`)، والرفع في 14 عيّنة بسطر `docker compose … exec -T … -e CPS_UPLOAD_ACCESS_KEY -e CPS_UPLOAD_SECRET_KEY … upload_backup_to_s3.py` — الاسمان بلا قيمة. `cps-db-20261018-190932` رُفعت (`Upload OK`) وفُكّت: 21075 سطرًا، العلامة موجودة. سطرها في backups.log يحمل `322560b` لأن التشغيلة جرت من الشجرة قبل commit هذه الكتلة. |

**حدّ الدليل — يُقرأ مع الأرقام:** العيّنة كل 0.2 ثانية، فأمرٌ أقصر من ذلك قد يفلت كليًا. «صفر ظهور» المقيسة بهذه العيّنة **ليست** «صفر ظهور» مطلقًا: في صف Pre-deploy 4 الصفر لا يثبت شيئًا عن gpg لأن gpg نفسه لم يُرَ. وفي صف Pre-deploy 5 (عيّنة أدقّ، 0.05 ثانية) رُئيت العمليتان كلتاهما، فصفرهما يعني شيئًا عن العمليتين — لكنه يبقى عيّنة. الدليل الحاسم لكل موضع هو اختبار الوحدة الذي يسجّل وسائط الأداة البديلة نفسها (`test_staging_refresh_puts_no_secret_on_a_command_line`، `test_smoke_sends_the_password_and_the_token_off_the_command_line`، `test_backup_gpg_passphrase.py`، `test_backup_upload_credentials.py`)، والمِعيان دليل مكمِّل على العملية الحقيقية لا بديل عنه.

**توافق النسخ بعد Pre-deploy 4 (القيمة لم تتغيّر، طريقة توصيلها فقط):** نسخة قديمة (`cps-db-20261018-030001.sql.gz.gpg`، شفّرها `backup.sh --passphrase` الساعة 03:00) فُكّت بسطر `restore.sh` الجديد على المضيف (gpg 2.2.20): 21075 سطر SQL، علامة `dump complete` موجودة. ونسخة جديدة (`cps-db-20261018-161211.sql.gz.gpg`، تشغيلة يدوية لـ`backup.sh --target live` بالكود الجديد، رُفعت إلى MinIO) فُكّت بالسطر الجديد: 21075 سطرًا، العلامة موجودة. اتجاه «جديدة ← الطريقة القديمة» مُثبَت في `test_backup_gpg_passphrase.py` (gpg 2.4.7) لا على ملف حقيقي — لأن الأمر القديم يضع العبارة في `ps` بطبيعته.

### حالة النظام إن سقطت بوابة (`--full` على staging، و`deploy.sh` على الحي)

**مقيس** = رُصد في بروفة 2026-10-18؛ **من الكود** = لم يُقَس بعد. «قابل للاستئناف» = إعادة تشغيل السكربت نفسه من أوله بعد الإصلاح؛ كل البوابات قبل `start` لا تغيّر ما يخدم الحي (على الحي يبقى الكود القديم يخدم طوال 1–6)، وكلها متساوية الأثر عند التكرار (`migrate` المطبَّقة لا تُعاد، `setup_rls`/`add_missing_system_accounts` idempotent).

| البوابة | حالة النظام إن سقطت | قابل للاستئناف | المصدر |
|---|---|---|---|
| (الفحص التمهيدي للأسرار) | لا شيء تغيّر — قبل build وقبل المسح | نعم: أنشئ/صحّح السرّ وأعد | اختبارات فقط |
| (وسيط خاطئ) | لا شيء: exit 2، صفر أوامر docker | نعم | **مقيس** |
| 1 `backup` | staging `--full`: القاعدة مُستعادة ومُخفاة، backend/celery_worker متوقفان. الحي: لم يتغيّر شيء يُخدَم | نعم | من الكود |
| 2 `migrate` | الهجرات الذرية ترجع كاملة؛ الثلاث غير الذرية قد تترك فهرسًا غير صالح (القسم أدناه). الحي: الكود القديم يخدم مخططًا مهاجَرًا جزئيًا | نعم، إلا الفهرس غير الصالح: مسار يدوي أدناه | من الكود |
| 3 `setup_rls` / 4 `verify_rls` | كما في 2 بعد هجرة كاملة؛ سياسة ناقصة لا تُفتح للخدمة على staging لأن backend متوقف | نعم | من الكود (4 مرّت: 50/50) |
| 5 `add_missing_system_accounts` | كما سبق | نعم | من الكود (مرّت: 0 حساب أُنشئ) |
| 6 `check_chart_health` | **staging `--full`: backend وcelery_worker في `Exited (0)`، والباقي `Up`؛ `/` يردّ 200 بينما `/api/` يردّ 502 بعد ~18 ثانية** (`/admin/login/` 502 بعد ~3). الإخفاء مكتمل، القاعدة باقية، لا وسوم rollback | نعم | **مقيس** |
| 7 `start` | بعض الحاويات استُبدلت وبعضها لا؛ وسوم `:rollback-*` موجودة على صور المشروع المبنية وحدها | يدويًا: أمر التراجع المطبوع، أو إعادة التشغيل | من الكود (مرّت: 4 حاويات أُعيد إنشاؤها) |
| 8 `ready` | الحاويات الجديدة تعمل ولا تردّ — **قد يكون الهدف على 502 الآن**؛ يُطبع أمر التراجع | يدويًا (قسم المهلة أدناه) | من الكود (مرّت في ~9 ث) |
| 9 `smoke` | الكود الجديد يخدم ولا يجتاز الفحص؛ على الحي كتب الدخول سطر تدقيق | قرار بشري: تراجع أو إصلاح | من الكود (مرّت) |

**الحالة المقيسة عند سقوط بوابة قبل `start` تخدع أي مراقبة تفحص الجذر:** الواجهة تُحمَّل (`/` → 200) والـAPI ميت (`/api/` → 502 بعد ~18 ثانية). المستخدم يرى صفحة سليمة تتعطّل، لا خطأً صريحًا — وهذا سبب القاعدة 35 (إشارة الصحة من الخارج) والقاعدة 36 (`Up` ليس دليلًا): فحص الصحة يطلب مسارًا يمرّ بالباك-إند، لا `/`.

**⚠️ `scripts/deploy.sh` نفسه لم يُنفَّذ قط بشكله الحالي.** البروفة على staging تثبت `production_gates.sh` المشترك، **لا** غلاف `deploy.sh` (أُعيدت كتابته في Pre-deploy 1، `8f9a0e6`: +20/−76 سطرًا، ثم الفحص التمهيدي في Pre-deploy 2: حارس الشجرة غير النظيفة، فحوص `.env`، `fail` وسطر `deploys.log`، الفحص التمهيدي قبل build، `GATE_BACKUP_TARGET=live`). لا تدخل أول نشر حي وأنت تظن أنه جُرِّب: أول تشغيل له سيكون على الحي نفسه.

كل تشغيلة تُسجَّل سطرًا في `docs/ops/deploys.log` (الوقت، الهاش،
النتيجة OK/FAILED والسبب عند الفشل).

### إن انقضت مهلة `ready` — لا تراجع تلقائي (Pre-deploy 1، 2026-10-17)

عند `ready` تكون `start` قد استبدلت الحاويات فعلًا، فالفشل السريع لا يعيد
شيئًا؛ لذلك المهلة 180 ثانية لا 30. والطلب الواحد يُمهَل 70 ثانية، أطول من
مهلة nginx (60) — القاعدة 36 — و`504` يُعَدّ «غير جاهز» مثل `502`/`503`
(كان يمرّ قبل هذه الكتلة، وهو بالضبط ما ردّ به انقطاع 2026-10-13). إن انقضت يطبع السكربت صراحةً أن الهدف
(live أو staging) **قد يكون على 502 الآن**، وحالة الحاويات (`ps`)، وسطرًا
جاهزًا للنسخ يعيد الصور السابقة: `start` تَسِم صورة كل حاوية قائمة قبل
`up -d` بـ`<image>:rollback-<YYYYmmdd-HHMMSS>`، والأمر يعيد كل وسم إلى
مكانه ثم `up -d --no-build` وإعادة تشغيل nginx. لا شيء يُشغَّل تلقائيًا:
اقرأ `logs --tail 100 backend` أولًا. التراجع للكود وحده — **الهجرات تبقى
مطبَّقة**، والكود السابق يخدم المخطط المهاجَر كما كان يخدمه بين `migrate`
و`start`. وسوم `rollback-*` القديمة تتراكم وسمًا لكل حاوية في كل نشر؛
تُحذف يدويًا بـ`docker rmi <image>:rollback-<...>` متى لم تعد مطلوبة.

### هجرة نصف مبنية — الهجرات الثلاث غير الذرية (مسار استئناف يدوي)

ثلاث هجرات تستعمل `AddIndexConcurrently` مع `atomic = False` (`CREATE INDEX
CONCURRENTLY` لا يعمل داخل معاملة):

| الهجرة | الفهارس |
|---|---|
| `accounting.0034_journalentry_accounting_je_entity_date_idx_and_more` | `accounting_je_entity_date_idx`، `accounting_je_status_idx`، `jrnl_line_acct_entry_idx`، `accounting_obe_status_idx`، `accounting_re_status_idx` |
| `sales.0023_invoice_sales_invoice_entity_date_idx_and_more` | `sales_invoice_entity_date_idx`، `sales_invoice_status_idx` |
| `vouchers.0005_voucher_vouchers_entity_date_idx_and_more` | `vouchers_entity_date_idx`، `vouchers_status_idx` |

إن سقطت إحداها في منتصفها (انقطاع، قفل، إلغاء) فلا شيء يُرجَع: الفهرس الذي
كان يُبنى يبقى **غير صالح** (`pg_index.indisvalid = false`) — لا يُستعمل في
الاستعلامات لكنه يُحدَّث مع كل كتابة — والفهارس التي اكتملت قبله تبقى صالحة،
والهجرة نفسها **لا تُسجَّل** في `django_migrations`. فإعادة `migrate` تعيد
الهجرة من أولها وتسقط على `relation "..." already exists`. الاكتشاف (على
الهدف المعني؛ مثال الحي):

```
cd /opt/cps/infra && docker compose --env-file /opt/cps/.env -f docker-compose.yml -f docker-compose.local.yml \
  exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
-- ثم داخل psql:
SELECT c.relname, i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
 WHERE NOT i.indisvalid OR c.relname IN (
  'accounting_je_entity_date_idx','accounting_je_status_idx','jrnl_line_acct_entry_idx',
  'accounting_obe_status_idx','accounting_re_status_idx','sales_invoice_entity_date_idx',
  'sales_invoice_status_idx','vouchers_entity_date_idx','vouchers_status_idx');
SELECT app, name FROM django_migrations
 WHERE name IN ('0034_journalentry_accounting_je_entity_date_idx_and_more',
                '0023_invoice_sales_invoice_entity_date_idx_and_more',
                '0005_voucher_vouchers_entity_date_idx_and_more');
```

الإزالة: لكل هجرة **غير مسجَّلة** في `django_migrations`، احذف كل فهرس من
فهارسها موجودٍ (صالحًا كان أو لا) — واحدًا واحدًا، خارج أي معاملة:

```
DROP INDEX CONCURRENTLY IF EXISTS <اسم_الفهرس>;
```

ثم أعد التشغيل (`scripts/deploy.sh`، أو `staging_refresh.sh` على staging):
بوابة `migrate` تعيد بناءها كاملة. لا `--fake` ولا حذف لهجرة مسجَّلة.

### ما يكتبه `smoke` على الحي، وبأي حساب

`scripts/smoke.sh` يسجّل الدخول فعلًا، فكل تشغيلة على الحي **تكتب**: سطر
`AuditLog` (`tenant_user.login`)، وصف `UserSession`، و`OutstandingToken`
(simplejwt)، وتحديث `last_login`. الحساب الافتراضي على الحي
`accountant@fatma.test` — مستخدم أُنشئ في UAT سبرنت 4 **داخل مستأجر Fatma
الحقيقي**. كلمة سره لا تُكتب في المستودع (القاعدة 50، 2026-10-17): `smoke.sh`
يقرأ `SMOKE_PASSWORD` من البيئة ويتوقف إن غاب، والقيمة في
`/etc/cps-secrets/smoke_password` (root:root، 600). `deploy.sh` يتحقق منه
بالفحص التمهيدي (`cps_gates_preflight`) قبل build وقبل أول بوابة، ويتوقف
إن غاب أو كانت أذوناته أوسع (إنشاؤه: الإجراء أدناه). أي أنه **ليس حساب فحص
مخصصًا**: سجل تدقيق عميل حقيقي يحمل دخول الفحص، و«آخر نشاط» للمستأجر في
لوحة المنصة يتحرك مع كل نشر. مفتوح: حساب فحص مخصص (مستأجر فحص منفصل) قبل
أول نشر حي عبر البوابات. على staging يدخل `smoke` بحساب المحاسب المُخفى
(`accountant@fatma.staging.test` وكلمة `STAGING_UAT_PASSWORD`) في النمطين.

**إنشاء `/etc/cps-secrets/smoke_password` — عمل المالك، مرة واحدة، وعند كل
تدوير لكلمة السر.** **من جلسة SSH عادية، لا من داخل Claude Code ولا بأي
أداة تُسجِّل المخرجات**، وبمحرّر لا بسطر أوامر:

```
umask 077
install -m 600 -o root -g root /dev/null /etc/cps-secrets/smoke_password
nano /etc/cps-secrets/smoke_password      # سطر واحد، بلا مسافات في آخره
ls -l /etc/cps-secrets/smoke_password     # يجب أن يظهر -rw------- root root
```

السبب: ما يُشغَّل بـ`!` داخل Claude Code، وسجل جلسة Claude Code نفسه، كلاهما
مُدوَّن على الخادم — أي قيمة تُكتب أو تُطبع هناك صارت في ملف. وقيمة تُكتب على
سطر الأوامر قد تبقى في تاريخ الصدفة؛ المحرّر لا يترك أثرًا إلا الملف نفسه.
(السطر الجديد الذي يضيفه المحرّر في آخر الملف يُنزَع عند القراءة.)

**قبل أي نشر حي: `make test-integration`** (سبرنت 7.0، CI #56/#61) —
على صندوق التطوير أو staging، حيث ClamAV وMinIO يعملان فعليًا (CI لا
يملك أيًا منهما — راجع سجل القرارات §11). يشغّل الاختبارات المعلَّمة
`@pytest.mark.clamav`/`@pytest.mark.minio` فقط (مستبعَدة من `make test`
الافتراضي بنفس العلامة): `test_eicar_real_clamav` (فحص فيروسات حقيقي
يرصد EICAR فعليًا) و`test_attachment_is_actually_stored_in_minio`
(رفع فعلي يصل إلى بادلة S3/MinIO حقيقية). هذه الوحيدة التي تتحقق من
الخدمتين الخارجيتين أنفسهما — الاختبارات الحتمية في `make test` تثبت
صحة كودنا بصرف النظر عن الخدمة الفعلية خلفه.

## حالة الحي — 2026-10-14

- **الشيفرة المخدومة:** `b15041c` (آخر `deploy.sh` في 2026-10-10، `docs/ops/deploys.log`).
  `main` متقدّم عليه، ومن ذلك هجرات المخطط `accounting/0043` و`inventory/0007` و`0008`.
- **تغيير بيانات واحد خارج `deploy.sh`:** في 2026-10-14 الساعة 14:19 نُفِّذ
  `backfill_default_approval_rules` على `1cps` وحده، بالأنواع الخمسة `opening_balance`
  و`recurring_entry` و`asset_addition` و`asset_depreciation` و`asset_disposal`. نُفِّذ في
  حاوية مؤقتة من صورة الحي بالأمر من `0e3631b` (مركَّب للقراءة فقط)، بعد نسخة احتياطية
  `cps-db-20261014-141906.sql.gz.gpg`. قواعد `1cps` النشطة صارت 11 بعد 6، والتشغيل الثاني
  «added 0»، وقواعد الحي كلها 389 → 394 صفًا والفرق كله في `1cps`. التفاصيل في
  `docs/sprints/7-summary.md`.
- **سابقة، واستثناء محدود لا عادة:** تشغيل أمر إدارة لمرة واحدة على الحي خارج `deploy.sh`
  حدث الآن مرة. كان مقبولًا لأن الشروط التالية اجتمعت كلها:
  1. مستأجر واحد مسمّى بالاسم، لا مسح لكل المستأجرين.
  2. أنواع `doc_type` مسمّاة صراحةً.
  3. أمر idempotent، والتشغيل الثاني أثبت ذلك («added 0»).
  4. الأمر من commit مُلتزَم ومدفوع، وهاشه (`0e3631b`) في `docs/ops/backups.log`.
  5. نسخة احتياطية (`scripts/backup.sh`) قبله مباشرة، وسببها يسمّي الأمر.
  6. لقطتا SELECT كاملتان قبل وبعد تثبتان أن خمسة صفوف بالضبط تغيّرت.
  7. لم تُمسّ الشيفرة المخدومة، فالحي باقٍ على `b15041c`.

  إن غاب أيّ شرط منها فالطريق هو `deploy.sh`.
- **غير منشور:** إصلاح التسجيل `b240087`. حتى النشر القادم، أي مستأجر يُسجَّل على الحي
  يولد ناقصًا الخمسة أعلاه. هذه كلفة الانتظار المقبولة بقرار المالك.
- **سبب عدم النشر:** نشر `main` لإصلاح خمس قواعد اعتماد على مستأجر تجريبي واحد يشحن معه
  7.3 و7.4 بلا UAT، وواجهة استعادة كلمة المرور في 7.2.9 دون مزوّد بريد مهيَّأ.

## Declared exception: live mail goes nowhere (`EMAIL_BACKEND` = dummy), 2026-10-19

- **What:** live's `.env` holds, in its email block, the line
  `EMAIL_BACKEND=django.core.mail.backends.dummy.EmailBackend`.
  The dummy backend sends nothing and logs nothing: password-reset mails (7.2.9) and the
  approvals digest are dropped silently.
- **Why:** before this, live had no `EMAIL_HOST`, so `config/settings.py` fell back to the
  console backend, and from 7.2.9 on every password-reset link, token included, would have
  been written to the backend/celery_worker log. `settings.py` did not read `EMAIL_BACKEND`
  from the environment at all until the commit that added this section; a `.env` line alone
  would have changed nothing.
- **Visible on every deploy:** `cps_run_gates` prints
  `email backend for <target>: <class path>` before gate 1 (asked of the newly built image
  with the target's env file), and every Django process logs `email backend: <class path>`
  at startup. Staging always prints the console backend (its hard override).
- **Temporary, until Phase B** (a real mail provider). Phase B uses the same variable, so the
  change back is exactly this one line in live's `.env`:
  - from: `EMAIL_BACKEND=django.core.mail.backends.dummy.EmailBackend`
  - to: `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend` (plus `EMAIL_HOST`,
    `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` filled in), then `deploy.sh`.
  - Do **not** just delete the line before Phase B: with `EMAIL_HOST` still empty, that
    falls back to the console backend, and reset tokens go to the log again.
- **Cost while it lasts:** "forgot password" on live answers normally but no mail arrives;
  a locked-out user needs the owner (see the live password-change paths report,
  `docs/reports/2026-10-19-live-password-change-paths.md`).

## Decision: branch protection on main — no required status checks, 2026-10-20

**Owner's decision, 2026-10-20.** On `main`:

- **Block force pushes** and **Restrict deletions** are on, with bypassing disallowed.
- **"Require status checks to pass" is NOT enabled.**

**Reason, verified against GitHub's documentation**
(docs/reports/2026-10-20-ci-parity-and-protection.md §2):

- With required checks, a push whose commit has not passed them is refused with `GH006: Protected branch
  update failed`.
- This server pushes with a **deploy key**. GitHub's SSH greeting names the repository, not a user. Our
  checks run only *after* a push (`on: push`), so every commit pushed from here would be refused.
- The owner's own pushes, as repository admin, are exempt by default.
- Required checks would therefore bind the automation and free the human: the reverse of what a gate is
  for.

CI still turns a bad push red: the Gate step and `scripts/check_ci_collection.sh` (docs/reports/2026-10-20-ci-coverage.md).
A red run marks the commit; it does not block it.

Re-open only with an answer to the deploy-key problem. Two ways would work:

- push to a branch and fast-forward `main` to a SHA that already passed;
- give the automation its own non-admin identity, with the owner bound by "Do not allow bypassing".

## `make ci-local` — البوابة الحقيقية طوال ثمانية أيام (سبرنت 7.0)

ثبت أن CI (`.github/workflows/ci.yml`) **لم تنجح ولا مرة واحدة منذ
إنشاء سير العمل** — 61/61 تشغيلة `conclusion=failure` (`docs/
SYSTEM_ANALYSIS.md` §11). ما اعتمد عليه هذا المشروع فعليًا طوال تلك
الفترة هو تشغيل بشري يدوي لنفس الفحوص — `make ci-local` يجعل ذلك
هدفًا مُسمًّى بنتيجة مُسجَّلة (`docs/ops/ci-local.log`)، لا ممارسة
شفهية. يشغّل، بالترتيب، نفس تسلسل مهمات `ci.yml` الثلاث زائد بوابة
المشروع القائمة (§0 القاعدة 7): `ruff` ← `manage.py check` ←
`makemigrations --check` ← pytest الكاملة ← `npm run build` (يُشغِّل
الفحوص البنيوية السبعة تلقائيًا عبر `prebuild`) ← e2e عبر
`make dev-up CI_OVERLAY=1` (نفس مسار CI الحقيقي بلا MinIO) ← `make
e2e`، ثم يعيد `make dev-up` العادي (بلا `CI_OVERLAY`) لإرجاع صندوق
التطوير لحالته الطبيعية بصرف النظر عن النتيجة. يُشغَّل بعد آخر commit
في كل كتلة (ضمن بوابة §0 القاعدة 7)، وناتجه (PASS/FAIL لكل خطوة) يُذكَر
في ملخص الكتلة.

```
make ci-local
```

## صندوق التطوير (`make dev-up`, منفذ 3002)

للكتابة والتجربة فقط — لا UAT هنا أبدًا. مستقل تمامًا (قاعدته/تخزينه
الخاص، فارغ عند أول تشغيل)؛ استخدم مستأجرات `smoke-*` عبر الـ
API/الواجهة، ثم `manage.py archive_smoke_tenants` في نفس الجلسة (§0
قاعدة 3) — لا تلمس Fatma/acme مباشرة هنا أو في أي بيئة أخرى.

```
make dev-up      # يبني ويشغّل
make dev-logs    # سجلات مباشرة
make dev-down    # إيقاف
make test        # pytest داخل الصندوق
make lint        # ruff داخل الصندوق
make check       # فحوص الواجهة البنيوية (brand/money/forms/entity-default)
make migrate     # migrate على قاعدة الصندوق فقط — لا يمسّ 3000 أبدًا
```

**تشغيلتا `pytest` على `test_cps` في وقت واحد تُنتجان فشلًا كاذبًا**
(سبرنت 6.6.7، مؤكَّد فعليًا): تشغيلة أمامية (foreground) تبدأ بينما
تشغيلة خلفية (background، مثل بوابة كاملة قبل commit) لا تزال تعمل
على نفس القاعدة تتصادمان — `DROP DATABASE ... is being accessed by
other users`، `SystemExit(2)`، أو مئات أخطاء التجميع (collection
errors) الكاذبة بلا علاقة بأي تغيير كود حقيقي. **قبل أي تشغيلة
أمامية:** تحقَّق أولًا أن لا تشغيلة خلفية جارية (`pgrep -f pytest`
داخل حاوية `backend`، أو `ps aux | grep pytest`)، أو استخدم اسم قاعدة
مميّز لكل تشغيلة (`--create-db` باسم مختلف عبر `PYTEST_XDIST`/متغيّر
بيئة خاص) إن احتجت تشغيلتين فعليًا متزامنتين. ملف خروج فارغ لمهمة
خلفية **لا يعني أنها ماتت** — تشغيلة كاملة (~11 دقيقة) تطبع نقاطًا
فقط عند الانتهاء؛ انتظر إشعار الاكتمال الفعلي بدل إعادة المحاولة.

## staging (`make staging-up`, منفذ 3001)

نسخة كاملة مستقلة، بيئتها `.env.staging` (نسخ `.env.staging.example`
وتعبئته فعليًا قبل أول تشغيل — لم يُدرَج في الريبو، مثل `.env`
نفسها). لا تُعدَّل بياناتها يدويًا أبدًا — فقط عبر:

```
scripts/staging_refresh.sh --full        # أو: make staging-refresh
scripts/staging_refresh.sh --code-only   # الكود فقط، البيانات كما هي
```

النمط **مطلوب صراحةً**: بلا وسيط، أو بوسيط غير معروف (`--code-onyl`)، أو
بالنمطين معًا، يرفض السكربت قبل أن يلمس أي شيء ويطبع الاستعمال (كان أي
وسيط غير `--code-only` يعني «امسح staging»؛ Pre-deploy 1، 2026-10-17).

`--full` يستعيد آخر نسخة احتياطية من `/opt/cps-backups/` (نفس نسخ الحي)
إلى قاعدة staging المستقلة، ثم **مباشرةً، قبل أول بوابة**، يُشغِّل
`manage.py anonymize_staging_users` في حاوية مؤقتة
(يرفض العمل خارج `CPS_ENVIRONMENT=staging` بشكل صريح — لا يمكن
تشغيله بالخطأ على الحي)، الذي:
- يبقي **الجزء المحلي** من بريد كل مستخدم، ويستبدل النطاق بـ
  `<subdomain المستأجر>.staging.test` — بريد حقيقي (بريد مالكة Fatma
  مثلًا Gmail حقيقي، لا `.test`) لا يصل لأحد فعليًا بعد هذا التغيير.
  تصادم نادر لجزء محلي متطابق داخل مستأجر واحد يُحلّ برقم لاحق
  (`owner-2@...`) لا بفشل التشغيلة.
- يعيد كتابة كلمة سر **كل** مستخدم إلى قيمة UAT معروفة واحدة
  (`STAGING_UAT_PASSWORD` في `.env.staging`) — **لا تُطبع** (القاعدة 50،
  2026-10-18): السكربت يذكر اسم المتغيّر ومصدره فقط؛ القيمة تُقرأ من
  `.env.staging` نفسه.
- مسار الدخول نفسه لا يحتاج أي تعديل — يطابق البريد المخزَّن فعليًا
  بعد إعادة الكتابة.

`EMAIL_BACKEND` على staging = console دائمًا (`config/settings.py`
يفرضها صراحةً عند `CPS_ENVIRONMENT=staging`، بصرف النظر عن أي
`EMAIL_HOST` قد يُضبَط بالخطأ في `.env.staging`) — لا رسالة حقيقية
تُرسَل لأي من هذه العناوين (المُعمَّاة أو الأصلية) من staging أبدًا.

**سُدِّد في سبرنت 6.6.3b:** `anonymize_staging_users` نفسه يعيد الآن
تهيئة 2FA (يمسح `totp_secret`/`totp_confirmed`/رموز الاسترداد) ويمسح
`must_change_password` ويُبطل كل توكن/جلسة لكل مستخدم مُعمَّى — قبل أي
جلسة UAT قادمة على هذا المنفذ. كما أضاف 6.6.3b خطوة `manage.py
setup_rls` + فحص عدد سياسات RLS — اليوم ضمن البوابات المشتركة، بعد
الإخفاء (التفاصيل والقاعدة الكاملة: `docs/ops/RLS.md`).

**الإخفاء يسبق البوابات (Pre-deploy 1، 2026-10-17):** كان يجري بعد آخر
بوابة، فكانت بيانات الحي الحقيقية على staging طوال التشغيلة — وإلى الأبد إن
سقطت بوابة — وكانت بوابة `backup` نفسها تكتبها في ملف ثانٍ تحت
`/opt/cps-backups/staging`. لا بوابة تحتاج البيانات الأصلية (`smoke` يدخل
بالحساب المُخفى). ولأنه يجري قبل `migrate`، أي بكود جديد على مخطط الحي،
لا يحمّل الأمر صفًّا كاملًا بل يسمّي أعمدته. وإن توقف السكربت بين بدء
الاستعادة ونهاية الإخفاء (استعادة ناقصة، إخفاء فاشل، Ctrl-C) **تُحذف قاعدة
staging** في `trap EXIT` — قاعدة فارغة تُصلحها إعادة التشغيل، وقاعدة تحمل
بيانات حقيقية لا.

بعد كل تشغيلة: نفس عدد المستأجرات كالحي (تحقّق يدوي بسيط)، والسكربت
نفسه يطبع بريد Owner مستأجر Fatma الجديد (بنمط `<subdomain>.staging.
test`) وكلمة السر الموحّدة — تسجيل الدخول بهما يعمل فورًا على
`http://<هذا الخادم>:3001`.

## الدوران وقناتا قاعدة البيانات، وقاعدة النشر على staging أولًا (سبرنت 6.6.3b)

منذ RLS (سبرنت 6.6.3)، هناك دوران (`cps` غير المقيَّد، `cps_app`
المقيَّد) وقناتان (`"default"`, `"platform"`) — الشرح الكامل، وقاعدة
"كل استعادة تتبعها `setup_rls` + فحص عدد السياسات"، في `docs/ops/
RLS.md`. **القاعدة التي تهمّ هذا المستند بالتحديد:**

> أي كتلة سبرنت تمس المصادقة (authentication)، أو أدوار قاعدة البيانات
> (`cps`/`cps_app`)، أو RLS نفسها (السياسات، `configure_database_
> roles_and_rls`، الوسيط `AdminDatabaseRoutingMiddleware`/الموجِّه
> `AdminBypassRouter`) — تُنشر على **staging أولًا** (`make
> staging-up` + `scripts/staging_refresh.sh --full` إن احتاجت بيانات جديدة)،
> ثم `make smoke` هناك فعليًا، **ثم فقط** على الحي عبر `scripts/
> deploy.sh` المعتاد. لا نشر مباشر على 3000 لأي كتلة من هذا النوع، بصرف
> النظر عن نتيجة الاختبارات المحلية وحدها — حادثة 6.6.3 نفسها (ثلاث
> كسرات حية متتالية في المصادقة، كل واحدة أمسكها `make smoke` على الحي
> نفسه بعد النشر) هي السبب المباشر لهذه القاعدة.

## `.env` الحي لا يُلمس أبدًا للتجربة — نسخة معزولة لمحاكاة أي بيئة (سبرنت 6.6.3d)

**حادثة 2026-10-01** (`docs/SYSTEM_ANALYSIS.md` §11، الدرس الكامل):
استبدال `.env` الحي بقيم `.env.example` الوهمية مؤقتًا (لمحاكاة بيئة
CI) ونسيان استرداده بعدها أدّى لاحقًا إلى تهيئة دور `postgres` الداخلي
على صندوق `cps-dev` بكلمة سر وهمية — استعادة `.env` وحدها لا تُصلح
ذلك (postgres لا يُعيد ضبط كلمة سره إلا عند تهيئة أولى لـvolume فارغ
فعليًا). الحي نفسه لم يُلمَس، لكن القاعدة الآن صريحة:

> **`.env` الحي (`/opt/cps/.env`) لا يُلمس أبدًا لأي تجربة أو إعادة
> إنتاج بيئة أخرى** — أي محاكاة (CI، اختبار سيناريو لا يحتاج القاعدة
> الحقيقية) تتم في `/opt/cps-ci`، نسخة `git worktree` معزولة كليًا
> بملفات `env` خاصة بها (نسخ من `.env.example`/`.env.staging.example`
> دومًا — لا سرّ حقيقي فيها إطلاقًا) ومشاريع compose بادئتها
> `cps-ci-*`، لا تتقاطع مع `infra`/`cps-dev`/`cps-staging` أبدًا.
> التفاصيل والاستخدام: `/opt/cps-ci/README-CI-WORKTREE.md`.

**الحارس البنيوي:** `scripts/deploy.sh` يفحص الآن، قبل أي خطوة، أن كل
سرّ مطلوب في `.env` (`DJANGO_SECRET_KEY`، `PLATFORM_JWT_SIGNING_KEY`،
`POSTGRES_PASSWORD`، `POSTGRES_APP_PASSWORD`، `MINIO_ACCESS_KEY`،
`MINIO_SECRET_KEY`، `ATTACHMENT_LINK_SIGNING_KEY`،
`CPS_BACKUP_ENCRYPTION_PASSPHRASE`) لا يحمل القيمة الوهمية الحرفية
(`change-me...`) التي يستخدمها `.env.example` لكل واحد منها — يرفض
النشر صريحًا بدل الاستمرار بأسرار وهمية لو حدث هذا مرة أخرى.

## ملاحظة فنية: `env_file: !override`

`infra/docker-compose.staging.yml` يستخدم `env_file: !override
[../.env.staging]` لكل خدمة (لا `env_file: ../.env.staging` كنص
عادي) — لأن compose **يُدمِج** قوائم `env_file` عبر الملفات (لا
يستبدلها) حين تكون نصًا عاديًا، فيبقى أي متغيّر موجود فقط في `.env`
الحقيقي (وليس في `.env.staging`) مسرَّبًا إلى حاوية staging. `!override`
هو الوسم الصريح في Compose لاستبدال القائمة كليًا بدل دمجها — تحقَّق
من هذا فعليًا بـ `docker compose ... config` قبل الاعتماد عليه (سبرنت
6.6.0).
