/**
 * Thin fetch wrapper that:
 *  - Prepends VITE_API_URL to relative paths.
 *  - Attaches Authorization: Bearer <token> when a token is supplied.
 *  - Parses JSON, surfaces the standardized error envelope, and
 *    notifies a 401 listener so the auth store can sign the user out.
 *
 * Why a thin wrapper (not axios): one small file we fully understand.
 * fetch is built into the browser and Node 18+. axios adds 30KB and
 * features we don't need (interceptors with state, transformers).
 */

const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

let onUnauthorized: (() => void) | null = null;

export function setUnauthorizedHandler(fn: () => void): void {
  onUnauthorized = fn;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly errorCode: string,
    readonly requestId: string | undefined,
    readonly details?: unknown
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  body?: unknown;
  token?: string;
  signal?: AbortSignal;
}

export async function apiRequest<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {
    Accept: "application/json",
  };
  if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  if (opts.token) {
    headers["Authorization"] = `Bearer ${opts.token}`;
  }

  const url = path.startsWith("http") ? path : `${BASE}${path}`;
  const response = await fetch(url, {
    method: opts.method ?? "GET",
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    signal: opts.signal,
  });

  // Attempt to parse a JSON body even on errors; tolerate empty bodies.
  let payload: unknown = null;
  const text = await response.text();
  if (text.length > 0) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = { raw: text };
    }
  }

  if (!response.ok) {
    const env = (payload ?? {}) as Record<string, unknown>;
    const errorCode = typeof env.error_code === "string" ? env.error_code : "http_error";
    const message =
      typeof env.message === "string"
        ? env.message
        : `request failed: ${response.status}`;
    const requestId = typeof env.request_id === "string" ? env.request_id : undefined;

    if (response.status === 401 && onUnauthorized) {
      onUnauthorized();
    }

    throw new ApiError(message, response.status, errorCode, requestId, env.details);
  }

  return payload as T;
}

export function getApiBaseUrl(): string {
  return BASE;
}
