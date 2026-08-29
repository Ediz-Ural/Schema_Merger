/** Every call the review screen makes to the Phase 6a backend.
 *
 * This module is the only place that knows about HTTP.  It shapes no plan and
 * decides nothing: the two-phase flow, the review guard and the validator all
 * live in the core behind these endpoints.
 */

import type {
  ApplyResult,
  Columns,
  Mapping,
  MappingEntry,
  ProviderInfo,
  ReviewGuardDetail,
  UploadResult,
} from "./types";

/** Same-origin `/api` in dev (Vite proxies it); override for a deployed API. */
export const API_BASE = import.meta.env?.VITE_API_BASE ?? "/api";

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
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
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

function json(body: unknown): RequestInit {
  return {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

export function getProvider(): Promise<ProviderInfo> {
  return request<ProviderInfo>("/provider");
}

export function upload(files: File[], targetSchema: File): Promise<UploadResult> {
  const form = new FormData();
  files.forEach((file) => form.append("files", file));
  form.append("target_schema", targetSchema);
  return request<UploadResult>("/upload", { method: "POST", body: form });
}

export function analyze(sessionId: string, sheet?: string | null): Promise<Mapping> {
  return request<Mapping>(`/analyze/${sessionId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sheet: sheet ?? null }),
  });
}

export function getMapping(sessionId: string): Promise<Mapping> {
  return request<Mapping>(`/mapping/${sessionId}`);
}

export function putMapping(sessionId: string, entries: MappingEntry[]): Promise<Mapping> {
  return request<Mapping>(`/mapping/${sessionId}`, json({ entries }));
}

export function getColumns(sessionId: string): Promise<Columns> {
  return request<Columns>(`/columns/${sessionId}`);
}

export function apply(
  sessionId: string,
  options: { output_format?: string | null } = {},
): Promise<ApplyResult> {
  return request<ApplyResult>(`/apply/${sessionId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ output_format: options.output_format ?? null }),
  });
}

export function downloadUrl(sessionId: string, artifact: "merged" | "report"): string {
  return `${API_BASE}/download/${sessionId}/${artifact}`;
}
