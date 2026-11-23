import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { api, ApiError } from "../api/client";
import type { LoginRequestResponse, User } from "../api/types";
import { LAST_ORGANIZATION_KEY } from "../lib/constants";

type ProfileUpdate = Partial<Pick<User, "first_name" | "last_name" | "navigation_app" | "route_display">> & {
  /** Ticked box of the confidentiality agreement (asked once, with the name). */
  accept_confidentiality?: boolean;
};

type AuthState = {
  user: User | null;
  loading: boolean;
  /** Step 1: send a login code (and link) to this email. */
  requestCode: (organization: string, email: string) => Promise<LoginRequestResponse>;
  /** Step 2: the code received by email. */
  verifyCode: (email: string, code: string) => Promise<void>;
  /** Step 2 (alternative): the link of the email. */
  verifyLink: (token: string) => Promise<void>;
  updateProfile: (data: ProfileUpdate) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
  setUser: (user: User) => void;
};

const AuthContext = createContext<AuthState | null>(null);

function remember(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* private mode: nothing to remember */
  }
}

function recall(key: string): string {
  try {
    return localStorage.getItem(key) ?? "";
  } catch {
    return "";
  }
}

const LAST_EMAIL_KEY = "canvassing:last-email";

export const lastOrganization = () => recall(LAST_ORGANIZATION_KEY);
export const lastEmail = () => recall(LAST_EMAIL_KEY);

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

  const requestCode = async (organization: string, email: string) => {
    const response = await api<LoginRequestResponse>("/auth/login/request/", {
      method: "POST",
      body: { organization: organization || null, email },
    });
    if (organization) remember(LAST_ORGANIZATION_KEY, organization);
    remember(LAST_EMAIL_KEY, response.email);
    return response;
  };

  // Django rotates the CSRF token on login: fetch the new cookie before the next POST.
  const signedIn = async (me: User) => {
    setUser(me);
    await api("/auth/csrf/");
  };

  const verifyCode = async (email: string, code: string) => {
    await signedIn(await api<User>("/auth/login/code/", { method: "POST", body: { email, code } }));
  };

  const verifyLink = useCallback(async (token: string) => {
    const me = await api<User>("/auth/login/link/", { method: "POST", body: { token } });
    setUser(me);
    await api("/auth/csrf/");
  }, []);

  const updateProfile = async (data: ProfileUpdate) => {
    setUser(await api<User>("/auth/me/", { method: "PATCH", body: data }));
  };

  const logout = async () => {
    await api("/auth/logout/", { method: "POST" });
    setUser(null);
    await api("/auth/csrf/");
  };

  return (
    <AuthContext.Provider value={{ user, loading, requestCode, verifyCode, verifyLink, updateProfile, logout, refresh, setUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
