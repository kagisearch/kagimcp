import asyncio
import io
import json
import unittest
from unittest.mock import patch

import httpx
from mcp.client.auth.utils import get_client_metadata_scopes
from mcp.shared.auth import ProtectedResourceMetadata

from kagimcp import server


class OAuthDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.enterContext(patch.object(server, "_oauth_metadata", None))
        self.enterContext(patch.object(server, "_oauth_metadata_lock", asyncio.Lock()))
        self.metadata = {
            "issuer": server._OAUTH_ISSUER,
            "authorization_endpoint": f"{server._OAUTH_ISSUER}/authorize",
            "token_endpoint": f"{server._OAUTH_ISSUER}/token",
            "registration_endpoint": f"{server._OAUTH_ISSUER}/register",
        }
        self.expected = {
            key: value
            for key, value in self.metadata.items()
            if key != "registration_endpoint"
        }
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.mcp.http_app()),
            base_url="https://mcp.kagi.com",
        )
        self.addAsyncCleanup(self.client.aclose)

    def metadata_response(self):
        return io.StringIO(json.dumps(self.metadata))

    async def get_metadata(self):
        return await self.client.get("/.well-known/oauth-authorization-server")

    async def assert_recovers_and_caches(self, failure):
        with patch.object(
            server, "urlopen", side_effect=[failure, self.metadata_response()]
        ) as fetch:
            with self.assertLogs(server.__name__, level="WARNING"):
                first = await self.get_metadata()
            second = await self.get_metadata()
            third = await self.get_metadata()

        self.assertEqual(first.status_code, 503)
        self.assertEqual(first.json(), {"error": "OAuth metadata unavailable"})
        self.assertEqual(first.headers["access-control-allow-origin"], "*")
        for response in (second, third):
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), self.expected)
            self.assertEqual(response.headers["access-control-allow-origin"], "*")
        self.assertEqual(fetch.call_count, 2)

    async def test_retries_after_network_failure(self):
        await self.assert_recovers_and_caches(OSError("temporarily unavailable"))

    async def test_retries_after_invalid_json(self):
        await self.assert_recovers_and_caches(io.StringIO("not JSON"))

    async def test_retries_after_issuer_mismatch(self):
        invalid = {**self.metadata, "issuer": "https://wrong-issuer.example"}
        await self.assert_recovers_and_caches(io.StringIO(json.dumps(invalid)))

    async def test_retries_after_missing_endpoint(self):
        invalid = {
            key: value
            for key, value in self.metadata.items()
            if key != "token_endpoint"
        }
        await self.assert_recovers_and_caches(io.StringIO(json.dumps(invalid)))

    async def test_concurrent_requests_share_successful_fetch(self):
        with patch.object(
            server, "urlopen", return_value=self.metadata_response()
        ) as fetch:
            responses = await asyncio.gather(*(self.get_metadata() for _ in range(8)))

        for response in responses:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), self.expected)
        fetch.assert_called_once_with(server._OAUTH_METADATA_URL, timeout=5)

    async def test_discovery_allows_clients_to_request_refresh_tokens(self):
        for path in (
            "/.well-known/oauth-protected-resource",
            "/.well-known/oauth-protected-resource/mcp",
        ):
            with self.subTest(path=path):
                response = await self.client.get(path)
                self.assertEqual(response.status_code, 200)
                metadata = ProtectedResourceMetadata.model_validate(response.json())
                self.assertIn("offline_access", metadata.scopes_supported)
                selected_scopes = get_client_metadata_scopes(None, metadata).split()
                self.assertIn("offline_access", selected_scopes)
                self.assertIn("openid", selected_scopes)


if __name__ == "__main__":
    unittest.main()
