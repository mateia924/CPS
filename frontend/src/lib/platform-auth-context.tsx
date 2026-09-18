"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { ApiError, platformApi } from "./api";
import type { PlatformUser } from "./types";

interface PlatformLoginPayload {
  access: string;
  refresh: string;
  user: PlatformUser;
}

interface PlatformAuthContextValue {
  user: PlatformUser | null;
  isReady: boolean;
  /** Mirrors the backend's two-step shape (apps/platform/views.py:
   * PlatformLoginView): posting without `totpCode` either fails on
   * email/password (throws) or succeeds in confirming credentials while
   * still requiring a code — the caller distinguishes those by checking
   * `codeRequired` on the resolved result. */
  login: (
    email: string,
    password: string,
    totpCode?: string
  ) => Promise<{ codeRequired: boolean }>;
  logout: () => void;
}

const PlatformAuthContext = createContext<PlatformAuthContextValue | null>(null);

function persist(payload: PlatformLoginPayload) {
  window.localStorage.setItem("cps_platform_access", payload.access);
  window.localStorage.setItem("cps_platform_refresh", payload.refresh);
  window.localStorage.setItem("cps_platform_user", JSON.stringify(payload.user));
}

export function PlatformAuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<PlatformUser | null>(null);
  const [isReady, setIsReady] = useState(false);

  useEffect(() => {
    const storedUser = window.localStorage.getItem("cps_platform_user");
    const storedAccess = window.localStorage.getItem("cps_platform_access");
    if (storedUser && storedAccess) {
      setUser(JSON.parse(storedUser));
    }
    setIsReady(true);
  }, []);

  const login: PlatformAuthContextValue["login"] = async (email, password, totpCode) => {
    // A missing totp_code on a request with correct credentials responds
    // 400 (see PlatformLoginView) — that's not an error state for this
    // screen's flow, it's the signal to show the code step, so it's
    // handled here rather than left for the caller to special-case.
    try {
      const payload = await platformApi.post<PlatformLoginPayload>(
        "/platform/auth/login/",
        { email, password, totp_code: totpCode ?? "" },
        false
      );
      persist(payload);
      setUser(payload.user);
      return { codeRequired: false };
    } catch (err) {
      if (err instanceof ApiError && err.status === 400 && !totpCode) {
        return { codeRequired: true };
      }
      throw err;
    }
  };

  const logout = () => {
    window.localStorage.removeItem("cps_platform_access");
    window.localStorage.removeItem("cps_platform_refresh");
    window.localStorage.removeItem("cps_platform_user");
    setUser(null);
  };

  return (
    <PlatformAuthContext.Provider value={{ user, isReady, login, logout }}>
      {children}
    </PlatformAuthContext.Provider>
  );
}

export function usePlatformAuth() {
  const ctx = useContext(PlatformAuthContext);
  if (!ctx) {
    throw new Error("usePlatformAuth must be used inside PlatformAuthProvider");
  }
  return ctx;
}
