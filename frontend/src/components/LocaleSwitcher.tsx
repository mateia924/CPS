"use client";

import { useLocale } from "@/lib/i18n";

export function LocaleSwitcher() {
  const { locale, setLocale } = useLocale();
  return (
    <button
      className="secondary"
      type="button"
      onClick={() => setLocale(locale === "ar" ? "en" : "ar")}
    >
      {locale === "ar" ? "English" : "العربية"}
    </button>
  );
}
