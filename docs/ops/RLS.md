# Row-Level Security — الدوران والقناتان والقاعدة (سبرنت 6.6.3 / 6.6.3b)

## الدوران (roles)

دوران فقط على كل بيئة فيها RLS (الحي `infra`، staging `cps-staging`؛
`cps-dev` يبقى على الدور الأصلي دومًا — ليس بيئة UAT/إنتاج، سبرنت
6.6.0):

| الدور | من يتصل به | يتجاوز RLS؟ |
|---|---|---|
| `cps` (الدور الأصلي، superuser) | migrations، الأوامر الإدارية، Celery، قناة `"platform"` | **نعم** — دومًا، بلا حاجة لسياسة استثناء، لأنه الدور الذي كان موجودًا قبل هذا السبرنت أصلًا |
| `cps_app` (`POSTGRES_APP_USER`/`POSTGRES_APP_PASSWORD`، `NOSUPERUSER NOBYPASSRLS`) | عملية gunicorn نفسها (طلبات المستأجرين) — `APP_DATABASE_URL` في `docker-compose.local.yml`/`docker-compose.staging.yml` فقط | لا |

`apps.tenants.services.configure_database_roles_and_rls` هو المكان
الوحيد الذي يُنشئ/يُحدّث `cps_app` ويمنحه الصلاحيات ويُفعّل RLS —
**idempotent** فعليًا (`CREATE ROLE` أو `ALTER ROLE` حسب الوجود،
`GRANT`/`ALTER DEFAULT PRIVILEGES` بلا شرط `IF NOT EXISTS`). يُستدعى
من مكانين فقط:
- migration واحدة (`apps.tenants.migrations.0016_row_level_security`) —
  أول مرة فقط، فعليًا، على كل قاعدة تُهاجَر من الصفر.
- `manage.py setup_rls` (`apps.tenants.management.commands.setup_rls`)
  — يُعاد تشغيله يدويًا/سكربتيًا بعد كل استعادة، لأن `pg_dump
  --no-privileges` (`scripts/backup.sh`) يُسقط كل GRANT وكل سياسة RLS
  من النسخة الاحتياطية نفسها؛ قاعدة مُستعادة بلا هذه الخطوة = صفر
  صلاحيات لـ`cps_app` وصفر سياسات.

## القناتان (DB aliases, `config/settings.py` → `DATABASES`)

| القناة | مُقيَّدة بـRLS؟ | من يستخدمها |
|---|---|---|
| `"default"` | نعم، إذا كان `DATABASE_URL` مضبوطًا على `cps_app` (الحي/staging) — لا، إذا كان على `cps` (`cps-dev`) | كل طلب مستأجر عادي؛ أيضًا كل migration/أمر إداري/Celery (تتصل بـ`"default"` أيضًا، لكن بدور `cps` دائمًا بصرف النظر عن القناة) |
| `"platform"` | لا — تتصل دائمًا بالدور الأصلي `cps` غير المقيَّد | استعلامات `apps.platform` العابرة للمستأجرات فقط. `apps.tenants.routers.AdminBypassRouter` يوجّه إليها تلقائيًا أي طلب `/admin/*` (عبر `apps.tenants.middleware.AdminDatabaseRoutingMiddleware`) — لا حاجة لـ`.using("platform")` صريح هناك. أي استخدام صريح آخر لهذه القناة خارج `apps/platform/`، `apps/*/admin.py`، والأوامر الإدارية يُفشِل `tests/test_platform_db_structural.py` (سبرنت 6.6.3b، البند أ) إلا باستثناء صريح موثَّق في `PLATFORM_DB_EXEMPTIONS` بذلك الملف — الاستثناء الوحيد اليوم: `AttachmentDownloadView` (رابط موقَّع، بلا سياق مستأجر على الإطلاق). |

## الجداول المستثناة من RLS

**لا يوجد اليوم أي جدول مستثنى.** كل جدول يحمل عمود `tenant_id`
(`apps.common.rls.tenant_scoped_tables()` — الاكتشاف نفسه الذي يستخدمه
كلٌّ من `configure_database_roles_and_rls` و`tests/
test_rls_structural.py`، فلا يمكن أن يختلفا) يحصل على RLS مفعّل +
سياسة `tenant_isolation` تلقائيًا، بلا آلية استثناء شبيهة بـ
`PLATFORM_DB_EXEMPTIONS` أصلًا — استثناء جدول من RLS هو قرار أعلى خطرًا
من استثناء كود من قناة `"platform"`، فلم يُبنَ له مسار سهل عمدًا. إن
احتاج جدول مستقبلًا استثناءً فعليًا، فذلك قرار صريح يُسجَّل هنا أولًا،
لا تعديل صامت على `configure_database_roles_and_rls`.

## القاعدة: كل استعادة تتبعها `setup_rls` + فحص العدّ

**كل استعادة لقاعدة البيانات — staging (`scripts/staging_refresh.sh`)،
`restore_test.sh` (سبرنت 6.6.4)، أو الإنتاج — يجب أن تتبعها فورًا:**

```
manage.py setup_rls
```

**ثم** فحص أن عدد صفوف `pg_policies` (بـ`policyname = 'tenant_isolation'`)
يساوي عدد الجداول التي يُرجعها `tenant_scoped_tables()` بالضبط — وليس
مجرد "نجح الأمر بلا خطأ". السبب: `pg_dump --no-privileges` يُسقط كل
GRANT والسياسات من النسخة نفسها، فأي قاعدة مُستعادة بلا هذه الخطوة
تعمل بصلاحيات `cps_app` كاملة (RLS متوقف فعليًا من منظور ذلك الدور) دون
أي خطأ ظاهر — الفحص هو ما يحوّل "صمت" إلى فشل صريح بدل تسرّب هادئ.

الصياغة المرجعية (نفسها في `tests/test_rls_structural.py` و
`scripts/staging_refresh.sh`'s الخطوة 6/7):

```python
from django.db import connection
from apps.common.rls import tenant_scoped_tables

tables = [name for name, _model in tenant_scoped_tables()]
with connection.cursor() as cursor:
    cursor.execute(
        "SELECT count(*) FROM pg_policies WHERE schemaname = 'public' "
        "AND policyname = 'tenant_isolation' AND tablename = ANY(%s)",
        [tables],
    )
    policy_count = cursor.fetchone()[0]
assert policy_count == len(tables)
```

- **staging** (`scripts/staging_refresh.sh`): هذه الخطوة مُضافة فعليًا
  الآن (سبرنت 6.6.3b) — الخطوة 6/7، قبل `anonymize_staging_users`؛
  تُوقف السكربت (`exit 1`) إن اختلف العددان، قبل أن تبدأ أي جلسة UAT
  على قاعدة بلا عزل حقيقي.
- **`restore_test.sh`**: نفس الخطوة تُضاف في سبرنت 6.6.4 (اختبار
  استعادة آلي) — لم يُبنَ هذا السكربت بعد.
- **الإنتاج**: نفس القاعدة تنطبق حرفيًا يوم يُبنى مسار استعادة فعلي
  للإنتاج (سبرنت 6.6.8 وما بعده) — تُضاف إلى `docs/ops/DEPLOY.md` حينها
  كخطوة إلزامية في أي إجراء استعادة حي، لا كملاحظة جانبية.

## القاعدة: أي كتلة تمس المصادقة/أدوار القاعدة/RLS تُنشر على staging أولًا

انظر `docs/ops/DEPLOY.md` — القاعدة نفسها مُسجَّلة هناك أيضًا، لأنها
قاعدة نشر (deploy) لا قاعدة RLS بالتحديد: أي كتلة سبرنت تمس المصادقة،
أو أدوار قاعدة البيانات، أو RLS نفسها، يجب أن تُنشر على staging أولًا،
ثم `make smoke` هناك، **ثم** فقط على الحي — لا نشر مباشر على 3000 لأي
كتلة من هذا النوع، بصرف النظر عن مدى نجاح الاختبارات المحلية.
