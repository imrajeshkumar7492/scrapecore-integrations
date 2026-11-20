"""Errors raised by the client. Every API error carries the fields of the API's error envelope."""
from __future__ import annotations

from typing import Any


class ScrapeCoreError(Exception):
    """Base class. `code` is stable (e.g. RATE_LIMITED); see https://scrapecore.com/docs/errors."""

    def __init__(self, message: str, *, code: str = "ERROR", status: int | None = None,
                 request_id: str | None = None, retryable: bool = False,
                 retry_after: float | None = None, details: dict | None = None, body: Any = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status
        self.request_id = request_id
        self.retryable = retryable
        self.retry_after = retry_after
        self.details = details or {}
        self.body = body

    def __str__(self) -> str:
        bits = [f"[{self.code}] {self.message}"]
        if self.status:
            bits.append(f"(HTTP {self.status})")
        if self.request_id:
            bits.append(f"request_id={self.request_id}")
        return " ".join(bits)


class AuthenticationError(ScrapeCoreError):
    """The API key is missing, wrong or revoked (401)."""


class InsufficientCreditsError(ScrapeCoreError):
    """Not enough credits left this month (402)."""


class PermissionDeniedError(ScrapeCoreError):
    """The plan does not include this feature, or the account is suspended (403)."""


class NotFoundError(ScrapeCoreError):
    """No such job / endpoint (404)."""


class InvalidRequestError(ScrapeCoreError):
    """The request was rejected: a bad URL or parameter (400, 409, 413, 422)."""


class RateLimitError(ScrapeCoreError):
    """Requests per minute/day, concurrency or queue limit reached (429). See `retry_after`."""


class APIError(ScrapeCoreError):
    """The server or the target site failed (5xx). Usually worth retrying."""


class APIConnectionError(ScrapeCoreError):
    """The API could not be reached (network error or timeout)."""


class JobFailedError(ScrapeCoreError):
    """wait_for_job(): the job ended as failure or cancelled."""

    def __init__(self, message: str, job: dict, **kw):
        super().__init__(message, **kw)
        self.job = job


class JobTimeoutError(ScrapeCoreError):
    """wait_for_job(): the job did not finish within the timeout (it keeps running)."""

    def __init__(self, message: str, job: dict, **kw):
        super().__init__(message, **kw)
        self.job = job


_BY_STATUS = {401: AuthenticationError, 402: InsufficientCreditsError, 403: PermissionDeniedError,
              404: NotFoundError, 429: RateLimitError}


def from_response(status: int, body: Any, headers) -> ScrapeCoreError:
    err = body.get("error") if isinstance(body, dict) and isinstance(body.get("error"), dict) else {}
    detail = body.get("detail") if isinstance(body, dict) else None
    message = err.get("message") or (detail if isinstance(detail, str) else None) or f"HTTP {status}"
    retry_after = err.get("retry_after_seconds")
    if retry_after is None:
        ra = headers.get("retry-after") if headers is not None else None
        try:
            retry_after = float(ra) if ra is not None else None
        except ValueError:
            retry_after = None
    cls = _BY_STATUS.get(status) or (APIError if status >= 500 else InvalidRequestError)
    return cls(message, code=err.get("code") or ("INTERNAL_ERROR" if status >= 500 else "INVALID_REQUEST"),
               status=status, request_id=err.get("request_id") or (headers.get("x-request-id") if headers is not None else None),
               retryable=bool(err.get("retryable", status in (408, 429) or status >= 500)),
               retry_after=retry_after, details=err.get("details"), body=body)
