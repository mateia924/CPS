# سبرنت 5 — ملخص التنفيذ (تدريجي، يُحدَّث بعد كل كتلة)

**بدأ:** 2026-09-23. **لا كتلة 5.5 عمدًا** (الرقم محجوز لسبرنت "التسوية البنكية" المستقل).

**قرارات المالك (D1-D4، `docs/CFO_REVIEW_1.md` §8):** سُجِّلت في Decision
Log (`docs/SYSTEM_ANALYSIS.md` §11، 2026-09-23) — D1/D2/D3 معتمدة
وتُنفَّذ في هذا السبرنت (D1/D2 في الكتلة 5.7، D3 في جدول §5 نفسه)؛ D4
معتمدة كسياسة لكن **تُنفَّذ في سبرنت 6 لا الآن**.

---

## الكتلة 5.0 — ما بعد UAT سبرنت 4 + تمهيد المحرك ✅

**Commit:** `Sprint 5.0: post-UAT fixes, per-line currency, sequences and approval types for vouchers, backups`

- **منح الوصول للكيان تلقائيًا عند إنشاء مستخدم** (`CreateUserSerializer`،
  `apps/access/serializers.py`): مستأجر بكيان واحد (الوضع المبسّط) →
  الفرع الوحيد يُمنح تلقائيًا؛ مستأجر متعدد الكيانات → حقل
  `legal_entity_ids` اختياري، الافتراضي (لو حُذف) = كل الكيانات. يحل
  بالضبط الفخ الذي احتاج السكربت المؤقت لـ UAT سبرنت 4 تفاديه يدويًا.
  3 اختبارات جديدة (`test_rbac.py`).
- **`JournalLine.currency` + `JournalLine.exchange_rate`** (حقلان
  جديدان، migration 0014 + تعبئة بيانات 0015): كل سطر يحمل عملته وسعره
  الخاصين بدل افتراض عملة رأس القيد فقط — تمهيدًا لسندات 5.3 التي قد
  تخلط عملات على أسطر مختلفة من نفس القيد. `build_journal_lines_with_
  fx_rounding` يدعم الآن `debit_base`/`credit_base` صريحة (تجاوز `fc ×
  rate` — من كود النظام فقط، غير مُعرَّض عبر أي API) لسطور بسعر
  تاريخي (تخصيصات الفواتير في 5.3). سطور النظام (تقريب) تُبنى بعملة
  الكيان الأساسية صراحة لا عملة القيد. **قرار تفصيلي:** التوازن بعملة
  المعاملة (`debit_fc`=`credit_fc`) يُفرض فقط حين تشارك كل سطور القيد
  (بما فيها أي سطر تقريب مُضاف) نفس العملة — أول قيد يدوي متعدد العملات
  فعليًا (سندات 5.3) يتخطى هذا الفحص تلقائيًا لأنه لا عملة معاملة واحدة
  له أصلًا؛ توازن العملة الأساسية يبقى إلزاميًا دائمًا بلا استثناء. كل
  اختبارات 4.2/4.4 عدّت بلا أي تعديل على نتائجها.
- **`DocumentSequence`/`ApprovalRule.DocType`:** أنواع مستندات جديدة
  `voucher_receipt`/`voucher_payment`/`voucher_settlement` ببادئات
  افتراضية RV/PV/SV (نفس آلية 4.1)، وخيارات اعتماد مطابقة على
  `ApprovalRule` — جاهزة لمحرك السندات في 5.3، لا شاشة تستخدمها بعد.
- **`Invoice.due_date`/`paid_fc`/`balance_fc`/`payment_status`** (حقول
  جديدة، migration 0017 + تعبئة بيانات 0018 **مُعدَّلة بطلب المالك**):
  `due_date` يُحسب من `issue_date + payment_terms_days` (من
  `PartyRole.details` للعميل) عند الإنشاء/التعديل، `null` لو لا شروط
  سداد مسجّلة. `balance_fc`/`payment_status` يُعاد حسابهما من `paid_fc`
  في كل `recalculate_invoice` (يبقى 0 دائمًا لمسودة). **تعبئة الفواتير
  الموجودة:** `balance_fc = total` لكل فاتورة **غير ملغاة ولم يُعكس
  قيدها**؛ الفواتير الملغاة (`status=cancelled`) أو التي عُكس قيدها
  (`JournalEntry.source_type='invoice', status='reversed'`) تبقى
  `balance_fc=0` — كي لا تظهر كذمم مفتوحة في كشوف 5.4/أعمار الذمم
  لاحقًا رغم أنه لا شيء مستحق فعليًا عليها. تحقّق فعلي على القاعدة
  الحية: فاتورة INV-0001 الملغاة الوحيدة (total=550.00) → balance_fc=0
  بعد التعبئة؛ كل الفواتير الأخرى غير الملغاة → balance_fc=total.
- **إصلاح hydration الفرونت-إند:** `<Link><button>...</button></Link>`
  (تعشيش عنصر تفاعلي داخل عنصر تفاعلي، HTML غير صالح) في شاشتي العملاء
  والموظفين — بالضبط تحذير "1 Issue" في UAT 4. الحل: `<Link
  className="secondary">` مباشرة بدل تغليف `<button>`؛ CSS
  `button.secondary`/`button.primary` وُسِّعت لتشمل `a.secondary`/
  `a.primary` بنفس المظهر. `next build` نظيف (بلا هذا التحذير الآن).
- **`docker-compose.dev.yml` — درس 4.8:** أمر تشغيل `backend` في وضع
  dev أصبح `gunicorn ... --reload` (الإنتاج بلا تغيير، بلا reload) —
  تحقّق فعلي في سجلات الحاوية بعد إعادة الإنشاء: "Reloader is on. Use
  in development only!" لكل worker. **قاعدة دائمة الآن:**
  `docker compose restart backend celery_worker` ثم `make smoke` بعد
  آخر commit في أي سبرنت — نُفِّذت بالفعل في نهاية هذه الكتلة (انظر
  أدناه).
- **`scripts/backup.sh`** (`pg_dump` مضغوط → `/opt/cps-backups/`، خارج
  الحاويات، صلاحيات 700، احتفاظ 14 يومًا، cron يومي 03:00 مُثبَّت فعليًا
  على crontab المستخدم root) + **`scripts/restore.sh`** (استعادة إلى
  قاعدة منفصلة دائمًا افتراضيًا، لا تلمس القاعدة الحية). **نُفِّذ اختبار
  استعادة فعلي:** نسخة 56,782 بايت (أصلها 316,445 بايت، `gzip -t`
  نظيفة) → استُعيدت إلى `cps_restore_test` (44 جدولًا) → عدد صفوف
  `tenants_tenant` طابق القاعدة الحية (13=13) → قاعدة الاختبار حُذفت
  بعدها. وجهة سحابية (OCI Object Storage) متروكة كمتغير `CPS_BACKUP_
  CLOUD_BUCKET` غير مُفعَّل (إجراء إداري لاحق).
- **`scripts/smoke.sh`** (`make smoke`): تسجيل دخول حقيقي عبر HTTP
  (subdomain=fatma، حساب المحاسب التجريبي من UAT 4 — لا كلمة مرور
  Fatma المالكة الحقيقية، غير معروفة لهذه الجلسة) ← `/auth/me/` ←
  `/invoices/` ← `/journal-entries/trial_balance/` (تحقّق مدين=دائن).
  **نتيجة التشغيل الفعلي بعد إعادة إنشاء `backend`:**
  ```
  [smoke] login OK
  [smoke] /auth/me/ OK (200)
  [smoke] /invoices/ OK (200)
  [smoke] trial balance OK (debit=credit=29802.59)
  [smoke] ALL CHECKS PASSED
  ```

**ناتج `free -m` (قبل الكتلة 5.1):**
```
              total        used        free      shared  buff/cache   available
Mem:          15705        4379         942        4485       10383        6510
Swap:          8075        2340        5735
```
**قرار ClamAV:** الذاكرة الكلية 15,705MB ≥ 6,144MB (6GB) → **تفعيل
clamd حقيقي** في حاوية مستقلة على الشبكة الداخلية (لا
`ATTACHMENT_SCAN_ENABLED=false`).

**الاختبارات:** 235/235 (232 + 3 جديدة). `ruff check .` نظيف.
`manage.py check`/`makemigrations --check` نظيفان. `next build` نظيف.
`make smoke` ناجح على البيئة الحية بعد إعادة إنشاء `backend`.

**لم يكتمل:** لا شيء متبقٍ من نطاق 5.0.
