"""Stage 2: proxy precedence and no duplicate --proxy arguments."""

from tadabbur.config.models import DownloadConfig, ProxyConfig, Settings
from tadabbur.downloader.client import YtDlpClient, get_effective_proxy


def _settings(proxy: ProxyConfig) -> Settings:
    return Settings(proxy=proxy, download=DownloadConfig(resume=False))


def test_config_proxy_only():
    s = _settings(ProxyConfig(enabled=True, url="http://p1:8888"))
    args = YtDlpClient(s)._base_args()
    assert args.count("--proxy") == 1
    assert "http://p1:8888" in args


def test_disabled_proxy_produces_no_proxy():
    s = _settings(ProxyConfig(enabled=False, url="http://p1:8888"))
    args = YtDlpClient(s)._base_args()
    assert "--proxy" not in args


def test_no_proxy_configured():
    s = _settings(ProxyConfig())
    args = YtDlpClient(s)._base_args()
    assert "--proxy" not in args


def test_override_takes_precedence():
    s = _settings(ProxyConfig(enabled=True, url="http://config:1"))
    args = YtDlpClient(s)._base_args(proxy="http://override:2")
    assert args.count("--proxy") == 1
    assert "http://override:2" in args
    assert "http://config:1" not in args


def test_override_only():
    s = _settings(ProxyConfig(enabled=False))
    client = YtDlpClient(s)
    args = client._base_args(proxy="http://override:2")
    assert args.count("--proxy") == 1


def test_download_methods_never_duplicate_proxy():
    """Full argv of every download path must contain at most one --proxy."""
    s = _settings(ProxyConfig(enabled=True, url="http://config:1"))
    client = YtDlpClient(s)

    video = client._base_args(proxy="http://ov:9") + client._common_download_args()
    audio = client._base_args(proxy=None) + client._common_download_args()
    for argv in (video, audio):
        assert argv.count("--proxy") <= 1


def test_get_effective_proxy_helper_matrix():
    p_on = ProxyConfig(enabled=True, url="http://cfg")
    p_off = ProxyConfig(enabled=False, url="http://cfg")
    assert get_effective_proxy(p_off, None) is None
    assert get_effective_proxy(p_off, "http://ov") == "http://ov"
    assert get_effective_proxy(p_on, None) == "http://cfg"
    assert get_effective_proxy(p_on, "http://ov") == "http://ov"


def test_enabled_proxy_requires_url():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ProxyConfig(enabled=True)
