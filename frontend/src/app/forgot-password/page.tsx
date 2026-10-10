"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useLocale } from "@/lib/i18n";
import { LocaleSwitcher } from "@/components/LocaleSwitcher";
import { FormField } from "@/components/FormField";
import { WarningsBanner } from "@/components/WarningsBanner";
import { api, ApiError, fieldErrors, generalError } from "@/lib/api";
import { lastRememberedSubdomain, subdomainFromHostname } from "@/lib/subdomain";

const FALLBACK_ERROR: Record<"ar" | "en", string> = {
  ar: "حدث خطأ غير متوقع. حاول مرة أخرى.",
  en: "Something went wrong. Please try again.",
};

export default function ForgotPasswordPage() {
  const { t, locale } = useLocale();

  const [subdomain, setSubdomain] = useState("");
  const [subdomainFromHost, setSubdomainFromHost] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [generalErrorText, setGeneralErrorText] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  // Sprint 7.2.9 (§8.9, R-7.2.9.3): the response is identical whether
  // or not an account exists — this screen has nothing to branch on
  // besides "the request was accepted" vs. "the input itself was
  // malformed" (handled in the catch block below).
  const [sent, setSent] = useState(false);

  useEffect(() => {
    const fromHost = subdomainFromHostname(window.location.hostname);
    if (fromHost) {
      setSubdomainFromHost(fromHost);
      setSubdomain(fromHost);
      return;
    }
    const remembered = lastRememberedSubdomain();
    if (remembered) setSubdomain(remembered);
  }, []);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrors({});
    setGeneralErrorText(null);
    setLoading(true);
    try {
      await api.post("/auth/password-reset/request/", { subdomain, email }, false);
      setSent(true);
    } catch (err) {
      if (err instanceof ApiError) {
        const fields = fieldErrors(err.body);
        setErrors(fields);
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
        <h1>{t("forgotPasswordTitle")}</h1>
        <LocaleSwitcher />
      </div>
      {sent ? (
        <>
          <WarningsBanner warnings={[t("resetRequestSent")]} />
          <p style={{ marginTop: "1.5rem" }}>
            <Link href="/login">{t("backToLogin")}</Link>
          </p>
        </>
      ) : (
        <form onSubmit={onSubmit}>
          <p style={{ color: "var(--muted)" }}>{t("forgotPasswordInstructions")}</p>
          {subdomainFromHost ? (
            <p style={{ margin: "0 0 1rem" }}>
              {t("companyLabel")}: <strong>{subdomainFromHost}</strong>
            </p>
          ) : (
            <FormField name="subdomain" label={t("companyUrlName")} required error={errors.subdomain}>
              <input
                value={subdomain}
                onChange={(e) => setSubdomain(e.target.value)}
                placeholder="fatma"
                required
              />
            </FormField>
          )}
          <FormField name="email" label={t("email")} required error={errors.email}>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </FormField>
          <WarningsBanner warnings={generalErrorText ? [generalErrorText] : []} variant="error" />
          <button className="primary" type="submit" disabled={loading}>
            {loading ? "..." : t("sendResetLink")}
          </button>
          <p style={{ marginTop: "1.5rem" }}>
            <Link href="/login">{t("backToLogin")}</Link>
          </p>
        </form>
      )}
    </div>
  );
}
