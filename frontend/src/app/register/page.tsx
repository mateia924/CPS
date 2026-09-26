"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { useLocale } from "@/lib/i18n";
import { LocaleSwitcher } from "@/components/LocaleSwitcher";
import { FormField } from "@/components/FormField";
import { WarningsBanner } from "@/components/WarningsBanner";
import { ApiError, fieldErrors, generalError } from "@/lib/api";

const FALLBACK_ERROR: Record<"ar" | "en", string> = {
  ar: "حدث خطأ غير متوقع. حاول مرة أخرى.",
  en: "Something went wrong. Please try again.",
};

export default function RegisterPage() {
  const { register } = useAuth();
  const { t, locale } = useLocale();
  const router = useRouter();

  const [companyName, setCompanyName] = useState("");
  const [subdomain, setSubdomain] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [generalErrorText, setGeneralErrorText] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrors({});
    setGeneralErrorText(null);
    setLoading(true);
    try {
      await register({
        company_name: companyName,
        subdomain,
        email,
        password,
        first_name: firstName,
        last_name: lastName,
      });
      router.replace("/dashboard");
    } catch (err) {
      if (err instanceof ApiError) {
        const fields = fieldErrors(err.body);
        setErrors(fields);
        // Only show a top-level message when there's no field to
        // attach it to (e.g. a network error, or a non_field_errors-only
        // response) — otherwise the per-field text under each input is
        // the whole story and a duplicate banner is just noise.
        if (Object.keys(fields).length === 0 || fields.non_field_errors) {
          setGeneralErrorText(generalError(err.body, FALLBACK_ERROR[locale]));
        }
      } else {
        setGeneralErrorText(FALLBACK_ERROR[locale]);
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="container">
      <img src="/brand/cps-logo-stacked.svg" alt="CPS" className="brand-lockup" style={{ width: 200 }} />
      <div className="topbar">
        <h1>{t("appName")}</h1>
        <LocaleSwitcher />
      </div>
      <form onSubmit={onSubmit}>
        <FormField name="company_name" label={t("companyName")} required error={errors.company_name}>
          <input value={companyName} onChange={(e) => setCompanyName(e.target.value)} required />
        </FormField>
        <FormField name="subdomain" label={t("subdomain")} required error={errors.subdomain}>
          <input value={subdomain} onChange={(e) => setSubdomain(e.target.value)} required />
        </FormField>
        <FormField name="first_name" label={t("firstName")} error={errors.first_name}>
          <input value={firstName} onChange={(e) => setFirstName(e.target.value)} />
        </FormField>
        <FormField name="last_name" label={t("lastName")} error={errors.last_name}>
          <input value={lastName} onChange={(e) => setLastName(e.target.value)} />
        </FormField>
        <FormField name="email" label={t("email")} required error={errors.email}>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </FormField>
        <FormField name="password" label={t("password")} required error={errors.password}>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </FormField>
        <WarningsBanner warnings={generalErrorText ? [generalErrorText] : []} variant="error" />
        <button className="primary" type="submit" disabled={loading}>
          {loading ? "..." : t("register")}
        </button>
      </form>
      <p style={{ marginTop: "1.5rem" }}>
        {t("alreadyHaveAccount")} <Link href="/login">{t("login")}</Link>
      </p>
    </div>
  );
}
