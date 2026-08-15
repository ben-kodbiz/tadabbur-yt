"""Diagnosis of yt-dlp/proxy failures into clear user messages."""

from __future__ import annotations

import pytest

from tadabbur.downloader import diagnose_error


def test_http_403_forbidden():
    d = diagnose_error("ERROR: Unable to download video: HTTP Error 403: Forbidden")
    assert "403" in d.summary
    assert d.is_proxy is True
    assert d.is_retryable is False
    assert d.hint and "proxy" in d.hint.lower()


def test_http_401_auth():
    d = diagnose_error("HTTP Error 401")
    assert "401" in d.summary
    assert d.is_proxy is True
    assert d.is_retryable is False


def test_http_429_rate_limit():
    d = diagnose_error("HTTP Error 429: Too Many Requests")
    assert "429" in d.summary
    assert d.is_retryable is False


def test_proxy_unreachable():
    d = diagnose_error(
        "Unable to connect to proxy", raw_stderr="ConnectTimeoutError(host='192.168.56.101')"
    )
    assert "unreachable" in d.summary
    assert d.is_proxy is True


def test_proxy_auth_required():
    d = diagnose_error("Proxy authentication required")
    assert "authentication" in d.summary
    assert d.is_proxy is True
    assert d.is_retryable is False


def test_sign_in_required():
    d = diagnose_error("Sign in to confirm you're not a bot")
    assert "sign-in" in d.summary.lower()
    assert d.is_retryable is False


def test_video_unavailable():
    d = diagnose_error("Video unavailable")
    assert "unavailable" in d.summary


def test_generic_network_timeout_is_retryable():
    d = diagnose_error("timed out after 300 seconds")
    assert d.is_retryable is True
    assert d.is_proxy is False


def test_unknown_error_fallback():
    d = diagnose_error("Some weird error nobody knows")
    assert d.summary
    assert d.is_retryable is True


def test_empty_message():
    d = diagnose_error("")
    assert "unknown" in d.summary.lower()
