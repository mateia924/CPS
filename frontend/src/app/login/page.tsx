"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { useLocale } from "@/lib/i18n";
import { LocaleSwitcher } from "@/components/LocaleSwitcher";
import { ApiError, fieldErrors, generalError } from "@/lib/api";
import { lastRememberedSubdomain, rememberSubdomain, subdomainFromHostname } from "@/lib/subdomain";

const APP_DOMAIN = process.env.NEXT_PUBLIC_APP_DOMAIN || "localhost:3000";

const FALLBACK_ERROR: Record<"ar" | "en", string> = {
  ar: "حدث خطأ غير متوقع. حاول مرة أخرى.",
  en: "Something went wrong. Please try again.",
};

export default function LoginPage() {
  const { login } = useAuth();
  const { t, locale } = useLocale();
  const router = useRouter();

  const [subdomain, setSubdomain] = useState("");
  const [subdomainFromHost, setSubdomainFromHost] = useState<string | null>(null);
  const [editingSubdomain, setEditingSubdomain] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [generalErrorText, setGeneralErrorText] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // Sprint 6.9.1 (item I): the host itself may already carry the
  // company identifier (production: fatma.app.cps-erp.com) — this dev
  // host never does, so this stays a no-op fallback to the last
  // remembered value instead.
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
      await login(subdomain, email, password);
      rememberSubdomain(subdomain);
      router.replace("/dashboard");
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
        <h1>{t("login")}</h1>
        <LocaleSwitcher />
      </div>
      <form onSubmit={onSubmit}>
        {subdomainFromHost && !editingSubdomain ? (
          <p style={{ margin: "0 0 1rem" }}>
            {t("companyLabel")}: <strong>{subdomainFromHost}</strong>{" "}
            <button type="button" className="secondary" onClick={() => setEditingSubdomain(true)}>
              {t("changeCompany")}
            </button>
          </p>
        ) : (
          <div className="form-field">
            <label>{t("companyUrlName")}</label>
            <input
              value={subdomain}
              onChange={(e) => setSubdomain(e.target.value)}
              placeholder="fatma"
              required
            />
            {subdomain && (
              <p style={{ color: "var(--muted)", fontSize: "0.85rem" }}>
                {subdomain}.{APP_DOMAIN}
              </p>
            )}
            {errors.subdomain && <p className="error-text">{errors.subdomain}</p>}
          </div>
        )}
        <div className="form-field">
          <label>{t("email")}</label>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          {errors.email && <p className="error-text">{errors.email}</p>}
        </div>
        <div className="form-field">
          <label>{t("password")}</label>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          {errors.password && <p className="error-text">{errors.password}</p>}
        </div>
        {generalErrorText && <p className="error-text">{generalErrorText}</p>}
        <button className="primary" type="submit" disabled={loading}>
          {loading ? "..." : t("login")}
        </button>
      </form>
      <p style={{ marginTop: "1.5rem" }}>
        {t("noSubdomainYet")} <Link href="/register">{t("createAccount")}</Link>
      </p>
    </div>
  );
}
