export class ApiError extends Error {
  status: number;
  data: unknown;

  constructor(status: number, data: unknown) {
    super(extractMessage(data) ?? `Erreur ${status}`);
    this.status = status;
    this.data = data;
  }
}

function extractMessage(data: unknown): string | null {
  if (!data || typeof data !== "object") return null;
  const record = data as Record<string, unknown>;
  if (typeof record.detail === "string") return record.detail;
  for (const value of Object.values(record)) {
    if (Array.isArray(value) && typeof value[0] === "string") return value[0];
    if (typeof value === "string") return value;
    const nested = extractMessage(value);
    if (nested) return nested;
  }
  return null;
}

function getCookie(name: string): string | null {
  const match = document.cookie.split("; ").find((c) => c.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.split("=")[1]) : null;
}

type Options = { method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE"; body?: unknown; query?: Record<string, string | number> };

export async function api<T>(path: string, { method = "GET", body, query }: Options = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  const isForm = body instanceof FormData;
  if (method !== "GET") {
    if (!isForm) headers["Content-Type"] = "application/json";
    const token = getCookie("csrftoken");
    if (token) headers["X-CSRFToken"] = token;
  }
  const qs = query ? `?${new URLSearchParams(Object.entries(query).map(([k, v]) => [k, String(v)]))}` : "";
  const response = await fetch(`/api${path}${qs}`, {
    method,
    headers,
    credentials: "same-origin",
    body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
  });
  if (response.status === 204) return undefined as T;
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, data);
  return data as T;
}

export function errorMessage(err: unknown): string {
  if (err instanceof Error) return err.message;
  return "Une erreur est survenue.";
}
