"use client";

import { useEffect, useState } from "react";
import { api, generalError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useLocale } from "@/lib/i18n";
import { WarningsBanner } from "@/components/WarningsBanner";
import type { MeResponse } from "@/lib/types";

// Sprint 6.8 (decision 17): "ملف المستخدم" — the one self-service
// setting a user has today (notify_approvals_email). Deliberately not a
// general profile-editor (name/email/password changes stay out of
// scope for this block).
export default function ProfilePage() {
  const { t } = useLocale();
  const { me, refreshMe } = useAuth();
  const [notify, setNotify] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (me) setNotify(me.user.notify_approvals_email);
  }, [me]);

  if (!me) return null;

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSaved(false);
    try {
      await api.patch<MeResponse>("/auth/me/", { notify_approvals_email: notify });
      await refreshMe();
      setSaved(true);
    } catch (err) {
      setError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  return (
    <div>
      <h1>{t("profileNav")}</h1>
      <div className="card">
        <p>{me.user.first_name} {me.user.last_name} — {me.user.email}</p>
        <form onSubmit={onSubmit}>
          <div className="form-field" style={{ marginTop: "0.5rem" }}>
            <label>
              <input type="checkbox" checked={notify} onChange={(e) => setNotify(e.target.checked)} />{/* form-ok: boolean toggle, never returns a field-level API error */}{" "}
              {t("notifyApprovalsEmail")}
            </label>
          </div>

          <br />
          <WarningsBanner warnings={error ? [error] : []} variant="error" />
          {saved && <p style={{ color: "var(--success)" }}>✓</p>}
          <button className="primary" type="submit">{t("saveChanges")}</button>
        </form>
      </div>
    </div>
  );
}
