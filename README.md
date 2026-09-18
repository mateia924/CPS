# CPS — منصة إدارة الأعمال (ERP)

منصة SaaS متعددة المستأجرين (Multi-tenant) لإدارة الأعمال، تبدأ كنظام
محاسبي ومخزني كامل. مبنية بـ Django REST Framework + Next.js، تدعم
العربية (افتراضي) والإنجليزية مع RTL كامل.

**المرجع المعماري الملزم لكل سبرنت:** [`docs/SYSTEM_ANALYSIS.md`](docs/SYSTEM_ANALYSIS.md)
— كل قرار تصميمي، خارطة الـ 13 سبرنت، والقواعد الثابتة (قسم 4) موجودة
هناك. أي تعارض بين هذا الملف والكود يُحل لصالح `SYSTEM_ANALYSIS.md`.

## الحالة الحالية

- **سبرنت 0 (التحصين):** ✅ مكتمل — انظر "GitHub / CI" و"كيف تشغّل
  الاختبارات" أدناه. 18 اختبار pytest ضد Postgres حقيقي، حاويات backend
  و celery_worker non-root، ruff نظيف، CI يفشل فعليًا عند أي خطأ.
- **المرحلة صفر/1 من العمل السابق (أساس تجاري أولي، قبل اعتماد خارطة
  الـ 13 سبرنت في SYSTEM_ANALYSIS.md):** Tenant/User، تسجيل شركة جديدة،
  تسجيل دخول JWT (subdomain + email + password)، دليل حسابات أولي،
  عملاء/منتجات/فواتير بحساب خادمي كامل وترحيل قيد متوازن عند الاعتماد.
  هذا **هيكل عظمي أولي فقط** — التقدير الواقعي في SYSTEM_ANALYSIS.md
  قسم 2: ≈5-7% من نطاق الـ ERP الكامل. الشجرتان (قانونية/مراكز تكلفة)،
  Party الموحّد، الفترات المالية، المستودعات، المشتريات، إلخ — **لم
  تُبنَ بعد**؛ هي خارطة سبرنتات 1-12 القادمة.

## البنية

```
backend/    Django 5.2 LTS + DRF — apps: tenants, accounts, accounting, sales
            + tests/ (pytest) + pyproject.toml (pytest/ruff config)
frontend/   Next.js 16 + TypeScript (App Router) — عربي/RTL افتراضيًا
infra/      docker-compose.yml (أساسي) + .dev.yml/.prod.yml (overlays) + nginx
.github/    workflows/ci.yml
Makefile    اختصارات: dev-up, dev-down, dev-logs, dev-build, dev-config,
            test, lint, prod-up, prod-down, prod-config
docs/       SYSTEM_ANALYSIS.md (المرجع الملزم) + CPS_Technical_Architecture_Study.md
```

### التطبيقات الخلفية (backend/apps)

- `tenants` — نموذج Tenant (subdomain, name).
- `accounts` — نموذج User مخصص (email فريد **ضمن** المستأجر لا عالميًا)،
  auth backend مخصص (`TenantEmailBackend`)، تسجيل/دخول/JWT.
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

**18 اختبارًا حاليًا** في `backend/tests/`:

- `test_health.py` (1): health check بسيط.
- `test_migrations.py` (1): طلب `db` fixture يُجبر pytest-django على بناء
  قاعدة الاختبار كاملة، فيفشل تلقائيًا لو أي migration معطوبة.
- `test_invoicing_e2e.py` (1): تحويل سيناريو الـ curl اليدوي القديم إلى
  اختبار دائم — تسجيل شركة ← دخول ← عميل ← منتجَين ← فاتورة ببندين
  (تحقق من subtotal/tax_total/total محسوبة خادميًا بالضبط: 531.00 /
  74.34 / 605.34) ← اعتماد الفاتورة ← تحقق أن قيد اليومية متوازن (مجموع
  المدين = مجموع الدائن = 605.34) وموزّع على الحسابات الصحيحة.
- `test_tenant_isolation.py` (15) — **أهم ملف اختبار في المشروع**:
  - رجعة (regression) لثغرة ModelBackend: تأكيد أن `AUTHENTICATION_BACKENDS`
    لا يحتوي عليها أبدًا، ودخول بـ subdomain خاطئ + بيانات صحيحة لمستأجر
    آخر يُرفض (400)، ودخول صحيح ينجح.
  - `list` (عملاء/منتجات/فواتير): مستأجر B لا يرى بيانات A إطلاقًا.
  - وصول مباشر بـ ID لسجل مستأجر آخر (GET/PATCH/DELETE على عميل، GET
    على منتج، GET/issue على فاتورة) → **404 دائمًا لا 403** بدون أي
    تعديل فعلي على السجل.
  - إنشاء فاتورة بـ `customer` أو `product` يخص مستأجر آخر → 400
    (السيرفر يحلّ كل id ضد `request.user.tenant`؛ لا حقل `tenant_id`
    موجود أصلًا ليُستغل).

`backend/tests/factories.py` (factory-boy): `TenantFactory`,
`UserFactory`, `CustomerFactory`, `ProductFactory` لبناء بيانات الاختبار
بسرعة دون المرور بكل الـ API لكل حالة.

## GitHub / CI

- الكود جاهز للنقل عبر GitHub: لا أسرار مكتوبة في الكود (كل شيء عبر متغيرات
  بيئة)، و`.gitignore` يستثني `.env`, `node_modules/`, `__pycache__/`,
  `backend/staticfiles/`, أدلة كاش pytest/ruff. **لم يُنفَّذ `git push`
  بعد** — بانتظار رابط الـ repository.
- `.github/workflows/ci.yml` يعمل على كل push، ويفشل فعليًا عند أي خطأ
  (لا إخفاء لأي فشل):
  - **backend**: `ruff check .` + `pytest -v` (18 اختبارًا، تفصيلها في
    "كيف تشغّل الاختبارات" أعلاه) ضد خدمة Postgres حقيقية داخل الـ CI
    نفسه (service container، ليست SQLite).
  - **frontend**: `npm install` + `npm run build` فقط (بدون lint/tests
    بعد — خارج نطاق سبرنت 0).

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
  فواتير) — فقط عرض وإضافة، بما يكفي لاختبار السيناريو الأساسي.
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

**سبرنت 1** حسب خارطة `docs/SYSTEM_ANALYSIS.md` قسم 5: الهيكل التنظيمي
والصلاحيات — الشجرة القانونية (عمق غير محدود)، شجرة مراكز التكلفة
بالأنواع والربط، RBAC على مستوى الشركة/الفرع/الشاشة، الوضع المبسّط.
معيار القبول: مستأجر بشركة واحدة لا يرى الهيكل التنظيمي إطلاقًا.
