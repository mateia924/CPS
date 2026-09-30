"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { api, ApiError, generalError } from "./api";
import { useLocale } from "./i18n";
import type { MeResponse } from "./types";

export interface Tenant {
  id: string;
  name: string;
  subdomain: string;
  status?: "trial" | "active" | "past_due" | "suspended" | "archived";
  past_due_since?: string | null;
}

export interface User {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  role: string;
}

interface AuthPayload {
  tenant: Tenant;
  user: User;
  access: string;
  refresh: string;
  // Sprint 6.6.2 (items 1/2): both also come back from /auth/me/ on
  // every later load — kept here too so the login page can redirect
  // straight to the right forced screen without waiting on a second
  // round trip.
  must_change_password: boolean;
  requires_2fa_setup: boolean;
}

interface AuthContextValue {
  tenant: Tenant | null;
  user: User | null;
  me: MeResponse | null;
  /** Set when the last /auth/me/ attempt failed for a reason other
   * than an invalid/expired token (network blip, backend 500, etc.) —
   * `me` stays whatever it was (null on first load, still-good stale
   * data on a later refresh). The dashboard shows this instead of
   * silently rendering a menu with every gated section missing, since
   * `me === null` is otherwise indistinguishable from "no permissions". */
  meError: string | null;
  isReady: boolean;
  login: (
    subdomain: string,
    email: string,
    password: string,
    totpCode?: string
  ) => Promise<{ must_change_password: boolean; requires_2fa_setup: boolean }>;
  register: (payload: {
    company_name: string;
    subdomain: string;
    email: string;
    password: string;
    first_name?: string;
    last_name?: string;
  }) => Promise<void>;
  logout: () => void;
  refreshMe: () => Promise<MeResponse | null>;
  hasPermission: (code: string) => boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function persist(payload: AuthPayload) {
  window.localStorage.setItem("cps_access", payload.access);
  window.localStorage.setItem("cps_refresh", payload.refresh);
  window.localStorage.setItem("cps_user", JSON.stringify(payload.user));
  window.localStorage.setItem("cps_tenant", JSON.stringify(payload.tenant));
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const { t } = useLocale();
  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [me, setMe] = useState<MeResponse | null>(null);
  const [meError, setMeError] = useState<string | null>(null);
  const [isReady, setIsReady] = useState(false);

  const logout = () => {
    // Sprint 6 (block 6.0, item 6): blacklist the refresh token
    // server-side so it can't be replayed after "logout" — best-effort
    // (fire-and-forget): local state is cleared either way, since the
    // user's own session must end locally even if the network call
    // fails or the token was already expired.
    const refresh = window.localStorage.getItem("cps_refresh");
    if (refresh) {
      api.post("/auth/logout/", { refresh }).catch(() => {});
    }
    window.localStorage.removeItem("cps_access");
    window.localStorage.removeItem("cps_refresh");
    window.localStorage.removeItem("cps_user");
    window.localStorage.removeItem("cps_tenant");
    setTenant(null);
    setUser(null);
    setMe(null);
    setMeError(null);
  };

  // A 401 means the token itself is invalid/expired — logout() clears
  // `user`, which the dashboard layout already redirects to /login on.
  // Any other failure (backend 500, network blip) is not an auth
  // problem: the token may be perfectly good, so `user`/`tenant` stay
  // put and the caller gets `meError` to show instead — never a
  // silently truncated menu (sprint 4.8: this is exactly the failure
  // mode that made every permission-gated sidebar section disappear
  // with no indication anything was wrong).
  const loadMe = async (): Promise<MeResponse | null> => {
    try {
      const data = await api.get<MeResponse>("/auth/me/");
      setMe(data);
      setMeError(null);
      return data;
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return null;
      }
      setMeError(generalError(err instanceof ApiError ? err.body : null, t("meLoadError")));
      return null;
    }
  };

  useEffect(() => {
    const storedUser = window.localStorage.getItem("cps_user");
    const storedTenant = window.localStorage.getItem("cps_tenant");
    if (storedUser && storedTenant) {
      setUser(JSON.parse(storedUser));
      setTenant(JSON.parse(storedTenant));
      loadMe().finally(() => setIsReady(true));
    } else {
      setIsReady(true);
    }
  }, []);

  const login = async (subdomain: string, email: string, password: string, totpCode?: string) => {
    const payload = await api.post<AuthPayload>(
      "/auth/login/",
      { subdomain, email, password, ...(totpCode ? { totp_code: totpCode } : {}) },
      false
    );
    // Auth itself succeeded once we have tokens — a subsequent /me
    // hiccup (slow backend, transient network blip) must not be
    // reported back to the caller as a login failure; loadMe() records
    // it in `meError` instead, and the dashboard shows that clearly.
    persist(payload);
    setTenant(payload.tenant);
    setUser(payload.user);
    await loadMe();
    return { must_change_password: payload.must_change_password, requires_2fa_setup: payload.requires_2fa_setup };
  };

  const register: AuthContextValue["register"] = async (data) => {
    const payload = await api.post<AuthPayload>("/auth/register/", data, false);
    persist(payload);
    setTenant(payload.tenant);
    setUser(payload.user);
    await loadMe();
  };

  const hasPermission = (code: string) => me?.permissions.includes(code) ?? false;

  return (
    <AuthContext.Provider
      value={{ tenant, user, me, meError, isReady, login, register, logout, refreshMe: loadMe, hasPermission }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used inside AuthProvider");
  }
  return ctx;
}
