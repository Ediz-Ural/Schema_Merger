/** Every call the review screen makes to the Phase 6a backend.
 *
 * This module is the only place that knows about HTTP.  It shapes no plan and
 * decides nothing: the two-phase flow, the review guard and the validator all
 * live in the core behind these endpoints.
 *
 * The sign-in token is kept here and sent as `Authorization: Bearer`.  The
 * user's provider key is never kept in the browser at all -- it is typed once,
 * sent once to `PUT /provider`, and lives in the server's memory from then on.
 */

import type {
  ApplyResult,
  Columns,
  Mapping,
  MappingEntry,
  ProviderInfo,
  ProviderSettings,
  ReviewGuardDetail,
  SessionToken,
  UploadResult,
  User,
} from "./types";

/** Same-origin `/api` in dev (Vite proxies it); override for a deployed API. */
export const API_BASE = import.meta.env?.VITE_API_BASE ?? "/api";

/** Where the sign-in token is remembered between reloads. */
export const TOKEN_STORAGE_KEY = "schema-merger.token";

let token: string | null = readStoredToken();

function readStoredToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function getToken(): string | null {
  return token;
}

export function setToken(next: string | null): void {
  token = next;
  try {
    if (next) {
      window.localStorage.setItem(TOKEN_STORAGE_KEY, next);
    } else {
      window.localStorage.removeItem(TOKEN_STORAGE_KEY);
    }
  } catch {
    /* a browser with storage disabled still works for this session */
  }
}

/** A non-2xx answer, with the backend's own message kept intact. */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, message: string, detail: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }

  /** The 409 body when apply was refused, otherwise `null`. */
  get guard(): ReviewGuardDetail | null {
    const detail = this.detail as ReviewGuardDetail | undefined;
    if (detail && typeof detail === "object" && "error" in detail) {
      return detail;
    }
    return null;
  }

  /** True when the session expired or no one is signed in. */
  get unauthorized(): boolean {
    return this.status === 401;
  }

  /** True when this user has not entered a provider key yet. */
  get missingKey(): boolean {
    return this.status === 503;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!response.ok) {
    throw await toError(response);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

async function toError(response: Response): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  const detail =
    body && typeof body === "object" && "detail" in body
      ? (body as { detail: unknown }).detail
      : body;
  return new ApiError(response.status, messageOf(detail, response), detail);
}

function messageOf(detail: unknown, response: Response): string {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object") {
    const guard = detail as { message?: string };
    if (typeof guard.message === "string") return guard.message;
  }
  return `İstek başarısız (HTTP ${response.status}).`;
}

function jsonBody(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

/* -- accounts ---------------------------------------------------------- */

export async function register(email: string, password: string): Promise<User> {
  const session = await request<SessionToken>("/auth/register", jsonBody("POST", { email, password }));
  setToken(session.token);
  return session.user;
}

export async function login(email: string, password: string): Promise<User> {
  const session = await request<SessionToken>("/auth/login", jsonBody("POST", { email, password }));
  setToken(session.token);
  return session.user;
}

export async function logout(): Promise<void> {
  try {
    await request<void>("/auth/logout", { method: "POST" });
  } finally {
    setToken(null);
  }
}

export function me(): Promise<User> {
  return request<User>("/auth/me");
}

/* -- provider settings ------------------------------------------------- */

export function getProvider(): Promise<ProviderInfo> {
  return request<ProviderInfo>("/provider");
}

/** Send the user's own provider choice; the key is stored server-side only. */
export function saveProvider(settings: ProviderSettings): Promise<ProviderInfo> {
  return request<ProviderInfo>("/provider", jsonBody("PUT", settings));
}

export function forgetKey(): Promise<ProviderInfo> {
  return request<ProviderInfo>("/provider", { method: "DELETE" });
}

/* -- the two-phase flow ------------------------------------------------ */

export function upload(files: File[], targetSchema: File): Promise<UploadResult> {
  const form = new FormData();
  files.forEach((file) => form.append("files", file));
  form.append("target_schema", targetSchema);
  return request<UploadResult>("/upload", { method: "POST", body: form });
}

export function analyze(sessionId: string, sheet?: string | null): Promise<Mapping> {
  return request<Mapping>(`/analyze/${sessionId}`, jsonBody("POST", { sheet: sheet ?? null }));
}

export function putMapping(sessionId: string, entries: MappingEntry[]): Promise<Mapping> {
  return request<Mapping>(`/mapping/${sessionId}`, jsonBody("PUT", { entries }));
}

export function getColumns(sessionId: string): Promise<Columns> {
  return request<Columns>(`/columns/${sessionId}`);
}

export function apply(
  sessionId: string,
  options: { output_format?: string | null } = {},
): Promise<ApplyResult> {
  return request<ApplyResult>(
    `/apply/${sessionId}`,
    jsonBody("POST", { output_format: options.output_format ?? null }),
  );
}

/** Artifact URL; the token travels in the header, so it is fetched, not linked. */
function downloadUrl(sessionId: string, artifact: "merged" | "report"): string {
  return `${API_BASE}/download/${sessionId}/${artifact}`;
}

/** Fetch an artifact with the bearer token and hand the browser a blob URL. */
export async function downloadArtifact(
  sessionId: string,
  artifact: "merged" | "report",
): Promise<Blob> {
  const headers = new Headers();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const response = await fetch(downloadUrl(sessionId, artifact), { headers });
  if (!response.ok) {
    throw await toError(response);
  }
  return response.blob();
}
