"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { usePlatformAuth } from "@/lib/platform-auth-context";
import { useLocale } from "@/lib/i18n";
import { LocaleSwitcher } from "@/components/LocaleSwitcher";
import { ApiError, fieldErrors, generalError } from "@/lib/api";

const FALLBACK_ERROR: Record<"ar" | "en", string> = {
  ar: "حدث خطأ غير متوقع. حاول مرة أخرى.",
  en: "Something went wrong. Please try again.",
};

export default function PlatformLoginPage() {
  const { login } = usePlatformAuth();
  const { t, locale } = useLocale();
  const router = useRouter();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [step, setStep] = useState<"credentials" | "code">("credentials");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [generalErrorText, setGeneralErrorText] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const onSubmitCredentials = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrors({});
    setGeneralErrorText(null);
    setLoading(true);
    try {
      const result = await login(email, password);
      if (result.codeRequired) {
        setStep("code");
      } else {
        router.replace("/platform/dashboard/tenants");
      }
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

  const onSubmitCode = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrors({});
    setGeneralErrorText(null);
    setLoading(true);
    try {
      await login(email, password, totpCode);
      router.replace("/platform/dashboard/tenants");
    } catch (err) {
      if (err instanceof ApiError) {
        setGeneralErrorText(generalError(err.body, FALLBACK_ERROR[locale]));
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
        <h1>{t("platformTitle")}</h1>
        <LocaleSwitcher />
      </div>

      {step === "credentials" && (
        <form onSubmit={onSubmitCredentials}>
          <div className="form-field">
            <label>{t("email")}</label>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
            {errors.email && <p className="error-text">{errors.email}</p>}
          </div>
          <div className="form-field">
            <label>{t("password")}</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
            {errors.password && <p className="error-text">{errors.password}</p>}
          </div>
          {generalErrorText && <p className="error-text">{generalErrorText}</p>}
          <button className="primary" type="submit" disabled={loading}>
            {loading ? "..." : t("continueLabel")}
          </button>
        </form>
      )}

      {step === "code" && (
        <form onSubmit={onSubmitCode}>
          <p style={{ color: "var(--muted)", fontSize: "0.9rem" }}>{t("totpCodeHint")}</p>
          <div className="form-field">
            <label>{t("totpCode")}</label>
            <input
              value={totpCode}
              onChange={(e) => setTotpCode(e.target.value)}
              autoFocus
              required
            />
          </div>
          {generalErrorText && <p className="error-text">{generalErrorText}</p>}
          <button className="primary" type="submit" disabled={loading}>
            {loading ? "..." : t("login")}
          </button>
          <button
            className="secondary"
            type="button"
            style={{ marginInlineStart: "0.5rem" }}
            onClick={() => {
              setStep("credentials");
              setTotpCode("");
              setGeneralErrorText(null);
            }}
          >
            {t("back")}
          </button>
        </form>
      )}
    </div>
  );
}
