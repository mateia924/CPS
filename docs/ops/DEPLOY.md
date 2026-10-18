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
إن غاب أو كانت أذوناته أوسع. إنشاؤه (مرة واحدة، كـroot، بلا أن تمر القيمة
بسجل الصدفة): `install -m 600 -o root -g root /dev/null /etc/cps-secrets/smoke_password`
ثم `read -rs p && printf '%s\n' "$p" > /etc/cps-secrets/smoke_password; unset p`. أي أنه **ليس حساب فحص
مخصصًا**: سجل تدقيق عميل حقيقي يحمل دخول الفحص، و«آخر نشاط» للمستأجر في
لوحة المنصة يتحرك مع كل نشر. مفتوح: حساب فحص مخصص (مستأجر فحص منفصل) قبل
أول نشر حي عبر البوابات. على staging يدخل `smoke` بحساب المحاسب المُخفى
(`accountant@fatma.staging.test` وكلمة `STAGING_UAT_PASSWORD`) في النمطين.

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
  (`STAGING_UAT_PASSWORD` في `.env.staging`) — تُطبع مرة واحدة في نهاية
  السكربت، لا تُسجَّل في أي ملف `docs/ops/*.log`.
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
