"""Conservative matching of conversation forks using shared ordered transcript prefixes."""
from __future__ import annotations

from difflib import SequenceMatcher
import re
from collections import defaultdict
from .common import *
from .text import clean_text, tokenize


def _normal(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").casefold()
    s = re.sub(r"https?://\S+", " ", s)
    return re.sub(r"[^\w\u0590-\u05ff]+", " ", s, flags=re.UNICODE).strip()


def _turns(chat: Chat) -> list[dict[str, str]]:
    turns = chat.turns or []
    if turns:
        return [{"role": str(t.get("role", "unknown")).casefold(), "text": _normal(t.get("text", ""))} for t in turns if _normal(t.get("text", ""))]
    fallback = []
    if chat.user_text:
        fallback.append({"role": "user", "text": _normal(chat.user_text)})
    if chat.assistant_text:
        fallback.append({"role": "assistant", "text": _normal(chat.assistant_text)})
    if not fallback and chat.text:
        fallback.append({"role": "unknown", "text": _normal(chat.text)})
    return fallback


def _candidate_keys(chat: Chat, turns: list[dict[str, str]]) -> set[str]:
    keys: set[str] = set()
    title_tokens = [t for t in tokenize(chat.title) if len(t) >= 3]
    first_user = next((t["text"] for t in turns if t["role"] in {"user", "human"}), "")
    opening_tokens = re.findall(r"[\w\u0590-\u05ff]{3,}", first_user)[:80]
    for seq, prefix in ((title_tokens, "t"), (opening_tokens, "u")):
        for i in range(max(0, len(seq) - 2)):
            gram = " ".join(seq[i:i + 3])
            if gram:
                keys.add(f"{prefix}:{gram}")
    if first_user:
        keys.add("u-prefix:" + first_user[:100])
    return keys


def _compare_prefix(a: list[dict[str, str]], b: list[dict[str, str]]) -> tuple[int, int, float]:
    common_turns = 0
    common_chars = 0
    similarity_sum = 0.0
    for ta, tb in zip(a, b):
        if ta["role"] != tb["role"] and {ta["role"], tb["role"]} not in ({"user", "human"}, {"assistant", "model"}):
            break
        sa, sb = ta["text"][:12000], tb["text"][:12000]
        if not sa or not sb:
            break
        ratio = SequenceMatcher(None, sa, sb, autojunk=False).ratio()
        if ratio < 0.93:
            break
        common_turns += 1
        common_chars += min(len(sa), len(sb))
        similarity_sum += ratio
    avg = similarity_sum / common_turns if common_turns else 0.0
    return common_turns, common_chars, avg


def detect_chat_branches(chats: list[Chat], *, enabled: bool = True, min_common_chars: int = 240, min_shared_turns: int = 2) -> tuple[list[dict], list[dict]]:
    """Return high-confidence pair matches and connected branch families.

    This deliberately uses shared transcript prefixes, not broad topic similarity:
    two chats that merely discuss the same subject should not be grouped as branches.
    """
    if not enabled or len(chats) < 2:
        return [], []
    turns = [_turns(c) for c in chats]
    buckets: dict[str, list[int]] = defaultdict(list)
    for i, chat in enumerate(chats):
        for key in _candidate_keys(chat, turns[i]):
            bucket = buckets[key]
            if len(bucket) < 80:
                bucket.append(i)
    candidates: set[tuple[int, int]] = set()
    for ids in buckets.values():
        if len(ids) < 2:
            continue
        for x, a in enumerate(ids):
            for b in ids[x + 1:]:
                if chats[a].digest and chats[a].digest == chats[b].digest:
                    continue
                candidates.add((min(a, b), max(a, b)))
                if len(candidates) >= 100_000:
                    break
            if len(candidates) >= 100_000:
                break
        if len(candidates) >= 100_000:
            break

    matches = []
    for a, b in sorted(candidates):
        if not turns[a] or not turns[b]:
            continue
        title_a, title_b = _normal(chats[a].title), _normal(chats[b].title)
        title_similarity = SequenceMatcher(None, title_a, title_b, autojunk=False).ratio() if title_a and title_b else 0.0
        shared_turns, shared_chars, turn_similarity = _compare_prefix(turns[a], turns[b])
        common_ratio = shared_chars / max(1, min(sum(len(t["text"]) for t in turns[a]), sum(len(t["text"]) for t in turns[b])))
        first_user_a = next((t["text"] for t in turns[a] if t["role"] in {"user", "human"}), "")
        first_user_b = next((t["text"] for t in turns[b] if t["role"] in {"user", "human"}), "")
        first_user_similarity = SequenceMatcher(None, first_user_a[:8000], first_user_b[:8000], autojunk=False).ratio() if first_user_a and first_user_b else 0.0
        # High confidence requires multiple matching turns, substantial shared content,
        # and some indication these are sibling exports rather than unrelated same-topic chats.
        title_or_opening = title_similarity >= 0.55 or first_user_similarity >= 0.985
        # Require both chats to continue beyond the shared prefix. A shorter snapshot
        # that is merely a prefix of a longer save is a revision, not a proven fork.
        diverges_on_both_sides = shared_turns < len(turns[a]) and shared_turns < len(turns[b])
        if shared_turns < min_shared_turns or shared_chars < min_common_chars or common_ratio < 0.12 or not title_or_opening or not diverges_on_both_sides:
            continue
        score = min(1.0, 0.50 * common_ratio + 0.25 * turn_similarity + 0.15 * title_similarity + 0.10 * first_user_similarity)
        matches.append({
            "a": a, "b": b, "score": round(score, 4),
            "shared_turns": shared_turns, "shared_chars": shared_chars,
            "common_ratio": round(common_ratio, 4),
            "title_similarity": round(title_similarity, 4),
            "first_user_similarity": round(first_user_similarity, 4),
            "title_a": chats[a].title, "title_b": chats[b].title,
            "source_a": chats[a].source, "source_b": chats[b].source,
        })

    parent = list(range(len(chats)))
    size = [1] * len(chats)
    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        if size[ra] < size[rb]:
            ra, rb = rb, ra
        parent[rb] = ra
        size[ra] += size[rb]
    for m in matches:
        union(m["a"], m["b"])
    components: dict[int, list[int]] = defaultdict(list)
    for m in matches:
        components[find(m["a"])].append(m["a"])
        components[find(m["b"])].append(m["b"])
    families = []
    for k, members in enumerate(sorted((sorted(set(v)) for v in components.values()), key=lambda x: (-len(x), x[0])), 1):
        if len(members) < 2:
            continue
        member_set = set(members)
        pair_count = sum(1 for m in matches if m["a"] in member_set and m["b"] in member_set)
        families.append({
            "id": f"B{k:04d}", "member_ids": [i + 1 for i in members],
            "members": [{"chat_id": i + 1, "title": chats[i].title, "source": chats[i].source, "date": chats[i].chat_date, "site": chats[i].site} for i in members],
            "pair_count": pair_count,
        })
    return matches, families
