"""Llm module for Chat Topic Finder."""
from __future__ import annotations
from .common import *
from .text import log_msg, tokenize

def build_llm_digest_input(chat: Chat, max_chars: int = DEFAULT_LLM_MAX_CHARS) -> str:
    """Compress a potentially huge conversation into a bounded representative excerpt,
    preserving the title, artifacts, opening goal, middle progression, and final resolution."""
    max_chars = max(2_000, min(max_chars, 320_000))
    header_lines = [
        f"Title: {chat.title}",
        f"Platform: {chat.site or 'unknown'}",
        f"Date: {chat.chat_date or 'unknown'}",
    ]
    if chat.project_tag:
        header_lines.append(f"Project: {chat.project_tag}")
    if chat.code_langs:
        header_lines.append(f"Code Languages: {', '.join(chat.code_langs[:8])}")
    if chat.artifact_names:
        header_lines.append(f"Artifacts Created: {', '.join(chat.artifact_names[:10])}")
    header = "\n".join(header_lines) + "\n\n"

    budget = max(1_000, max_chars - len(header))
    user_budget = int(budget * 0.58)
    asst_budget = int(budget * 0.30)
    art_budget = budget - user_budget - asst_budget

    def sample_section(text: str, limit: int) -> str:
        if not text or limit <= 0:
            return ""
        if len(text) <= limit:
            return text
        head = int(limit * 0.45)
        mid = int(limit * 0.20)
        tail = limit - head - mid
        mid_start = max(head, (len(text) - mid) // 2)
        return (
            text[:head].strip()
            + "\n... [middle excerpt] ...\n"
            + text[mid_start:mid_start + mid].strip()
            + "\n... [closing excerpt] ...\n"
            + text[-tail:].strip()
        )

    user_src = chat.user_text or chat.text
    sections = [header]
    if user_src:
        sections.append("[USER PROMPTS]\n" + sample_section(user_src, user_budget))
    if chat.assistant_text:
        sections.append("\n\n[ASSISTANT REPLIES]\n" + sample_section(chat.assistant_text, asst_budget))
    if chat.artifact_text and art_budget > 120:
        sections.append("\n\n[ARTIFACTS / CODE]\n" + sample_section(chat.artifact_text, art_budget))
    return "".join(sections)[:max_chars]

def _extract_json_object(raw_text: str) -> dict | None:
    """Extract a JSON object from an LLM response even if wrapped in markdown fences."""
    cleaned = raw_text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        obj = json.loads(cleaned)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    m = re.search(r"\{[\s\S]*\}", cleaned)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    return None

def normalize_llm_report(raw_obj: dict | None, fallback_text: str = "") -> dict:
    """Sanitize the per-chat LLM report into a consistent schema, including multi-topic segments."""
    if not isinstance(raw_obj, dict):
        raw_obj = {}

    def _str_list(val, max_items: int = 12) -> list[str]:
        if isinstance(val, str):
            val = [x.strip() for x in re.split(r"[,;\n]+", val) if x.strip()]
        if not isinstance(val, list):
            return []
        out = []
        for item in val:
            s = str(item).strip()
            if s and len(s) <= 80 and s not in out:
                out.append(s)
            if len(out) >= max_items:
                break
        return out

    summary = str(raw_obj.get("summary") or fallback_text[:350] or "").strip()
    primary_topic = str(raw_obj.get("primary_topic") or "").strip()[:90]
    intent = str(raw_obj.get("intent") or "").strip()[:50]
    subtopics = _str_list(raw_obj.get("subtopics"), 8)
    entities = _str_list(raw_obj.get("entities_and_tools") or raw_obj.get("entities"), 12)
    keywords = _str_list(raw_obj.get("canonical_keywords") or raw_obj.get("keywords"), 15)

    # Normalize topic segments (captures topic switches inside a single conversation)
    raw_segments = raw_obj.get("segments")
    segments: list[dict] = []
    if isinstance(raw_segments, list):
        for seg in raw_segments[:6]:
            if not isinstance(seg, dict):
                continue
            seg_topic = str(seg.get("topic") or "").strip()[:90]
            seg_sum = str(seg.get("summary") or "").strip()[:240]
            seg_part = str(seg.get("part") or seg.get("turns") or "").strip()[:40]
            seg_kw = _str_list(seg.get("keywords"), 8)
            if seg_topic or seg_sum:
                segments.append({
                    "part": seg_part or f"Part {len(segments) + 1}",
                    "topic": seg_topic or primary_topic,
                    "summary": seg_sum,
                    "keywords": seg_kw,
                })
    if not segments and (primary_topic or summary):
        segments.append({
            "part": "Full chat",
            "topic": primary_topic or "General",
            "summary": summary[:240],
            "keywords": keywords[:6],
        })

    cross_grades = raw_obj.get("cross_topic_grades")
    if not isinstance(cross_grades, list):
        cross_grades = []

    return {
        "summary": summary,
        "primary_topic": primary_topic,
        "intent": intent,
        "subtopics": subtopics,
        "entities_and_tools": entities,
        "canonical_keywords": keywords,
        "segments": segments,
        "cross_topic_grades": cross_grades,
    }

def _invoke_local_llm_json(
    system_prompt: str,
    user_prompt: str,
    model: str,
    base_url: str = DEFAULT_LLM_URL,
    timeout_sec: int = 180,
    api_key: str = "",
    provider: str = DEFAULT_LLM_PROVIDER,
) -> tuple[dict | None, str]:
    """Call Ollama, Anthropic Messages, or any OpenAI-compatible chat-completions API."""
    url = base_url.rstrip("/")
    selected = (provider or "auto").strip().casefold()
    if selected == "auto":
        if "api.anthropic.com" in url or url.endswith("/messages"):
            selected = "anthropic"
        elif ":11434" in url or url.endswith("/api/chat") or "/api/" in url:
            selected = "ollama"
        else:
            selected = "openai-compatible"
    if selected not in {"ollama", "anthropic", "openai-compatible"}:
        raise ValueError(f"Unsupported LLM provider: {provider}")

    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key and selected == "anthropic":
        headers["x-api-key"] = api_key
        headers["anthropic-version"] = "2023-06-01"
    elif api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    def _post_with_retry(endpoint: str, payload: dict, extra_headers: dict | None = None) -> dict:
        last_err: Exception | None = None
        request_headers = {**headers, **(extra_headers or {})}
        for attempt in range(4):
            try:
                req = urllib.request.Request(
                    endpoint,
                    data=json.dumps(payload).encode("utf-8"),
                    headers=request_headers,
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                    return json.loads(resp.read().decode("utf-8", errors="replace"))
            except urllib.error.HTTPError as e:
                last_err = e
                if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                    time.sleep(1.5 * (2 ** attempt))
                    continue
                raise
            except urllib.error.URLError as e:
                last_err = e
                if attempt < 3:
                    time.sleep(1.5 * (2 ** attempt))
                    continue
                raise
        raise last_err or RuntimeError("LLM request failed")

    def _text_content(value) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return "\n".join(str(x.get("text", "")) for x in value if isinstance(x, dict) and x.get("text"))
        return ""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    if selected == "anthropic":
        endpoint = url if url.endswith("/messages") else f"{url}/messages"
        payload = {
            "model": model,
            "max_tokens": 4096,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
            "temperature": 0.1,
        }
        body = _post_with_retry(endpoint, payload)
        content = _text_content(body.get("content", []))
        return _extract_json_object(content), content

    if selected == "openai-compatible":
        endpoint = url if url.endswith("/chat/completions") else f"{url}/chat/completions"
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        try:
            body = _post_with_retry(endpoint, payload)
        except urllib.error.HTTPError as e:
            # Many compatible servers omit JSON mode; retry without response_format.
            if e.code != 400:
                raise
            payload.pop("response_format", None)
            body = _post_with_retry(endpoint, payload)
        content = _text_content(body.get("choices", [{}])[0].get("message", {}).get("content", ""))
        return _extract_json_object(content), content

    endpoint = url if url.endswith("/api/chat") else f"{url}/api/chat"
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1},
    }
    body = _post_with_retry(endpoint, payload)
    content = body.get("message", {}).get("content") or body.get("response", "")
    return _extract_json_object(content), content

def call_llm_for_chat(
    chat: Chat,
    model: str,
    base_url: str = DEFAULT_LLM_URL,
    max_chars: int = DEFAULT_LLM_MAX_CHARS,
    timeout_sec: int = 180,
    api_key: str = "",
    provider: str = DEFAULT_LLM_PROVIDER,
) -> dict:
    """Pass 1: Send a context-budgeted chat digest to the configured LLM provider and return a structured JSON
    report including topic segments if the user switched topics mid-conversation."""
    digest_input = build_llm_digest_input(chat, max_chars=max_chars)
    system_prompt = (
        "You are a conversation archivist. Analyze the conversation excerpt and output ONLY a valid JSON object. "
        "If the user switches topics during the conversation, list each distinct topic segment (up to 4) in 'segments'.\n"
        "Required JSON schema:\n"
        '{\n'
        '  "primary_topic": "short canonical English topic name (2-5 words)",\n'
        '  "summary": "concise 2-3 sentence summary of the problem, discussion, and outcome",\n'
        '  "intent": "one of: coding, debugging, architecture, learning, writing, research, data-analysis, translation, planning, general",\n'
        '  "subtopics": ["3 to 6 specific subtopics in canonical English"],\n'
        '  "entities_and_tools": ["specific libraries, tools, frameworks, texts, or domain concepts mentioned"],\n'
        '  "canonical_keywords": ["8 to 12 normalized English keywords/phrases for cross-chat topic linking"],\n'
        '  "segments": [\n'
        '    {"part": "Opening / Middle / Closing", "topic": "canonical English topic for this segment", "summary": "1 sentence summary", "keywords": ["3-5 keywords"]}\n'
        '  ]\n'
        '}'
    )
    user_prompt = f"Analyze this conversation and return the JSON report:\n\n{digest_input}"
    parsed, raw_content = _invoke_local_llm_json(system_prompt, user_prompt, model, base_url=base_url, timeout_sec=timeout_sec, api_key=api_key, provider=provider)
    return normalize_llm_report(parsed, fallback_text=raw_content)


# Backward-compatible alias for earlier releases.
call_local_llm_for_chat = call_llm_for_chat

def grade_cross_chat_topics_pass2(
    chats: list[Chat],
    db_path: Path,
    model: str,
    base_url: str = DEFAULT_LLM_URL,
    max_candidates_per_chat: int = 25,
    min_grade: float = 0.35,
    api_key: str = "",
    provider: str = DEFAULT_LLM_PROVIDER,
    log: Callable[[str], None] | None = None,
) -> int:
    """Pass 2: Build the global topic catalog across all chats and ask the configured LLM provider to grade
    how strongly each chat (or segment of a chat) connects to topics sourced from OTHER chats
    (strictly excluding any topic whose only source is the same chat)."""
    if not model.strip() or len(chats) < 2:
        return 0
    model = model.strip()
    cache_model = f"{provider}:{base_url.rstrip('/')}:{model}"

    # 1. Build global catalog of canonical topics -> {label, sources: set[int], keywords: set[str]}
    topic_catalog: dict[str, dict] = {}

    def _register_topic(chat_idx: int, label: str, extra_kw: Iterable[str]) -> None:
        clean_lbl = re.sub(r"\s+", " ", label.strip())
        if len(clean_lbl) < 3:
            return
        norm_key = " ".join(tokenize(clean_lbl))
        if not norm_key:
            return
        if norm_key not in topic_catalog:
            topic_catalog[norm_key] = {
                "key": norm_key,
                "label": clean_lbl,
                "sources": set(),
                "tokens": set(tokenize(clean_lbl)),
            }
        topic_catalog[norm_key]["sources"].add(chat_idx)
        for kw in extra_kw:
            topic_catalog[norm_key]["tokens"].update(tokenize(kw))

    for i, c in enumerate(chats):
        rep = c.llm_report
        if not rep:
            continue
        kws = rep.get("canonical_keywords", []) or []
        if rep.get("primary_topic"):
            _register_topic(i, rep["primary_topic"], kws)
        for sub in (rep.get("subtopics", []) or [])[:4]:
            _register_topic(i, sub, kws[:4])
        for seg in (rep.get("segments", []) or []):
            if isinstance(seg, dict) and seg.get("topic"):
                _register_topic(i, seg["topic"], seg.get("keywords", []) or [])

    if not topic_catalog:
        return 0

    conn = sqlite3.connect(str(db_path))
    graded_chats = 0
    cached_grades = 0
    try:
        with conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS llm_pass2_grades (
                    digest TEXT,
                    model TEXT,
                    catalog_hash TEXT,
                    grades_json TEXT,
                    updated_at TEXT,
                    PRIMARY KEY (digest, model, catalog_hash)
                )"""
            )
        cur = conn.cursor()

        for i, c in enumerate(chats):
            rep = c.llm_report
            if not rep or not any(rep.values()):
                continue

            # Exclude any topic that ONLY originated from chat `i` itself
            external_topics = [
                info for info in topic_catalog.values()
                if len(info["sources"] - {i}) > 0
            ]
            if not external_topics:
                continue

            # Collect all tokens from this chat's Pass-1 report + segments to shortlist top candidates
            chat_rep_tokens = set(tokenize(rep.get("primary_topic", "") + " " + rep.get("summary", "")))
            for kw in rep.get("canonical_keywords", []) or []:
                chat_rep_tokens.update(tokenize(kw))
            for sub in rep.get("subtopics", []) or []:
                chat_rep_tokens.update(tokenize(sub))
            for seg in rep.get("segments", []) or []:
                if isinstance(seg, dict):
                    chat_rep_tokens.update(tokenize(str(seg.get("topic", "")) + " " + str(seg.get("summary", ""))))
                    for skw in seg.get("keywords", []) or []:
                        chat_rep_tokens.update(tokenize(skw))

            # Score external topics by token overlap + multi-chat popularity so Pass-2 prompt stays <600 tokens
            scored_ext = []
            for info in external_topics:
                overlap = len(chat_rep_tokens & info["tokens"])
                popularity = len(info["sources"] - {i})
                scored_ext.append((overlap * 2.5 + math.log1p(popularity), info["key"], info))
            scored_ext.sort(key=lambda x: (-x[0], x[1]))
            shortlist = [x[2] for x in scored_ext[:max_candidates_per_chat]]

            cat_sig = hashlib.sha256(
                ("|".join(t["key"] for t in shortlist)).encode("utf-8", errors="ignore")
            ).hexdigest()[:16]

            if c.digest:
                row = cur.execute(
                    "SELECT grades_json FROM llm_pass2_grades WHERE digest = ? AND model = ? AND catalog_hash = ?",
                    (c.digest, cache_model, cat_sig),
                ).fetchone()
                if row and row[0]:
                    try:
                        c.llm_report["cross_topic_grades"] = json.loads(row[0])
                        cached_grades += 1
                        continue
                    except Exception:
                        pass

            log_msg(log, f"LLM provider Pass-2 [{model}] grading external topics for {i + 1}/{len(chats)}: {c.title[:50]}…")
            segments_desc = "\n".join(
                f"- [{s.get('part', f'Part {idx+1}')}] Topic: {s.get('topic', '')} | Summary: {s.get('summary', '')} | Keywords: {', '.join(s.get('keywords', []))}"
                for idx, s in enumerate(rep.get("segments") or [])
            )
            candidates_desc = "\n".join(
                f"T{idx + 1}: {t['label']}"
                for idx, t in enumerate(shortlist)
            )

            sys_p2 = (
                "You evaluate how strongly a conversation (or one of its topic segments) connects to external topics "
                "from other conversations in the user's archive. Output ONLY valid JSON:\n"
                '{\n'
                '  "matches": [\n'
                '    {"topic_id": "T1", "segment": "Part 1", "score": 0.85, "reason": "short explanation"}\n'
                '  ]\n'
                '}\n'
                "Rules: Only include external topics with score >= 0.35 (on a 0.0 to 1.0 scale, where 1.0 = exact same subject, "
                "0.7 = closely related subtopic/workflow, 0.4 = partial thematic overlap). Maximum 8 matches."
            )
            usr_p2 = (
                f"Chat Title: {c.title}\n"
                f"Overall Summary: {rep.get('summary', '')}\n"
                f"Chat Segments:\n{segments_desc}\n\n"
                f"External Topics from OTHER Chats (self-topics excluded):\n{candidates_desc}\n\n"
                "Grade which external topics connect to this chat or its segments:"
            )

            try:
                parsed_p2, _ = _invoke_local_llm_json(sys_p2, usr_p2, model, base_url=base_url, timeout_sec=120, api_key=api_key, provider=provider)
                raw_matches = (parsed_p2 or {}).get("matches", []) if isinstance(parsed_p2, dict) else []
                clean_grades = []
                id_map = {f"T{idx + 1}": t for idx, t in enumerate(shortlist)}
                for m in raw_matches if isinstance(raw_matches, list) else []:
                    if not isinstance(m, dict):
                        continue
                    tid = str(m.get("topic_id", "")).strip().upper()
                    t_info = id_map.get(tid)
                    if not t_info:
                        # Also allow matching by exact topic label if model returned label instead of T-id
                        for cand in shortlist:
                            if cand["label"].casefold() == str(m.get("topic_id") or m.get("topic") or "").strip().casefold():
                                t_info = cand
                                break
                    if not t_info:
                        continue
                    try:
                        sc = float(m.get("score", 0.0))
                        if sc > 1.0 and sc <= 10.0:
                            sc = sc / 10.0
                        elif sc > 10.0:
                            sc = sc / 100.0
                    except (ValueError, TypeError):
                        continue
                    if sc < min_grade:
                        continue
                    clean_grades.append({
                        "topic": t_info["label"],
                        "topic_key": t_info["key"],
                        "segment": str(m.get("segment") or "Full chat")[:40],
                        "score": round(min(1.0, sc), 3),
                        "reason": str(m.get("reason") or "")[:140],
                    })
                clean_grades.sort(key=lambda x: -x["score"])
                c.llm_report["cross_topic_grades"] = clean_grades[:8]
                graded_chats += 1
                if c.digest:
                    with conn:
                        conn.execute(
                            "INSERT OR REPLACE INTO llm_pass2_grades (digest, model, catalog_hash, grades_json, updated_at) VALUES (?, ?, ?, ?, ?)",
                            (c.digest, cache_model, cat_sig, json.dumps(clean_grades[:8], ensure_ascii=False), datetime.now().astimezone().isoformat()),
                        )
            except Exception as e:
                log_msg(log, f"  ✗ LLM provider Pass-2 failed on '{c.title[:40]}': {e}")
    finally:
        conn.close()

    log_msg(log, f"LLM provider Pass-2 complete: {graded_chats} newly graded, {cached_grades} loaded from SQLite cache.")
    return graded_chats + cached_grades

def generate_llm_reports(
    chats: list[Chat],
    db_path: Path,
    model: str,
    base_url: str = DEFAULT_LLM_URL,
    max_chars: int = DEFAULT_LLM_MAX_CHARS,
    run_pass2: bool = False,
    api_key: str = "",
    provider: str = DEFAULT_LLM_PROVIDER,
    log: Callable[[str], None] | None = None,
) -> int:
    """Generate or load cached per-chat reports from the configured LLM provider (Pass 1) and optionally
    grade cross-chat topic connections excluding self-sourced topics (Pass 2)."""
    if not model.strip():
        return 0
    model = model.strip()
    cache_model = f"{provider}:{base_url.rstrip('/')}:{model}"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    cached_count = 0
    generated_count = 0
    try:
        with conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS llm_reports (
                    digest TEXT,
                    model TEXT,
                    report_json TEXT,
                    updated_at TEXT,
                    PRIMARY KEY (digest, model)
                )"""
            )
        cur = conn.cursor()
        for idx, chat in enumerate(chats, 1):
            if chat.digest:
                row = cur.execute(
                    "SELECT report_json FROM llm_reports WHERE digest = ? AND model = ?",
                    (chat.digest, cache_model),
                ).fetchone()
                if row and row[0]:
                    try:
                        chat.llm_report = normalize_llm_report(json.loads(row[0]))
                        cached_count += 1
                        continue
                    except Exception:
                        pass
            log_msg(log, f"LLM provider Pass-1 [{model}] summarizing {idx}/{len(chats)}: {chat.title[:55]}…")
            try:
                report = call_llm_for_chat(chat, model=model, base_url=base_url, max_chars=max_chars, api_key=api_key, provider=provider)
                chat.llm_report = report
                generated_count += 1
                if chat.digest and any(report.values()):
                    with conn:
                        conn.execute(
                            "INSERT OR REPLACE INTO llm_reports (digest, model, report_json, updated_at) VALUES (?, ?, ?, ?)",
                            (chat.digest, cache_model, json.dumps(report, ensure_ascii=False), datetime.now().astimezone().isoformat()),
                        )
            except Exception as e:
                log_msg(log, f"  ✗ LLM provider Pass-1 failed on '{chat.title[:40]}': {e}")
    finally:
        conn.close()
    log_msg(log, f"LLM provider Pass-1 reports ready: {generated_count} newly generated, {cached_count} loaded from SQLite cache.")
    if run_pass2 and len(chats) >= 2:
        grade_cross_chat_topics_pass2(chats, db_path=db_path, model=model, base_url=base_url, api_key=api_key, provider=provider, log=log)
    return generated_count + cached_count

def export_online_ai_bundle(
    chats: list[Chat],
    outdir: Path,
    max_chars_per_chat: int = 2_400,
    chunk_chars: int = 600_000,
    log: Callable[[str], None] | None = None,
) -> list[str]:
    """Export compact, upload-ready Markdown bundle(s) for online AI web UIs
    (Gemini, NotebookLM, Claude Projects, ChatGPT) with an embedded prompt to
    categorize/search and optionally emit JSON compatible with --import-reports."""
    outdir.mkdir(parents=True, exist_ok=True)
    prompt_header = (
        "# AI Chat Archive — Online AI Categorization & Search Bundle\n\n"
        "Upload this file to Gemini, NotebookLM, Claude, or ChatGPT, subject to each service's context and upload limits.\n\n"
        "## Suggested Prompt to Paste\n"
        "```text\n"
        "Read all conversations in this archive. Group them into cohesive topics, "
        "identify cross-chat themes, and output a JSON array where each element has:\n"
        '{"chat_id": <int>, "digest": "<exact digest>", "primary_topic": "...", '
        '"summary": "2-sentence summary", "intent": "coding|debugging|research|writing|planning|general", '
        '"subtopics": ["..."], "entities_and_tools": ["..."], "canonical_keywords": ["..."], '
        '"segments": [{"part": "Opening/Middle/Closing", "topic": "...", "summary": "..."}]}\n'
        "```\n\n---\n\n"
    )
    parts: list[str] = []
    cur_buf: list[str] = [prompt_header]
    cur_len = len(prompt_header)

    for idx, c in enumerate(chats, 1):
        digest_snip = build_llm_digest_input(c, max_chars=max_chars_per_chat)
        entry = f"## Chat #{idx} (digest: `{c.digest[:16]}`)\n\n{digest_snip}\n\n---\n\n"
        if cur_len + len(entry) > chunk_chars and len(cur_buf) > 1:
            parts.append("".join(cur_buf))
            cur_buf = [prompt_header, entry]
            cur_len = len(prompt_header) + len(entry)
        else:
            cur_buf.append(entry)
            cur_len += len(entry)
    if cur_buf:
        parts.append("".join(cur_buf))

    written: list[str] = []
    for p_idx, content in enumerate(parts, 1):
        fname = "online_ai_bundle.md" if len(parts) == 1 else f"online_ai_bundle_part{p_idx}.md"
        fpath = outdir / fname
        fpath.write_text(content, encoding="utf-8")
        written.append(str(fpath))
    log_msg(log, f"Exported {len(written)} online AI upload bundle(s) ({len(chats)} chats).")
    return written

def import_online_ai_reports(chats: list[Chat], json_path: Path, log: Callable[[str], None] | None = None) -> int:
    """Import categorized JSON reports produced by an online AI (Gemini/Claude/ChatGPT)
    into the current chats list by matching chat_id, digest prefix, or title."""
    raw_text = json_path.read_text(encoding="utf-8", errors="replace").strip()
    raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text, flags=re.I)
    raw_text = re.sub(r"\s*```$", "", raw_text)
    data = json.loads(raw_text)
    if isinstance(data, dict):
        data = data.get("chats") or data.get("reports") or data.get("items") or [data]
    if not isinstance(data, list):
        raise ValueError("Imported JSON must be a list of chat report objects.")

    by_digest_prefix = {c.digest[:16]: c for c in chats if c.digest}
    by_full_digest = {c.digest: c for c in chats if c.digest}
    by_title = {c.title.casefold().strip(): c for c in chats if c.title}

    applied = 0
    for item in data:
        if not isinstance(item, dict):
            continue
        target: Chat | None = None
        d = str(item.get("digest") or "").strip()
        if d and d in by_full_digest:
            target = by_full_digest[d]
        elif d and d[:16] in by_digest_prefix:
            target = by_digest_prefix[d[:16]]
        elif item.get("chat_id") is not None:
            try:
                cid = int(item["chat_id"])
                if 1 <= cid <= len(chats):
                    target = chats[cid - 1]
            except (ValueError, TypeError):
                pass
        if target is None and item.get("title"):
            target = by_title.get(str(item["title"]).casefold().strip())
        if target is not None:
            rep = item.get("report") if isinstance(item.get("report"), dict) else item
            target.llm_report = normalize_llm_report(rep)
            applied += 1
    log_msg(log, f"Imported online AI categorization for {applied}/{len(chats)} chat(s) from {json_path.name}.")
    return applied

def apply_llm_report_features(chat: Chat, llm_mode: str = "hybrid") -> None:
    """Inject the configured LLM provider's structured report (including multi-topic segments and Pass-2
    cross-topic grades) into the chat's feature Counter."""
    rep = chat.llm_report
    if not rep or not any(rep.values()):
        return
    if llm_mode == "report-only":
        chat.features = Counter()

    # Primary topic gets highest weight, both as a phrase and individual tokens
    pt = rep.get("primary_topic", "")
    if pt:
        pt_tokens = tokenize(pt)
        if pt_tokens:
            chat.features["r:" + " ".join(pt_tokens)] += 5.0
            for t in pt_tokens:
                chat.features["r:" + t] += 3.8

    # Multi-topic segments (so a chat that switches topics mid-stream links to each topic cluster)
    for seg in rep.get("segments", []) or []:
        if not isinstance(seg, dict):
            continue
        st_toks = tokenize(str(seg.get("topic", "")))
        if st_toks:
            chat.features["r:" + " ".join(st_toks)] += 4.2
            for t in st_toks:
                chat.features["r:" + t] += 3.0
        for skw in seg.get("keywords", []) or []:
            for t in tokenize(skw):
                chat.features["r:" + t] += 2.4

    # Pass-2 Cross-Topic Grades (links verified against external chat topics)
    for cg in rep.get("cross_topic_grades", []) or []:
        if not isinstance(cg, dict):
            continue
        tkey = str(cg.get("topic_key") or "")
        score = float(cg.get("score") or 0.0)
        if tkey and score >= 0.35:
            chat.features["r:" + tkey] += 5.5 * score
            for t in tkey.split():
                chat.features["r:" + t] += 3.5 * score

    # Subtopics
    for sub in rep.get("subtopics", []) or []:
        st_tokens = tokenize(sub)
        if st_tokens:
            chat.features["r:" + " ".join(st_tokens)] += 4.0
            for t in st_tokens:
                chat.features["r:" + t] += 3.0

    # Canonical keywords (cross-lingual bridge)
    for kw in rep.get("canonical_keywords", []) or []:
        kw_tokens = tokenize(kw)
        if kw_tokens:
            if len(kw_tokens) > 1:
                chat.features["r:" + " ".join(kw_tokens)] += 3.6
            for t in kw_tokens:
                chat.features["r:" + t] += 2.8

    # Entities, libraries, and tools
    for ent in rep.get("entities_and_tools", []) or []:
        ent_tokens = tokenize(ent)
        if ent_tokens:
            chat.features["r:" + " ".join(ent_tokens)] += 3.2
            for t in ent_tokens:
                chat.features["r:" + t] += 2.4

    # Report summary sentences
    summary_tokens = tokenize(rep.get("summary", ""))
    for t in summary_tokens:
        chat.features["r:" + t] += 1.6
    for a, b in zip(summary_tokens, summary_tokens[1:]):
        chat.features["r:" + a + " " + b] += 1.8
