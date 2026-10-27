"""Tests for proxy support in the REST client."""

import pytest
import urllib3
from urllib3.contrib.socks import SOCKSProxyManager

from openapi_client.configuration import Configuration
from openapi_client.rest import RESTClientObject


class TestProxyFromEnv:
    """RESTClientObject should use proxy from environment variables."""

    @pytest.fixture(autouse=True)
    def clean_proxy_env(self, monkeypatch):
        """Clear all proxy environment variables before each test."""
        for key in [
            "HTTP_PROXY",
            "http_proxy",
            "HTTPS_PROXY",
            "https_proxy",
            "ALL_PROXY",
            "all_proxy",
            "NO_PROXY",
            "no_proxy",
        ]:
            monkeypatch.delenv(key, raising=False)

    def test_no_proxy_uses_pool_manager(self):
        """Without any proxy config, PoolManager is used (no proxy)."""
        config = Configuration()
        client = RESTClientObject(config)
        assert isinstance(client.pool_manager, urllib3.PoolManager)
        assert not isinstance(client.pool_manager, urllib3.ProxyManager)

    def test_https_proxy_env_uses_proxy_manager(self, monkeypatch):
        """HTTPS_PROXY env var should cause ProxyManager to be used."""
        monkeypatch.setenv("HTTPS_PROXY", "http://localhost:8080")
        config = Configuration()
        client = RESTClientObject(config)
        assert isinstance(client.pool_manager, urllib3.ProxyManager)

    def test_http_proxy_env_uses_proxy_manager(self, monkeypatch):
        """HTTP_PROXY env var should cause ProxyManager to be used."""
        monkeypatch.setenv("HTTP_PROXY", "http://localhost:8080")
        config = Configuration()
        client = RESTClientObject(config)
        assert isinstance(client.pool_manager, urllib3.ProxyManager)

    def test_all_proxy_env_uses_proxy_manager(self, monkeypatch):
        """ALL_PROXY env var should cause ProxyManager to be used."""
        monkeypatch.setenv("ALL_PROXY", "http://localhost:8080")
        config = Configuration()
        client = RESTClientObject(config)
        assert isinstance(client.pool_manager, urllib3.ProxyManager)

    def test_all_proxy_socks_uses_socks_proxy_manager(self, monkeypatch):
        """ALL_PROXY with socks5h should use SOCKSProxyManager."""
        monkeypatch.setenv("ALL_PROXY", "socks5h://localhost:1080")
        config = Configuration()
        client = RESTClientObject(config)
        assert isinstance(client.pool_manager, SOCKSProxyManager)

    def test_no_proxy_env_bypasses_proxy(self, monkeypatch):
        """NO_PROXY env var should cause ProxyManager NOT to be used for matching host."""
        monkeypatch.setenv("HTTPS_PROXY", "http://localhost:8080")
        monkeypatch.setenv("NO_PROXY", "kagi.com")
        config = Configuration()
        # default host is https://kagi.com/api/v1, hostname is kagi.com
        client = RESTClientObject(config)
        assert isinstance(client.pool_manager, urllib3.PoolManager)
        assert not isinstance(client.pool_manager, urllib3.ProxyManager)
