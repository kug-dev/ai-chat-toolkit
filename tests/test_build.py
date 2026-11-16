import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class BrowserBuildTests(unittest.TestCase):
    def test_build_is_reproducible_and_has_all_adapters(self):
        subprocess.run([sys.executable, str(ROOT / "browser" / "build.py")], check=True, capture_output=True, text=True)
        bundle = (ROOT / "browser" / "dist" / "ai-chat-backup.user.js").read_text(encoding="utf-8")
        self.assertNotIn("/*__", bundle)
        self.assertIn("const claude =", bundle)
        self.assertIn("const chatgpt =", bundle)
        self.assertIn("const gemini =", bundle)
        self.assertIn("language: 'en'", bundle)


if __name__ == "__main__":
    unittest.main()
