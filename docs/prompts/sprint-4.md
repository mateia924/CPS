# سبرنت 4 — قلب المحاسبة: الدليل الشجري + محرك القيود + الاعتماد + الضرائب + الترقيم الذري

**المراجع الملزمة (اقرأها كاملة قبل أي سطر كود):**
- `docs/SYSTEM_ANALYSIS.md` v1.5 — الأقسام 3.4، 3.11، 3.15.1، 3.15.2، 3.15.3، 3.16.2، 3.18، والقواعد 1–19 (خصوصًا 3، 4، 13، 16).
- `docs/ARCH_REVIEW_1.md` — القسم 3.3 (قائمة التغييرات)، 3.4 (تصميم DocumentSequence جاهز للتنفيذ حرفيًا)، 4 (الديون #1 #2 #3 #8 #9 #20)، 5.1 (N+1 #1)، 5.2 (backends.py).

**طريقة العمل في هذا السبرنت:** هو الأكبر في المشروع. نفّذ الكتل بالترتيب أدناه، و**اعمل commit مستقل بعد كل كتلة** تعبر اختباراتها (`Sprint 4.1: ...`, `Sprint 4.2: ...`) — لا كوميت واحد ضخم في الآخر. لو كتلة كشفت قرارًا غير موثّق، توقف واسأل قبل الافتراض.

---

## الكتلة 4.0 — أمان وجودة سريعة (من المراجعة #1)

1. **Rate limiting** على `/api/auth/login/` و`/api/auth/register/` و`/api/platform/auth/login/`: `limit_req` في nginx (منطقة بالـ IP، 10 طلبات/دقيقة، burst 5) **+** `django-ratelimit` كطبقة ثانية داخل الـ views (5/دقيقة لكل IP+email). رد 429 برسالة عربية.
2. **اختبار `apps/accounts/backends.py`** مسار الدخول بلا subdomain: يمر فقط لـ `is_superuser=True`؛ أي حساب آخر بنفس البريد في أي مستأجر يُرفض؛ وحساب superuser معطّل يُرفض. (الدين #8 — أمان.)
3. اختبارات `check_branch_limit` و`check_invoice_limit` (تغطية `tenants/services.py`).
4. `TenantAdminSerializer`: استبدل الـ 3 `SerializerMethodField` بـ `annotate(Count/Max)` في `get_queryset` — الشاشة بصفحة 25 مستأجرًا ≤ 5 استعلامات (اختبر بـ `django_assert_num_queries`).
5. ثبّت `ruff` في صورة الـ backend (مرحلة dev) حتى يعمل `make lint` داخل الحاوية.
6. اكتب الملخص النهائي لهذا السبرنت في `docs/sprints/4-summary.md` (والتزم بذلك لكل السبرنتات القادمة).

commit: `Sprint 4.0: rate limiting, auth backend tests, platform N+1 fix`

---

## الكتلة 4.1 — الترقيم الذري (قبل أي مستند جديد)

- نفّذ `DocumentSequence` و`next_document_number()` **حرفيًا كما في ARCH_REVIEW_1 §3.4** (`select_for_update` داخل `transaction.atomic`).
- النطاق: `(tenant, doc_type, legal_entity, year)`. الصيغة الافتراضية `{prefix}-{year}-{seq:05d}`.
- نموذج `DocumentNumberingSetting` (tenant, doc_type, prefix, reset_yearly=True) بشاشة في الإعدادات ← "ترقيم المستندات" (أساسي: البادئة؛ متقدم: إعادة التصفير سنويًا).
- طبّقه على: الفواتير (`generate_invoice_number`)، أكواد الأطراف (`generate_party_code` — بادئة حسب الدور: CUS/SUP/EMP/AFF)، وكل مستند جديد في هذا السبرنت (القيود اليدوية JV).
- **الأرقام القديمة تبقى كما هي**؛ migration تضبط `last_number` لكل نطاق من الحد الأقصى الموجود.
- **اختبار تزامن حقيقي:** 50 thread تنشئ فواتير في نفس اللحظة (pytest بـ `transaction=True`) → 50 رقمًا فريدًا متتاليًا بلا فجوة.

commit: `Sprint 4.1: atomic document numbering`

---

## الكتلة 4.2 — العملة وسعر الصرف على كل سطر (الفجوة الأهم)

- نموذج `ExchangeRate` (tenant, from_currency, to_currency, date, rate 18,8, source: MANUAL/API, created_by). فريد على (tenant, from, to, date). شاشة في الخزينة ← "أسعار الصرف" (جدول + إضافة). خدمة `get_rate(tenant, from, to, date)` تُرجع أحدث سعر بتاريخ ≤ التاريخ المطلوب؛ نفس العملة = 1؛ لا سعر = خطأ واضح بالعربي.
- **العملة الأساسية** = `LegalEntity.base_currency` (موجود). كل مستند يحمل `currency` + `exchange_rate` (يُسحب تلقائيًا من ExchangeRate بتاريخ المستند، قابل للتجاوز يدويًا مع تسجيل `exchange_rate_overridden=True` في AuditLog).
- **`JournalLine`:** `debit_fc`/`credit_fc` (بعملة المعاملة، 14,2) + `debit`/`credit` (بالعملة الأساسية، 14,2 — الموجودان). التوازن إلزامي **بالعملتين**: بعملة المعاملة بالضبط؛ وبالعملة الأساسية بعد التحويل، وفرق التقريب (≤ 0.05) يُضاف لسطر تقريب تلقائي على حساب "فروق تقريب العملة" (من القالب) — موثّق.
- **`InvoiceLine`/`Invoice`:** `currency` + `exchange_rate` على الفاتورة؛ مبالغ السطر بعملة الفاتورة؛ `base_total` محسوب على الفاتورة للتقارير.
- **Migration بيانات:** كل السجلات الموجودة: `currency = legal_entity.base_currency`, `exchange_rate = 1`, `*_fc = *`. تحقق على بيانات Acme الفعلية.
- ثوابت `RATE_MAX_DIGITS/RATE_DECIMAL_PLACES = 18/8` في `common/constants.py`.
- اختبار: قيد بـ USD على كيان أساسه SAR بسعر 3.75 → `debit_fc=100`, `debit=375`; تغيير السعر في ExchangeRate بتاريخ لاحق لا يغيّر قيدًا مرحّلًا.

commit: `Sprint 4.2: multi-currency on every line, ExchangeRate`

---

## الكتلة 4.3 — الدليل الشجري وقوالب النشاط والحسابات التلقائية

- **`Account`** (إعادة بناء جزئي كما في ARCH_REVIEW_1 §3.1): `parent` (self-FK, PROTECT, nullable)، `level` (محسوب عند الحفظ)، `is_leaf` (خاصية: لا أبناء)، `normal_balance` (DEBIT/CREDIT صريح؛ افتراضي من النوع: ASSET/EXPENSE=DEBIT، LIABILITY/EQUITY/REVENUE=CREDIT، قابل للتجاوز للحسابات المقابلة)، `allow_posting` (الترحيل على الأوراق فقط)، `is_intercompany` (للجاري البيني)، `party` (FK nullable — الحساب الجاري لطرف)، `code` هرمي فريد لكل مستأجر، `is_active`.
- **قواعد:** لا ترحيل على حساب له أبناء (400)؛ حساب عليه سطور لا يُحذف ولا يُغيَّر نوعه ولا أبوه (400/409 — 3.15.9)؛ لا دورات؛ الأب والابن من نفس النوع.
- **قوالب الدليل حسب النشاط** (3.4): ملفات JSON في `apps/accounting/chart_templates/`: `service` (~15 حسابًا)، `trading`، `manufacturing`، `holding`. أضف حقل `business_type` للتسجيل (اختيار "نوع النشاط" — أساسي في فورم التسجيل) ولـ `Tenant`. كل قالب يحمل **حسابات نظام مُعلَّمة بمفتاح** (`system_key`: CASH, BANKS, CUSTOMERS, SUPPLIERS, EMPLOYEES, CUSTODIES, AFFILIATES, SALES, COGS, VAT_OUTPUT, VAT_INPUT, VAT_NON_DEDUCTIBLE, FX_REALIZED, FX_UNREALIZED, ROUNDING, RETAINED_EARNINGS, OPENING_BALANCE...) — الكود يشير للحساب عبر `system_key` لا عبر الرقم.
- **Migration للمستأجرين الحاليين:** طبّق قالب `service` كأب للحسابات الموجودة دون حذف أي حساب (اربطها بالمفاتيح المطابقة؛ الباقي تحت "حسابات أخرى").
- **الحسابات التلقائية:** عند إنشاء دور CUSTOMER/SUPPLIER/EMPLOYEE/AFFILIATE → حساب جاري ورقة تلقائي تحت الأب المطابق (`system_key`) بكود متسلسل واسم الطرف، `Account.party` = الطرف. عند إنشاء Bank/CashBox/Custody → حساب تلقائي تحت BANKS/CASH/CUSTODIES ويُملأ `gl_account` (الدين #20). لا يتكرر (idempotent). الطرف بدورين = حسابان (عملاء/موردون) — موثّق.
- **`JournalLine.party`** (FK nullable) يُملأ تلقائيًا عند الترحيل على حساب جاري — للكشوف وأعمار الذمم لاحقًا.
- **شاشة "دليل الحسابات"** (المحاسبة): شجرة قابلة للطي مع الأرصدة الحالية، إضافة ابن، تعديل، تعطيل، بحث بالكود/الاسم، وشارة "نظام" للحسابات المفتاحية. أساسي: كود، اسم، النوع، الأب؛ متقدم: normal_balance، allow_posting، is_intercompany.
- اختبار: قالب `trading` ينشئ الشجرة كاملة؛ ترحيل على حساب أب → 400؛ إنشاء عميل يولّد حسابه تحت CUSTOMERS مرة واحدة؛ حذف حساب عليه سطر → 409.

commit: `Sprint 4.3: hierarchical chart of accounts, activity templates, auto sub-ledger accounts`

---

## الكتلة 4.4 — محرك القيود: الحالة، المصدر، التسوية، مراكز التكلفة

- **`JournalEntry.status`**: `DRAFT → PENDING_APPROVAL → APPROVED → POSTED → REVERSED` عبر `DocumentStateMixin` عام (سيُعاد استخدامه للسندات والفواتير). **الأرصدة والتقارير تقرأ POSTED فقط** (القاعدة 13). كل انتقال يُسجَّل في AuditLog مع الفاعل.
- **المصدر:** استبدل `source_type/source_id` بـ GenericFK حقيقي (`ContentType` + `object_id`) مع migration للبيانات الموجودة.
- **العكس:** `reverse(reason)` ينشئ قيدًا عكسيًا POSTED مرتبطًا بالأصل، ويحوّل الأصل إلى REVERSED؛ لا تعديل على POSTED أبدًا.
- **حقول التسوية البنكية على `JournalLine`** (3.15.2): `reconciled_at` (nullable), `reconciled_by` (nullable), `bank_statement_line` (FK nullable). أنشئ الآن نموذجي `BankStatement` (tenant, bank, statement_date, opening/closing balance, source_file nullable) و`BankStatementLine` (statement, date, amount, description, reference, matched) **بحقولهم الدنيا فقط** — بلا استيراد ولا مطابقة (سبرنت 5.5).
- **توزيع مركز التكلفة:** `post_invoice_journal_entry` يولّد سطر إيراد لكل مركز تكلفة في بنود الفاتورة (الدين #5 — يُحل الآن)، وسطر ضريبة لكل TaxCode (الكتلة 4.6).
- **القيود اليدوية:** شاشة "القيود اليدوية" (المحاسبة): رأس (تاريخ، كيان قانوني، عملة + سعر، وصف، مرجع) + سطور (حساب ورقة ببحث، مدين/دائن بعملة المعاملة، مركز تكلفة، طرف تلقائي، بيان). حفظ كمسودة، إرسال للاعتماد، ترحيل. ترقيم `JV` عبر الكتلة 4.1. **لا قيد يدوي يُرحَّل بلا اعتماد** (3.15.9 — قاعدة اعتماد افتراضية على JV لدور ACCOUNTANT_MANAGER/OWNER).
- **ميزان مراجعة أولي** (endpoint + شاشة بسيطة في التقارير): لكل حساب ورقة: مدين/دائن الحركة والرصيد بالعملة الأساسية، فلاتر: كيان قانوني، من/إلى تاريخ، مستوى الشجرة (تجميع للآباء). **الغرض: أداة تحقق للـ UAT** — التقارير الكاملة بـ Drill-down سبرنت 10. الإجمالي مدين = دائن دائمًا.
- اختبار: قيد DRAFT لا يظهر في الميزان؛ POSTED يظهر؛ REVERSED يُصفّر أثره؛ فاتورة ببندين على مركزين تولّد سطري إيراد؛ كل الاختبارات القديمة على الفواتير تعدّي.

commit: `Sprint 4.4: journal engine — states, GenericFK source, reversal, reconciliation fields, cost-center split`

---

## الكتلة 4.5 — محرك الاعتماد وفصل الواجبات (3.15.1)

- **`ApprovalRule`** (tenant, doc_type: JOURNAL_ENTRY/INVOICE/…, min_amount بالعملة الأساسية, required_role, is_active). شاشة في الإعدادات ← "قواعد الاعتماد" (DataTable + فورم). لا قاعدة مطابقة = اعتماد تلقائي عند الإرسال.
- **فصل الواجبات:** إذا انطبقت قاعدة، المنشئ لا يستطيع اعتماد مستنده (403 برسالة عربية) — إلا إذا كان المستأجر بمستخدم نشط واحد (الوضع المبسّط) فيُعفى تلقائيًا مع تسجيل ذلك.
- **صندوق الاعتماد:** `/api/approvals/pending/` يُرجع المستندات التي تنتظر اعتماد المستخدم الحالي (حسب دوره)؛ شاشة "صندوق الاعتماد" + عدّاد في الشريط العلوي (3.18). إجراءات: اعتماد / رفض بسبب إلزامي.
- طبّقه على **JournalEntry** (الكتلة 4.4) و**Invoice**: `DRAFT → PENDING_APPROVAL → APPROVED → ISSUED(=POSTED)`؛ الفواتير الحالية DRAFT/ISSUED تُهاجَر بلا كسر؛ الفاتورة بلا قاعدة مطابقة تُعتمد تلقائيًا عند الإصدار (سلوك العميل الصغير لا يتغير).
- AuditLog على كل اعتماد/رفض (من، متى، السبب).
- اختبار: قاعدة JV > 10,000 تتطلب OWNER؛ محاسب ينشئ قيد 20,000 ويحاول اعتماده → 403؛ Owner يعتمد → POSTED؛ مستأجر بمستخدم واحد يُعفى؛ رفض بلا سبب → 400.

commit: `Sprint 4.5: approval engine, segregation of duties, approval inbox`

---

## الكتلة 4.6 — أكواد الضريبة وفترة الإقرار (3.16.2)

- **`TaxCode`** (tenant, code, name, rate 5,2, kind: STANDARD/ZERO_RATED/EXEMPT/OUT_OF_SCOPE/REVERSE_CHARGE, direction: OUTPUT/INPUT/BOTH, deductible: FULL/NONE, account (FK Account عبر system_key VAT_OUTPUT/VAT_INPUT/VAT_NON_DEDUCTIBLE), country_code, effective_from, is_active). فريد (tenant, code).
- **حزمة الامتثال السعودية:** `apps/compliance/sa/tax_codes.json` تُبذر لكل مستأجر سعودي عند التسجيل ولكل الحاليين عبر migration: `S` 15% قياسي، `Z` 0% صفري، `E` معفى، `O` خارج النطاق، `RC` ضريبة عكسية، `SN` 15% غير قابل للخصم. شاشة "أكواد الضريبة" في المحاسبة (قراءة + تعديل الاسم/التفعيل؛ إضافة كود جديد للمدير المالي).
- **البند يحمل `tax_code` (FK)** لا نسبة حرّة (القاعدة 16): `InvoiceLine.tax_code` إلزامي؛ `tax_rate` يبقى كلقطة (snapshot) محسوبة من الكود وقت الحفظ؛ `Product.default_tax_code`. الفرونت: قائمة أكواد في السطر بدل رقم. Migration: كل بند قديم بنسبة 15 → `S`، 0 → `Z`.
- **الترحيل:** سطر ضريبة لكل TaxCode في الفاتورة على حسابه؛ `NONE` deductible يُحمَّل على حساب المصروف/الأصل لا حساب الضريبة (منطقه جاهز؛ يُستخدم فعليًا من فاتورة المورد سبرنت 8)؛ `REVERSE_CHARGE` يولّد سطري مخرجات ومدخلات متساويين (جاهز لسبرنت 8).
- **`TaxPeriod`** (tenant, legal_entity, period_type: MONTHLY/QUARTERLY, start, end, status: OPEN/FILED/PAID, filed_at, reference) **مستقل عن الفترة المالية**؛ توليد تلقائي للسنة الحالية حسب نوع الفترة المختار في إعدادات الكيان؛ شاشة قائمة بسيطة (الإقرار نفسه سبرنت 10).
- اختبار: فاتورة بثلاثة بنود (S، Z، E) → ضريبة 15% على بند S فقط، وسطر ضريبة واحد في القيد بمبلغه الصحيح؛ بند بلا tax_code → 400؛ `RC` يولّد سطرين متساويين.

commit: `Sprint 4.6: tax codes, KSA compliance seed, tax periods`

---

## الكتلة 4.7 — الفرونت والتكامل والـ UAT

- القائمة (3.18): المحاسبة ← دليل الحسابات، القيود اليدوية، أكواد الضريبة، فترات الإقرار؛ الخزينة ← أسعار الصرف؛ الإعدادات ← قواعد الاعتماد، ترقيم المستندات؛ التقارير ← ميزان المراجعة (أولي)؛ صندوق الاعتماد في الشريط العلوي.
- شارة حالة موحّدة (مسودة/بانتظار اعتماد/معتمد/مرحّل/معكوس/ملغى) على الفواتير والقيود (3.18 قاعدة 5).
- الفاتورة: عملة + سعر صرف (مطوي، افتراضي من ExchangeRate)، كود ضريبة لكل سطر، مركز تكلفة لكل سطر.
- **سكربت UAT للمحاسب** في `docs/UAT/sprint-4.md` (القاعدة 18): خطوات مرقّمة يقوم بها محاسب بشري — إنشاء دليل بقالب تجاري، 10 قيود متنوعة (منها قيد USD)، قاعدة اعتماد، محاولة اعتماد ذاتي، فاتورة بثلاثة أكواد ضريبية، ميزان مراجعة يتوازن، عكس قيد — مع خانة "النتيجة" لكل خطوة. النتائج تُدوَّن في `docs/UAT_LOG.md`.
- Decision Log في `SYSTEM_ANALYSIS.md` لكل قرار تفصيلي جديد، وتحديث الحالة في القسم 2 والجدول في القسم 5.
- README: التشغيل، الاختبارات، الديون التقنية (شيل المحلول: #1 #2 #3 #4 #5 #6 #8 #9 #20 #23؛ أضف الجديد).

commit: `Sprint 4.7: accounting screens, unified status badges, UAT script`

---

## معايير القبول الإجمالية (لا يُغلق السبرنت قبلها)

- كل الاختبارات القديمة (133) + الجديدة تعدّي على Postgres حقيقي؛ `ruff` نظيف؛ `next build` بلا أخطاء.
- قيد لا يُرحَّل إلا POSTED، وعلى حسابات أوراق فقط، ومتوازن بالعملتين.
- 50 فاتورة متزامنة → 50 رقمًا فريدًا بلا فجوة.
- فاتورة بثلاثة أكواد ضريبية تُحسب وتُرحَّل صحيحًا.
- منشئ قيد خاضع لقاعدة اعتماد لا يعتمده لنفسه.
- ميزان المراجعة يتوازن دائمًا؛ REVERSED يُصفّر أثره.
- عزل مستأجر على كل المسارات الجديدة (list / 404 / create) + الاختبار البنيوي يعبر بلا استثناءات جديدة غير مبرّرة.
- `docs/sprints/4-summary.md` مكتوب: عدد الاختبارات، ما عدّى، ما لم يكتمل ولماذا.

**قواعد:** لا فيتشر خارج النطاق (لا سندات، لا فترات مالية، لا مرفقات — سبرنتات 5/6). لا حذف بيانات/volumes. أي migration تلمس بيانات موجودة → اسأل قبل تشغيلها. قرار غير واضح → اسأل.
