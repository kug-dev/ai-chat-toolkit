"""Text module for Chat Topic Finder."""
from __future__ import annotations
from .common import *

def log_msg(cb: Callable[[str], None] | None, message: str) -> None:
    if cb:
        cb(message)

def clean_text(value: str) -> str:
    value = value.replace("\x00", " ").replace("\r\n", "\n").replace("\r", "\n")
    value = unicodedata.normalize("NFKC", value)
    # Strip Markdown images before URLs; otherwise the URL regex leaves image alt text behind.
    value = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", value)
    value = MEDIA_URL_RE.sub(" ", value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()

def normalize_token(token: str) -> str:
    token = unicodedata.normalize("NFKC", token).casefold().replace("׳", "'").replace("״", '"')
    # Removing combining marks is useful for Hebrew nikkud and Latin accents.
    token = "".join(ch for ch in unicodedata.normalize("NFD", token) if not unicodedata.category(ch).startswith("M"))
    return token.strip("'-’ʼ")

def hebrew_stem(token: str) -> str | None:
    """Lightweight Hebrew/Yiddish morphological normalizer (prefix/suffix stripping)."""
    if len(token) < 4 or not HEBREW_CHAR_RE.search(token):
        return None
    w = token.translate(HEBREW_FINAL_MAP)
    # Strip common compound or single prefixes if the remaining root stays >= 3 chars.
    for pre in HEBREW_DOUBLE_PREFIXES:
        if w.startswith(pre) and len(w) - len(pre) >= 3:
            w = w[len(pre):]
            break
    else:
        for pre in HEBREW_SINGLE_PREFIXES:
            if w.startswith(pre) and len(w) - 1 >= 3:
                w = w[1:]
                break
    for suf in HEBREW_SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            w = w[:-len(suf)]
            break
    w = w.translate(HEBREW_FINAL_MAP)
    if len(w) >= 3 and w != token.translate(HEBREW_FINAL_MAP) and w not in STOPWORDS:
        return w
    return None

def extract_code_blocks(text: str) -> tuple[str, str, list[str]]:
    """Separate fenced code blocks from prose and return (prose, code_text, code_langs)."""
    langs: list[str] = []
    code_parts: list[str] = []

    def _repl(m: re.Match) -> str:
        lang = (m.group(1) or "").strip().casefold()
        body = m.group(2) or ""
        if lang and lang not in langs and len(lang) <= 20:
            langs.append(lang)
        if body.strip():
            code_parts.append(body)
        return " "

    prose = CODE_BLOCK_RE.sub(_repl, text)
    return prose, "\n".join(code_parts), langs

def tokenize(text: str) -> list[str]:
    out = []
    for item in TOKEN_RE.findall(text):
        t = normalize_token(item)
        if len(t) < 2 or t in STOPWORDS or not any(c.isalpha() for c in t):
            continue
        out.append(t)
    return out

def tokenize_code(code_text: str) -> list[str]:
    """Extract high-signal identifiers (including snake_case/camelCase splits) from code."""
    out: list[str] = []
    for raw in CODE_IDENT_RE.findall(code_text):
        low = raw.casefold()
        if low in CODE_STOPWORDS or low in STOPWORDS or len(low) < 3:
            continue
        out.append(low)
        # Also split camelCase / snake_case into sub-identifiers
        parts = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", raw).casefold().split("_")
        if len(parts) > 1:
            for p in parts:
                if len(p) >= 3 and p not in CODE_STOPWORDS and p not in STOPWORDS:
                    out.append(p)
    return out

def extract_date_from_string(s: str) -> str:
    if not s:
        return ""
    m = DATE_ISO_RE.search(s)
    return m.group(1) if m else ""

def parse_chat_markdown(text: str, fallback_title: str = "Untitled") -> tuple[str, str, str, str]:
    """Return title, user-authored text, assistant text, and first detected date."""
    lines = text.splitlines()
    title = fallback_title
    body_start = 0
    for i, line in enumerate(lines[:30]):
        if line.lstrip().startswith("# "):
            title = line.lstrip()[2:].strip() or fallback_title
            body_start = i + 1
            break
    role = None
    user_parts: list[str] = []
    assistant_parts: list[str] = []
    current: list[str] = []
    found_role = False
    detected_date = ""

    def commit() -> None:
        if not current or not role:
            return
        segment = "\n".join(current).strip()
        if role in ("user", "human"):
            user_parts.append(segment)
        elif role in ("assistant", "model"):
            assistant_parts.append(segment)

    for line in lines[body_start:]:
        m = ROLE_RE.match(line)
        if m:
            commit()
            role = m.group(1).casefold()
            if not detected_date and m.group(2):
                detected_date = extract_date_from_string(m.group(2))
            current = []
            found_role = True
        elif line.strip() == "---" and found_role:
            commit()
            current = []
            role = None
        elif role:
            current.append(line)

    commit()
    if not found_role:
        content = "\n".join(lines[body_start:]).strip() or text
        user_parts = [content]
        assistant_parts = []
    if not detected_date:
        detected_date = extract_date_from_string("\n".join(lines[:40]))
    return title, "\n".join(user_parts), "\n".join(assistant_parts), detected_date

def extract_turns(content: str) -> list[dict[str, str]]:
    """Extract ordered role/text turns from the archive Markdown or common raw JSON layouts."""
    lines = content.splitlines()
    role = None
    current: list[str] = []
    turns: list[dict[str, str]] = []
    found_role = False

    def commit() -> None:
        nonlocal current
        value = clean_text("\n".join(current))
        if role and value:
            normalized_role = {"human": "user", "model": "assistant"}.get(role, role)
            turns.append({"role": normalized_role, "text": value})
        current = []

    for line in lines:
        match = ROLE_RE.match(line)
        if match:
            if found_role:
                commit()
            role = match.group(1).casefold()
            found_role = True
            current = []
        elif line.strip() == "---" and found_role:
            commit()
            role = None
        elif role:
            current.append(line)
    if found_role:
        commit()
        if turns:
            return turns

    # Fallback for common JSON exports with a message list or ChatGPT mapping.
    try:
        obj = json.loads(content)
    except Exception:
        obj = None
    raw_messages = []
    if isinstance(obj, dict):
        for key in ("messages", "chat_messages", "turns"):
            value = obj.get(key)
            if isinstance(value, list):
                raw_messages = value
                break
        if not raw_messages and isinstance(obj.get("mapping"), dict):
            nodes = [v.get("message") for v in obj["mapping"].values() if isinstance(v, dict) and isinstance(v.get("message"), dict)]
            raw_messages = sorted(nodes, key=lambda m: (m.get("create_time") or 0))
    for item in raw_messages:
        if not isinstance(item, dict):
            continue
        author = item.get("author") if isinstance(item.get("author"), dict) else {}
        role = item.get("role") or item.get("sender") or author.get("role") or "unknown"
        content_value = item.get("content", item.get("text", item.get("message", "")))
        if isinstance(content_value, dict):
            content_value = content_value.get("parts", content_value.get("text", content_value.get("content", "")))
        if isinstance(content_value, list):
            content_value = "\n".join(str(x) if isinstance(x, str) else str(x.get("text", x.get("content", ""))) if isinstance(x, dict) else "" for x in content_value)
        if isinstance(content_value, str) and clean_text(content_value):
            turns.append({"role": str(role).casefold(), "text": clean_text(content_value)})
    return turns

def json_text_extract(value, key_context: str = "", out: list[str] | None = None) -> list[str]:
    if out is None:
        out = []
    allowed = {
        "text", "content", "parts", "message", "prompt", "title", "body", "transcript",
        "utterance", "input", "output", "result", "summary", "user", "assistant", "messages",
        "chat_messages", "chunks", "segments", "text_content", "markdown", "value",
    }
    if isinstance(value, dict):
        for key, child in value.items():
            k = str(key).casefold()
            if k in allowed:
                json_text_extract(child, k, out)
    elif isinstance(value, list):
        for child in value:
            json_text_extract(child, key_context, out)
    elif isinstance(value, str):
        if key_context in allowed:
            s = value.strip()
            if s and not s.lower().startswith(("http://", "https://", "data:", "blob:")) and len(s) >= 2:
                out.append(s)
    return out

def parse_raw_json(text: str, fallback_title: str = "Untitled") -> tuple[str, str, str, str]:
    try:
        obj = json.loads(text)
    except Exception:
        return fallback_title, text, "", ""
    title = fallback_title
    detected_date = ""
    if isinstance(obj, dict):
        for k in ("title", "name", "conversation_title"):
            if isinstance(obj.get(k), str) and obj[k].strip():
                title = obj[k].strip()
                break
        for dk in ("updated_at", "created_at", "update_time", "create_time"):
            val = obj.get(dk)
            if isinstance(val, str):
                detected_date = extract_date_from_string(val)
            elif isinstance(val, (int, float)) and val > 1e8:
                ts = val / 1000.0 if val > 1e12 else float(val)
                try:
                    detected_date = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
                except Exception:
                    pass
            if detected_date:
                break
    strings = json_text_extract(obj)
    seen: set[str] = set()
    unique = []
    for s in strings:
        norm = re.sub(r"\s+", " ", s).strip()
        if norm and norm not in seen:
            seen.add(norm)
            unique.append(s)
    return title, "\n".join(unique), "", detected_date

def digest_chat(title: str, text: str, artifact_text: str = "") -> str:
    canonical = re.sub(r"\s+", " ", (title + "\n" + text + "\n" + artifact_text).casefold()).strip()
    return hashlib.sha256(canonical.encode("utf-8", errors="ignore")).hexdigest()

def fallback_title_from_path(path: str) -> str:
    name = Path(path.replace("\\", "/")).parent.name or Path(path).stem
    name = re.sub(r"^\d{4}-\d{2}-\d{2}_", "", name)
    name = re.sub(r"_[0-9a-fA-F-]{6,}$", "", name)
    return name.replace("_", " ").strip() or Path(path).stem

def chat_from_text(
    title: str,
    content: str,
    source: str,
    archive: str = "",
    member: str = "",
    chat_date: str = "",
    site: str = "",
    project_tag: str = "",
    model_slug: str = "",
    conv_id: str = "",
    artifact_text: str = "",
    artifact_names: list[str] | None = None,
) -> Chat:
    truncated = len(content) > MAX_TEXT_CHARS
    if truncated:
        content = content[:MAX_TEXT_CHARS]
    parsed_title, user, assistant, md_date = parse_chat_markdown(content, title)
    if not user and not assistant and content.lstrip().startswith(("{", "[")):
        parsed_title, user, assistant, md_date = parse_raw_json(content, title)

    user_prose, user_code, u_langs = extract_code_blocks(user)
    asst_prose, asst_code, a_langs = extract_code_blocks(assistant)
    langs = list(dict.fromkeys(u_langs + a_langs))
    combined_code = "\n".join(x for x in (user_code, asst_code) if x.strip())

    body = "\n".join(x for x in (user_prose, asst_prose) if x.strip()) or content
    whole = clean_text(body)
    final_date = chat_date or md_date or extract_date_from_string(member) or extract_date_from_string(source)
    return Chat(
        title=parsed_title or title,
        text=whole,
        user_text=clean_text(user_prose),
        assistant_text=clean_text(asst_prose),
        source=source,
        archive=archive,
        member=member,
        digest=digest_chat(parsed_title or title, whole, artifact_text),
        truncated=truncated,
        chat_date=final_date,
        site=site,
        project_tag=project_tag,
        model_slug=model_slug,
        conv_id=conv_id,
        code_text=combined_code[:300_000],
        code_langs=langs,
        artifact_text=clean_text(artifact_text)[:300_000],
        artifact_names=artifact_names or [],
        turns=extract_turns(content),
    )
