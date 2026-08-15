"""Classification of yt-dlp / network failures into clear user messages.

The goal: when a download fails because of the proxy or YouTube access
restrictions, the user must get an explicit, actionable reason (e.g. "HTTP 403
forbidden - try another proxy") instead of a raw traceback, so they can switch
proxy and resume.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# --- raw patterns extracted from yt-dlp stderr -------------------------------
_PATTERNS: list[tuple[re.Pattern, str]] = [
    # HTTP status codes with meaning
    (re.compile(r"HTTP Error 401", re.I), "HTTP 401 - authentication required (proxy/youtube login failed)"),
    (re.compile(r"HTTP Error 403", re.I), "HTTP 403 - forbidden (blocked by YouTube or proxy; try another proxy)"),
    (re.compile(r"HTTP Error 429", re.I), "HTTP 429 - too many requests (rate limited; wait or change proxy)"),
    (re.compile(r"HTTP Error 5\d\d", re.I), "HTTP 5xx - server error from YouTube/proxy"),
    (re.compile(r"HTTP Error (\d{3})", re.I), r"HTTP Error \1 - request rejected (try another proxy)"),
    # proxy-specific failures
    (re.compile(r"Unable to connect to proxy", re.I), "proxy is unreachable - check the proxy URL and that it is running"),
    (re.compile(r"Proxy authentication required", re.I), "proxy requires authentication (username/password)"),
    (re.compile(r"proxy.*(?:auth|login|credential)", re.I), "proxy authentication problem - check proxy credentials"),
    (re.compile(r"407", re.I), "HTTP 407 - proxy requires authentication (username/password)"),
    # login / sign-in required
    (re.compile(r"(?:Sign in|sign in to confirm|login required|log in|login)", re.I),
     "YouTube requires sign-in/confirmation (often an IP/region block; try another proxy)"),
    (re.compile(r"Video unavailable", re.I), "video unavailable (private, region-locked, or removed)"),
    # throttling / bot detection
    (re.compile(r"account associated with this video has been terminated", re.I),
     "YouTube terminated access (bot detection) - switch proxy/network"),
    (re.compile(r"bot|captcha|confirm you.re a human|verify", re.I),
     "YouTube bot-detection challenge - switch proxy/network"),
    (re.compile(r"too many request", re.I), "rate limited by YouTube - wait or change proxy"),
    # generic network
    (re.compile(r"\[Errno \d+\].*?timed out|timed out", re.I), "network timeout - slow or unstable connection (retrying)"),
    (re.compile(r"\[Errno 111\]|connection refused", re.I), "connection refused - proxy not accepting connections"),
    (re.compile(r"\[Errno 110\]", re.I), "connection timed out - proxy unreachable or slow"),
    (re.compile(r"unable to download video data", re.I), "download interrupted (network/proxy dropped the transfer)"),
    (re.compile(r"requested range not satisfiable", re.I), "HTTP 416 - partial/corrupt file; retry after cleanup"),
]


@dataclass
class FailureDiagnosis:
    """A human-readable diagnosis of a failed operation."""

    summary: str
    is_proxy: bool = False
    is_retryable: bool = True
    hint: str | None = None


def diagnose_error(message: str | None, *, raw_stderr: str | None = None) -> FailureDiagnosis:
    """Inspect an error message (plus optional raw yt-dlp stderr) and produce
    a clear user-facing reason.
    """
    text = "\n".join(filter(None, [message, raw_stderr]))
    if not text.strip():
        return FailureDiagnosis(summary="unknown error (no detail available)")

    for pattern, summary in _PATTERNS:
        if pattern.search(text):
            proxy_like = any(
                kw in summary.lower()
                for kw in ("proxy", "401", "403", "407", "bot", "rate limit", "sign-in")
            )
            return FailureDiagnosis(
                summary=summary,
                is_proxy=proxy_like,
                # clear-cut proxy/auth problems should not burn retries
                is_retryable=not proxy_like,
                hint=_hint(summary),
            )

    # Fallback: keep first line, trimmed.
    first = text.strip().splitlines()[0][:160]
    return FailureDiagnosis(summary=f"failed: {first}", is_retryable=True)


def _hint(summary: str) -> str | None:
    if "proxy" in summary.lower() or "401" in summary or "403" in summary:
        return "Update proxy.url in your config (or TADABBUR_PROXY_URL) then run: tadabbur retry --failed"
    if "sign-in" in summary.lower() or "bot" in summary.lower() or "rate limit" in summary.lower():
        return "Wait a while or switch network/proxy, then run: tadabbur retry --failed"
    if "416" in summary:
        return "Clean up partial files (tadabbur retry cleans them automatically) then retry"
    return None
