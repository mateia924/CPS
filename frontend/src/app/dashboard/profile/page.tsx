"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, fieldErrors, generalError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useLocale } from "@/lib/i18n";
import { formatDateTime } from "@/lib/date";
import { FormField } from "@/components/FormField";
import { WarningsBanner } from "@/components/WarningsBanner";
import type { MeResponse } from "@/lib/types";

interface Session {
  id: string;
  ip_address: string | null;
  user_agent: string;
  created_at: string;
}

// Sprint 6.8 (decision 17) + sprint 6.6.2 (items 1/2/4): "ملف المستخدم"
// — notify_approvals_email, change password, 2FA enrollment, and the
// active-sessions/logout-all-devices list. This screen is also where
// DashboardLayout forces a redirect while must_change_password or
// requires_2fa_setup is true — the backend's own middleware enforces
// the same gate on every other endpoint regardless.
export default function ProfilePage() {
  const { t } = useLocale();
  const { me, refreshMe, logout } = useAuth();
  const router = useRouter();

  const [notify, setNotify] = useState(true);
  const [notifyError, setNotifyError] = useState<string | null>(null);
  const [notifySaved, setNotifySaved] = useState(false);

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [passwordFieldErr, setPasswordFieldErr] = useState<Record<string, string>>({});
  const [passwordError, setPasswordError] = useState<string | null>(null);

  const [setupSecret, setSetupSecret] = useState<string | null>(null);
  const [qrCode, setQrCode] = useState<string | null>(null);
  const [confirmCode, setConfirmCode] = useState("");
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [backupCodes, setBackupCodes] = useState<string[] | null>(null);
  const [disablePassword, setDisablePassword] = useState("");
  const [disableError, setDisableError] = useState<string | null>(null);

  const [sessions, setSessions] = useState<Session[]>([]);

  useEffect(() => {
    if (me) setNotify(me.user.notify_approvals_email);
  }, [me]);

  useEffect(() => {
    api.get<Session[]>("/auth/sessions/").then(setSessions).catch(() => undefined);
  }, []);

  if (!me) return null;

  const forced = me.user.must_change_password || me.requires_2fa_setup;

  const onSaveNotify = async (e: React.FormEvent) => {
    e.preventDefault();
    setNotifyError(null);
    setNotifySaved(false);
    try {
      await api.patch<MeResponse>("/auth/me/", { notify_approvals_email: notify });
      await refreshMe();
      setNotifySaved(true);
    } catch (err) {
      setNotifyError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  const onChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setPasswordFieldErr({});
    setPasswordError(null);
    try {
      await api.post("/auth/change-password/", { current_password: currentPassword, new_password: newPassword });
      // Sprint 6.6.2 (item 4): the server just blacklisted this very
      // session's refresh token — there is nothing left to refreshMe()
      // with. Send the user back to a fresh login.
      logout();
      router.replace("/login?password_changed=1");
    } catch (err) {
      const body = (err as { body?: unknown }).body;
      setPasswordFieldErr(fieldErrors(body));
      setPasswordError(generalError(body, t("couldNotSave")));
    }
  };

  const onStartSetup = async () => {
    setConfirmError(null);
    setBackupCodes(null);
    const result = await api.post<{ secret: string; qr_code: string }>("/auth/2fa/setup/");
    setSetupSecret(result.secret);
    setQrCode(result.qr_code);
  };

  const onConfirmSetup = async (e: React.FormEvent) => {
    e.preventDefault();
    setConfirmError(null);
    try {
      const result = await api.post<{ backup_codes: string[] }>("/auth/2fa/confirm/", { code: confirmCode });
      setBackupCodes(result.backup_codes);
      setSetupSecret(null);
      setQrCode(null);
      setConfirmCode("");
      await refreshMe();
    } catch (err) {
      setConfirmError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  const onDisable = async (e: React.FormEvent) => {
    e.preventDefault();
    setDisableError(null);
    try {
      await api.post("/auth/2fa/disable/", { password: disablePassword });
      setDisablePassword("");
      setBackupCodes(null);
      await refreshMe();
    } catch (err) {
      setDisableError(generalError((err as { body?: unknown }).body, t("couldNotSave")));
    }
  };

  const onLogoutAllDevices = async () => {
    if (!window.confirm(t("logoutAllDevicesConfirm"))) return;
    await api.post("/auth/logout-all/");
    logout();
    router.replace("/login");
  };

  return (
    <div>
      <h1>{t("profileNav")}</h1>

      {forced && (
        <WarningsBanner
          warnings={[me.user.must_change_password ? t("forcedPasswordChangeNotice") : t("forced2faSetupNotice")]}
          variant="error"
        />
      )}

      {!forced && (
        <div className="card">
          <p>{me.user.first_name} {me.user.last_name} — {me.user.email}</p>
          <form onSubmit={onSaveNotify}>
            <div className="form-field" style={{ marginTop: "0.5rem" }}>
              <label>
                <input type="checkbox" checked={notify} onChange={(e) => setNotify(e.target.checked)} />{/* form-ok: boolean toggle, never returns a field-level API error */}{" "}
                {t("notifyApprovalsEmail")}
              </label>
            </div>
            <br />
            <WarningsBanner warnings={notifyError ? [notifyError] : []} variant="error" />
            {notifySaved && <p style={{ color: "var(--success)" }}>✓</p>}
            <button className="primary" type="submit">{t("saveChanges")}</button>
          </form>
        </div>
      )}

      <div className="card">
        <h3>{t("changePasswordTitle")}</h3>
        <form onSubmit={onChangePassword}>
          <FormField name="current_password" label={t("currentPassword")} required error={passwordFieldErr.current_password}>
            <input
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              required
            />
          </FormField>
          <FormField name="new_password" label={t("newPassword")} required error={passwordFieldErr.new_password}>
            <input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
              minLength={12}
            />
          </FormField>
          <WarningsBanner warnings={passwordError ? [passwordError] : []} variant="error" />
          <button className="primary" type="submit">{t("changePasswordTitle")}</button>
        </form>
      </div>

      <div className="card">
        <h3>{t("twoFactorTitle")}</h3>
        {me.user.totp_confirmed ? (
          <>
            <p>{t("twoFactorEnabled")}</p>
            <form onSubmit={onDisable}>
              <FormField name="disable_password" label={t("twoFactorDisableConfirmPassword")} required>
                <input type="password" value={disablePassword} onChange={(e) => setDisablePassword(e.target.value)} required />
              </FormField>
              <WarningsBanner warnings={disableError ? [disableError] : []} variant="error" />
              <button className="secondary" type="submit">{t("twoFactorDisableButton")}</button>
            </form>
          </>
        ) : backupCodes ? (
          <div>
            <h4>{t("twoFactorBackupCodesTitle")}</h4>
            <p>{t("twoFactorBackupCodesHint")}</p>
            <ul>
              {backupCodes.map((code) => (
                <li key={code}><code>{code}</code></li>
              ))}
            </ul>
          </div>
        ) : setupSecret ? (
          <form onSubmit={onConfirmSetup}>
            <p>{t("twoFactorScanQr")}</p>
            {qrCode && <img src={qrCode} alt="QR" style={{ width: 200, height: 200 }} />}
            <p><code>{setupSecret}</code></p>
            <FormField name="code" label={t("twoFactorConfirmCode")} required error={confirmError ?? undefined}>
              <input value={confirmCode} onChange={(e) => setConfirmCode(e.target.value)} required autoFocus />
            </FormField>
            <button className="primary" type="submit">{t("twoFactorConfirmButton")}</button>
          </form>
        ) : (
          <>
            <p>{t("twoFactorDisabled")}</p>
            <button className="primary" type="button" onClick={onStartSetup}>{t("twoFactorSetupStart")}</button>
          </>
        )}
      </div>

      {!forced && (
        <div className="card">
          <h3>{t("activeSessionsTitle")}</h3>
          {sessions.length === 0 ? (
            <p>{t("noActiveSessions")}</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>{t("sessionCreatedAt")}</th>
                  <th>IP</th>
                </tr>
              </thead>
              <tbody>
                {sessions.map((s) => (
                  <tr key={s.id}>
                    <td>{formatDateTime(s.created_at)}</td>
                    <td>{s.ip_address ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <button className="secondary" type="button" style={{ marginTop: "0.5rem" }} onClick={onLogoutAllDevices}>
            {t("logoutAllDevices")}
          </button>
        </div>
      )}
    </div>
  );
}
