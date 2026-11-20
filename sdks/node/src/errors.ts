/** Errors thrown by the client. Each carries the fields of the API's error envelope. */
export interface ErrorFields {
  code?: string;
  status?: number;
  requestId?: string;
  retryable?: boolean;
  retryAfter?: number;
  details?: Record<string, unknown>;
  body?: unknown;
}

export class ScrapeCoreError extends Error {
  /** Stable error code, e.g. RATE_LIMITED. See https://scrapecore.com/docs/errors */
  readonly code: string;
  readonly status?: number;
  /** Quote this to support. */
  readonly requestId?: string;
  readonly retryable: boolean;
  /** Seconds to wait before retrying, when the API says so. */
  readonly retryAfter?: number;
  readonly details: Record<string, unknown>;
  readonly body?: unknown;

  constructor(message: string, f: ErrorFields = {}) {
    super(message);
    this.name = new.target.name;
    this.code = f.code ?? "ERROR";
    this.status = f.status;
    this.requestId = f.requestId;
    this.retryable = f.retryable ?? false;
    this.retryAfter = f.retryAfter;
    this.details = f.details ?? {};
    this.body = f.body;
  }
}

/** Missing, wrong or revoked API key (401). */
export class AuthenticationError extends ScrapeCoreError {}
/** Monthly credits used up (402). */
export class InsufficientCreditsError extends ScrapeCoreError {}
/** Feature not in the plan, or account suspended (403). */
export class PermissionDeniedError extends ScrapeCoreError {}
/** No such job or endpoint (404). */
export class NotFoundError extends ScrapeCoreError {}
/** Bad URL or parameter (400, 409, 413, 422). */
export class InvalidRequestError extends ScrapeCoreError {}
/** Per-minute, daily, concurrency or queue limit (429). */
export class RateLimitError extends ScrapeCoreError {}
/** Server or target-site failure (5xx). */
export class APIError extends ScrapeCoreError {}
/** Network error or timeout. */
export class APIConnectionError extends ScrapeCoreError {}

export class JobFailedError extends ScrapeCoreError {
  constructor(message: string, readonly job: Record<string, any>, f: ErrorFields = {}) {
    super(message, f);
  }
}
export class JobTimeoutError extends ScrapeCoreError {
  constructor(message: string, readonly job: Record<string, any>, f: ErrorFields = {}) {
    super(message, f);
  }
}

const BY_STATUS: Record<number, typeof ScrapeCoreError> = {
  401: AuthenticationError, 402: InsufficientCreditsError, 403: PermissionDeniedError,
  404: NotFoundError, 429: RateLimitError,
};

export function fromResponse(status: number, body: any, headers: Headers): ScrapeCoreError {
  const err = body && typeof body.error === "object" && body.error ? body.error : {};
  const detail = body?.detail;
  const message = err.message ?? (typeof detail === "string" ? detail : undefined) ?? `HTTP ${status}`;
  let retryAfter: number | undefined = err.retry_after_seconds;
  if (retryAfter === undefined) {
    const h = Number(headers.get("retry-after"));
    if (Number.isFinite(h) && headers.get("retry-after") !== null) retryAfter = h;
  }
  const Cls = BY_STATUS[status] ?? (status >= 500 ? APIError : InvalidRequestError);
  return new Cls(message, {
    code: err.code ?? (status >= 500 ? "INTERNAL_ERROR" : "INVALID_REQUEST"),
    status,
    requestId: err.request_id ?? headers.get("x-request-id") ?? undefined,
    retryable: err.retryable ?? (status === 408 || status === 429 || status >= 500),
    retryAfter,
    details: err.details,
    body,
  });
}
