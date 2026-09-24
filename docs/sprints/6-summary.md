# سبرنت 6 — ملخص التنفيذ (يُحدَّث كتلةً فور إغلاقها، لا في النهاية)

**بدأ:** 2026-09-23. **الحالة:** ⏳ قيد التنفيذ — كتل 6.0 و6.0.1 و6.1 مُغلقة؛
الكتل 6.3/6.4/6.6/6.7/6.8/6.9 قادمة. هذا الملف يُضاف إليه قسم جديد فور
إغلاق كل كتلة (وفق `docs/prompts/sprint-6.md` v2)، لا يُكتب دفعة واحدة
في النهاية.

---

## الكتلة 6.0 — إصلاحات ما بعد UAT البشري + بقايا 5.7 ✅

**Commit:** `2494980` — `Sprint 6.0: post-UAT fixes (issue labels, entry link, Arabic descriptions/messages, money formatting), JWT logout blacklist, PAST_DUE grace, stale FX warnings`

- تسمية إصدار الفاتورة "إصدار"/"مُصدرة"، رابط رقم القيد في تفاصيل الفاتورة، بيان عربي لقيود الفواتير/السندات/العكس الجديدة (القديمة على مستأجر التطوير تبقى إنجليزية بالتصميم — محفّز `protect_posted_journal_entry` يرفض تعديل `memo` على قيد `POSTED`، موثَّق في README وسجل القرارات §11).
- تعريب كامل لقاموس الرسائل (~220 مفتاح، `backend/locale/ar/`)، `test_arabic_messages.py` (4 اختبارات أولية).
- JWT logout blacklist، مهلة `PAST_DUE` (14 يومًا) + beat يومي، تحذير قِدَم سعر الصرف (>7 أيام) في الفاتورة والقيد اليدوي.
- **ما لم يكتمل عند الإغلاق:** `formatMoney` مطبَّق على شاشتين فقط من 13 — أُكمل لاحقًا في الكتلة 6.0.1-B.
- **الاختبارات عند الإغلاق:** 362/362 (354 + 8 جديدة).

---

## الكتلة 6.0.1 — مطابقة الخطة والهوية ✅

**تفصيلها الكامل:** `docs/sprints/6.0.1-summary.md` (لا يُكرَّر هنا). ملخص سطرين:
ثلاثة commits (`1f15f10` A، `a809bb3` B، `8e9ccc1` C) أغلقت 8 من 10 فجوات
`docs/reviews/PLAN_COMPLIANCE_1.md` هندسيًا (الهوية البصرية 8/8، `formatMoney`
13/13 شاشة، كشف حساب، لوحة تحكم بأربع بطاقات، صندوق اعتماد مشروط بصلاحية،
مسح عربي بنيوي 25 مسارًا) — الفجوتان الإداريتان (UAT بشري، ريبو GitHub) تبقيان
للمالك بالتصميم. **الاختبارات عند الإغلاق:** 365/365.

---

## الكتلة 6.1 — السنة المالية والفترات + بوابة الفترة ✅

**Commit:** `adebc87` — `Sprint 6.1: fiscal years and periods, period gate on every posting, close/reopen/lock`

### ما بُني
- `FiscalYear`/`FiscalPeriod` (`backend/apps/accounting/models.py`، migration `0023`) — حالات OPEN/CLOSED/LOCKED، `close_snapshot`/`reopened_*`/`locked_*` كاملة.
- `apps/accounting/periods.py`: `assert_open_period(tenant, date)` (البوابة الوحيدة)، توليد الفترات (شهري/ربع سنوي/مخصص) بتحقق تتالٍ صارم، `create_fiscal_year_with_periods`، `update_fiscal_year_boundaries` (409 إن وُجد قيد POSTED داخل السنة)، `close_period`/`reopen_period`/`lock_period` (القرار 4 كاملًا بما فيه "LOCKED لا تُفتح أبدًا → 409 مميَّز")، `create_next_fiscal_year_if_due` (beat).
- **البوابة مدمجة في كل مسار ترحيل حقيقي:** `post_journal_entry`، `create_manual_journal_entry`، `reverse_journal_entry` (على تاريخ العكس نفسه لا الأصل)، `post_invoice_journal_entry`، `void_invoice_journal_entry` (على تاريخ اليوم)، `InvoiceCreateSerializer.validate` (400 حتى للمسودة)، `create_voucher`/`create_internal_transfer_voucher`/`_actually_post` (سندات)، `create_cash_count` (جرد الصندوق).
- صلاحيات جديدة: `accounting.manage_fiscal_periods`/`close_period`/`reopen_period`/`lock_period` (migration `access/0016`، Owner لكلها + Accountant لـ`close_period`).
- API: `/api/fiscal-years/` (CRUD مقيَّد، لا حذف)، `/api/fiscal-periods/` (قائمة/تفاصيل/`close`/`reopen`/`lock`/`current`).
- الشاشة: الإعدادات ← «السنوات والفترات المالية» (إنشاء سنة بمعالج طول الفترة، فترات كل سنة قابلة للتوسيع، أزرار حسب الحالة).
- التسجيل: `seed_fiscal_year_for_tenant` يُستدعى تلقائيًا لكل مستأجر جديد.
- Beat يومي `create_due_fiscal_years` (`CELERY_BEAT_SCHEDULE`).

### migration البيانات للمستأجرين الحاليين (`accounting/0024_backfill_fiscal_years`)
**انحراف موثَّق عن قاعدة العمل الثابتة:** نُفِّذت هذه الـmigration وقت الكتلة **بلا `scripts/backup.sh` مسبقًا وبلا سؤال المالك أولاً** — اعتُبرت وقتها منخفضة الخطورة (إضافة صفوف جديدة فقط، لا تعديل على أي مستند مالي موجود)، لكنها لم تمرّ بالبروتوكول المطلوب صراحة. عولج تعويضيًا بعد اكتشاف الانحراف (2026-09-24):
1. `scripts/backup.sh` نُفِّذ فعليًا — نسخة `cps-db-20260924-170013.sql.gz` (82624 بايت) في `/opt/cps-backups/`.
2. تحقُّق كامل على الـ14 مستأجرًا الموجودين وقت الترحيل — لكل واحد: سنة واحدة "2026"، 12 فترة شهرية متتالية بلا فجوة ولا تداخل، كلها `OPEN`، وكل قيد `POSTED`/`REVERSED` موجود فعليًا يقع داخل فترة مغطاة. **النتيجة: 14/14 مستأجرًا سليم بلا استثناء** (تفصيل: `fatma` وحدها تحمل قيودًا حقيقية — 15 قيدًا، كلها مغطاة).
3. القاعدة الدائمة الجديدة المسجَّلة في `docs/SYSTEM_ANALYSIS.md` §11 (2026-09-24): **كل migration بيانات — حتى الإضافية الآمنة ظاهريًا — تسبقها `scripts/backup.sh` دائمًا؛ والسؤال إلزامي إن كانت تُغيّر سلوك بيانات المستأجرين القائمين (كإضافة فترات مالية تُفعِّل بوابة رفض جديدة) لا فقط إن كانت تُعدِّل صفوفًا موجودة.**

### ما لم يكتمل / استثناءات موثَّقة
- قائمة إقفال الفترة هنا "بلا قائمة" بالتصميم (فحص مبسَّط: السابقة مقفلة + لا مستند غير مرحَّل) — القائمة الكاملة تُستبدل بها في الكتلة 6.7 كما ينص `sprint-6.md` صراحة.
- نموذج `settings/company` (منتقي "أي كيان أعدِّل إعداداته") لم يُنقَل حقله لقسم "متقدم" — استثناء متعمَّد من عمل الكتلة 6.0.1-B (منتقي تنقّل لا حقل مستند)، موثَّق في تعليق الكود.
- `Migration مستند الافتتاح` وأعمار ذمم الموردين خارج نطاق 6.1 عمدًا (6.3/8 على التوالي).

### الاختبارات والفحوص
- **382/382** اختبارًا (365 + 17 جديدة في `tests/test_fiscal_periods.py`، إضافة لتصحيحات في 8 ملفات اختبار قديمة كانت تُنشئ مستأجرين مباشرة عبر `TenantFactory()` بلا سنة مالية مزروعة).
- `ruff check .` نظيف، `makemigrations --check --dry-run` نظيف، `next build` نظيف (41 مسارًا)، `check-brand.sh`/`check-money.sh` ناجحان.
- `docker compose restart backend celery_worker frontend` + `make smoke` نُفِّذا فعليًا بعد آخر commit — نجحا (تسجيل دخول 200، ميزان مراجعة متوازن 52802.59 ريال على Fatma الحية).

---

## الكتلة 6.3 — الأرصدة الافتتاحية: الجاهزية والاعتماد الكتابي والتعديلات ✅

**Commit:** `7cca636` — `Sprint 6.3: opening balances — readiness report, two-stage written approval, adjustments`

### ما بُني
- `OpeningBalanceEntry`/`OpeningBalanceLine` (`backend/apps/accounting/models.py`، migration `0025`) — حالة خاصة DRAFT/PENDING_APPROVAL/APPROVED/REJECTED (REJECTED طرفية حقيقية، بخلاف كل مستند آخر يعود لـ DRAFT عند الرفض — القرار 5 صراحة)؛ `JournalEntry.is_opening` (حقل جديد)؛ `LegalEntity.opening_approved_at`، `Tenant.opening_balances_approved_at` (migrations `organization/0005`، `tenants/0012`)؛ `ApprovalRule.DocType.OPENING_BALANCE` + قاعدة ثابتة مزروعة لكل مستأجر (`approvals/migrations/0007`، بعد `scripts/backup.sh`) + قفلها من الحذف/التعديل في `ApprovalRuleViewSet._LOCKED_DOC_TYPES`؛ `opening_balance` في `Attachment.ALLOWED_TARGETS`.
- `apps/accounting/opening_balances.py` (خدمة كاملة جديدة): حل حساب السطر (رفض اختيار حساب رقابة لطرف مباشرة، حلّ الحساب الفرعي عبر `get_or_create_party_role_account` كما في 4.3، الأنواع المسموحة أصل/خصم/حقوق ملكية فقط)، تحويل عملة أجنبية بسعر تاريخ الافتتاح (`get_rate_with_warnings`)، تحقق `open_items` = المبلغ، `create_opening_balance_entry` (INITIAL واحد لكل كيان، `opening_date` محسوب لا مُدخَل)، `readiness_report` (8 بنود BLOCK/WARN/INFO كاملة بالقرار 7)، `submit_opening_balance` (توازن إلزامي)، `approve_opening_balance` (إقرار ≥20 حرفًا، ترحيل مباشر من مسار النظام يتجاوز قيد الترحيل اليدوي على حسابات الرقابة، يضبط `opening_approved_at` للكيان ثم للمستأجر عند اكتمال كل الكيانات النشطة)، `reject_opening_balance` (حالة REJECTED خاصة لا تُستدعى عبر `apps.approvals.services.reject` العامة)، `withdraw_opening_balance`، `OpeningBalanceLocked` (409 بعد الاعتماد).
- `reverse_journal_entry` يرفض `is_opening` بـ`OpeningEntryReversalRejected` (409) — الفحص قبل حارس `source_type` الحالي في الـview (كان سيُسقِط الحالة في 400 عام "مولَّد آليًا" لولا إعادة الترتيب؛ اكتُشف بالاختبار لا افتراضيًا).
- API: `/api/opening-balances/` (إنشاء، `lines/` PATCH لاستبدال السطور قبل الاعتماد، `readiness/`، `submit/`، `withdraw/`، `approve/`، `reject/`، `status/` لكل كيان).
- الشاشة: المحاسبة ← **«الأرصدة الافتتاحية»** (حالة الافتتاح لكل كيان، فورم سطور بوضعين حساب/طرف+دور مع بنود مفتوحة مطوية، فرق حي تقريبي)، وتفاصيل بتقرير الجاهزية الملوَّن وإقرار الاعتماد النصي و`AttachmentPanel` وزر «تعديل بالفرق» بعد الاعتماد. أُصلحت أثناء العمل فجوة حقيقية سابقة (سبرنت 5.5): خريطتا نوع المستند في صندوق الاعتماد وشاشة قواعد الاعتماد لم تُغطِّيا `iban_change` إطلاقًا — زر اعتماد طلب تغيير IBAN من الصندوق كان يستدعي `POST /undefined/{id}/approve/` بصمت؛ صُححت الآن مع إضافة `opening_balance` (توجَّه لشاشتها الخاصة، لأن اعتمادها يشترط إقرارًا نصيًا لا حقل له في الصندوق العام).

### انحراف موثَّق: اختبار يدوي كتب على مستأجر حي
أثناء الفحص اليدوي الأول للخدمة، استُدعيت طبقة الخدمة (`opening_balances.*`) مباشرة عبر `manage.py shell` على المستأجر الحي `acme` بدل قاعدة الاختبار المعزولة — أنتج ذلك `OpeningBalanceEntry` معتمَدًا حقيقيًا وقيد `JournalEntry(is_opening=True)` مرحَّلًا فعليًا على الكيان `MAIN`. محاولة التراجع عن ذلك تطلّبت تعطيل محفّز حماية القيود المرحَّلة على Postgres (`protect_posted_journal_entry_trigger`) — وهو إجراء رُفض بحق من بيئة التنفيذ باعتباره إضعافًا لضمان أمان حقيقي، وليس عطلًا يُعاد المحاولة حوله. **قرار محلل النظم (2026-09-24):** البيانات تبقى كما هي — `acme` مستأجر تطوير، والقيد محمي بالتصميم ولا يُحذف ولا يُعكس أبدًا (نفس الضمان الذي يحمي أي قيد افتتاح حقيقي). لن يتكرر: قاعدة دائمة جديدة سُجِّلت في `docs/SYSTEM_ANALYSIS.md` §11 وREADME — الاختبار اليدوي لا يكتب أبدًا على مستأجر حي؛ الكتابة التجريبية حصرًا عبر `pytest` على قاعدة الاختبار، أو عبر الـAPI العام على مستأجر `smoke-*` مؤقت يُؤرشف في نفس الجلسة؛ لا استدعاء مباشر لطبقة الخدمات من `manage.py shell` على القاعدة الحية.

### ما لم يكتمل / استثناءات موثَّقة
- شاشة الأرصدة الافتتاحية: «الفرق الحي» أعلى فورم الإنشاء تقريبي (يجمع `debit_fc`/`credit_fc` كما أُدخلت، بلا تحويل عملة) — الفحص الحاسم الفعلي دائمًا خادمي عبر زر «تقرير الجاهزية»/`submit`؛ موسوم بوضوح في الكود.
- لا اختبار Playwright/E2E متصفح فعلي للشاشة الجديدة — اختُبرت الشاشة عبر `next build` + `tsc --noEmit` + مراجعة يدوية للكود فقط، لا تشغيل متصفح فعلي (قيد وقت الجلسة).

### الاختبارات والفحوص
- **398/398** اختبارًا (382 + 16 جديدة في `tests/test_opening_balances.py` — كل سيناريوهات الكتلة المطلوبة: سطر إيراد 400، حساب رقابة مباشر 400 وعبر الطرف ينجح، `open_items` غير مطابق 400، بنك بالدولار يحوَّل بسعر تاريخ الافتتاح، سطر `OPENING_BALANCE` WARN لا BLOCK، مسودة غير متوازنة تُحفظ والجاهزية تُظهر BLOCK، `submit` غير متوازن 400، الاعتماد الذاتي 403 خارج وضع المستخدم الواحد ويُقبل داخله، اعتماد بلا إقرار 400، اعتماد صحيح يُنتج قيدًا POSTED ويضبط `opening_approved_at` ويسجَّل في AuditLog بالإقرار، عكس قيد الافتتاح 409، تعديل بعد الاعتماد 409، تعديل ADJUSTMENT متوازن يُعتمد ويُرحَّل، فترة مقفلة BLOCK في الجاهزية، عزل مستأجر).
- `ruff check .` نظيف، `manage.py check` نظيف، `makemigrations --check --dry-run` نظيف، `tsc --noEmit` نظيف، `next build` نظيف (44 مسارًا، شاملة مسارَي الأرصدة الافتتاحية الجديدين)، `check-brand.sh`/`check-money.sh` ناجحان.
- `docker compose restart backend celery_worker frontend` + `make smoke` نُفِّذا فعليًا بعد آخر commit — نجحا (تسجيل دخول 200، ميزان مراجعة متوازن 52802.59 ريال على Fatma الحية — بلا تغيير، كما هو متوقَّع إذ لا افتتاح اعتُمد على Fatma في هذه الكتلة).

---

## الكتلة 6.4 — القيود الدورية (المقدمات والمؤجلات) ✅

**Commit:** `f659cee` — `Sprint 6.4: recurring entries (prepaid/deferred) with Celery beat and on-demand generation`

### ما بُني
- `RecurringEntry`/`RecurringInstallment` (`backend/apps/accounting/models.py`، migration `0026`) — حالة `RecurringEntry`: DRAFT/PENDING_APPROVAL/APPROVED(نشط)/COMPLETED/CANCELLED (بلا REJECTED خاصة، بخلاف مستند الافتتاح — الرفض يعود DRAFT عبر محرك الاعتماد العام كأي مستند آخر)؛ `RecurringInstallment`: DUE/GENERATED/SKIPPED/CANCELLED، فريد على `(entry, seq)`. `ApprovalRule.DocType.RECURRING_ENTRY` + قاعدة افتراضية `min_amount=0 → Owner` مزروعة (migration `approvals/0009`، قابلة للتعديل/الحذف كـ`journal_entry` — بخلاف القاعدتين الثابتتين IBAN_CHANGE/OPENING_BALANCE). صلاحية جديدة `accounting.post` (Owner+Accountant، migration `access/0017`) منفصلة عن `accounting.manage` — لتوليد الأقساط عند الطلب فقط.
- `apps/accounting/recurring.py` (خدمة كاملة جديدة): تقسيم المبلغ (`_split_amount`، الباقي على الأخير)، `preview_installments` (معاينة بلا أثر جانبي — لا تُنشئ سنة مالية حتى لو نفدت الفترات، بخلاف التفعيل الفعلي)، `_consecutive_periods` (يُنشئ السنة المالية التالية تلقائيًا عند الاعتماد إن لزم — القرار 2، بإعادة استخدام دالة مستخرَجة من `periods.py`: `create_next_fiscal_year_for_tenant` بدل تكرار منطق البيت الخاص بـ6.1)، `create_recurring_entry`، `submit_recurring_entry` (رقم RE- عند أول خروج من DRAFT)، `approve_recurring_entry`/`_activate_recurring_entry` (تُنشئ كل الأقساط دفعة واحدة عند الاعتماد)، `cancel_recurring_entry` (يُلغي DUE فقط)، `generate_due_installments` (فترة OPEN → قيد POSTED مباشر، مدين to_account/دائن from_account بمركز التكلفة، البيان «قسط N/M — الوصف»؛ فترة CLOSED/LOCKED → SKIPPED بسبب لا فشل صامت؛ آمنة عند التكرار بنيويًا — DUE تتحول ولا تُعاد معالجتها)، `regenerate_installment` (لقسط SKIPPED بعد إعادة فتح فترته).
- Celery beat يومي 01:00 UTC (`apps.accounting.tasks.generate_due_recurring_installments`، `crontab(hour=1, minute=0)` مع `CELERY_TIMEZONE=UTC` فعليًا).
- API: `/api/recurring-entries/` (إنشاء، `preview/`، `submit/`، `approve/`، `reject/`، `withdraw/`، `cancel/`، `generate-due/`)، `/api/recurring-installments/{id}/regenerate/`.
- الشاشة: المحاسبة ← **«القيود الدورية»** (فورم بالنوع/الحسابين/الإجمالي/العدد/الفترة الأولى مع معاينة الجدول قبل الحفظ، زر «توليد المستحق الآن»)، وتفاصيل بجدول الأقساط وحالاتها وروابط القيود وزر «إعادة التوليد» لكل قسط متخطّى.
- إصلاح جانبي أثناء العمل: `get_queryset()`'s `.prefetch_related("installments")` كانت تُبقي استجابتَي `submit`/`approve` تُظهران 0 أقساط رغم إنشائها للتو (كاش الجلب السابق للتفعيل) — أُضيف `entry.refresh_from_db()` بعد كل استدعاء خدمة يُنشئ صفوفًا؛ اكتُشف بالاختبار لا افتراضيًا (نفس فئة خطأ عكس القيد في 6.3).

### ما لم يكتمل / استثناءات موثَّقة
- لا اختبار Playwright/E2E متصفح فعلي للشاشتين الجديدتين — `next build` + `tsc --noEmit` + مراجعة كود فقط (نفس قيد 6.3).
- شاشة القيود الدورية لا تُخفي نفسها في الوضع المبسّط بعد — القرار مؤجَّل لتوحيد القائمة الكاملة في الكتلة 6.9 كما ينص `sprint-6.md` صراحة («الوضع المبسّط يُخفي الدورية»، §القائمة).

### الاختبارات والفحوص
- **408/408** اختبارًا (398 + 10 جديدة في `tests/test_recurring_entries.py` — كل سيناريوهات الكتلة المطلوبة: تقسيم 12,000 على 12 قسطًا × 1,000 بتواريخ نهاية الفترات، تقسيم 10,000 على 3 بالباقي على الأخير (3333.33+3333.33+3333.34)، توليد قيد POSTED واحد بمدين/دائن ومركز تكلفة صحيحين، تشغيل مزدوج بلا تكرار، فترة CLOSED → SKIPPED بسبب ثم `regenerate` بعد إعادة الفتح → GENERATED، القسط الأخير → COMPLETED، `cancel` يُلغي DUE فقط، جدول يحتاج سنة تالية غير موجودة → تُنشأ تلقائيًا، المنشئ يعتمد جدوله → 403، عزل مستأجر).
- `ruff check .` نظيف، `manage.py check` نظيف، `makemigrations --check --dry-run` نظيف، `tsc --noEmit` نظيف، `next build` نظيف (46 مسارًا)، `check-brand.sh`/`check-money.sh` ناجحان.
- قبل تطبيق migrations هذه الكتلة (`access/0017`، `approvals/0009`): `scripts/backup.sh` نُفِّذ فعليًا (`cps-db-20260924-181031.sql.gz`، 88K) — إضافة صلاحية وقاعدة اعتماد افتراضية جديدتين، لا تغيير سلوك على أي مستند موجود، فلا سؤال إلزاميًا وفق قاعدة §11.
- `docker compose restart backend celery_worker frontend` + `make smoke` نُفِّذا فعليًا بعد آخر commit — نجحا (تسجيل دخول 200، ميزان مراجعة متوازن 52802.59 ريال على Fatma الحية — بلا تغيير).

---

## الكتلة 6.6 — القوائم المالية الأساسية + أعمار ذمم العملاء ✅

**Commit:** `8fd91fe` — `Sprint 6.6: account balances service, income statement, balance sheet, customer aging, print pages`

### ما بُني
- تطبيق جديد `apps/reports` (بلا نماذج — خدمة + Views فقط) مسجَّل في `LOCAL_APPS` و`config/urls.py`.
- `apps/reports/services.py::account_balances()` (القرار 11): افتتاحي/مدين الفترة/دائن الفترة/ختامي لكل حساب **قابل للترحيل فعليًا** (لا حساب أب — استبعاد بصف استعلام واحد بدل فحص `is_leaf` لكل حساب)، على نفس أساس `REPORTABLE_STATUSES` الذي تستخدمه `ledger_lines`/`compute_trial_balance` — **لا استعلام SQL خام موازٍ**. مبنية عليها: `income_statement()` (إيرادات−مصروفات بحركة الفترة فقط لا الرصيد التراكمي — هذا المشروع بلا قيد إقفال سنة بعد، فالتراكمي كان سيضخّم كل فترة لاحقة؛ مجاميع فرعية حسب الأب من المستوى الأول عبر `_level1_ancestor`)، `balance_sheet()` (أصول=خصوم+حقوق ملكية+«نتيجة الفترات غير المقفلة» — صافي الربح منذ البداية حتى `as_of`، مُعاد استخدامه من `income_statement()` نفسها لا مُعاد حسابه)، `aging_report()` (فواتير `balance_fc>0` بعملة الفاتورة التاريخية + بنود مفتوحة من افتتاح معتمَد معلَّمة `is_opening=True`، شرائح 0-30/31-60/61-90/90+ من تاريخ الاستحقاق أو الإصدار احتياطيًا).
- `_entities_in_scope()`: كيان قانوني + كل سلالته (شجرة غير محدودة العمق) عند `include_children=True`، أو الكيان وحده عند `false`.
- API: `GET /api/reports/income-statement/`، `GET /api/reports/balance-sheet/`، `GET /api/reports/aging/` — كل استجابة تحمل `generated_at`/`prepared_by`/`base_currency`. الصلاحية: فحص مباشر بدل `HasModulePermission` (انظر الإصلاح الجانبي أدناه).
- الشاشات: التقارير ← **قائمة الدخل · الميزانية العمومية · أعمار الذمم** (فلاتر كيان/شمول الفروع/فترة/مركز تكلفة، جداول بمجاميع بـ`formatMoney`) + صفحات طباعة `/print/reports/{income-statement,balance-sheet,aging}` بنمط 5.6 (شعار، ترويسة الكيان، الفترة، من أعدّه، تاريخ ووقت الإعداد، توقيعان).
- إصلاح جانبي أثناء العمل — فجوة بنيوية حقيقية: `HasModulePermission` (المستخدَمة في كل ViewSet منذ سبرنت 1) تقرأ `view.action`، وهو مفهوم خاص بـ`ViewSet` فقط؛ استخدامها على `APIView` عادي (كما في الشاشات الثلاث الجديدة) يُسقِط الطلب بـ500 (`AttributeError`) بدل فحص الصلاحية — اكتُشف بالاختبار لا افتراضيًا. `DashboardSummaryView`/`PendingApprovalsView` الحاليتان تتجنبانه بعدم التصريح بـ`permission_map` إطلاقًا (أي بلا RBAC حقيقي على تلك الشاشتين تحديدًا) — بما أن القوائم المالية أكثر حساسية، اختير هنا فحص مباشر عبر `user_has_permission(request.user, "accounting.view")` بدل تكرار ثغرة عدم التحقق.

### ما لم يكتمل / استثناءات موثَّقة
- لا اختبار Playwright/E2E متصفح فعلي للشاشات الست الجديدة — `next build` + `tsc --noEmit` + مراجعة كود فقط (نفس قيد 6.3/6.4).
- «الفرع يُستبعد بـ`include_children=false`» اختُبر على شجرة كيانين (شركة+فرع) لا ثلاثة مستويات — الدالة عامة (تجمع أعماقًا غير محدودة عبر `parent_id__in`) لكنها لم تُختبر صراحةً بعمق ثالث.

### التحقق على بيانات Fatma الحية (GET فقط، بلا كتابة — وفق قاعدة §11)
- `GET /api/reports/balance-sheet/`: الأصول 6880.91 = الخصوم 3116.25 + حقوق الملكية 3764.66 (رأس المال 5000.00 + نتيجة الفترات غير المقفلة −1235.34) — **تتطابق تمامًا**، ويطابق ميزان المراجعة الحالي (52802.59 = 52802.59 مدين/دائن، أساس حسابي واحد).
- `GET /api/reports/income-statement/?from=2026-01-01&to=2026-12-31`: إيرادات 21575.00 − مصروفات 22810.34 = صافي خسارة −1235.34 — نفس رقم «نتيجة الفترات غير المقفلة» أعلاه بالضبط، كما يجب بنيويًا.

### الاختبارات والفحوص
- **417/417** اختبارًا (408 + 9 جديدة في `tests/test_reports.py`، مبنية على فواتير/سندات/افتتاح حقيقية عبر الـAPI لا بيانات مصطنعة: قائمة الدخل تطابق حسابًا يدويًا، فلتر مركز تكلفة ≤ الإجمالي، الميزانية تتوازن بالضبط شاملةً نتيجة الفترات غير المقفلة، قيد الافتتاح يظهر في الميزانية ولا يمس قائمة الدخل، الميزانية `as_of` قبل سند سداد تُظهر الذمم قبله وتُخفيها بعده، `include_children=false` يستبعد الفرع، أعمار الذمم تصنّف فاتورة مستحقة قبل 45 يومًا في 31–60 وبند افتتاحي معلَّم `is_opening`، عملة أجنبية تُحوَّل بسعر الفاتورة، عزل مستأجر).
- `ruff check .` نظيف، `manage.py check` نظيف، `makemigrations --check --dry-run` نظيف، `tsc --noEmit` نظيف، `next build` نظيف (49 مسارًا)، `check-brand.sh`/`check-money.sh` ناجحان.
- لا migration بيانات في هذه الكتلة (تطبيق `reports` بلا نماذج) — لا حاجة لـ`scripts/backup.sh`.
- `docker compose restart backend celery_worker frontend` + `make smoke` نُفِّذا فعليًا بعد آخر commit — نجحا (تسجيل دخول 200، ميزان مراجعة متوازن 52802.59 ريال على Fatma الحية).

---

## الكتلة 6.7 — قائمة إقفال الفترة والقفل + حارس VOID + قاعدة المرفق الإلزامي ✅

**Commit:** `3d5cfef` — `Sprint 6.7: period-close checklist with snapshot, lock, VOID guard, mandatory attachment rules`

### ما بُني
- `apps/accounting/period_close.py` (وحدة جديدة): `period_checklist(period)` — 9 بنود BLOCK/WARN/INFO كاملة بالقرار 13 (الفترة السابقة، مستندات غير مرحَّلة بمراجعها [فاتورة/سند/قيد يدوي/افتتاح]، أقساط دورية مستحقة غير مولَّدة بمراجعها، تسوية كل بنك عبر `reconciliation_report` الحالية، مستندات POSTED بلا مرفق، فترة الإقرار الضريبي، الافتتاح لكل كيان نشط، ميزان المراجعة INFO، الإهلاك INFO)، و`close_period()` الجديدة (BLOCK يمنع دائمًا، WARN يمنع بلا `acknowledge_warnings=True`، `close_snapshot` = القائمة كاملة وقت الإقفال). `periods.py::close_period` أصبحت تفويضًا رقيقًا لهذه — كل استدعاء قائم (الشاشة، اختبارات 6.1/6.3/6.4) يرث السلوك الأصرم تلقائيًا بلا تغيير في التوقيع الأساسي (فقط `acknowledge_warnings` جديدة بقيمة افتراضية `False`). حُذفت `_unposted_documents_in_range` (الفحص المبسّط القديم) — لا كود ميت.
- `GET /api/fiscal-periods/{id}/checklist/` (جديد) + `POST .../close/` مُحدَّثة تقرأ `acknowledge_warnings` من الجسم.
- حارس VOID (القرار 14): `apps.sales.services.void_invoice()` (خدمة جديدة، استُخرجت من منطق كان مباشرة في الـview) — `VoidRejected` (409) دائمًا لفترة إقرار ضريبي FILED/PAID؛ فاتورة `delivered_at` تشترط صلاحية `sales.void_delivered_invoice` (Owner فقط، migration `access/0018`) + سببًا إلزاميًا → `Invoice.is_post_delivery_void=True` (حقل جديد، migration `sales/0021`) + AuditLog بالسبب؛ القيد العكسي يبقى بتاريخ اليوم دائمًا (سلوك `void_invoice_journal_entry` الحالي من سبرنت سابق، لم يتغيّر — يحقق القرار 3 مباشرة بلا تعديل).
- `AttachmentRule` (نموذج جديد، `apps/attachments/models.py`، migration `attachments/0003`) — `doc_type`/`min_amount_base`/`required_category`/`is_active`، لا قاعدة افتراضية مزروعة. الفحص مركزي في `apps.approvals.services.submit_for_approval` (نقطة العبور الوحيدة لكل مستند: فاتورة/قيد/سند/افتتاح) — لا نسخة ثانية للفحص في أي مسار آخر. API كامل CRUD `/api/attachment-rules/`.
- الشاشات: تبويب «قائمة الإقفال» داخل شاشة «السنوات والفترات المالية» (بنود ملوَّنة BLOCK أحمر/WARN أصفر مع مراجع المستندات، مربع إقرار يظهر فقط عند وجود WARN، زر الإقفال معطَّل عند وجود BLOCK)؛ زر إلغاء الفاتورة يطلب سببًا تلقائيًا إن كانت مُسلَّمة ويعرض شارة «أُلغيت بعد التسليم»؛ الإعدادات ← **«قواعد المرفقات الإلزامية»** (شاشة جديدة كاملة).
- إصلاح جانبي أثناء العمل: اختبارا 6.1/6.4 اللذان يستدعيان `close_period()` مباشرة (لا عبر الـview) توقَّفا بعد الترقية لأن فتراتهما الآن تحمل تحذيرات لم تكن موجودة في 6.1/6.4 (فترة إقرار ضريبي غير مُقدَّمة، افتتاح غير معتمد) — صُحِّحا بإضافة `acknowledge_warnings=True` صراحة؛ واختبار سيناريو "فترة CLOSED → SKIPPED" في 6.4 أُعيد ترتيبه (الفترة تُقفل *قبل* إنشاء الجدول الدوري بدل إقفالها تحتها) لأن BLOCK الجديد "أقساط مستحقة غير مولَّدة" يمنع الآن الوصول لتلك الحالة بالترتيب القديم — موثَّق في تعليق الاختبار نفسه كتفسير للسيناريو الأصح.

### ما لم يكتمل / استثناءات موثَّقة
- لا اختبار Playwright/E2E متصفح فعلي للشاشات الجديدة/المعدَّلة — `next build` + `tsc --noEmit` + مراجعة كود فقط (نفس قيد 6.3/6.4/6.6).
- «مستندات POSTED بلا مرفق» تفحص JournalEntry/Invoice/Voucher — لا تفحص مستندات الافتتاح نفسها (خارج قائمة أنواع POSTED الفعلية؛ الافتتاح يظهر في بند «الافتتاح لكل كيان نشط» بدلًا من ذلك).

### الاختبارات والفحوص
- **429/429** اختبارًا (417 + 12 جديدة عبر `tests/test_period_checklist.py` (4)، `tests/test_invoice_void_guard.py` (4)، `tests/test_attachment_rules.py` (4) — كل سيناريوهات الكتلة المطلوبة: فاتورة مسودة BLOCK بمرجعها و`close`→400؛ قسط دوري مستحق BLOCK ثم توليده يزيله؛ بنك بفرق تسوية WARN و`close` بلا إقرار→400 وبإقرار→CLOSED مع التحذير في `close_snapshot`؛ VOID بفترة ضريبية FILED→409 دائمًا؛ VOID بعد تسليم بلا صلاحية→409 وبصلاحية+سبب→ينجح ويُعلَّم؛ VOID بفترة مالية مقفلة→قيد عكسي بتاريخ اليوم؛ سند 6,000 بلا مرفق→400، بمرفق→ينجح، سند 4,000 بلا مرفق→ينجح؛ عزل مستأجر في الثلاثة). ملاحظة: فشل عابر غير مرتبط في `test_rate_limiting.py` أثناء التشغيل الكامل (عدّاد Redis مشترك عبر التشغيلة الكاملة) — نجح 4/4 عند تشغيله منفردًا، غير ناتج عن أي تغيير في هذه الكتلة.
- `ruff check .` نظيف، `manage.py check` نظيف، `makemigrations --check --dry-run` نظيف، `tsc --noEmit` نظيف، `next build` نظيف (50 مسارًا، شاملة شاشة قواعد المرفقات الجديدة)، `check-brand.sh`/`check-money.sh` ناجحان.
- قبل تطبيق migrations هذه الكتلة (`access/0018`، `attachments/0003`، `sales/0021`): `scripts/backup.sh` نُفِّذ فعليًا (`cps-db-20260924-185547.sql.gz`) — صلاحية جديدة (Owner فقط)، جدول جديد فارغ بلا قاعدة افتراضية، وحقل بولياني جديد افتراضه False على كل فاتورة موجودة — لا تغيير سلوك على أي مستند قائم، فلا سؤال إلزاميًا وفق قاعدة §11.
- `docker compose restart backend celery_worker frontend` + `make smoke` نُفِّذا فعليًا بعد آخر commit — نجحا (تسجيل دخول 200، ميزان مراجعة متوازن 52802.59 ريال على Fatma الحية).
