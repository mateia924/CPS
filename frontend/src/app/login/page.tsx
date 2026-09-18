"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { useLocale } from "@/lib/i18n";
import { LocaleSwitcher } from "@/components/LocaleSwitcher";
import { ApiError, fieldErrors, generalError } from "@/lib/api";

const FALLBACK_ERROR: Record<"ar" | "en", string> = {
  ar: "حدث خطأ غير متوقع. حاول مرة أخرى.",
  en: "Something went wrong. Please try again.",
};

export default function LoginPage() {
  const { login } = useAuth();
  const { t, locale } = useLocale();
  const router = useRouter();

  const [subdomain, setSubdomain] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [generalErrorText, setGeneralErrorText] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrors({});
    setGeneralErrorText(null);
    setLoading(true);
    try {
      await login(subdomain, email, password);
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
      <div className="topbar">
        <h1>{t("appName")}</h1>
        <LocaleSwitcher />
      </div>
      <form onSubmit={onSubmit}>
        <div className="form-field">
          <label>{t("subdomain")}</label>
          <input value={subdomain} onChange={(e) => setSubdomain(e.target.value)} required />
          {errors.subdomain && <p className="error-text">{errors.subdomain}</p>}
        </div>
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
