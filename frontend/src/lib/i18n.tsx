"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";

export type Locale = "ar" | "en";

const dictionaries: Record<Locale, Record<string, string>> = {
  ar: {
    appName: "CPS",
    login: "تسجيل الدخول",
    register: "تسجيل شركة جديدة",
    subdomain: "النطاق الفرعي",
    email: "البريد الإلكتروني",
    password: "كلمة المرور",
    companyName: "اسم الشركة",
    firstName: "الاسم الأول",
    lastName: "اسم العائلة",
    submit: "إرسال",
    logout: "تسجيل الخروج",
    dashboard: "لوحة التحكم",
    customers: "العملاء",
    products: "المنتجات",
    invoices: "الفواتير",
    name: "الاسم",
    phone: "الهاتف",
    taxNumber: "الرقم الضريبي",
    address: "العنوان",
    add: "إضافة",
    sku: "الرمز",
    unitPrice: "سعر الوحدة",
    taxRate: "نسبة الضريبة %",
    active: "نشط",
    number: "الرقم",
    status: "الحالة",
    issueDate: "تاريخ الإصدار",
    total: "الإجمالي",
    subtotal: "الإجمالي قبل الضريبة",
    taxTotal: "إجمالي الضريبة",
    customer: "العميل",
    createInvoice: "إنشاء فاتورة",
    quantity: "الكمية",
    product: "المنتج",
    addLine: "إضافة بند",
    issue: "اعتماد الفاتورة",
    draft: "مسودة",
    issued: "معتمدة",
    paid: "مدفوعة",
    cancelled: "ملغاة",
    noSubdomainYet: "أول مرة؟",
    createAccount: "أنشئ حساب شركتك",
    alreadyHaveAccount: "لديك حساب بالفعل؟",
    welcome: "مرحبًا",
    organization: "الهيكل التنظيمي",
    costCenters: "مراكز التكلفة",
    rolesAndUsers: "الأدوار والمستخدمون",
    code: "الكود",
    type: "النوع",
    parent: "الأب",
    none: "بدون",
    advanced: "متقدم",
    holding: "قابضة",
    company: "شركة",
    branch: "فرع",
    department: "إدارة",
    vehicle: "سيارة",
    warehouse: "مستودع",
    employee: "موظف",
    project: "مشروع",
    general: "عام",
    deactivate: "تعطيل",
    inactive: "معطّل",
    legalEntity: "الكيان القانوني",
    costCenter: "مركز التكلفة",
    distributeCostCenters: "توزيع على مراكز تكلفة",
    roles: "الأدوار",
    entities: "الكيانات المسموحة",
    save: "حفظ",
    countryCode: "رمز الدولة",
    currency: "العملة",
    permissions: "الصلاحيات",
    search: "بحث...",
    showInactive: "إظهار المعطّل",
    edit: "تعديل",
    activate: "تفعيل",
    cancel: "إلغاء",
    noData: "لا توجد بيانات لعرضها.",
    confirmDeactivate: "هل أنت متأكد من تعطيل هذا العنصر؟",
    confirmActivate: "هل تريد إعادة تفعيل هذا العنصر؟",
    void: "إلغاء الفاتورة",
    confirmVoid: "سيتم إلغاء الفاتورة وترحيل قيد عكسي متوازن. متابعة؟",
    editInvoice: "تعديل الفاتورة",
    saveChanges: "حفظ التعديلات",
  },
  en: {
    appName: "CPS",
    login: "Log in",
    register: "Register a new company",
    subdomain: "Subdomain",
    email: "Email",
    password: "Password",
    companyName: "Company name",
    firstName: "First name",
    lastName: "Last name",
    submit: "Submit",
    logout: "Log out",
    dashboard: "Dashboard",
    customers: "Customers",
    products: "Products",
    invoices: "Invoices",
    name: "Name",
    phone: "Phone",
    taxNumber: "Tax number",
    address: "Address",
    add: "Add",
    sku: "SKU",
    unitPrice: "Unit price",
    taxRate: "Tax rate %",
    active: "Active",
    number: "Number",
    status: "Status",
    issueDate: "Issue date",
    total: "Total",
    subtotal: "Subtotal",
    taxTotal: "Tax total",
    customer: "Customer",
    createInvoice: "Create invoice",
    quantity: "Quantity",
    product: "Product",
    addLine: "Add line",
    issue: "Issue invoice",
    draft: "Draft",
    issued: "Issued",
    paid: "Paid",
    cancelled: "Cancelled",
    noSubdomainYet: "First time?",
    createAccount: "Create your company account",
    alreadyHaveAccount: "Already have an account?",
    welcome: "Welcome",
    organization: "Organization structure",
    costCenters: "Cost centers",
    rolesAndUsers: "Roles & users",
    code: "Code",
    type: "Type",
    parent: "Parent",
    none: "None",
    advanced: "Advanced",
    holding: "Holding",
    company: "Company",
    branch: "Branch",
    department: "Department",
    vehicle: "Vehicle",
    warehouse: "Warehouse",
    employee: "Employee",
    project: "Project",
    general: "General",
    deactivate: "Deactivate",
    inactive: "Inactive",
    legalEntity: "Legal entity",
    costCenter: "Cost center",
    distributeCostCenters: "Distribute across cost centers",
    roles: "Roles",
    entities: "Allowed entities",
    save: "Save",
    countryCode: "Country code",
    currency: "Currency",
    permissions: "Permissions",
    search: "Search...",
    showInactive: "Show inactive",
    edit: "Edit",
    activate: "Activate",
    cancel: "Cancel",
    noData: "No data to show.",
    confirmDeactivate: "Are you sure you want to deactivate this item?",
    confirmActivate: "Reactivate this item?",
    void: "Void invoice",
    confirmVoid: "This will void the invoice and post a balanced reversing entry. Continue?",
    editInvoice: "Edit invoice",
    saveChanges: "Save changes",
  },
};

interface LocaleContextValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: string) => string;
  dir: "rtl" | "ltr";
}

const LocaleContext = createContext<LocaleContextValue | null>(null);

export function LocaleProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>("ar");

  useEffect(() => {
    const stored = window.localStorage.getItem("cps_locale") as Locale | null;
    if (stored === "ar" || stored === "en") {
      setLocaleState(stored);
    }
  }, []);

  const dir = locale === "ar" ? "rtl" : "ltr";

  useEffect(() => {
    document.documentElement.lang = locale;
    document.documentElement.dir = dir;
  }, [locale, dir]);

  const setLocale = (next: Locale) => {
    setLocaleState(next);
    window.localStorage.setItem("cps_locale", next);
  };

  const t = useMemo(() => {
    const dict = dictionaries[locale];
    return (key: string) => dict[key] ?? key;
  }, [locale]);

  return (
    <LocaleContext.Provider value={{ locale, setLocale, t, dir }}>
      {children}
    </LocaleContext.Provider>
  );
}

export function useLocale() {
  const ctx = useContext(LocaleContext);
  if (!ctx) {
    throw new Error("useLocale must be used inside LocaleProvider");
  }
  return ctx;
}
