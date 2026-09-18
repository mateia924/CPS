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
frontend/   Next.js 16 + TypeScript (App Router) — عربي/RTL افتراضيًا
infra/      docker-compose.yml + nginx (reverse proxy)
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

## التشغيل محليًا

```bash
cd /opt/cps
cp .env.example .env        # ثم عدّل القيم، خصوصًا DJANGO_SECRET_KEY وكلمات المرور
docker compose -f infra/docker-compose.yml --env-file .env up -d --build
```

**ملاحظة عن المنفذ:** الإعداد الافتراضي يعرض الخدمة على **8080** لا 80،
لأن هذا السيرفر لديه بالفعل nginx نظامي شغّال على 80/443 لخدمات أخرى. غيّر
`HTTP_PORT` في `.env` فقط لو كنت متأكدًا أن المنفذ البديل متاح.

بعد التشغيل:
- الواجهة: http://localhost:8080/
- الـ API: http://localhost:8080/api/
- لوحة إدارة Django: http://localhost:8080/admin/

الـ backend container يشغّل `migrate` و `collectstatic` تلقائيًا عند كل
إقلاع (`backend/entrypoint.sh`).

### إنشاء مستخدم مشرف (superuser) لدخول /admin

```bash
docker compose -f infra/docker-compose.yml --env-file .env exec backend \
  python manage.py createsuperuser
```
(سيطلب منك اختيار Tenant موجود مسبقًا — أنشئ مستأجرًا أولًا عبر
`/api/auth/register/` أو عبر الـ admin نفسه بعد أول دخول.)

## اختبار end-to-end (تم تنفيذه فعليًا أثناء البناء)

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

## الخطوات التالية المقترحة

1. استكمال المرحلة 1: تعديل/حذف الفواتير (مع قيود عكسية إن كانت معتمدة)،
   تقارير محاسبية (ميزان مراجعة، قائمة دخل مبسطة).
2. توليد فاتورة PDF عبر Celery task.
3. المرحلة 2: نقاط بيع (POS) Offline-first، إدارة الفروع.
