"""Indexing module for Chat Topic Finder."""
from __future__ import annotations
from .common import *
from .text import hebrew_stem, log_msg, tokenize, tokenize_code

def build_features(chat: Chat) -> Counter:
    features: Counter = Counter()
    title_tokens = tokenize(chat.title)
    user_tokens = tokenize(chat.user_text)
    asst_tokens = tokenize(chat.assistant_text)
    if not user_tokens and not asst_tokens:
        user_tokens = tokenize(chat.text)
    chat.tokens = title_tokens + user_tokens

    for t in title_tokens:
        features["w:" + t] += 3.0
        stem = hebrew_stem(t)
        if stem:
            features["s:" + stem] += 1.6
    for a, b in zip(title_tokens, title_tokens[1:]):
        features["b:" + a + " " + b] += 2.3

    for t in user_tokens:
        features["w:" + t] += 2.0
        stem = hebrew_stem(t)
        if stem:
            features["s:" + stem] += 0.95
    for a, b in zip(user_tokens, user_tokens[1:]):
        features["b:" + a + " " + b] += 1.5

    for t in asst_tokens:
        features["w:" + t] += 0.38
        stem = hebrew_stem(t)
        if stem:
            features["s:" + stem] += 0.22
    for a, b in zip(asst_tokens, asst_tokens[1:]):
        features["b:" + a + " " + b] += 0.20

    # Artifact-aware topic matching (2.5x weight boost on artifact titles & tokens)
    for aname in chat.artifact_names:
        for t in tokenize(Path(aname).stem.replace("_", " ")):
            features["a:" + t] += 2.5
    if chat.artifact_text:
        for t in tokenize(chat.artifact_text)[:400]:
            features["a:" + t] += 1.25

    # Separate code identifier indexing with boilerplate syntax filtered out
    if chat.code_text:
        for ident in tokenize_code(chat.code_text)[:500]:
            features["k:" + ident] += 0.45

    for t in title_tokens + user_tokens:
        if len(t) >= 6:
            grams = {t[i:i + 4] for i in range(len(t) - 3)}
            for g in grams:
                features["c:" + g] += 0.13
    chat.features = features
    return features

def sync_sqlite_cache_and_fts(chats: list[Chat], db_path: Path, log: Callable[[str], None] | None = None) -> int:
    """Persist chat digests, cached feature Counters, and an FTS5 full-text index."""
    cached_hits = 0
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        with conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS chat_cache (
                    digest TEXT PRIMARY KEY,
                    title TEXT,
                    source TEXT,
                    chat_date TEXT,
                    site TEXT,
                    project_tag TEXT,
                    token_count INTEGER DEFAULT 0,
                    features_json TEXT
                )"""
            )
            # Ensure token_count column exists if upgrading from an older table schema
            try:
                conn.execute("ALTER TABLE chat_cache ADD COLUMN token_count INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            cur = conn.cursor()
            for chat in chats:
                if not chat.digest:
                    build_features(chat)
                    continue
                row = cur.execute("SELECT features_json, token_count FROM chat_cache WHERE digest = ?", (chat.digest,)).fetchone()
                if row and row[0]:
                    try:
                        loaded = json.loads(row[0])
                        chat.features = Counter(loaded)
                        tok_cnt = int(row[1] or 0)
                        if tok_cnt > 0:
                            chat.tokens = ["_"] * tok_cnt
                        else:
                            chat.tokens = [k[2:] for k in chat.features if k.startswith("w:")]
                        cached_hits += 1
                        continue
                    except Exception:
                        pass
                build_features(chat)
                cur.execute(
                    "INSERT OR REPLACE INTO chat_cache (digest, title, source, chat_date, site, project_tag, token_count, features_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        chat.digest,
                        chat.title,
                        chat.source,
                        chat.chat_date,
                        chat.site,
                        chat.project_tag,
                        len(chat.tokens),
                        json.dumps(dict(chat.features), ensure_ascii=False),
                    ),
                )
            # Rebuild FTS5 table for current analysis set so full-text search is always fresh
            try:
                conn.execute("DROP TABLE IF EXISTS chats_fts")
                conn.execute(
                    "CREATE VIRTUAL TABLE chats_fts USING fts5(chat_id UNINDEXED, title, user_text, assistant_text, code_text, artifact_text, llm_report_text, source, chat_date UNINDEXED, site UNINDEXED)"
                )
                fts_rows = [
                    (
                        str(i + 1),
                        c.title,
                        c.user_text or c.text,
                        c.assistant_text,
                        c.code_text,
                        c.artifact_text,
                        json.dumps(c.llm_report, ensure_ascii=False) if c.llm_report else "",
                        c.source,
                        c.chat_date,
                        c.site,
                    )
                    for i, c in enumerate(chats)
                ]
                conn.executemany("INSERT INTO chats_fts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", fts_rows)
            except sqlite3.OperationalError:
                # Fallback if Python build lacks FTS5 extension
                pass
        conn.close()
        if cached_hits:
            log_msg(log, f"SQLite cache hit for {cached_hits}/{len(chats)} unchanged conversation(s).")
    except Exception as e:
        log_msg(log, f"SQLite cache warning (falling back to in-memory): {e}")
        for chat in chats:
            if not chat.features:
                build_features(chat)
    return cached_hits

def search_fts_database(db_path: Path, query: str, limit: int = 40) -> list[dict]:
    """Query the SQLite FTS5 index (with LIKE fallback) for instant full-text search."""
    if not db_path.exists() or not query.strip():
        return []
    results: list[dict] = []
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        try:
            rows = cur.execute(
                """SELECT chat_id, title, source, chat_date, site,
                          snippet(chats_fts, 2, '[', ']', ' … ', 24) AS u_snip,
                          snippet(chats_fts, 3, '[', ']', ' … ', 24) AS a_snip
                   FROM chats_fts
                   WHERE chats_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (query, limit),
            ).fetchall()
            for r in rows:
                results.append({
                    "chat_id": r[0],
                    "title": r[1],
                    "source": r[2],
                    "chat_date": r[3] or "",
                    "site": r[4] or "",
                    "snippet": (r[5] or r[6] or "").strip(),
                })
        except sqlite3.OperationalError:
            like_q = f"%{query.strip()}%"
            rows = cur.execute(
                """SELECT chat_id, title, source, chat_date, site, substr(user_text, 1, 220)
                   FROM chats_fts
                   WHERE title LIKE ? OR user_text LIKE ? OR assistant_text LIKE ? OR code_text LIKE ? OR llm_report_text LIKE ?
                   LIMIT ?""",
                (like_q, like_q, like_q, like_q, like_q, limit),
            ).fetchall()
            for r in rows:
                results.append({
                    "chat_id": r[0],
                    "title": r[1],
                    "source": r[2],
                    "chat_date": r[3] or "",
                    "site": r[4] or "",
                    "snippet": (r[5] or "").strip(),
                })
    finally:
        conn.close()
    return results
