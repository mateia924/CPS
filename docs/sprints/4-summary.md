# سبرنت 4 — ملخص التنفيذ (تدريجي، يُحدَّث بعد كل كتلة)

**بدأ:** 2026-09-22. أول سبرنت يُنشئ ملفًا مستقلًا من هذا النوع (4.0 بند 6) — يُتَّبع نفس النمط لكل سبرنت قادم.

---

## الكتلة 4.0 — أمان وجودة سريعة ✅

**Commit:** `Sprint 4.0: rate limiting, auth backend tests, platform N+1 fix`

- **Rate limiting** طبقتان: nginx `limit_req` (10r/m, burst 5, بالـ IP) على `/api/auth/login/`، `/api/auth/register/`، `/api/platform/auth/login/` + `django-ratelimit` (5/دقيقة لكل IP+email) داخل الـ views، رد 429 برسالة عربية. الطبقة الثانية تحتاج cache مشترك بين عمليات gunicorn — أُضيف `CACHES` (Redis) لأول مرة في المشروع.
- اختبارات `apps/accounts/backends.py`: مسار الدخول بلا subdomain مقصور فعليًا على `is_superuser=True` نشط، برقم تعريف بريد واحد فقط (6 اختبارات جديدة).
- اختبارات `check_branch_limit`/`check_invoice_limit` (كانا بلا تغطية إطلاقًا) — 5 اختبارات جديدة في `test_platform_admin.py`.
- `TenantAdminSerializer`: استبدال 3 `SerializerMethodField` بـ `annotate(Count/Max)` — اختبار `django_assert_max_num_queries` يثبت ≤ 6 استعلامات لصفحة 25 مستأجرًا (كانت حتى 75).
- `ruff` أصبح مثبَّتًا في مرحلة `dev` من صورة الـ backend (Dockerfile مقسوم إلى `dev`/`prod` stages؛ `docker-compose.dev.yml` يبني بـ `target: dev`) — يعمل الآن داخل الحاوية الدائمة مباشرة، لا فقط عبر `make lint`.

**الاختبارات:** 149/149 (133 سابقة + 16 جديدة). `ruff check .` نظيف. `manage.py check` و`makemigrations --check` نظيفان.

**لم يكتمل:** لا شيء متبقٍ من نطاق 4.0.

---

---

## الكتلة 4.1 — الترقيم الذري ✅

**Commit:** `Sprint 4.1: atomic document numbering`

- تطبيق `apps.numbering` جديد: `DocumentSequence` (`select_for_update` داخل `transaction.atomic`، نطاق `(tenant, doc_type, legal_entity, year)`) + `DocumentNumberingSetting` (بادئة قابلة للتعديل، `reset_yearly`). الصيغة `{prefix}-{year}-{seq:05d}`.
- **قرار تفصيلي (يُوثَّق في 4.7):** `legal_entity` صار nullable على `DocumentSequence` — تصميم ARCH_REVIEW_1 الأصلي افترض أن كل مستند مرتبط بكيان قانوني، لكن أكواد الأطراف ليست كذلك؛ استُخدم `nulls_distinct=False` (Postgres 15+/Django 5+، كلاهما متوفر) لمنع تعدد الصفوف حين `legal_entity=None`.
- طُبِّق على: `generate_invoice_number` (كان COUNT-based)، `generate_party_code` (بادئة CUS/SUP/EMP/AFF حسب الدور، كان COUNT-based أيضًا).
- **ثغرة اكتُشفت وأُصلحت أثناء التنفيذ:** الترقيم الجديد لكل فاتورة أصبح بنطاق كيان قانوني، فصار من الممكن أن يتطابق رقمان لفرعين مختلفين لنفس المستأجر — بينما قيد `unique_invoice_number_per_tenant` القديم كان على (tenant, number) فقط. أُصلح بتغيير القيد إلى `(tenant, legal_entity, number)` (migration `sales/0010`) — اكتُشف عبر فشل حقيقي في اختبار RBAC موجود مسبقًا (`test_owner_bypasses_entity_access_and_sees_both_branches`)، لا عبر مراجعة يدوية.
- Migration بيانات (`numbering/0002`) تضبط `last_number` لكل نطاق موجود من العدّ الفعلي (الأرقام القديمة نفسها لا تتغيّر؛ الصيغة الجديدة لا يمكن أن تتصادم نصيًا مع القديمة أصلًا).
- شاشة إعدادات API (`/api/document-numbering-settings/`، صلاحيتا `numbering.view`/`numbering.manage`) — الواجهة الفعلية مؤجّلة لكتلة 4.7 (قائمة "الإعدادات" فيها).
- **اختبار تزامن حقيقي:** 50 thread تنشئ فواتير بنفس اللحظة (`pytest.mark.django_db(transaction=True)`) → 50 رقمًا فريدًا متتاليًا بلا فجوة، فعليًا لا محاكاة.

**الاختبارات:** 161/161 (149 + 12 جديدة). `ruff`/`manage.py check`/`makemigrations --check` نظيفة.

**لم يكتمل:** ربط JV (القيود اليدوية) بالترقيم الذري — يحدث في كتلة 4.4 حين تُبنى الشاشة نفسها؛ شاشة "ترقيم المستندات" في الفرونت — كتلة 4.7.

---

*(تُضاف الكتل التالية هنا بعد إغلاق كل واحدة.)*
