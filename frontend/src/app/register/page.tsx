"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { useLocale } from "@/lib/i18n";
import { LocaleSwitcher } from "@/components/LocaleSwitcher";
import { ApiError } from "@/lib/api";

export default function RegisterPage() {
  const { register } = useAuth();
  const { t } = useLocale();
  const router = useRouter();

  const [companyName, setCompanyName] = useState("");
  const [subdomain, setSubdomain] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
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
      setError(err instanceof ApiError ? JSON.stringify(err.body) : "Registration failed");
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
          <label>{t("companyName")}</label>
          <input value={companyName} onChange={(e) => setCompanyName(e.target.value)} required />
        </div>
        <div className="form-field">
          <label>{t("subdomain")}</label>
          <input value={subdomain} onChange={(e) => setSubdomain(e.target.value)} required />
        </div>
        <div className="form-field">
          <label>{t("firstName")}</label>
          <input value={firstName} onChange={(e) => setFirstName(e.target.value)} />
        </div>
        <div className="form-field">
          <label>{t("lastName")}</label>
          <input value={lastName} onChange={(e) => setLastName(e.target.value)} />
        </div>
        <div className="form-field">
          <label>{t("email")}</label>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </div>
        <div className="form-field">
          <label>{t("password")}</label>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </div>
        {error && <p className="error-text">{error}</p>}
        <button className="primary" type="submit" disabled={loading}>
          {t("register")}
        </button>
      </form>
      <p style={{ marginTop: "1.5rem" }}>
        {t("alreadyHaveAccount")} <Link href="/login">{t("login")}</Link>
      </p>
    </div>
  );
}
