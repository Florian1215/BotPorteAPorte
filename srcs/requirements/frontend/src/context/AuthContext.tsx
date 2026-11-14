import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { api, ApiError } from "../api/client";
import type { User } from "../api/types";

type RegisterData = { username: string; first_name: string; password: string; scope: string | null };

type AuthState = {
  user: User | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (data: RegisterData) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      setUser(await api<User>("/auth/me/"));
    } catch (err) {
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) setUser(null);
      else throw err;
    }
  }, []);

  useEffect(() => {
    api("/auth/csrf/")
      .then(refresh)
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, [refresh]);

  const login = async (username: string, password: string) => {
    setUser(await api<User>("/auth/login/", { method: "POST", body: { username, password } }));
  };

  const register = async (data: RegisterData) => {
    setUser(await api<User>("/auth/register/", { method: "POST", body: data }));
  };

  const logout = async () => {
    await api("/auth/logout/", { method: "POST" });
    setUser(null);
    await api("/auth/csrf/");
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout, refresh }}>{children}</AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
