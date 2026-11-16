import unittest
import json

from chat_topic_finder.common import Chat
from chat_topic_finder.branches import detect_chat_branches
from chat_topic_finder.text import extract_turns, chat_from_text


COMMON_USER = (
    "I need help designing a reproducible conversation archive pipeline. "
    "Please preserve the exact ordered messages, identify when a thread forks, "
    "and distinguish a genuine branch from two conversations about the same topic. "
    "The implementation should stay deterministic and explain why it matched."
)
COMMON_ASSISTANT = (
    "A reliable approach is to parse each transcript into ordered role and text turns, "
    "normalize harmless whitespace differences, compare the shared opening prefix, "
    "and require both transcripts to continue in different directions after that prefix. "
    "This prevents topic similarity alone from being treated as branch identity."
)


def make_chat(title, turns, source):
    text = " ".join(t["text"] for t in turns)
    user = " ".join(t["text"] for t in turns if t["role"] == "user")
    assistant = " ".join(t["text"] for t in turns if t["role"] == "assistant")
    return Chat(title=title, text=text, user_text=user, assistant_text=assistant,
                source=source, turns=turns)


class BranchMatchingTests(unittest.TestCase):
    def test_detects_sibling_branches_with_shared_prefix_and_divergence(self):
        a = make_chat("Archive pipeline design", [
            {"role": "user", "text": COMMON_USER},
            {"role": "assistant", "text": COMMON_ASSISTANT},
            {"role": "user", "text": "Now implement a SQLite-backed branch browser."},
            {"role": "assistant", "text": "Use a family table and branch edges."},
        ], "branch-a/chat.md")
        b = make_chat("Archive pipeline design", [
            {"role": "user", "text": COMMON_USER},
            {"role": "assistant", "text": COMMON_ASSISTANT},
            {"role": "user", "text": "Instead, add a report export for branch families."},
            {"role": "assistant", "text": "Export a CSV and a JSON index."},
        ], "branch-b/chat.md")
        matches, families = detect_chat_branches([a, b])
        self.assertEqual(len(matches), 1)
        self.assertEqual(len(families), 1)
        self.assertEqual(families[0]["member_ids"], [1, 2])
        self.assertGreaterEqual(matches[0]["shared_turns"], 2)

    def test_does_not_match_same_topic_without_shared_ordered_prefix(self):
        a = make_chat("Archive pipeline design", [
            {"role": "user", "text": COMMON_USER},
            {"role": "assistant", "text": COMMON_ASSISTANT},
            {"role": "user", "text": "Create a SQLite schema."},
        ], "a/chat.md")
        b = make_chat("Archive pipeline design", [
            {"role": "user", "text": "I have a different question about backup archive compression and search."},
            {"role": "assistant", "text": "Here is an explanation of archive compression."},
            {"role": "user", "text": "Compare several compression formats."},
        ], "b/chat.md")
        matches, families = detect_chat_branches([a, b])
        self.assertEqual(matches, [])
        self.assertEqual(families, [])

    def test_does_not_call_a_shorter_snapshot_a_fork(self):
        prefix = [
            {"role": "user", "text": COMMON_USER},
            {"role": "assistant", "text": COMMON_ASSISTANT},
        ]
        a = make_chat("Archive pipeline design", prefix, "early/chat.md")
        b = make_chat("Archive pipeline design", prefix + [
            {"role": "user", "text": "Continue with a different branch."},
        ], "later/chat.md")
        matches, _ = detect_chat_branches([a, b])
        self.assertEqual(matches, [])

    def test_extracts_role_order_from_markdown(self):
        md = "# Topic\n\n## user\n\nFirst prompt.\n\n---\n\n## assistant\n\nFirst answer.\n\n---\n\n## user\n\nSecond prompt."
        turns = extract_turns(md)
        self.assertEqual([x["role"] for x in turns], ["user", "assistant", "user"])
        self.assertEqual(turns[0]["text"], "First prompt.")

    def test_extracts_ordered_turns_from_message_list_json(self):
        raw = json.dumps({
            "title": "Forkable chat",
            "messages": [
                {"role": "user", "content": "First prompt"},
                {"role": "assistant", "content": {"parts": ["First answer"]}},
                {"role": "user", "content": "Second prompt"},
            ],
        })
        turns = extract_turns(raw)
        self.assertEqual([turn["role"] for turn in turns], ["user", "assistant", "user"])
        self.assertEqual(turns[1]["text"], "First answer")

    def test_chat_constructor_keeps_raw_json_turn_order(self):
        raw = json.dumps({"messages": [
            {"role": "user", "content": "Opening request"},
            {"role": "assistant", "content": "Opening response"},
        ]})
        chat = chat_from_text("JSON conversation", raw, "raw.json")
        self.assertEqual([turn["role"] for turn in chat.turns], ["user", "assistant"])


if __name__ == "__main__":
    unittest.main()
