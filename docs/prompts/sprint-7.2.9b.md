# 7.2.9-b — تأكيد استرجاع كلمة السر يفشل تحت RLS (A-7 على staging، 10 أكتوبر 2026)

**الحالة (11 أكتوبر ظهرًا):** السبب محدَّد بالأدلة. الباتش على القرص في `backend/apps/accounts/serializers.py` (الـ16 اختبارًا الحالية خضراء عليه)، والاختبار الجديد في `backend/tests/test_rls.py`. إثبات قاعدة 11 وcommit وstaging: في تقرير التنفيذ أسفل هذا الملف. staging في حالة نظيفة: لم تتغير أي كلمة سر، التوكنات انتهت دون استخدام.

## 1. الملاحظة

A-7 (التحقق النهائي من 7.2.9 على staging عبر nginx → gunicorn):
`POST /api/auth/password-reset/confirm/` يعيد دائمًا
`{"token":["This reset link is invalid or has expired."]}` — حتى لتوكن عمره 3 ثوانٍ، التُقط من لوج `cps-staging-celery_worker-1` وأُرسل خلال نفس البلوك.

النتائج المصاحبة كلها متسقة مع "لم يتغير شيء": `login_old_again=200`، `login_new=400`، `old_access=200`، `old_refresh=200`.

## 2. الأدلة بترتيب جمعها (كلها قراءة فقط، لا أسرار طُبعت)

| # | الفحص | النتيجة |
|---|---|---|
| 1 | بصمة الـ hash المحسوبة من التوكن (`hash_token`) مقابل `left(token_hash,8)` في القاعدة | **متطابقة** (`3d59f9a1`) |
| 2 | الصف في `accounts_passwordresettoken` (superuser) | موجود، `used_at` فارغ، `expires_at` بعد 30 دقيقة من الإنشاء — طازج |
| 3 | نفس الاستعلام من `manage.py shell` داخل حاوية backend | `orm_finds_token True` |
| 4 | نفس الطلب عبر `django.test.Client` داخل الحاوية (مع rollback) | **التوكن مقبول** — الخطأ الوحيد كان قوة كلمة السر الجديدة |
| 5 | الحاويتان backend / celery_worker: الصورة، كل ملفات `apps/accounts`، `SECRET_KEY` الفعلي، القاعدة | متطابقة بالكامل |
| 6 | `pg_stat_activity` أثناء 240 طلب `me` متوازٍ | اتصالات gunicorn باسم **`cps_staging_app`** |
| 7 | `\du` | `cps_staging` = Superuser + Bypass RLS (المالك) · `cps_staging_app` = بلا صلاحيات |
| 8 | بدور `cps_staging_app`: `count(*)` من الجدول | **0** بلا سياق · **1** بعد `SET cps.tenant_id` |
| 9 | `pg_class`: `relrowsecurity`/`relforcerowsecurity` | 49 جدولًا RLS مفعّل، `force_rls = f` على كلها (المالك يتخطاها بالتصميم) |

## 3. السبب الجذري

`PasswordResetConfirmSerializer.validate()` كان يبحث عن التوكن بالـ hash **أولًا** ثم يقارن `subdomain` **بعدها**. طلب التأكيد غير مصادَق (لا JWT) وعلى staging بلا نطاق في الـ Host، فلا يوجد ما يضبط `RLSTenantMiddleware` منه `cps.tenant_id`. تحت الدور المقيَّد، سياسة `tenant_isolation` (`tenant_id = NULLIF(current_setting('cps.tenant_id', true), '')::uuid`) تعيد صفر صفوف لأي توكن، صحيحًا كان أو لا. الخطأ fail-closed: لا تسريب، الميزة فقط غير قابلة للاستخدام.

**نفس فئة العيب حُلّت من قبل** في 6.6.3 (البند 1) لتسجيل الدخول — تعليق `TenantLoginSerializer` يقول حرفيًا "found live, the hard way". النمط هناك: `Tenant.objects.filter(subdomain=…)` → `set_local_tenant_id(cursor, tenant.id)` → ثم الاستعلام. (الاستخدام الثالث لنفس الأداة في نفس الملف بعد التسجيل والدخول.)

**الآلية:** `settings.py` §180: compose الخاص بـlive وstaging يستبدل `DATABASE_URL` لعملية gunicorn بـ`APP_DATABASE_URL` (الدور المقيَّد)، بينما بيئة الحاوية نفسها (`docker exec`) تحمل دور المالك. **dev على :3002 لا يستبدله** — فكل تحقق يدوي على dev يعمل بدور المالك ولا يمرّ على RLS.

**لماذا لم تكتشفه الاختبارات (758 خضراء):** اختبارات 7.2.9 الستة عشر تعمل على اتصال pytest الافتراضي (دور المالك، يتخطى RLS)، وفحوص الوكيل اليدوية كانت على dev (دور المالك أيضًا). النمط الصحيح كان موجودًا منذ 6.6.3 في `tests/test_rls.py` — التسجيل والدخول تحت الدور المقيَّد `cps_app_test` — لكنه لم يُطبَّق على الـendpoint الجديد. `manage.py shell` ≠ مسار الطلب.

## 4. الإصلاح المطبَّق (10 أكتوبر 22:32)

في `validate()` قبل البحث:
```
subdomain = attrs["subdomain"].strip().lower()
tenant = Tenant.objects.filter(subdomain=subdomain).first()
if tenant is None: raise ValidationError(generic_error)
with connection.cursor() as cursor: set_local_tenant_id(cursor, tenant.id)
record = PasswordResetToken.objects.select_related("user","tenant").filter(tenant=tenant, token_hash=token_hash).first()
```
- حُذفت المقارنة اللاحقة `record.tenant.subdomain != …` لأنها أصبحت زائدة: `subdomain` مفتاح بحث الآن.
- الحارس الأقوى: توكن مستأجر A غير موجود أصلًا داخل سياق مستأجر B.
- لا imports جديدة (`Tenant`، `connection`، `set_local_tenant_id` مستخدمة في نفس الملف).
- `SET LOCAL` يمتد لنهاية معاملة الطلب، فـ`set_password`/`invalidate_all_sessions`/`log_action` في الـ view تعمل داخل نفس السياق — نفس ما يحدث في login.
- لم يُمس: مسار `/request/` وعقد استعلاماته الثلاثة، البريد، شكل التوكن، TTL، الـ hashing، الـ rate-limit.

## 5. الاختبار (11 أكتوبر)

`tests/test_rls.py::test_password_reset_confirm_under_the_restricted_role` — بنفس شكل `test_login_under_the_restricted_role_for_a_pre_existing_user`: إصدار التوكن بالـtask الحقيقية وقراءته من صندوق البريد (نفس اتفاق `test_password_reset.py`) → تبديل الاتصال إلى `cps_app_test` → `POST confirm` → `204` → دخول بالجديدة → `200`.

**إثبات قاعدة 11 بالبناء:** على الكود قبل الباتش (`git stash push -- apps/accounts/serializers.py`) يجب أن يفشل بالرسالة نفسها `This reset link is invalid or has expired.`؛ على الباتش يمرّ. النتيجة الحرفية في تقرير التنفيذ.

## 6. الخطوات المتبقية بالترتيب

1. إثبات قاعدة 11 (أعلاه) ثم الـsuite كاملة — 759 متوقَّعة. pytest واحد في كل مرة (`docker top`).
2. commit للملفات الثلاثة (serializer، test_rls، هذا الملف) + `git push origin main`.
3. staging `--code-only`، ثم A-7 كاملة بـcurl عبر nginx: `confirm=204 · login_new=200 · login_old_again=400 · old_access=401 · old_refresh=401`. كلمة السر الجديدة ≥12 حرفًا وغير مشابهة للاسم (سياسة القوة — تعمل كما صُمِّمت).
4. بعد التحقق، إعادة كلمة سر مستخدم staging إلى `STAGING_UAT_PASSWORD` بنفس المسار، حتى يبقى UAT قابلًا للاستخدام دون انتظار refresh كامل.

## 7. بنود مفتوحة

- بأي دور يتصل Celery worker؟ يُثبَت بـ`pg_stat_activity` أثناء task فعلي. إن كان المالك، فكل task خارج عزل المستأجرين.
- هل الـ SHA المنشور على live يحتوي 7.2.9؟ (`docs/ops/deploys.log`). لا نشر على live قبل اكتمال §6.
- dev على :3002 لا يمرّ على RLS: أي تحقق يدوي لكتل auth/RLS يكون على staging، أو يُجعل dev يستخدم `APP_DATABASE_URL` مثل staging — قرار منفصل.

## 8. القواعد

- **قاعدة 34 (جديدة):** أي endpoint يعمل بلا مصادقة ويلمس جدولًا عليه RLS يحصل على اختبار في `tests/test_rls.py` بالدور المقيَّد قبل اعتباره مكتملًا. النمط موجود (التسجيل، الدخول، والآن التأكيد). الاختبار الذي يسلك مسارًا مختلفًا عن الإنتاج ليس اختبارًا للإنتاج.
- ملاحظة تشغيل: `docker exec … manage.py shell` يتصل بدور المالك — لا يُستدَل به على سلوك الطلبات.

## 9. أخطاء المالك المسجَّلة

- **#11 (جوهري):** تعليق "2026-10-10 (owner review)" في الكود — توجيهي بأن يكون التوكن مفتاح البحث الوحيد والنطاق يُقارَن بعدها ("قيمة من المستخدم لا تختار الصف"). الحجة صحيحة لمفتاح الـ rate-limit، خاطئة هنا: النطاق هو السياق الذي بدونه لا صف مرئيًا أصلًا. نفس الدرس المسجَّل في 6.6.3 كان موجودًا في نفس الملف ولم أقرأه قبل التوجيه.
- **#12:** ادّعاء "الـ suite لا تمر على RLS إطلاقًا" (10 أكتوبر مساءً) — أوسع من الدليل. `tests/test_rls.py` كان موجودًا، وdocstring `apps/common/rls.py` كان يشير إليه. الصحيح: النمط موجود ولم يُطبَّق على الـendpoint الجديد.
- إجرائي: `read -s` داخل بلوك لصق متعدد الأسطر يلتهم السطر التالي ككلمة سر — السطر الذي فيه `read` يُلصق وحده دائمًا.

## 10. حادثة الوكيل

خمس جلسات Claude Code متتالية أُنهيت بـsafeguard `[bio]` على هذه المهمة (عربي/إنجليزي، مع/بدون قراءة ملفات، Sonnet/Opus) — قبل أي تغيير في الريبو كل مرة. Request IDs: `req_011CfthwVidQZMyyvBE4ZHKq`، `req_011CftmpL2VjGiNWfih5gAXp`، `req_011CftxujmAHHeiKRUHQ3nhn`، `req_011CftyfgMkutqppVFKhGqju` (+ خامسة لم يُلتقط رقمها). التشخيص والباتش والاختبار نُفِّذت يدويًا من Xshell أمرًا بأمر. يُبلَّغ عبر `/feedback`.

## 11. تقرير التنفيذ

(يُلحق هنا: ناتج إثبات قاعدة 11، سطر ملخص الـsuite، SHA الـcommit، ناتج staging refresh، أكواد HTTP الخمسة للـA-7.)

### 11.1 إثبات قاعدة 11 (dev، 11 أكتوبر 16:11)
- على الكود قبل الباتش (`git stash push -- apps/accounts/serializers.py`):
  `FAILED tests/test_rls.py::test_password_reset_confirm_under_the_restricted_role` —
  `AssertionError: b'{"token":["This reset link is invalid or has expired."]}'` / `assert 400 == 204` — `1 failed, 6 passed`.
- على الباتش: `7 passed`.

### 11.2 الـsuite كاملة (dev)
`759 passed, 2 deselected, 2 errors in 776.65s`. الخطآن: `tests/test_deploy_sh_guards.py` × 2 —
`FileNotFoundError: No such file or directory: 'git'` — حاوية dev بلا git؛ بيئي، يتكرر بصفر تغييرات، مكانه الـhost (`ci_local.sh`).

### 11.3 commit
`feed71c` → `origin/main` (`d1187ca..feed71c`): serializer، test_rls، هذا الملف، سطر الربط في sprint-7.md.

### 11.4 staging `--code-only` (18:50–18:51)
RLS 49/49 · smoke: login/me/invoices/trial balance `105250.59` — ALL CHECKS PASSED.

### 11.5 A-7 عبر nginx بـcurl (20:45)
`login_old=200` · `reset_request=200` · `token_len=43` · **`confirm=204`** · `login_new=200` · `login_old_again=400` · `old_access=200` · `old_refresh=401`.

### 11.6 إعادة كلمة UAT بنفس المسار (21:09)
`restore_request=200` · `token_len=43` · `restore_confirm=204` · `login_uat=200`. المسار نُفِّذ مرتين كاملتين؛ staging في حالته الأصلية.

### 11.7 ملاحظة مفتوحة جديدة — access token بعد الاسترجاع
`old_access=200`: `invalidate_all_sessions` تُبطل الـrefresh tokens فقط؛ الـaccess token بلا حالة ويبقى صالحًا حتى انتهائه — `ACCESS_TOKEN_LIFETIME` = 30 دقيقة (`JWT_ACCESS_MINUTES`). نفس سلوك تغيير كلمة السر الحالي. التوصية: claim لنسخة كلمة السر يُفحص في `TenantAwareJWTAuthentication`، واختباره في `test_rls.py` بالدور المقيَّد (قاعدة 34). قرار مستقل عن 7.2.9-b.

### 11.8 الوكيل
جلسة سادسة أُنهيت بنفس الـsafeguard على برمنت التنفيذ (`req_011CfvUZCdbd2kQ3bBaHRLpk`) قبل أي أمر. كل ما سبق نُفِّذ يدويًا من Xshell.
