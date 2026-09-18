# CPS — منصة إدارة الأعمال

منصة SaaS متعددة المستأجرين (Multi-tenant) لإدارة الأعمال: فوترة، محاسبة،
مخزون، موارد بشرية، نقاط بيع، CRM. مبنية بـ Django REST Framework +
Next.js، تدعم العربية (افتراضي) والإنجليزية مع RTL كامل.

## الحالة الحالية

- **المرحلة صفر (أساس):** ✅ مكتملة ومُختبرة — Tenant/User، تسجيل شركة
  جديدة، تسجيل دخول JWT (subdomain + email + password)، دليل حسابات
  أولي يُنشأ تلقائيًا مع كل مستأجر جديد.
- **المرحلة 1 (جزئية):** ✅ العملاء، المنتجات، الفواتير متعددة البنود مع
  حساب تلقائي للإجمالي والضريبة من طرف الخادم، وترحيل قيود تلقائي لدليل
  الحسابات عند اعتماد الفاتورة (issue). باقي المرحلة 1 (تقارير محاسبية
  أوسع، تعديل/حذف الفواتير، إلخ) لم يُبنَ بعد.
- **المرحلة 2 (POS)، المرحلة 3 (HR + Workflow):** لم تبدأ بعد.

## البنية

```
backend/    Django 5.2 LTS + DRF — apps: tenants, accounts, accounting, sales
            + tests/ (pytest) + pyproject.toml (pytest/ruff config)
frontend/   Next.js 16 + TypeScript (App Router) — عربي/RTL افتراضيًا
infra/      docker-compose.yml (أساسي) + .dev.yml/.prod.yml (overlays) + nginx
.github/    workflows/ci.yml
Makefile    اختصارات: dev-up, dev-down, dev-logs, dev-build, dev-config,
            prod-up, prod-down, prod-config
docs/       (فارغ حاليًا)
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
إقلاع (`backend/entrypoint.sh`).

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

## اختبار end-to-end (تم تنفيذه فعليًا أثناء البناء، وأُعيد التحقق بعد
إعادة هيكلة infra إلى base/dev/prod وتغيير المنفذ لـ 3000)

السيناريو التالي اختُبر عبر curl على Postgres حقيقي داخل Docker ونجح:

1. `POST /api/auth/register/` — تسجيل شركة (Tenant + Owner user في
   transaction واحدة + دليل حسابات تلقائي).
2. `POST /api/auth/login/` — دخول بـ subdomain + email + password.
3. `POST /api/customers/`, `POST /api/products/` — إنشاء عميل ومنتجين.
4. `POST /api/invoices/` — فاتورة ببندين: 3× (150.00, ضريبة 14%) +
   2× (40.50, ضريبة 14%) → subtotal=531.00, tax_total=74.34,
   total=605.34 — **محسوبة بالكامل من الخادم**.
5. `POST /api/invoices/{id}/issue/` — اعتماد الفاتورة → قيد يومية تلقائي
   متوازن: مدين Accounts Receivable 605.34 = دائن Sales Revenue 531.00 +
   دائن Tax Payable 74.34.
6. اختبار عزل المستأجر: تسجيل مستأجر ثانٍ، والتأكد أنه (أ) لا يرى عملاء
   المستأجر الأول في القائمة، (ب) يحصل على 404 عند طلب customer id
   principal بشكل مباشر، (ج) لا يمكنه تسجيل الدخول بـ subdomain المستأجر
   الأول حتى ببيانات اعتماد صحيحة لحسابه هو في مستأجر آخر (هذا الاختبار
   بالذات كشف ثغرة ModelBackend المذكورة أعلاه).

## GitHub / CI

- الكود جاهز للنقل عبر GitHub: لا أسرار مكتوبة في الكود (كل شيء عبر متغيرات
  بيئة)، و`.gitignore` يستثني `.env`, `node_modules/`, `__pycache__/`,
  `backend/staticfiles/`, أدلة كاش pytest/ruff. **لم يُنفَّذ `git push`
  بعد** — بانتظار رابط الـ repository.
- `.github/workflows/ci.yml` يعمل على كل push:
  - **backend**: `ruff check` + `pytest` (يشغّل Postgres service container
    في الـ CI نفسه). يحتوي حاليًا 5 اختبارات: health check، تأكيد أن
    migrations تُطبَّق بدون أخطاء، واختبارا regression صريحان لثغرة
    ModelBackend المذكورة أعلاه (تأكيد أن `AUTHENTICATION_BACKENDS` لا
    يحتوي عليها أبدًا + أن تسجيل الدخول بـ subdomain خاطئ يُرفض حتى ببيانات
    صحيحة لمستأجر آخر).
  - **frontend**: `npm install` + `npm run build` فقط (بدون lint/tests
    بعد).
  - اختبارات أوسع (عملاء/منتجات/فواتير/حساب الضريبة) "خطوة جاية" كما
    اتفقنا — البنية التحتية (pytest + pytest-django + fixtures) جاهزة
    الآن في `backend/tests/` و`backend/pyproject.toml`.

## ديون تقنية يجب معالجتها قبل الإنتاج

- **ترقيم الفواتير** (`apps/sales/services.py: generate_invoice_number`)
  يعتمد على `count() + 1` وهو غير آمن تحت الكتابة المتزامنة لنفس
  المستأجر. يحتاج DB sequence أو `select_for_update` قبل الإنتاج.
- **صورة Docker الخلفية تعمل كـ root** (`backend/Dockerfile`) — تم التراجع
  عن مستخدم غير مميز (`appuser`) لأن الـ named volume `static_data` كان
  يُنشأ مملوكًا لـ root ولا يمكن لـ appuser الكتابة فيه أثناء
  `collectstatic`. يحتاج إضافة أداة إسقاط صلاحيات (gosu/tini) تعمل
  كـ entrypoint root ثم تُسلّم التنفيذ لمستخدم غير مميز.
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

## الخطوات التالية المقترحة

1. استكمال المرحلة 1: تعديل/حذف الفواتير (مع قيود عكسية إن كانت معتمدة)،
   تقارير محاسبية (ميزان مراجعة، قائمة دخل مبسطة).
2. توليد فاتورة PDF عبر Celery task.
3. المرحلة 2: نقاط بيع (POS) Offline-first، إدارة الفروع.
