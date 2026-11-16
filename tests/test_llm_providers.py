import json
import unittest
from unittest.mock import patch

from chat_topic_finder.llm import _invoke_local_llm_json


class FakeResponse:
    def __init__(self, value):
        self.payload = json.dumps(value).encode("utf-8")
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self):
        return self.payload


class LLMProviderTests(unittest.TestCase):
    def test_openai_compatible_provider(self):
        response = {"choices": [{"message": {"content": "```json\n{\"ok\": true}\n```"}}]}
        with patch("urllib.request.urlopen", return_value=FakeResponse(response)) as opened:
            parsed, raw = _invoke_local_llm_json("system", "user", "example-model",
                base_url="https://example.invalid/v1", api_key="secret", provider="openai-compatible")
        self.assertEqual(parsed, {"ok": True})
        self.assertIn('"model": "example-model"', opened.call_args.args[0].data.decode())
        self.assertTrue(opened.call_args.args[0].full_url.endswith("/v1/chat/completions"))

    def test_anthropic_messages_provider(self):
        response = {"content": [{"type": "text", "text": "{\"ok\": true}"}]}
        with patch("urllib.request.urlopen", return_value=FakeResponse(response)) as opened:
            parsed, _ = _invoke_local_llm_json("system", "user", "claude-model",
                base_url="https://api.anthropic.com/v1", api_key="secret", provider="anthropic")
        self.assertEqual(parsed, {"ok": True})
        req = opened.call_args.args[0]
        self.assertTrue(req.full_url.endswith("/v1/messages"))
        headers = dict(req.header_items())
        self.assertEqual(headers.get("X-api-key"), "secret")
        self.assertEqual(headers.get("Anthropic-version"), "2023-06-01")

    def test_ollama_native_provider(self):
        response = {"message": {"content": "{\"ok\": true}"}}
        with patch("urllib.request.urlopen", return_value=FakeResponse(response)) as opened:
            parsed, _ = _invoke_local_llm_json("system", "user", "local-model",
                base_url="http://localhost:11434", provider="ollama")
        self.assertEqual(parsed, {"ok": True})
        req = opened.call_args.args[0]
        self.assertTrue(req.full_url.endswith("/api/chat"))


if __name__ == "__main__":
    unittest.main()
