# الكتلة 6.0.1 — مطابقة الخطة والهوية (تُنفَّذ قبل 6.1)

**النسخة:** v1 — معتمدة من محلل النظم (2026-09-24). **مصدرها:** `docs/reviews/PLAN_COMPLIANCE_1.md` (commit `3cb9886`) — كل فجوة هندسية فيه تُغلق هنا. تعديل على ترتيب `docs/prompts/sprint-6.md` v2: كانت 6.0.1 «قبل 6.9» وأصبحت **قبل 6.1**. الفجوات الإدارية (UAT بشري، GitHub، SSH) ليست هنا — يتولاها المالك بالتوازي.

**المراجع الملزمة:** `docs/BRAND.md` كاملًا، `docs/brand/tokens.css` (المصدر الوحيد للألوان والخطوط والأشكال — **لا يُعدَّل هنا**)، `docs/SYSTEM_ANALYSIS.md` §3.18 و§3.3 والقواعد 1–23، `docs/prompts/sprint-6.md` (الكتلة 6.0 وقواعدها)، `docs/reviews/PLAN_COMPLIANCE_1.md` (الأدلة بالملف والسطر — لا تعد البحث من الصفر).

**طريقة العمل:** ثلاثة commits مستقلة (A, B, C) بالترتيب، كلٌّ بعد اختباراته؛ سطران بعد كل commit. قرار غير موثّق → توقف واسأل. لا مساس بأي منطق محاسبي في هذه الكتلة (واجهة + تقارير قراءة + وثائق فقط).

---

## قواعد دائمة من هذه الكتلة فصاعدًا (تدخل معايير قبول كل كتلة قادمة)

1. **لا لون حرفي خارج `tokens.css`:** `scripts/check-brand.sh` يفشل إن وُجد `#[0-9a-fA-F]{3,8}` أو `rgb(`/`hsl(` في `frontend/src` خارج `frontend/src/styles/tokens.css` (تُستثنى ملفات `.svg`). يُستدعى من `make check` ومن `next build` (سكربت `prebuild`).
2. **`frontend/src/styles/tokens.css` نسخة مطابقة حرفيًا لـ `docs/brand/tokens.css`:** نفس السكربت يفشل عند أي اختلاف (`diff`). تغيير لون = تغيير في `docs/brand/tokens.css` أولًا (بموافقة محلل النظم) ثم نسخه.
3. **كل مبلغ مالي في أي شاشة أو طباعة يمر بـ `<Money>`/`formatMoney`** — لا `toFixed` ولا عرض خام؛ اختبار Playwright/grep بنيوي `scripts/check-money.sh` يفشل عند `toFixed(2)` أو `{…total}`/`{…amount_fc}`/`{…balance_fc}`/`{…debit`/`{…credit`/`{…unit_price}` داخل JSX بلا `<Money`.
4. **كل شاشة تفاصيل جديدة تحمل `AttachmentPanel`** (القاعدة 14) — اختبار بنيوي يمسح `frontend/src/app/dashboard/**/[id]/page.tsx`.
5. **الحصيلة في نهاية كل سبرنت:** قسم «المطابقة» في `docs/sprints/<n>-summary.md`: نتيجة `check-brand` و`check-money` و`test_arabic_messages`، وأي انحراف عن 3.18.

---

## A — تطبيق الهوية البصرية (BRAND.md §1–§5 — كل البنود الثمانية)

1. **tokens.css:** انسخ `docs/brand/tokens.css` إلى `frontend/src/styles/tokens.css` واستورده **أول سطر** في `globals.css`. احذف من `globals.css` كل تعريفات الألوان الحالية (`--bg`, `--primary:#2c5f4f` …) واستبدل كل استخدام بأسماء التوكنات (`--color-primary`, `--ground`, `--surface`, `--border`, `--ink`, `--muted`, …). الأزرار: الرئيسية `--color-primary` بنص `--color-on-primary` (hover/active من التوكنات)؛ الثانوية بحدود `--border-strong` ونص `--ink`؛ الخطرة `--danger` بنص أبيض؛ الروابط `--color-link`. الحقول: حد `--border-strong`، تركيز حد `--color-focus` 2px. الزوايا: أزرار/حقول `--radius`، بطاقات `--radius-lg`، شارات `--radius-pill`. الظل الوحيد `--shadow`. لا تدرجات.
2. **الألوان الحرفية الـ33** (القائمة بالملف والسطر في التقرير قسم ب بند 2: `StatusBadge.tsx`، `globals.css`، `dashboard/layout.tsx`، `AttachmentPanel.tsx`، `BankReconciliationCard.tsx`، `CashCountCard.tsx`، `AccountTree.tsx`، `settings/company/page.tsx`) → كلها `var(--…)`. ثم `scripts/check-brand.sh` يمر بصفر مطابقات.
3. **الخطوط:** `next/font/google` (تُضمَّن وقت البناء — لا طلب شبكي وقت التشغيل): `Tajawal` (500/700/800) و`IBM_Plex_Sans_Arabic` (400/500/600) بـ `subsets: ['arabic','latin']` و`display: 'swap'`، تُربط بمتغيري `--font-display`/`--font-body` في `app/layout.tsx` (className على `<html>`)؛ إن فشل التنزيل وقت البناء على السيرفر (لا إنترنت للحاوية) → ضع ملفات woff2 في `frontend/public/fonts/` و`@font-face` في tokens-fonts.css محلي — وثّق أيهما اعتمدت. حجم الأساس 15px، سطر 1.6، أرقام لاتينية جدولية (`.amount`).
4. **الشعار:** الشريط الجانبي خلفيته `--sidebar-bg` (كحلي) ونصه `--sidebar-text`، البند النشط `--sidebar-active-bg` مع شريط `--sidebar-active-bar` على الحافة؛ أعلاه `<img src="/brand/cps-logo-stacked-compact-white.svg" alt="CPS">` بعرض 120px وتحته اسم المستأجر (`tenant.name`) بخط أصغر — **الشعار الرأسي المدمج هو الأساسي** (قرار المالك 2026-09-23؛ يُحدَّث في BRAND.md §1 ضمن C). الشريط العلوي أبيض بحد سفلي. صفحة الدخول/التسجيل: `cps-logo-stacked.svg` بعرض 200px فوق النموذج. صفحات الطباعة (`/print/invoices`, `/print/vouchers` وكل صفحة طباعة قادمة): `cps-logo-horizontal.svg` أعلى اليمين بارتفاع 48px بجانب رأس الكيان (BRAND.md §2.8 ق5)، وإن كان للكيان شعار مرفوع (5.6) يُعرض شعار الكيان بدل شعار CPS ويبقى «CPS» نصًا صغيرًا في التذييل.
5. **favicon وأيقونات التطبيق:** انسخ `public/brand/favicon.ico` → `public/favicon.ico`، وفي `metadata.icons`: `icon` = `/brand/cps-app-icon-32.png` و`/brand/cps-app-icon-192.png`، `apple` = `/brand/cps-app-icon-180.png`؛ `metadata.title` = «CPS — {اسم المستأجر}» حيث يتاح، وإلا «CPS».
6. **StatusBadge:** يقرأ حصريًا `--status-*`/`--status-*-bg` (زوج نص/خلفية، لا لون صلب): `draft`→draft، `pending_approval`→pending، `approved`→approved، `posted`/`issued`/`paid`→posted، `partially_paid`→approved (نص «مسدَّدة جزئيًا»)، `reversed`→reversed، `cancelled`/`rejected`/`void`→void، `active`/`completed`→posted، `suspended`/`skipped`→pending. نص الشارة من `status_label` (الخلفية) أو قاموس i18n — لا كود حالة خام. حجم `--radius-pill`، وزن 600.
7. **فحص التباين آليًا:** `frontend/scripts/contrast-check.mjs` يقرأ `tokens.css`، يحسب نسبة WCAG لكل زوج مُعرَّف في BRAND.md §2.4/§2.5 (نص/خلفية) + `--color-on-primary` على `--color-primary` + `--ink` على `--ground`/`--surface` + `--muted` على `--surface` + `--color-link` على `--surface` + `--sidebar-text` على `--sidebar-bg`، ويفشل تحت 4.5:1 (3:1 للنص ≥ 18px إن استُخدم). يُستدعى من `check-brand.sh`. **إن توفّر `npx playwright`** في بيئة البناء: شغّل axe على `/dashboard`، `/dashboard/invoices/[id]`، `/dashboard/accounting/accounts` وأرفق النتيجة في الملخص؛ وإلا اذكر أنه لم يُنفَّذ ووثّق الفحص البرمجي بديلًا (كما في التقرير قسم ز).
8. **الوضع الداكن:** لا واجهة تبديل الآن؛ فقط تأكد أن `:root[data-theme="dark"]` من tokens.css يعمل إن ضُبطت السمة يدويًا (لا تكسر شيئًا). تبديل المستخدم ← لاحقًا.

- اختبارات/تحقق: `check-brand.sh` صفر ألوان حرفية + diff صفر + التباين يمر؛ `next build` نظيف؛ `curl` 200 على الدخول ولوحة التحكم وفاتورة وسند وطباعتهما ودليل الحسابات؛ لقطة نصية من `layout.tsx` تُظهر `<img src="/brand/…">`؛ اختبار جيست/بنيوي بسيط لـ StatusBadge يغطي كل الحالات أعلاه بأسماء التوكنات.

commit: `Sprint 6.0.1-A: brand tokens, fonts, logo, favicon, StatusBadge, contrast check, no literal colors`

---

## B — الأرقام والشاشات الناقصة (التقرير قسم هـ بند 4، قسم ج، القاعدة 14 و19)

1. **`<Money>` في كل موضع من الـ11 المذكورة** (قسم هـ الجدول): لوحة التحكم، قائمة الفواتير (عبر `render` مخصص/نوع عمود `money` في `DataTable` مع `td.amount` LTR جدولي محاذاة يسار داخل RTL)، تفاصيل الفاتورة، تفاصيل القيد، تفاصيل السند، الصندوق (`max_balance`)، تفاصيل العميل (`credit_limit` + جدول الفواتير)، المنتجات (`unit_price`)، طباعة الفاتورة والسند — ثم `scripts/check-money.sh` يمر. الصيغة: فاصل آلاف، منزلتان، الأرقام لاتينية، رمز/كود العملة بعد الرقم (`1,234.50 SAR`)، السالب بعلامة `−` لا أقواس، الصفر `0.00`.
2. **صفحة «كشف حساب»** تحت التقارير (`/dashboard/reports/statement`): اختيار الطرف (بحث موحّد على العملاء/الموردين/الموظفين — يعرض الاسم والدور)، الفترة، ← جدول من `GET /api/parties/{id}/statement/?role&from&to` (رصيد افتتاحي، حركات بالتاريخ والرقم والبيان ومدين/دائن ورصيد جارٍ، رصيد ختامي، والفواتير المفتوحة للعميل) بـ `<Money>`، ورابط كل سطر إلى مستنده؛ زر طباعة → `/print/reports/statement?party=&role=&from=&to=` بنمط 5.6 (رأس الكيان، الشعار، عنوان «كشف حساب»، الطرف، الفترة، من أعدّه، توقيعان). صلاحية القراءة نفسها لتقرير دفتر الأستاذ.
3. **صندوق الاعتماد بشرط الصلاحية:** الرابط والعدّاد في `layout.tsx` يظهران فقط إذا كان للمستخدم صلاحية الاعتماد (المفتاح الفعلي المستخدم في `PendingApprovalsView`/`can_approve` — تحقق واستخدم نفسه؛ لا تخترع صلاحية جديدة).
4. **لوحة التحكم (3.18 صف 1):** `GET /api/dashboard/summary/` نقطة واحدة تعيد: `cash` (المنطق الحالي)، `receivables_open` (Σ`balance_fc` بالعملة الأساسية للفواتير غير المسدَّدة — بسعر الفاتورة)، `sales_month` (Σ`base_total` للفواتير المُصدرة هذا الشهر الميلادي)، `overdue_invoices` (عدد ومبلغ الفواتير `due_date < اليوم` وبرصيد)، `pending_approvals` (العدد من المنطق الموجود)، `payables_open: null` (يظهر «مع المشتريات — سبرنت 8» لا رقمًا مختلقًا — القاعدة 23). أربع بطاقات: النقدية · الذمم المدينة · مبيعات الشهر · تنبيهات (فواتير متأخرة + بانتظار اعتمادي) بروابط إلى شاشاتها، كلها بـ `<Money>`. (بطاقات الفترة المالية/الافتتاح/الدورية تُضاف في 6.9 كما هو مخطط.)
5. **`AttachmentPanel` على `journal-entries/[id]`** (القاعدة 14) + اختبار بنيوي يمسح كل `dashboard/**/[id]/page.tsx` ويفشل عند غيابه (مع قائمة استثناء فارغة الآن).
6. **مصطلح «الكيان القانوني»:** مفتاح `legalEntity` في `i18n.tsx` → «الشركة / الفرع»، والحقل ينتقل إلى القسم المطوي «متقدم» في النماذج التسعة مع قيمة افتراضية = الكيان الافتراضي للمستخدم (يبقى مخفيًا كليًا في الوضع المبسّط كما هو الآن). لا تغيير في الـ API.
7. **اختبار بنيوي عام للرسائل العربية** (إكمال بند 6.0-5): `tests/test_arabic_messages.py` يضيف مسحًا آليًا: لعيّنة ≥ 25 مسارًا (كل ViewSet مالي: فاتورة، قيد، سند، حساب، بنك، صندوق، عهدة، طرف، قاعدة اعتماد، كشف بنكي، طلب IBAN، جرد) يستدعي مسارًا يُنتج 400 (حمولة فارغة) و403 (مستخدم بلا صلاحية) و409 (حيث ينطبق) ويفحص أن نصوص `detail`/الحقول تحوي حرفًا عربيًا واحدًا على الأقل ولا تطابق `^[A-Za-z0-9 .,'_()-]+$`؛ استثناءات موثَّقة بقائمة صريحة فقط (مثل أسماء الحقول التقنية داخل المفاتيح).
8. **`frontend` لا يرث `.env` كاملًا** (دَين README #13): في `docker-compose*.yml` أزل `env_file` عن خدمة `frontend` وأبقِ `environment:` بالمتغيرات الثلاثة التي تحتاجها فقط؛ تحقق بـ `docker compose config` أن أسرار DB/MinIO لم تعد في بيئتها.

- اختبارات/تحقق: `check-money.sh` صفر؛ اختبار API لـ `dashboard/summary` (الأرقام تطابق حسابًا يدويًا على بيانات الاختبار، `payables_open` null، عزل مستأجر)؛ اختبار كشف الحساب عبر الواجهة (`curl` 200 + استجابة الـ API الموجودة)؛ اختبار الصلاحية على صندوق الاعتماد (مستخدم Viewer لا يرى الرابط — اختبار بنيوي/جيست على `layout`)؛ المسح العربي يمر؛ `next build` نظيف.

commit: `Sprint 6.0.1-B: Money everywhere, party statement screen + print, dashboard summary, gated approvals inbox, AttachmentPanel on JE, Arabic message sweep, frontend env isolation`

---

## C — الوثائق والكتالوج وإغلاق التقرير

1. **`README.md`:** شطب البندين المحلولين (`Plan.storage_mb` ✅ 5.1، Celery ✅ مهمتان تعملان) بنمط `~~…~~ ✅`، وإضافة دَين: «الوضع الداكن بلا واجهة تبديل».
2. **`docs/catalog/modules.json`:** `mobile_pwa` → `planned` مع `notes` («رفع الإيصالات من الكاميرا متاح عبر المتصفح؛ PWA/offline لاحقًا»)؛ `credit_balances` تبقى `in_progress` مع `notes` («الدفعة على الحساب ✅ 5.3؛ نقاط الولاء 13»). لا تغيير آخر.
3. **`docs/SYSTEM_ANALYSIS.md` §3.18:** أضف «المنتجات» في المبيعات، «فترات الضريبة» في المحاسبة، «الشركات الشقيقة» و«ترقيم المستندات» في الإعدادات، و«كشف حساب» في التقارير كـ ✅ (بُني 6.0.1)؛ صف لوحة التحكم ← البطاقات الأربع (بُنيت 6.0.1). سجل القرارات §11: «6.0.1: الشعار الرأسي المدمج هو شعار الشريط الجانبي؛ لا لون خارج tokens.css (فحص آلي)؛ كل مبلغ عبر Money (فحص آلي)».
4. **`docs/BRAND.md`:** §1 سطر «الاستخدام حسب المكان» ← الشريط الجانبي: `cps-logo-stacked-compact-white.svg`؛ الدخول: `cps-logo-stacked.svg`؛ الطباعة: الأفقي؛ و§5 البند 4 ← «الأصول في `frontend/public/brand/` ✅». (تعديل وثيقة هوية فقط — بموافقة محلل النظم المسبقة هنا.)
5. **`docs/reviews/PLAN_COMPLIANCE_1.md`:** أضف قسمًا ختاميًا «المتابعة بعد 6.0.1» بجدول: كل فجوة من قائمة العشرة ← الحالة الآن (✅/⏳ إداري) والدليل (commit/ملف)؛ الفجوات الإدارية (1، 3) تبقى ⏳ باسم المالك.
6. **`docs/UAT/sprint-6.0.1.md`** (قصير، 8 خطوات للواجهة: الشعار والألوان في الشريط الجانبي والأزرار، الشارات، الأرقام في فاتورة/قيد/سند/طباعة، كشف الحساب وطباعته، لوحة التحكم، صندوق الاعتماد بحساب Viewer، تسمية «الشركة / الفرع») بعمود نتيجة فارغ.
7. بعد آخر commit: `docker compose restart backend celery_worker frontend` + `make smoke` + `make check` (يشمل `check-brand`/`check-money`) — تُذكر النتائج في `docs/sprints/6.0.1-summary.md` (قصير: ما عُدّي، ما لم يكتمل، نتائج الفحوص، الخط المُعتمد).

commit: `Sprint 6.0.1-C: docs/catalog sync, compliance follow-up, UAT script, summary`

---

## معايير القبول (لا تُفتح 6.1 قبلها)

- `scripts/check-brand.sh` و`scripts/check-money.sh` يمران ومضافان إلى `make check` و`prebuild`؛ `frontend/src/styles/tokens.css` مطابق لـ `docs/brand/tokens.css`؛ صفر ألوان حرفية في `frontend/src` خارجه.
- الشعار ظاهر في الشريط الجانبي (كحلي) والدخول والطباعة؛ favicon مستبدل؛ الخطوط Tajawal/IBM Plex Sans Arabic محمّلة فعليًا (`next build` يُظهر تضمينها أو `@font-face` محلي موثَّق).
- كل الحالات في StatusBadge تمر تباين AA (برمجيًا)، وثلاث الحالات الراسبة في التقرير (draft/pending/posted) أصبحت من أزواج §2.5.
- 13/13 شاشة تعرض مبالغ عبر `<Money>`؛ كشف الحساب وطباعته يعملان؛ لوحة التحكم بأربع بطاقات صادقة؛ صندوق الاعتماد مشروط بالصلاحية؛ `journal-entries/[id]` يحمل `AttachmentPanel`؛ «الشركة / الفرع» في القسم المطوي.
- المسح العربي البنيوي (≥ 25 مسارًا) يمر؛ `frontend` لا يرى أسرار الخلفية.
- كل الاختبارات (≥ 362 + الجديدة) على Postgres حقيقي؛ `ruff` نظيف؛ `next build` نظيف؛ الاختبار البنيوي للعزل يعبر (`dashboard/summary` مصنَّف).
- الوثائق والكتالوج والتقرير محدَّثة؛ `docs/sprints/6.0.1-summary.md` مكتوب؛ restart + smoke + check ناجحة على Fatma.

**قواعد:** لا مساس بأي منطق محاسبي أو migration بيانات في هذه الكتلة (واجهة/تقارير قراءة/وثائق فقط)؛ لا تعديل على `docs/brand/tokens.css` أو `docs/CPS_MASTER_PLAN.md`؛ لا حذف بيانات؛ قرار غير واضح → اسأل. بعد إغلاقها: ابدأ 6.1 من `docs/prompts/sprint-6.md` مباشرة بلا انتظار.
