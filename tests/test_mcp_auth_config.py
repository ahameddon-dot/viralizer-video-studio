import os
import unittest
from unittest.mock import patch

from mcp_outline_client import _mcp_config


class MCPAuthConfigTests(unittest.TestCase):
    def test_internal_key_replaces_oauth(self):
        with patch.dict(os.environ, {
            "MCP_SERVER_URL": "https://mcp.viralizer.ai/mcp",
            "VIRALIZER_MCP_API_KEY": "internal-key",
            "MCP_API_KEY": "legacy-key",
            "MCP_AUTH_TOKEN": "metered-token",
        }, clear=False):
            url, headers = _mcp_config()
        self.assertEqual("https://mcp.viralizer.ai/mcp", url)
        self.assertEqual({"X-API-Key": "internal-key"}, headers)

    def test_legacy_api_key_remains_supported(self):
        with patch.dict(os.environ, {
            "MCP_SERVER_URL": "https://mcp.viralizer.ai/mcp",
            "VIRALIZER_MCP_API_KEY": "",
            "MCP_API_KEY": "legacy-key",
            "MCP_AUTH_TOKEN": "metered-token",
        }, clear=False):
            _, headers = _mcp_config()
        self.assertEqual({"X-API-Key": "legacy-key"}, headers)

    def test_oauth_is_only_fallback(self):
        with patch.dict(os.environ, {
            "MCP_SERVER_URL": "https://mcp.viralizer.ai/mcp",
            "VIRALIZER_MCP_API_KEY": "",
            "MCP_API_KEY": "",
            "MCP_AUTH_TOKEN": "oauth-token",
        }, clear=False):
            _, headers = _mcp_config()
        self.assertEqual({"Authorization": "Bearer oauth-token"}, headers)


if __name__ == "__main__":
    unittest.main()
