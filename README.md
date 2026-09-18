# CPS — منصة إدارة الأعمال (ERP)

منصة SaaS متعددة المستأجرين (Multi-tenant) لإدارة الأعمال، تبدأ كنظام
محاسبي ومخزني كامل. مبنية بـ Django REST Framework + Next.js، تدعم
العربية (افتراضي) والإنجليزية مع RTL كامل.

**المرجع المعماري الملزم لكل سبرنت:** [`docs/SYSTEM_ANALYSIS.md`](docs/SYSTEM_ANALYSIS.md)
— كل قرار تصميمي، خارطة الـ 13 سبرنت، والقواعد الثابتة (قسم 4) موجودة
هناك. أي تعارض بين هذا الملف والكود يُحل لصالح `SYSTEM_ANALYSIS.md`.

## الحالة الحالية

- **سبرنت 0 (التحصين):** ✅ مكتمل — pytest ضد Postgres حقيقي، حاويات
  backend/celery_worker non-root، ruff نظيف، CI يفشل فعليًا عند أي خطأ.
- **سبرنت 1 (الهيكل التنظيمي + الصلاحيات + الوضع المبسّط):** ✅ مكتمل —
  شجرة قانونية (`LegalEntity`: holding/company/branch، عمق غير محدود)،
  شجرة مراكز تكلفة (`CostCenter`)، RBAC كامل (`Role`/`Permission`/
  `UserEntityAccess`) مطبّق على كل ViewSet موجود، `TenantFeatures` +
  `simplified_mode` في `/api/auth/me/`. `Invoice`/`JournalEntry` يحملان
  `legal_entity` إلزامي، `InvoiceLine`/`JournalLine` يحملان `cost_center`
  اختياري على مستوى السطر. تسجيل شركة جديدة يُنشئ COMPANY+BRANCH + الأدوار
  الأربعة (Owner/Accountant/Sales/Viewer) تلقائيًا. بيانات ما قبل هذا
  السبرنت هوجرت بـ data migrations حقيقية (تحقّق منها ضد بيانات فعلية،
  ليس فقط قاعدة اختبار فارغة). 36 اختبار pytest إجمالًا. تفاصيل كاملة في
  "كيف تشغّل الاختبارات" أدناه وفي `docs/SYSTEM_ANALYSIS.md` قسم 11.
- **العمل السابق لاعتماد خارطة الـ 13 سبرنت:** Tenant/User، تسجيل شركة،
  تسجيل دخول JWT، دليل حسابات أولي، عملاء/منتجات/فواتير بحساب خادمي كامل
  وترحيل قيد متوازن عند الاعتماد.
- **التقدير الواقعي** (`docs/SYSTEM_ANALYSIS.md` قسم 2): ≈12-15% من نطاق
  الـ ERP الكامل. Master Data الموحّد (Party)، الدليل الشجري الكامل،
  السندات، الفترات المالية، المستودعات، المشتريات — **لم تُبنَ بعد**؛ هي
  خارطة سبرنتات 2-12 القادمة.

## البنية

```
backend/    Django 5.2 LTS + DRF — apps: tenants, accounts, organization,
            access, accounting, sales + tests/ (pytest) + pyproject.toml
frontend/   Next.js 16 + TypeScript (App Router) — عربي/RTL افتراضيًا
infra/      docker-compose.yml (أساسي) + .dev.yml/.prod.yml (overlays) + nginx
.github/    workflows/ci.yml
Makefile    اختصارات: dev-up, dev-down, dev-logs, dev-build, dev-config,
            test, lint, prod-up, prod-down, prod-config
docs/       SYSTEM_ANALYSIS.md (المرجع الملزم) + CPS_Technical_Architecture_Study.md
```

### التطبيقات الخلفية (backend/apps)

- `tenants` — نموذج Tenant، و`TenantFeatures` (وحدات مفعّلة لكل مستأجر).
- `accounts` — نموذج User مخصص (email فريد **ضمن** المستأجر لا عالميًا)،
  auth backend مخصص (`TenantEmailBackend`)، تسجيل/دخول/JWT، `/api/auth/me/`.
- `organization` — الشجرة القانونية (`LegalEntity`) وشجرة مراكز التكلفة
  (`CostCenter`)، كل منهما بعمق غير محدود عبر `parent` self-FK.
- `access` — RBAC: `Permission` (كتالوج ثابت عالمي)، `Role` (لكل مستأجر،
  قابل للتعديل)، `UserEntityAccess` (نطاق الكيانات لكل مستخدم).
- `accounting` — دليل الحسابات (Account) وقيود اليومية (JournalEntry/Line).
- `sales` — العملاء، المنتجات، الفواتير وبنودها.

## قاعدة الأمان الأهم: عزل المستأجر (Tenant Isolation)

كل استعلام على جداول الأعمال يُقيَّد بـ `request.user.tenant` فقط
(`apps/common/viewsets.py: TenantScopedViewSet`). لا يوجد أي endpoint
يقبل `tenant_id` من العميل. **تم اكتشاف وإصلاح ثغرة حرجة أثناء بناء هذه
المرحلة:** وجود `django.contrib.auth.backends.ModelBackend` في
`AUTHENTICATION_BACKENDS` كان يسمح بتسجيل الدخول بـ subdomain خاطئ طالما
البريد/كلمة المرور صحيحين لمستخدم في **أي** مستأجر آخر، لأن ModelBackend
يبحث عن المستخدم بالبريد عالميًا بدون تصفية بالمستأجر. تم حذفه نهائيًا من
الإعدادات — `TenantEmailBackend` هو الوحيد المعتمد. **لا تُرجعه أبدًا.**

## الصلاحيات (RBAC) ونطاق الكيانات

طبقة فوق عزل المستأجر، لا بديلًا عنه (`docs/SYSTEM_ANALYSIS.md` قسم 3):

- **الصلاحيات**: `Permission` كتالوج عالمي ثابت بصيغة `<module>.<action>`
  (مثال: `invoices.create`)، مرتبط بـ `Role` (لكل مستأجر) عبر M2M.
  `apps/access/permissions.py: HasModulePermission` تُطبَّق على كل
  ViewSet موجود عبر `permission_map = {action: "code"}` — ViewSet بدون
  `permission_map` غير مقيّد بها إطلاقًا (opt-in لا افتراضي-رفض).
- **نطاق الكيانات**: `UserEntityAccess` يحدد أي كيانات قانونية يرى
  المستخدم؛ الوصول لكيان يشمل كل أبنائه تلقائيًا
  (`apps/organization/services.py: get_accessible_entity_ids`).
  المستخدم الحائز على دور "Owner" النظامي يتجاوز هذا القيد ويرى كل
  كيانات مستأجره (`apps.access.services.user_is_owner`) — **هذا منفصل
  تمامًا عن حقل `User.role` القديم من سبرنت 0**، انظر سجل القرارات.
- **الأدوار النظامية الأربعة** (Owner/Accountant/Sales/Viewer) تُنشأ
  تلقائيًا مع كل مستأجر جديد بصلاحيات افتراضية معقولة، وقابلة للتعديل
  لكل مستأجر عبر `/api/roles/` (لا تمس مستأجرين آخرين — كل نسخة منفصلة).

## قرار البنية التحتية: هذا السيرفر للتطوير فقط

هذا السيرفر (Oracle Linux) **بيئة تطوير فقط**. الدومين والمنفذين 80/443
سيكونان على سيرفر إنتاج منفصل لاحقًا، والنقل بين السيرفرين عبر GitHub —
لا نشر مباشر من هنا. لذلك:

- الـ stack هنا يعمل دائمًا على **المنفذ 3000** فقط (dev overlay).
- ملفات الإنتاج (`docker-compose.prod.yml`) جاهزة ومُختبرة syntax لكنها
  **لا تعمل على هذا السيرفر أبدًا**.

### المنافذ المحجوزة على هذا السيرفر — لا تستخدمها

| المنفذ | الخدمة |
|---|---|
| 80, 443 | nginx نظامي (يخدم `saas.cps-oracle.com`، يوجّه لـ Tomcat وORDS) |
| 1521 | Oracle Listener (`tnslsnr`) |
| 8080 | **Oracle ORDS** (إنتاجي) — لا تُستخدم أبدًا لأي حاوية Docker |
| 8081 | Tomcat 9 (`/jri/` عبر nginx النظامي) |
| 9475 | ORDS standalone HTTP (حسب `/opt/ords/config/global/settings.xml`؛
  لاحظ أن هذا يختلف عن 8080 المذكور أعلاه — وثّقنا 8080 كمحجوز بناءً على
  توجيه صريح رغم أن إعداد ORDS الحالي يُظهر 9475؛ لو دة غير دقيق صحّحه) |
| 9475, 11839, 16385, 22, 6010, 111 | خدمات نظام/Oracle أخرى (راجع `ss -tlnp` قبل حجز أي منفذ جديد) |
| **3000** | **CPS (هذا المشروع) — dev فقط** |

قبل حجز أي منفذ جديد لهذا المشروع مستقبلاً، شغّل `ss -tlnp` وتأكد إنه فاضي.

## التشغيل محليًا (تطوير)

```bash
cd /opt/cps
cp .env.example .env        # ثم عدّل القيم، خصوصًا DJANGO_SECRET_KEY وكلمات المرور
make dev-up                 # = docker compose -f infra/docker-compose.yml
                             #   -f infra/docker-compose.dev.yml --env-file .env up -d --build
```

أوامر أخرى: `make dev-down`, `make dev-logs`, `make dev-build`,
`make dev-config` (للتحقق من الـ YAML بدون تشغيل).

في وضع dev الـ frontend يعمل بـ `next dev` (Turbopack، hot-reload حقيقي
عبر mount لمجلد `frontend/` بالكامل) بدل الـ build الثابت المستخدم في
الإنتاج.

بعد التشغيل:
- الواجهة: http://localhost:3000/
- الـ API: http://localhost:3000/api/
- لوحة إدارة Django: http://localhost:3000/admin/

الـ backend container يشغّل `migrate` و `collectstatic` تلقائيًا عند كل
إقلاع (جزء من `command:` في `infra/docker-compose.yml`). حاويتا `backend`
و`celery_worker` تعملان بمستخدم غير مميز (`appuser`, uid 1000) — الصورة
تبدأ بـ root فقط لأن `entrypoint.sh` يحتاجه لعمل `chown` على الـ named
volume `static_data` (يُنشأ root-owned افتراضيًا)، ثم يُسقط الصلاحيات عبر
`gosu appuser` قبل تشغيل أي كود تطبيقي فعلي — لا gunicorn ولا celery
يعملان كـ root أبدًا.

### إنشاء مستخدم مشرف (superuser) لدخول /admin

```bash
docker compose -f infra/docker-compose.yml -f infra/docker-compose.dev.yml \
  --env-file .env exec backend python manage.py createsuperuser
```
(سيطلب منك اختيار Tenant موجود مسبقًا — أنشئ مستأجرًا أولًا عبر
`/api/auth/register/` أو عبر الـ admin نفسه بعد أول دخول.)

## نشر الإنتاج لاحقًا (سيرفر منفصل — غير مُفعّل هنا)

`infra/docker-compose.prod.yml` جاهز ومُختبر (`make prod-config`) لكن لا
يُشغَّل على هذا السيرفر أبدًا. عند توفر سيرفر إنتاج منفصل ونقل الكود عبر
GitHub:

1. عدّل `.env` على سيرفر الإنتاج: `DOMAIN_NAME`, `CERTBOT_EMAIL`، وكل
   الأسرار (`DJANGO_SECRET_KEY`, كلمات مرور Postgres، إلخ) بقيم إنتاجية
   حقيقية — **لا تنسخ `.env` هذا السيرفر كما هو**.
2. أول إصدار شهادة SSL يحتاج خطوة يدوية لمرة واحدة (bootstrap) لأن nginx
   لن يبدأ بملف `nginx.prod.conf.template` كما هو بدون شهادة موجودة
   مسبقًا — التفاصيل موثقة كتعليق داخل
   `infra/nginx/nginx.prod.conf.template`.
3. `make prod-up` (= compose الأساسي + `docker-compose.prod.yml`، بورت
   80/443، بدون أي source bind-mounts، Next.js build ثابت).

## كيف تشغّل الاختبارات

```bash
make test    # pytest ضد Postgres حقيقي (خدمة postgres في dev compose)،
             # في قاعدة test_<POSTGRES_DB> منفصلة يُنشئها/يمسحها
             # pytest-django تلقائيًا — ليست SQLite أبدًا.
make lint    # ruff check .
```

كلاهما يُشغَّل أيضًا في CI على كل push (انظر "GitHub / CI" تحت) ويفشل
البناء فعليًا لو أي اختبار أو مخالفة lint فشلت — لا `continue-on-error`
ولا إخفاء لأخطاء في أي مكان.

**36 اختبارًا حاليًا** في `backend/tests/`:

- `test_health.py` (1): health check بسيط.
- `test_migrations.py` (1): طلب `db` fixture يُجبر pytest-django على بناء
  قاعدة الاختبار كاملة، فيفشل تلقائيًا لو أي migration معطوبة (بما فيها
  كل الـ data migrations — لكن على قاعدة فارغة؛ انظر ملاحظة أدناه عن حدود
  هذا الاختبار).
- `test_invoicing_e2e.py` (1): تحويل سيناريو الـ curl اليدوي القديم إلى
  اختبار دائم — تسجيل شركة ← دخول ← عميل ← منتجَين ← فاتورة ببندين
  (تحقق من subtotal/tax_total/total محسوبة خادميًا بالضبط: 531.00 /
  74.34 / 605.34) ← اعتماد الفاتورة ← تحقق أن قيد اليومية متوازن (مجموع
  المدين = مجموع الدائن = 605.34) وموزّع على الحسابات الصحيحة.
- `test_organization_tree.py` (4): منع BRANCH من امتلاك أبناء، منع الدورات
  (entity كأب لنفسه، وأب غير مباشر)، وendpoint `/tree/` يُرجع تعشيشًا
  صحيحًا لعمق 4 مستويات (Holding→Company→Company→Branch).
- `test_rbac.py` (4): دور Viewer لا يقدر ينشئ فاتورة (403 — داخل نفس
  المستأجر فالـ403 هنا صحيح ومختلف عن قاعدة الـ404 لعزل المستأجر)، لكنه
  يقدر يشوفها؛ مستخدم مقيّد بفرع A لا يرى تفاصيل ولا قائمة فواتير فرع B؛
  Owner يتجاوز القيد ويرى الفرعين معًا.
- `test_simplified_mode.py` (2): مستأجر جديد → `simplified_mode=true`
  فورًا بعد التسجيل؛ إضافة فرع ثانٍ عبر API → `false`.
- `test_tenant_isolation.py` (23) — **أهم ملف اختبار في المشروع**، يغطي
  كل نموذج قابل للوصول عبر API (عملاء، منتجات، فواتير، LegalEntity،
  CostCenter، Role):
  - رجعة (regression) لثغرة ModelBackend: تأكيد أن `AUTHENTICATION_BACKENDS`
    لا يحتوي عليها أبدًا، ودخول بـ subdomain خاطئ + بيانات صحيحة لمستأجر
    آخر يُرفض (400)، ودخول صحيح ينجح.
  - `list` لكل نموذج: مستأجر B لا يرى بيانات A إطلاقًا.
  - وصول مباشر بـ ID لسجل مستأجر آخر (GET/PATCH/DELETE) → **404 دائمًا
    لا 403** بدون أي تعديل أو تعطيل فعلي على السجل.
  - إنشاء فاتورة/كيان قانوني بمرجع (customer/product/parent) يخص مستأجر
    آخر → 400 (السيرفر يحلّ كل id ضد `request.user.tenant`؛ لا حقل
    `tenant_id` موجود أصلًا ليُستغل).

`backend/tests/factories.py` (factory-boy): `TenantFactory`,
`UserFactory`, `CustomerFactory`, `ProductFactory`, `LegalEntityFactory`,
`CostCenterFactory`, `RoleFactory` لبناء بيانات الاختبار بسرعة دون المرور
بكل الـ API لكل حالة.

**حدود معروفة في التغطية الآلية:** لم أكتب اختبار pytest آلي لمنطق
الـ backfill نفسه في data migrations (`organization/migrations/0002...`,
`sales/migrations/0003...`, إلخ) — يحتاج ذلك Django's `MigrationExecutor`
للرجوع لحالة تاريخية عبر 5 تطبيقات متشابكة التبعيات (organization،
accounts، access، sales، accounting)، وهو تعقيد حقيقي لم أعتبره يستاهل
الهشاشة الناتجة. بدلًا من ذلك: **تحققت يدويًا وفعليًا ضد بيانات حقيقية
موجودة من سبرنت 0** (مستأجر Acme Trading وفاتورته INV-0001) وتأكدت أنها
حصلت على `legal_entity=MAIN-01` الصحيح بعد تشغيل الـ migration فعليًا —
ليس فقط على قاعدة اختبار فارغة. التفاصيل في سجل القرارات
(`docs/SYSTEM_ANALYSIS.md` قسم 11، أو اسأل لرؤية سجل الجلسة).

## GitHub / CI

- الكود جاهز للنقل عبر GitHub: لا أسرار مكتوبة في الكود (كل شيء عبر متغيرات
  بيئة)، و`.gitignore` يستثني `.env`, `node_modules/`, `__pycache__/`,
  `backend/staticfiles/`, أدلة كاش pytest/ruff. **لم يُنفَّذ `git push`
  بعد** — بانتظار رابط الـ repository.
- `.github/workflows/ci.yml` يعمل على كل push، ويفشل فعليًا عند أي خطأ
  (لا إخفاء لأي فشل):
  - **backend**: `ruff check .` + `pytest -v` (36 اختبارًا، تفصيلها في
    "كيف تشغّل الاختبارات" أعلاه) ضد خدمة Postgres حقيقية داخل الـ CI
    نفسه (service container، ليست SQLite).
  - **frontend**: `npm install` + `npm run build` فقط (بما فيه فحص أنواع
    TypeScript كامل عبر `next build`؛ بدون lint/tests مخصصة بعد).

## ديون تقنية يجب معالجتها قبل الإنتاج

- **ترقيم الفواتير** (`apps/sales/services.py: generate_invoice_number`)
  يعتمد على `count() + 1` وهو غير آمن تحت الكتابة المتزامنة لنفس
  المستأجر. يحتاج DB sequence أو `select_for_update` قبل الإنتاج.
- **Django admin وتسجيل الدخول بدون subdomain**: `TenantEmailBackend`
  يسمح بمسار دخول بديل بدون subdomain، لكنه مقصور على `is_superuser=True`
  فقط ويتطلب أن يكون بريد المشرف فريدًا عالميًا (غير مفروض كقيد قاعدة
  بيانات، فقط اتفاقية تشغيلية). وثّق هذا عند إنشاء superusers.
- **لا يوجد rate limiting** على `/api/auth/login/` أو `/api/auth/register/`
  بعد — يُنصح بإضافته قبل الإنتاج لمنع brute-force.
- **الترجمة (i18n) في الـ backend**: النصوص مُغلّفة بـ `gettext_lazy`
  لكن لم يتم تشغيل `makemessages`/`compilemessages` بعد لتوليد ملفات
  `.po`/`.mo` الفعلية — الرسائل الحالية تظهر بالإنجليزية المصدرية داخل
  `.po` غير الموجود بعد، والعربية تعمل فقط لأن `LANGUAGE_CODE = "ar"` هو
  نص المصدر نفسه في هذه الحالة الخاصة عبر fallback القياسي لـ Django).
  شغّل:
  ```bash
  docker compose -f infra/docker-compose.yml --env-file .env exec backend \
    python manage.py makemessages -l ar -l en
  ```
  وترجم ملفات `.po` الناتجة في `backend/locale/`.
- **الفرونت إند**: لا توجد شاشة تعديل/حذف بعد لأي كيان (عملاء/منتجات/
  فواتير) — فقط عرض وإضافة، بما يكفي لاختبار السيناريو الأساسي. شاشات
  سبرنت 1 (الهيكل التنظيمي، مراكز التكلفة، الأدوار) نفس الشيء: عرض/إضافة
  فقط، بدون تعديل/حذف من الواجهة (الـ API يدعم PATCH وsoft-delete، لكن
  الشاشات لا تعرضهما بعد).
- **ترحيل قيد الفاتورة لا يوزّع `cost_center`** من بنود الفاتورة على
  سطور القيد بعد (`apps/accounting/services.py: post_invoice_journal_entry`)
  — القيد الحالي مجمّع (سطر إيراد واحد). التوزيع الدقيق لكل مركز تكلفة
  مؤجل لسبرنت التقارير (10). موثّق أيضًا كتعليق في الكود.
- **حذف LegalEntity/CostCenter عبر الـ API هو soft-deactivate دائمًا**
  (`is_active=False`)، حتى لو لم توجد أي معاملات عليه — قرار متعمد للبساطة
  والأمان (انظر سجل القرارات)، وليس تنفيذًا حرفيًا لصياغة "لا حذف لكيان
  عليه معاملات" التي تسمح ضمنيًا بحذف فعلي لكيان بلا معاملات.
- **Celery**: الـ worker يعمل ومتصل بـ Redis لكن لا توجد مهام (tasks)
  مُعرّفة بعد — سيُستخدم لاحقًا لتوليد PDF والإشعارات وإرسال الفوترة
  الإلكترونية كما هو مخطط.
- **`frontend` container يرث كل متغيرات `.env` عبر `env_file`** (بما فيها
  `DJANGO_SECRET_KEY` وكلمة مرور Postgres) رغم أنه لا يحتاج أيًا منها —
  Next.js نفسه لا يعرّضها للمتصفح (فقط `NEXT_PUBLIC_*` تُحقن في الـ build)،
  لكن تعريضها داخل بيئة الحاوية أصلاً غير ضروري. يُستحسن تحديد `environment:`
  صريحة بدل `env_file` الكامل لخدمة frontend قبل الإنتاج.
- **إصدار الشهادة الأولى في الإنتاج**: `infra/nginx/nginx.prod.conf.template`
  يفترض وجود شهادة Let's Encrypt مسبقًا (`ssl_certificate` يشير لمسار
  `/etc/letsencrypt/live/${DOMAIN_NAME}/...`) — nginx لن يُقلع بدونها. خطوة
  bootstrap يدوية لمرة واحدة موثّقة كتعليق داخل نفس الملف.

## الخطوة التالية

**سبرنت 2** حسب خارطة `docs/SYSTEM_ANALYSIS.md` قسم 5: إدارة المنصة
الأساسية — Super Admin بجدول مستخدمين منفصل تمامًا عن مستخدمي المستأجرين
+ 2FA إلزامي، لوحة المستأجرين (حالة/باقة/نشاط/تعليق/تفعيل)، الباقات
والحدود (تربط بـ `TenantFeatures` الموجود بالفعل)، سجل تدقيق غير قابل
للتعديل. معيار القبول: تغيير باقة يفعّل/يخفي وحدات فورًا.
