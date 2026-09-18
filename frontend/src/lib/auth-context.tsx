"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { api } from "./api";

export interface Tenant {
  id: string;
  name: string;
  subdomain: string;
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
}

interface AuthContextValue {
  tenant: Tenant | null;
  user: User | null;
  isReady: boolean;
  login: (subdomain: string, email: string, password: string) => Promise<void>;
  register: (payload: {
    company_name: string;
    subdomain: string;
    email: string;
    password: string;
    first_name?: string;
    last_name?: string;
  }) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function persist(payload: AuthPayload) {
  window.localStorage.setItem("cps_access", payload.access);
  window.localStorage.setItem("cps_refresh", payload.refresh);
  window.localStorage.setItem("cps_user", JSON.stringify(payload.user));
  window.localStorage.setItem("cps_tenant", JSON.stringify(payload.tenant));
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [isReady, setIsReady] = useState(false);

  useEffect(() => {
    const storedUser = window.localStorage.getItem("cps_user");
    const storedTenant = window.localStorage.getItem("cps_tenant");
    if (storedUser && storedTenant) {
      setUser(JSON.parse(storedUser));
      setTenant(JSON.parse(storedTenant));
    }
    setIsReady(true);
  }, []);

  const login = async (subdomain: string, email: string, password: string) => {
    const payload = await api.post<AuthPayload>(
      "/auth/login/",
      { subdomain, email, password },
      false
    );
    persist(payload);
    setTenant(payload.tenant);
    setUser(payload.user);
  };

  const register: AuthContextValue["register"] = async (data) => {
    const payload = await api.post<AuthPayload>("/auth/register/", data, false);
    persist(payload);
    setTenant(payload.tenant);
    setUser(payload.user);
  };

  const logout = () => {
    window.localStorage.removeItem("cps_access");
    window.localStorage.removeItem("cps_refresh");
    window.localStorage.removeItem("cps_user");
    window.localStorage.removeItem("cps_tenant");
    setTenant(null);
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ tenant, user, isReady, login, register, logout }}>
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
