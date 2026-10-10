"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useLocale } from "@/lib/i18n";
import { LocaleSwitcher } from "@/components/LocaleSwitcher";
import { FormField } from "@/components/FormField";
import { WarningsBanner } from "@/components/WarningsBanner";
import { api, ApiError, fieldErrors, generalError } from "@/lib/api";
import { subdomainFromHostname } from "@/lib/subdomain";

const FALLBACK_ERROR: Record<"ar" | "en", string> = {
  ar: "حدث خطأ غير متوقع. حاول مرة أخرى.",
  en: "Something went wrong. Please try again.",
};

export default function ResetPasswordPage() {
  const { t, locale } = useLocale();

  const [token, setToken] = useState<string | null>(null);
  const [tokenMissing, setTokenMissing] = useState(false);
  const [subdomain, setSubdomain] = useState<string | null>(null);
  const [newPassword, setNewPassword] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [generalErrorText, setGeneralErrorText] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);

  // Sprint 7.2.9 (R-7.2.9.5/.6): read via window.location directly, not
  // useSearchParams — same reasoning as login/page.tsx's own
  // session_expired flag (sprint 6.5.10, UAT note 7): this page needs
  // no Suspense boundary just for a one-time read on mount. The
  // subdomain always comes from the HOST this link was built for
  // (apps.accounts.services.build_tenant_url) — never a manual field,
  // since a per-tenant link already carries it.
  useEffect(() => {
    const fromQuery = new URLSearchParams(window.location.search).get("token");
    if (!fromQuery) {
      setTokenMissing(true);
      return;
    }
    setToken(fromQuery);
    setSubdomain(subdomainFromHostname(window.location.hostname));
  }, []);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrors({});
    setGeneralErrorText(null);
    setLoading(true);
    try {
      await api.post(
        "/auth/password-reset/confirm/",
        { subdomain, token, new_password: newPassword },
        false
      );
      setDone(true);
    } catch (err) {
      if (err instanceof ApiError) {
        const fields = fieldErrors(err.body);
        setErrors(fields);
        if (fields.token) {
          setGeneralErrorText(t("resetTokenInvalid"));
        } else if (Object.keys(fields).length === 0 || fields.non_field_errors) {
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
        <h1>{t("resetPasswordTitle")}</h1>
        <LocaleSwitcher />
      </div>
      {tokenMissing ? (
        <>
          <WarningsBanner warnings={[t("resetTokenMissing")]} variant="error" />
          <p style={{ marginTop: "1.5rem" }}>
            <Link href="/forgot-password">{t("forgotPassword")}</Link>
          </p>
        </>
      ) : done ? (
        <>
          <WarningsBanner warnings={[t("resetPasswordSuccess")]} />
          <p style={{ marginTop: "1.5rem" }}>
            <Link href="/login">{t("backToLogin")}</Link>
          </p>
        </>
      ) : (
        <form onSubmit={onSubmit}>
          <FormField name="new_password" label={t("newPassword")} required error={errors.new_password}>
            <input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
              autoFocus
            />
          </FormField>
          <WarningsBanner warnings={generalErrorText ? [generalErrorText] : []} variant="error" />
          <button className="primary" type="submit" disabled={loading || !token}>
            {loading ? "..." : t("resetPasswordSubmit")}
          </button>
        </form>
      )}
    </div>
  );
}
