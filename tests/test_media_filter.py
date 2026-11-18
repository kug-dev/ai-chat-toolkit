import csv
import tempfile
import unittest
import zipfile
from pathlib import Path

from chat_topic_finder.app import analyze
from chat_topic_finder.common import ArchiveHealth
from chat_topic_finder.ingest import load_zip
from chat_topic_finder.reports import _matching_excerpt


MEDIA_ONLY_TRANSCRIPT = """# Image-only conversation

## user

![Uploaded reference](https://example.invalid/reference.png)

---

## assistant

![Generated image](https://example.invalid/generated.png)
"""

PROMPTED_IMAGE_TRANSCRIPT = """# Prompted image conversation

## user

Please generate a clean blue geometric cube on a plain white background.

---

## assistant

![Generated image](https://example.invalid/generated.png)
"""


class MediaOnlyFilterTests(unittest.TestCase):
    def _archive(self, path: Path) -> Path:
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("image_only_abcdef12/chat.md", MEDIA_ONLY_TRANSCRIPT)
            archive.writestr("image_only_abcdef12/generated/001_generated.png", b"not-a-real-image")
            archive.writestr("prompted_image_abcdef13/chat.md", PROMPTED_IMAGE_TRANSCRIPT)
            archive.writestr("prompted_image_abcdef13/generated/001_generated.png", b"not-a-real-image")
        return path

    def test_generated_media_only_classification_is_conservative(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = self._archive(Path(temp) / "media-chats.zip")
            health = []
            chats = load_zip(archive, health, log=lambda _message: None)
            by_title = {chat.title: chat for chat in chats}

            self.assertEqual(len(chats), 2)
            self.assertTrue(by_title["Image-only conversation"].generated_media_only)
            self.assertEqual(by_title["Image-only conversation"].generated_media_count, 1)
            self.assertFalse(by_title["Prompted image conversation"].generated_media_only)
            self.assertEqual(by_title["Prompted image conversation"].generated_media_count, 1)

    def test_extracted_folder_media_only_chat_is_classified(self):
        from chat_topic_finder.ingest import load_loose
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "chat.md").write_text(MEDIA_ONLY_TRANSCRIPT, encoding="utf-8")
            (root / "generated").mkdir()
            (root / "generated" / "generated.png").write_bytes(b"not-a-real-image")
            chat = load_loose(root / "chat.md", log=lambda _message: None)
            self.assertIsNotNone(chat)
            self.assertTrue(chat.generated_media_only)
            self.assertEqual(chat.generated_media_count, 1)

    def test_filter_excludes_only_media_only_chats_from_analysis(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = self._archive(root / "media-chats.zip")
            result = analyze(
                [archive],
                root / "report",
                threshold=0.1,
                exclude_generated_media_only=True,
                log=lambda _message: None,
            )

            self.assertEqual(result["chat_count"], 1)
            self.assertEqual(result["excluded_media_only_count"], 1)
            with (root / "report" / "chat_index.csv").open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["title"], "Prompted image conversation")

    def test_matching_excerpt_finds_a_late_section_instead_of_only_the_opening(self):
        transcript = ("opening filler " * 400) + (
            "The important section explains eigenvector stability over a finite field "
            "and how the modular transformation preserves the invariant."
        )
        excerpt = _matching_excerpt(transcript, ["eigenvector", "finite field", "invariant"])
        self.assertIn("eigenvector", excerpt)
        self.assertIn("finite field", excerpt)
        self.assertNotIn("opening filler opening filler opening filler", excerpt)


if __name__ == "__main__":
    unittest.main()
