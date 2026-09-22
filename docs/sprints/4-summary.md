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

*(تُضاف الكتل التالية هنا بعد إغلاق كل واحدة.)*
