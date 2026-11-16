import csv
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from chat_topic_finder.app import analyze


COMMON_USER = (
    "I am building a reliable personal archive for AI conversations. "
    "Preserve the exact sequence of messages and help determine when a copied thread "
    "later branches into two separate continuations. The match must use the ordered "
    "shared opening turns rather than merely matching a general topic."
)
COMMON_ASSISTANT = (
    "Parse each transcript into role-labelled turns, normalize harmless whitespace, "
    "and compare consecutive messages from the start. When multiple turns match and "
    "both transcripts continue in different directions afterward, record a likely "
    "sibling branch pair and explain the shared-prefix evidence in the report."
)


def transcript(next_user: str, next_assistant: str) -> str:
    return (
        "# Conversation archive branch\n\n"
        f"## user\n\n{COMMON_USER}\n\n---\n\n"
        f"## assistant\n\n{COMMON_ASSISTANT}\n\n---\n\n"
        f"## user\n\n{next_user}\n\n---\n\n"
        f"## assistant\n\n{next_assistant}\n"
    )


class AnalysisIntegrationTests(unittest.TestCase):
    def test_zip_ingestion_generates_branch_csv_json_and_html(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "synthetic-branches.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr(
                    "branch-a/chat.md",
                    transcript(
                        "Please add a local browser for inspecting branch families.",
                        "I will add a searchable family page and link each transcript.",
                    ),
                )
                zf.writestr(
                    "branch-b/chat.md",
                    transcript(
                        "Instead, export branch families to CSV and JSON for analysis.",
                        "I will add structured pair scores and shared-prefix evidence.",
                    ),
                )

            output = root / "reports"
            result = analyze([archive], output, threshold=0.12, log=lambda _message: None)
            self.assertEqual(result["chat_count"], 2)
            self.assertEqual(result["branch_match_count"], 1)

            payload = json.loads((output / "branch_families.json").read_text(encoding="utf-8"))
            self.assertEqual(len(payload["families"]), 1)
            self.assertEqual(len(payload["matches"]), 1)
            with (output / "branch_matches.csv").open(encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 1)
            self.assertGreater(int(rows[0]["shared_turns"]), 1)
            html = (output / "topic_report.html").read_text(encoding="utf-8")
            self.assertIn("Related conversation branches", html)
            self.assertIn("B0001", html)


if __name__ == "__main__":
    unittest.main()
