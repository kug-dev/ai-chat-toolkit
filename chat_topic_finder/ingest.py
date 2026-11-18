"""Ingest module for Chat Topic Finder."""
from __future__ import annotations
from .common import *
from .text import chat_from_text, extract_date_from_string, fallback_title_from_path, log_msg, parse_raw_json

def safe_read_zip(zf: zipfile.ZipFile, member: zipfile.ZipInfo, max_bytes: int = 8_000_000) -> str:
    with zf.open(member) as f:
        raw = f.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raw = raw[:max_bytes]
    return raw.decode("utf-8", errors="replace")

def inspect_manifest(
    zf: zipfile.ZipFile,
    archive_path: str,
    health: ArchiveHealth,
    repair_entries: list[dict] | None = None,
) -> tuple[dict[str, dict], str]:
    manifests = [i for i in zf.infolist() if Path(i.filename).name == "_manifest.json"]
    result: dict[str, dict] = {}
    site_name = ""
    if not manifests:
        health.notes = "No _manifest.json found"
        return result, site_name
    try:
        obj = json.loads(safe_read_zip(zf, manifests[-1]))
        site_name = str(obj.get("site", "")) if isinstance(obj, dict) else ""
        chats = obj.get("chats", []) if isinstance(obj, dict) else []
        health.manifest_chats = len(chats) if isinstance(chats, list) else 0
        errors = obj.get("errors", []) if isinstance(obj, dict) else []
        health.manifest_errors = len(errors) if isinstance(errors, list) else 0
        error_ids = {str(err.get("id", "")): str(err.get("error", "")) for err in errors if isinstance(err, dict) and err.get("id")}
        for entry in chats if isinstance(chats, list) else []:
            if not isinstance(entry, dict):
                continue
            saved = entry.get("files_saved", []) or []
            missing = entry.get("files_missing", []) or []
            skipped = entry.get("files_skipped", []) or []
            health.files_saved += len(saved)
            health.files_missing += len(missing)
            health.files_skipped += len(skipped)
            cid = str(entry.get("id", ""))
            if cid:
                result[cid] = entry
                if repair_entries is not None and (missing or cid in error_ids):
                    repair_entries.append({
                        "id": cid,
                        "title": str(entry.get("title", "")),
                        "site": str(entry.get("site", "") or site_name),
                        "archive": Path(archive_path).name,
                        "files_missing": missing,
                        "error": error_ids.get(cid, ""),
                    })
    except Exception as e:
        health.notes = f"Manifest parse error: {e}"
    return result, site_name

GENERATED_MEDIA_EXTS = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".apng", ".svg", ".bmp",
    ".tif", ".tiff", ".heic", ".heif", ".avif", ".ico",
    ".mp4", ".webm", ".mov", ".mkv", ".avi", ".m4v",
    ".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac", ".opus",
}


def _count_generated_media(infos: list[zipfile.ZipInfo], chat_directory: str) -> int:
    """Count saved media files under this chat's generated/ or artifacts/ folders."""
    prefix = chat_directory.rstrip("/") + "/" if chat_directory else ""
    count = 0
    for info in infos:
        path = info.filename.replace("\\", "/")
        if prefix:
            if not path.startswith(prefix):
                continue
            relative = path[len(prefix):]
        else:
            relative = path
        parts = relative.split("/")
        if len(parts) < 2 or parts[0].casefold() not in {"generated", "artifacts"}:
            continue
        if Path(parts[-1]).suffix.casefold() in GENERATED_MEDIA_EXTS:
            count += 1
    return count


def _has_meaningful_transcript_text(chat: Chat) -> bool:
    """Ignore media embeds and stock completion phrases, but retain real prompts/replies."""
    value = "\n".join((chat.user_text, chat.assistant_text, chat.text))
    value = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", value)
    value = re.sub(r"\[[^\]]*\]\([^)]*\)", " ", value)
    boilerplate = (
        r"\b(?:here(?:'s| is) (?:the|your) )?"
        r"(?:(?:generated|created) )?(?:image|picture|video|audio)"
        r"(?: (?:was|has been) (?:generated|created))?(?: successfully)?\b"
    )
    value = re.sub(boilerplate, " ", value, flags=re.I)
    value = re.sub(r"[\W_]+", " ", value, flags=re.UNICODE)
    return bool(re.search(r"\w{2,}", value, flags=re.UNICODE))


def load_zip(
    path: Path,
    health_list: list[ArchiveHealth],
    log: Callable[[str], None] | None = None,
    repair_entries: list[dict] | None = None,
) -> list[Chat]:
    health = ArchiveHealth(str(path))
    health_list.append(health)
    chats: list[Chat] = []
    try:
        with zipfile.ZipFile(path) as zf:
            bad = zf.testzip()
            health.zip_status = f"CRC error: {bad}" if bad else "OK"
            manifest_map, archive_site = inspect_manifest(zf, str(path), health, repair_entries=repair_entries)
            # Map 8-char ID prefix or full ID for directory matching
            manifest_by_prefix: dict[str, dict] = {}
            for cid, entry in manifest_map.items():
                manifest_by_prefix[cid[:8]] = entry
                manifest_by_prefix[cid] = entry

            infos = [i for i in zf.infolist() if not i.is_dir()]
            by_dir: dict[str, dict[str, zipfile.ZipInfo]] = defaultdict(dict)
            artifacts_by_dir: dict[str, list[zipfile.ZipInfo]] = defaultdict(list)

            for info in infos:
                normalized = info.filename.replace("\\", "/")
                base = normalized.rsplit("/", 1)[-1].casefold()
                directory = normalized.rsplit("/", 1)[0] if "/" in normalized else ""
                if base in ("chat.md", "raw.json"):
                    by_dir[directory][base] = info
                elif "/artifacts/_latest/" in normalized or "/artifacts/" in normalized:
                    if not base.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm", ".zip", ".pdf")):
                        chat_dir = normalized.split("/artifacts/", 1)[0]
                        artifacts_by_dir[chat_dir].append(info)

            selected = []
            for directory, files in by_dir.items():
                pick = files.get("chat.md")
                if pick:
                    selected.append((directory, pick, "markdown"))
                    health.chat_markdown_files += 1
                elif files.get("raw.json"):
                    selected.append((directory, files["raw.json"], "json"))
                    health.raw_json_fallbacks += 1
            if not selected:
                for info in infos:
                    name = info.filename.rsplit("/", 1)[-1].casefold()
                    if name.endswith((".md", ".txt")) and name not in ("readme.md", "license.txt") and not name.startswith("_"):
                        selected.append((info.filename, info, "markdown"))

            for directory, info, kind in selected:
                raw = safe_read_zip(zf, info)
                fallback = fallback_title_from_path(directory or info.filename)
                title, body = fallback, raw
                json_date = ""
                if kind == "json":
                    title, _, _, json_date = parse_raw_json(raw, fallback)
                    body = raw  # Preserve structured turns for branch-family matching.

                folder_name = directory.rsplit("/", 1)[-1] if directory else ""
                id_match = re.search(r"_([0-9a-zA-Z-]{6,})$", folder_name)
                short_id = id_match.group(1) if id_match else ""
                m_entry = manifest_by_prefix.get(short_id, {})

                conv_id = str(m_entry.get("id", short_id))
                chat_date = extract_date_from_string(str(m_entry.get("updated", ""))) or extract_date_from_string(folder_name) or json_date
                site = str(m_entry.get("site", "") or archive_site)
                project_tag = str(m_entry.get("tag", ""))
                model_slug = str(m_entry.get("model", ""))

                # Collect artifact filenames & text for Artifact-Aware Topic Matching
                art_names: list[str] = []
                art_texts: list[str] = []
                for art_rec in m_entry.get("artifacts", []) or []:
                    if isinstance(art_rec, dict) and art_rec.get("title"):
                        art_names.append(str(art_rec["title"]))
                for art_info in artifacts_by_dir.get(directory, [])[:12]:
                    aname = Path(art_info.filename).name
                    if aname not in art_names:
                        art_names.append(aname)
                    if "/_latest/" in art_info.filename.replace("\\", "/") or len(art_texts) < 4:
                        try:
                            art_texts.append(safe_read_zip(zf, art_info, max_bytes=120_000))
                        except Exception:
                            pass

                chat = chat_from_text(
                    title,
                    body,
                    source=f"{path.name}::{info.filename}",
                    archive=str(path),
                    member=info.filename,
                    chat_date=chat_date,
                    site=site,
                    project_tag=project_tag,
                    model_slug=model_slug,
                    conv_id=conv_id,
                    artifact_text="\n".join(art_names + art_texts),
                    artifact_names=art_names,
                )
                media_count = _count_generated_media(infos, directory)
                chat.generated_media_count = media_count
                chat.generated_media_only = media_count > 0 and not _has_meaningful_transcript_text(chat)
                if chat.title in ("Untitled", "raw", "raw.json") and title:
                    chat.title = title
                chats.append(chat)
    except (zipfile.BadZipFile, OSError, RuntimeError) as e:
        health.zip_status = f"FAILED: {e}"
        health.notes = str(e)
        log_msg(log, f"Cannot read ZIP {path.name}: {e}")
    log_msg(log, f"Read {path.name}: {len(chats)} chat(s), ZIP {health.zip_status}")
    return chats

def discover_inputs(paths: Iterable[str | Path]) -> tuple[list[Path], list[Path]]:
    zips: set[Path] = set()
    loose: set[Path] = set()
    for p0 in paths:
        p = Path(p0).expanduser().resolve()
        if not p.exists():
            continue
        if p.is_file():
            if p.suffix.casefold() == ".zip":
                zips.add(p)
            elif p.name.casefold() in ("chat.md", "raw.json") or p.suffix.casefold() in (".md", ".txt"):
                loose.add(p)
            continue
        for root, dirs, files in os.walk(p):
            dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", "node_modules", ".venv", "venv"}]
            for name in files:
                full = Path(root) / name
                low = name.casefold()
                if low.endswith(".zip"):
                    zips.add(full.resolve())
                elif low in ("chat.md", "raw.json"):
                    loose.add(full.resolve())
                elif Path(name).suffix.casefold() in (".md", ".txt") and not low.startswith(("readme", "license", "topic_report", "groups", "similar_pairs", "chat_index", "analysis")):
                    loose.add(full.resolve())
    return sorted(zips), sorted(loose)

def load_loose(path: Path, log: Callable[[str], None] | None = None) -> Chat | None:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        log_msg(log, f"Cannot read {path}: {e}")
        return None
    title = fallback_title_from_path(str(path))
    kind = "json" if path.name.casefold() == "raw.json" or raw.lstrip().startswith(("{", "[")) else "markdown"
    json_date = ""
    if kind == "json":
        title, _, _, json_date = parse_raw_json(raw, title)
    chat = chat_from_text(title, raw, source=str(path), member=str(path), chat_date=json_date)
    log_msg(log, f"Read loose file: {path.name}")
    return chat
