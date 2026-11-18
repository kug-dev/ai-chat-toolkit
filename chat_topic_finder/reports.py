"""Reports module for Chat Topic Finder."""
from __future__ import annotations
from .common import *
from .similarity import group_label, safe_slug, top_chat_terms
from .text import log_msg
from .i18n import load_locale
from .branches import detect_chat_branches

def export_grouped_archive(
    zip_out_path: Path,
    chats: list[Chat],
    groups: list[TopicGroup],
    log: Callable[[str], None] | None = None,
) -> str:
    """Write a clean, deduplicated ZIP organized by Topic Group and Unclustered folders."""
    seen_digests: set[str] = set()
    assigned_indices: set[int] = set()
    written_count = 0
    dedup_skipped = 0

    with zipfile.ZipFile(zip_out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for tg in groups:
            lbl_slug = safe_slug(group_label(tg.members, chats), 42)
            folder_prefix = f"Grouped_Chats/Group_{tg.id}_{lbl_slug}"
            for idx in tg.members:
                assigned_indices.add(idx)
                c = chats[idx]
                if c.digest and c.digest in seen_digests:
                    dedup_skipped += 1
                    continue
                if c.digest:
                    seen_digests.add(c.digest)
                date_part = f"{c.chat_date}_" if c.chat_date else ""
                chat_folder = f"{folder_prefix}/{date_part}{safe_slug(c.title, 50)}_{idx + 1:04d}"
                orig_md = None
                if c.archive and c.member and Path(c.archive).exists():
                    try:
                        with zipfile.ZipFile(c.archive) as src_zf:
                            orig_md = src_zf.read(c.member).decode("utf-8", errors="replace")
                    except Exception:
                        orig_md = None
                if orig_md is None:
                    code_sec = f"\n\n---\n\n## code blocks\n\n```\n{c.code_text}\n```\n" if c.code_text else ""
                    orig_md = f"# {c.title}\n\n- **Source:** `{c.source}`\n- **Date:** {c.chat_date or 'unknown'}\n- **Platform:** {c.site or 'unknown'}\n- **Topic Group:** {tg.id} ({lbl_slug})\n\n---\n\n## user\n\n{c.user_text or c.text}\n\n---\n\n## assistant\n\n{c.assistant_text}{code_sec}"
                zf.writestr(f"{chat_folder}/chat.md", orig_md)
                written_count += 1

        for idx, c in enumerate(chats):
            if idx in assigned_indices:
                continue
            if c.digest and c.digest in seen_digests:
                dedup_skipped += 1
                continue
            if c.digest:
                seen_digests.add(c.digest)
            date_part = f"{c.chat_date}_" if c.chat_date else ""
            chat_folder = f"Grouped_Chats/Unclustered/{date_part}{safe_slug(c.title, 50)}_{idx + 1:04d}"
            orig_md = None
            if c.archive and c.member and Path(c.archive).exists():
                try:
                    with zipfile.ZipFile(c.archive) as src_zf:
                        orig_md = src_zf.read(c.member).decode("utf-8", errors="replace")
                except Exception:
                    orig_md = None
            if orig_md is None:
                code_sec = f"\n\n---\n\n## code blocks\n\n```\n{c.code_text}\n```\n" if c.code_text else ""
                orig_md = f"# {c.title}\n\n- **Source:** `{c.source}`\n- **Date:** {c.chat_date or 'unknown'}\n- **Platform:** {c.site or 'unknown'}\n\n---\n\n## user\n\n{c.user_text or c.text}\n\n---\n\n## assistant\n\n{c.assistant_text}{code_sec}"
            zf.writestr(f"{chat_folder}/chat.md", orig_md)
            written_count += 1

    log_msg(log, f"Exported deduplicated topic archive: {zip_out_path.name} ({written_count} unique chats written, {dedup_skipped} exact duplicates omitted).")
    return str(zip_out_path)

def esc(v) -> str:
    return html.escape(str(v), quote=True)

def write_csv(path: Path, rows: list[dict], headers: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

def _matching_excerpt(text: str, terms: list[str], limit: int = 440) -> str:
    """Select a compact passage containing as many shared clues as possible."""
    text = (text or "").strip()
    if not text or not terms:
        return ""
    needles: list[str] = []
    seen: set[str] = set()
    for raw_term in terms:
        term = re.sub(r"^(?:artifact|code|report):", "", str(raw_term), flags=re.I).strip()
        key = term.casefold()
        if len(term) < 3 or key in seen:
            continue
        seen.add(key)
        needles.append(term)
    windows: list[dict] = []
    for term in needles:
        pattern = re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)", re.I)
        for match in pattern.finditer(text):
            windows.append({
                "start": max(0, match.start() - 150),
                "end": min(len(text), match.end() + 190),
                "terms": {term.casefold()},
                "hits": 1,
            })
    if not windows:
        return ""
    windows.sort(key=lambda item: item["start"])
    merged: list[dict] = []
    for item in windows:
        if merged and item["start"] <= merged[-1]["end"] + 70:
            merged[-1]["end"] = max(merged[-1]["end"], item["end"])
            merged[-1]["terms"].update(item["terms"])
            merged[-1]["hits"] += item["hits"]
        else:
            merged.append({
                "start": item["start"], "end": item["end"],
                "terms": set(item["terms"]), "hits": item["hits"],
            })
    best = max(merged, key=lambda item: (len(item["terms"]), item["hits"], -item["start"]))
    start, end = best["start"], best["end"]
    if end - start > limit:
        center = (start + end) // 2
        start = max(0, center - limit // 2)
        end = min(len(text), start + limit)
        start = max(0, end - limit)
    excerpt = text[start:end].strip()
    if start:
        excerpt = "…" + excerpt
    if end < len(text):
        excerpt += "…"
    return excerpt


def _matching_sections(chat: Chat, terms: list[str]) -> dict[str, str]:
    return {
        "user": _matching_excerpt(chat.user_text, terms),
        "assistant": _matching_excerpt(chat.assistant_text, terms),
        "code": _matching_excerpt(chat.code_text, terms, limit=360),
    }


def generate_reports(
    outdir: Path,
    chats: list[Chat],
    edges: list[dict],
    groups: list[TopicGroup],
    health: list[ArchiveHealth],
    threshold: float,
    mutual_knn: int = 12,
    max_group_size: int = 25,
    min_group_size: int = 2,
    subcluster_step: float = 0.08,
    interactive_edges: list[dict] | None = None,
    repair_entries: list[dict] | None = None,
    branch_matching: bool = True,
) -> dict[str, str]:
    outdir.mkdir(parents=True, exist_ok=True)
    from .branches import detect_chat_branches
    branch_matches, branch_families = detect_chat_branches(chats, enabled=branch_matching)
    from .i18n import load_locale
    report_phrases_json = json.dumps(load_locale("he").get("topic_report_phrases", []), ensure_ascii=False)
    chat_group: dict[int, str] = {}
    group_info = []
    edge_by_group: dict[str, list[dict]] = defaultdict(list)

    for tg in groups:
        gid = tg.id
        member_set = set(tg.members)
        for i in tg.members:
            chat_group[i] = gid
            chats[i].group_id = gid
        group_edges = [e for e in edges if e["a"] in member_set and e["b"] in member_set]
        group_info.append({
            "id": gid,
            "parent_id": tg.parent_id,
            "subclustered": tg.subclustered,
            "effective_threshold": tg.effective_threshold,
            "label": group_label(tg.members, chats),
            "members": tg.members,
            "edge_count": len(group_edges),
            "min_link_score": min((e["score"] for e in group_edges), default=0.0),
            "mean_link_score": sum(e["score"] for e in group_edges) / len(group_edges) if group_edges else 0.0,
        })
        edge_by_group[gid] = group_edges

    chat_rows = []
    for i, c in enumerate(chats):
        chat_rows.append({
            "chat_id": i + 1,
            "topic_group": chat_group.get(i, ""),
            "title": c.title,
            "date": c.chat_date,
            "site": c.site,
            "project_tag": c.project_tag,
            "llm_primary_topic": (c.llm_report or {}).get("primary_topic", ""),
            "llm_intent": (c.llm_report or {}).get("intent", ""),
            "llm_summary": (c.llm_report or {}).get("summary", ""),
            "code_languages": ", ".join(c.code_langs),
            "artifacts": ", ".join(c.artifact_names),
            "generated_media_only": c.generated_media_only,
            "generated_media_count": c.generated_media_count,
            "source": c.source,
            "archive": c.archive,
            "member": c.member,
            "characters": len(c.text),
            "token_count": len(c.tokens),
            "truncated": c.truncated,
            "exact_content_hash": c.digest,
        })
    pair_rows = []
    for e in edges:
        a, b = chats[e["a"]], chats[e["b"]]
        ga = chat_group.get(e["a"], "")
        gb = chat_group.get(e["b"], "")
        pair_group = ga if ga == gb else (f"{ga} <-> {gb}" if ga or gb else "")
        pair_rows.append({
            "similarity": round(e["score"], 4),
            "topic_group": pair_group,
            "chat_a": a.title,
            "source_a": a.source,
            "chat_b": b.title,
            "source_b": b.source,
            "shared_terms": ", ".join(e["shared_terms"]),
        })
    write_csv(
        outdir / "chat_index.csv",
        chat_rows,
        ["chat_id", "topic_group", "title", "date", "site", "project_tag", "llm_primary_topic", "llm_intent", "llm_summary", "code_languages", "artifacts", "generated_media_only", "generated_media_count", "source", "archive", "member", "characters", "token_count", "truncated", "exact_content_hash"],
    )
    write_csv(outdir / "similar_pairs.csv", pair_rows, ["similarity", "topic_group", "chat_a", "source_a", "chat_b", "source_b", "shared_terms"])
    health_rows = []
    for h in health:
        health_rows.append({
            "archive": h.archive,
            "zip_status": h.zip_status,
            "manifest_chats": h.manifest_chats,
            "chat_markdown_files": h.chat_markdown_files,
            "raw_json_fallbacks": h.raw_json_fallbacks,
            "files_saved": h.files_saved,
            "files_missing": h.files_missing,
            "files_skipped": h.files_skipped,
            "manifest_errors": h.manifest_errors,
            "notes": h.notes,
        })
    write_csv(outdir / "archive_health.csv", health_rows, ["archive", "zip_status", "manifest_chats", "chat_markdown_files", "raw_json_fallbacks", "files_saved", "files_missing", "files_skipped", "manifest_errors", "notes"])

    # Cross-Script Synergy: Write retry_chat_ids.json for conversations with missing media or errors
    repair_list = repair_entries or []
    retry_payload = {
        "created": datetime.now().astimezone().isoformat(),
        "tool": APP_NAME,
        "retry_ids": sorted({r["id"] for r in repair_list if r.get("id")}),
        "details": repair_list,
    }
    retry_path = outdir / "retry_chat_ids.json"
    retry_path.write_text(json.dumps(retry_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # Export dedicated per-chat LLM reports file when available
    llm_reports_list = [
        {
            "chat_id": i + 1,
            "title": c.title,
            "source": c.source,
            "date": c.chat_date,
            "site": c.site,
            "topic_group": chat_group.get(i, ""),
            "report": c.llm_report,
        }
        for i, c in enumerate(chats)
        if c.llm_report and any(c.llm_report.values())
    ]
    reports_json_path = outdir / "chat_reports.json"
    reports_json_path.write_text(json.dumps(llm_reports_list, ensure_ascii=False, indent=2), encoding="utf-8")

    branch_rows = [{
        "score": m["score"], "shared_turns": m["shared_turns"], "shared_chars": m["shared_chars"],
        "common_ratio": m["common_ratio"], "title_similarity": m["title_similarity"],
        "chat_a_id": m["a"] + 1, "chat_a": m["title_a"], "source_a": m["source_a"],
        "chat_b_id": m["b"] + 1, "chat_b": m["title_b"], "source_b": m["source_b"],
    } for m in branch_matches]
    write_csv(outdir / "branch_matches.csv", branch_rows, [
        "score", "shared_turns", "shared_chars", "common_ratio", "title_similarity",
        "chat_a_id", "chat_a", "source_a", "chat_b_id", "chat_b", "source_b",
    ])
    branches_json_path = outdir / "branch_families.json"
    branches_json_path.write_text(json.dumps({"families": branch_families, "matches": branch_matches}, ensure_ascii=False, indent=2), encoding="utf-8")

    analysis = {
        "tool": APP_NAME,
        "version": VERSION,
        "created": datetime.now().astimezone().isoformat(),
        "method": "offline TF-IDF + optional provider-based LLM reports + Mutual k-NN + recursive sub-clustering",
        "threshold": threshold,
        "mutual_knn": mutual_knn,
        "max_group_size": max_group_size,
        "chat_count": len(chats),
        "llm_reported_chats": len(llm_reports_list),
        "pair_count": len(edges),
        "group_count": len(groups),
        "retry_chat_count": len(retry_payload["retry_ids"]),
        "branch_match_count": len(branch_matches),
        "branch_families": branch_families,
        "warning": "Topic matches are lexical, not chatbot/LLM judgments. Oversized components are automatically refined using Mutual k-NN and recursive sub-clustering.",
        "groups": [
            {
                "id": g["id"],
                "parent_id": g["parent_id"],
                "subclustered": g["subclustered"],
                "effective_threshold": round(g["effective_threshold"], 4),
                "label": g["label"],
                "members": [{"title": chats[i].title, "source": chats[i].source, "chat_id": i + 1, "date": chats[i].chat_date, "site": chats[i].site} for i in g["members"]],
                "edge_count": g["edge_count"],
                "min_link_score": round(g["min_link_score"], 4),
                "mean_link_score": round(g["mean_link_score"], 4),
            }
            for g in group_info
        ],
        "pairs": [
            {
                "score": round(e["score"], 6),
                "chat_a": chats[e["a"]].title,
                "source_a": chats[e["a"]].source,
                "chat_b": chats[e["b"]].title,
                "source_b": chats[e["b"]].source,
                "shared_terms": e["shared_terms"],
            }
            for e in edges
        ],
        "archives": [h.__dict__ for h in health],
    }
    (outdir / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")

    all_interactive_edges = interactive_edges if interactive_edges is not None else edges
    slider_min = round(min(threshold, REPORT_PAIR_FLOOR), 2)
    embedded_chats = []
    for idx, c in enumerate(chats):
        u_snip = (c.user_text or c.text)[:2400].strip()
        a_snip = c.assistant_text[:2400].strip()
        embedded_chats.append({
            "id": idx,
            "title": c.title,
            "source": c.source,
            "date": c.chat_date,
            "month": c.chat_date[:7] if len(c.chat_date) >= 7 else "",
            "site": c.site or "unknown",
            "tag": c.project_tag,
            "langs": c.code_langs[:5],
            "artifacts": c.artifact_names[:6],
            "generated_media_only": c.generated_media_only,
            "generated_media_count": c.generated_media_count,
            "llm": c.llm_report if (c.llm_report and any(c.llm_report.values())) else None,
            "chars": len(c.text),
            "tokens": len(c.tokens),
            "snippet": c.text[:260].strip() + ("…" if len(c.text) > 260 else ""),
            "user_preview": u_snip + ("…" if len(c.user_text or c.text) > 2400 else ""),
            "asst_preview": a_snip + ("…" if len(c.assistant_text) > 2400 else ""),
            "top_terms": top_chat_terms(c, 8),
        })
    embedded_edges = [
        {
            "a": e["a"],
            "b": e["b"],
            "score": round(e["score"], 4),
            "terms": e["shared_terms"][:6],
            "match_a": _matching_sections(chats[e["a"]], e["shared_terms"]),
            "match_b": _matching_sections(chats[e["b"]], e["shared_terms"]),
        }
        for e in all_interactive_edges
    ]
    interactive_payload = json.dumps(
        {
            "config": {
                "threshold": threshold,
                "sliderMin": slider_min,
                "mutualKnn": mutual_knn,
                "maxGroupSize": max_group_size,
                "minGroupSize": min_group_size,
                "subclusterStep": subcluster_step,
            },
            "chats": embedded_chats,
            "edges": embedded_edges,
            "repair": retry_payload,
            "branchMatches": branch_matches,
            "branchFamilies": branch_families,
        },
        ensure_ascii=False,
    ).replace("</", "<\\/")

    html_path = outdir / "topic_report.html"
    total = len(chats)
    subclustered_count = sum(1 for g in group_info if g["subclustered"])
    html_parts = [f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Chat Topic Finder — Interactive Report</title><style>
:root{{color-scheme:light dark;--line:#8884;--panel:Canvas;--muted:GrayText;--accent:#0d9488;--accent-soft:color-mix(in srgb,Canvas 86%,#0d9488);--hub:#d97706;--code:#6366f1;--mark-bg:color-mix(in srgb,Canvas 70%,#f59e0b)}}
*{{box-sizing:border-box}}
body{{font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;max-width:1280px;margin:1.8rem auto;padding:0 1.2rem;background:Canvas;color:CanvasText}}
h1,h2,h3,h4{{line-height:1.25;margin-top:0}}
.muted{{color:var(--muted)}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:.65rem;margin:1rem 0}}
.stat{{border:1px solid var(--line);padding:.65rem .9rem;border-radius:.55rem;background:color-mix(in srgb,Canvas 97%,CanvasText)}}
.stat b{{font-size:1.2rem;font-variant-numeric:tabular-nums}}
.controls-panel{{border:1px solid var(--line);border-radius:.75rem;padding:1rem 1.1rem;margin:1rem 0;background:color-mix(in srgb,Canvas 96%,CanvasText)}}
.controls-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:.9rem 1.2rem;align-items:end}}
.ctrl{{display:flex;flex-direction:column;gap:.3rem;font-size:.9rem}}
.ctrl label{{font-weight:600;display:flex;justify-content:space-between;gap:.5rem}}
.ctrl input[type=range]{{width:100%;accent-color:var(--accent);cursor:pointer}}
.ctrl input[type=text],.ctrl input[type=number],.ctrl input[type=date],.ctrl select{{font:inherit;padding:.42rem .55rem;border:1px solid var(--line);border-radius:.45rem;background:Canvas;color:CanvasText}}
.btn{{font:inherit;font-size:.86rem;padding:.42rem .75rem;border:1px solid var(--line);border-radius:.45rem;background:Canvas;color:CanvasText;cursor:pointer;transition:background .15s,border-color .15s}}
.btn:hover,.btn.active{{border-color:var(--accent);background:var(--accent-soft)}}
.timeline-box{{border:1px solid var(--line);border-radius:.75rem;padding:.85rem 1.1rem;margin:1rem 0;background:Canvas}}
.heatmap-row{{display:flex;gap:.35rem;overflow-x:auto;padding:.4rem 0;align-items:flex-end}}
.hm-cell{{display:flex;flex-direction:column;align-items:center;gap:.2rem;min-width:44px;cursor:pointer;padding:.25rem;border-radius:.4rem;border:1px solid transparent}}
.hm-cell:hover,.hm-cell.active{{border-color:var(--accent);background:var(--accent-soft)}}
.hm-bar{{width:24px;border-radius:4px 4px 2px 2px;background:var(--accent);min-height:4px;transition:height .2s}}
.hm-lbl{{font-size:.7rem;color:var(--muted);font-variant-numeric:tabular-nums}}
.group{{border:1px solid var(--line);border-radius:.75rem;padding:1.1rem;margin:1.1rem 0;background:Canvas}}
.group.sub{{border-left:4px solid var(--accent)}}
.group-header{{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:baseline;gap:.5rem;margin-bottom:.4rem}}
.group-layout{{display:grid;grid-template-columns:1.15fr .85fr;gap:1.1rem;align-items:start;margin-top:.75rem}}
@media(max-width:920px){{.group-layout{{grid-template-columns:1fr}}}}
.chat-list{{display:flex;flex-direction:column;gap:.45rem;max-height:480px;overflow:auto;padding-right:.25rem}}
.chat{{padding:.65rem .75rem;border:1px solid var(--line);border-radius:.55rem;cursor:pointer;transition:border-color .15s,background .15s}}
.chat:hover,.chat.active-node{{border-color:var(--accent);background:var(--accent-soft)}}
.chat-head{{display:flex;justify-content:space-between;align-items:flex-start;gap:.5rem;flex-wrap:wrap}}
.score{{font-variant-numeric:tabular-nums;font-weight:600}}
.tag{{display:inline-block;margin:.12rem .22rem .12rem 0;padding:.08rem .42rem;border:1px solid var(--line);border-radius:.4rem;font-size:.82rem}}
.tag.clickable{{cursor:pointer}}
.tag.clickable:hover{{border-color:var(--accent);background:var(--accent-soft)}}
.badge-sub{{display:inline-block;margin-left:.45rem;padding:.1rem .45rem;border-radius:.35rem;font-size:.76rem;font-weight:600;background:var(--accent-soft);color:var(--accent);border:1px solid var(--accent)}}
.badge-hub{{display:inline-block;padding:.06rem .38rem;border-radius:.35rem;font-size:.73rem;font-weight:600;background:color-mix(in srgb,Canvas 85%,var(--hub));color:var(--hub);border:1px solid var(--hub)}}
.badge-lang{{display:inline-block;padding:.05rem .36rem;border-radius:.32rem;font-size:.72rem;font-weight:600;background:color-mix(in srgb,Canvas 86%,var(--code));color:var(--code);border:1px solid var(--code);margin-right:.22rem}}
.badge-site{{display:inline-block;padding:.05rem .36rem;border-radius:.32rem;font-size:.72rem;border:1px solid var(--line);color:var(--muted);margin-right:.22rem}}
.graph-box{{border:1px solid var(--line);border-radius:.6rem;padding:.55rem;background:color-mix(in srgb,Canvas 97%,CanvasText);display:flex;flex-direction:column;align-items:center}}
.graph-box svg{{width:100%;height:auto;max-height:360px;display:block;user-select:none}}
.graph-legend{{display:flex;flex-wrap:wrap;justify-content:space-between;width:100%;font-size:.78rem;color:var(--muted);margin-top:.35rem;gap:.4rem}}
table{{border-collapse:collapse;width:100%;margin-top:.75rem}}
th,td{{text-align:left;vertical-align:top;border-bottom:1px solid var(--line);padding:.5rem}}
tr.pair-row{{cursor:pointer;transition:background .12s}}
tr.pair-row:hover{{background:var(--accent-soft)}}
code{{overflow-wrap:anywhere}}
.warn{{border-left:4px solid #d99824;padding:.6rem .85rem;border-radius:0 .45rem .45rem 0;background:color-mix(in srgb,Canvas 92%,#d99824);margin:.9rem 0}}
details{{margin:.6rem 0}}
summary{{cursor:pointer;font-weight:600}}
.modal-backdrop{{position:fixed;inset:0;background:rgba(0,0,0,.58);display:none;align-items:center;justify-content:center;z-index:9999;padding:1rem}}
.modal-backdrop.open{{display:flex}}
.modal{{background:Canvas;color:CanvasText;border:1px solid var(--line);border-radius:.8rem;width:min(1140px,96vw);max-height:90vh;display:flex;flex-direction:column;box-shadow:0 20px 50px rgba(0,0,0,.45);overflow:hidden}}
.modal-header{{display:flex;justify-content:space-between;align-items:center;padding:.85rem 1.15rem;border-bottom:1px solid var(--line);gap:1rem}}
.modal-body{{padding:1rem 1.15rem;overflow:auto;flex:1}}
.diff-grid{{display:grid;grid-template-columns:1fr 1fr;gap:1rem}}
@media(max-width:800px){{.diff-grid{{grid-template-columns:1fr}}}}
.diff-col{{border:1px solid var(--line);border-radius:.6rem;padding:.85rem;background:color-mix(in srgb,Canvas 98%,CanvasText)}}
.turn-box{{margin-top:.6rem;padding:.65rem;border-radius:.45rem;border:1px solid var(--line);background:Canvas;white-space:pre-wrap;font-size:.9rem;max-height:300px;overflow:auto;line-height:1.45}}
.turn-label{{font-size:.76rem;font-weight:700;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin-bottom:.25rem}}
mark.hl{{background:var(--mark-bg);color:CanvasText;padding:.05rem .2rem;border-radius:.22rem;font-weight:600}}
.lang-toggle{{position:fixed;top:1rem;right:max(1rem,calc((100vw - 1280px)/2));z-index:10000;display:inline-flex;align-items:center;gap:.45rem;background:Canvas;color:CanvasText;border:1px solid var(--line);border-radius:.5rem;padding:.48rem .75rem;box-shadow:0 2px 10px #0002;cursor:pointer;font:inherit}}
.lang-toggle svg{{width:17px;height:17px;stroke:currentColor;fill:none;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}}
body[dir="rtl"]{{direction:rtl}}
body[dir="rtl"] th,body[dir="rtl"] td{{text-align:right}}
body[dir="rtl"] .group.sub{{border-left:1px solid var(--line);border-right:4px solid var(--accent)}}
body[dir="rtl"] .warn{{border-left:0;border-right:4px solid #d99824;border-radius:.45rem 0 0 .45rem}}
</style></head><body>
<button type="button" class="lang-toggle" id="lang-toggle" aria-label="Switch report language"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"></circle><path d="M3 12h18M12 3a15 15 0 0 1 0 18M12 3a15 15 0 0 0 0 18"></path></svg><span id="lang-toggle-label">עברית</span></button>
<h1>Chat Topic Finder</h1>
<p class="muted">Generated {esc(datetime.now().astimezone().strftime('%Y-%m-%d %H:%M %Z'))} · Offline TF-IDF + Hebrew Stems + Code/Artifact Indexing · Interactive Explorer</p>

<div class="stats" id="stats-bar">
  <div class="stat"><b id="st-chats">{total}</b><br>chats scanned</div>
  <div class="stat"><b id="st-groups">{len(groups)}</b><br><span id="st-groups-sub">topic groups{f' ({subclustered_count} sub-clustered)' if subclustered_count else ''}</span></div>
  <div class="stat"><b id="st-pairs">{len(edges)}</b><br>qualifying pairs</div>
  <div class="stat"><b id="st-clustered">{sum(len(g.members) for g in groups)}</b><br>clustered chats</div>
  <div class="stat"><b id="st-threshold">{threshold:.2f}</b><br>active threshold</div>
</div>

<div class="warn"><b>Interactive Explorer:</b> Adjust the sliders to <b>re-cluster live in your browser</b>, filter by <b>Platform / Cross-Platform / Code Language / Date Range</b>, click any month bar in the <b>Activity Timeline</b>, or click any chat/edge for full previews and side-by-side diffs.</div>

<section class="controls-panel">
  <div class="controls-grid">
    <div class="ctrl">
      <label for="sl-threshold"><span>Similarity Threshold</span><span id="lbl-threshold" class="score">{threshold:.2f}</span></label>
      <input type="range" id="sl-threshold" min="{slider_min:.2f}" max="0.90" step="0.01" value="{threshold:.2f}">
      <span class="muted" style="font-size:.78rem">Candidate pairs down to {slider_min:.2f} preloaded</span>
    </div>
    <div class="ctrl">
      <label for="sl-knn"><span>Mutual <i>k</i>-NN Filter (0 = Off)</span><span id="lbl-knn" class="score">{mutual_knn}</span></label>
      <input type="range" id="sl-knn" min="0" max="30" step="1" value="{mutual_knn}">
      <span class="muted" style="font-size:.78rem">Prunes weak bridge edges between hubs</span>
    </div>
    <div class="ctrl">
      <label for="sl-maxg"><span>Max Group Size (0 = Off)</span><span id="lbl-maxg" class="score">{max_group_size}</span></label>
      <input type="range" id="sl-maxg" min="0" max="80" step="1" value="{max_group_size}">
      <span class="muted" style="font-size:.78rem">Auto sub-clusters oversized components</span>
    </div>
    <div class="ctrl">
      <label for="flt-site"><span>Platform &amp; Code Filter</span><span class="muted">Min group: <input type="number" id="in-ming" min="2" max="20" value="{min_group_size}" style="width:3.2rem;padding:.1rem .25rem"></span></label>
      <div style="display:flex;gap:.35rem">
        <select id="flt-site" style="flex:1">
          <option value="">All Platforms</option>
          <option value="__cross__">★ Cross-Platform Groups Only</option>
        </select>
        <select id="flt-lang" style="flex:1"><option value="">All Code/Artifacts</option></select>
        <select id="flt-media" style="flex:1" aria-label="Generated media filter">
          <option value="">Generated media: Include all</option>
          <option value="exclude">Exclude media-only chats</option>
          <option value="only">Only media-only chats</option>
        </select>
      </div>
    </div>
    <div class="ctrl">
      <label><span>Date Range Filter</span><span id="lbl-month-active" class="muted" style="font-weight:400">All dates</span></label>
      <div style="display:flex;gap:.35rem">
        <input type="date" id="flt-from" style="flex:1" title="From date">
        <input type="date" id="flt-to" style="flex:1" title="To date">
      </div>
    </div>
    <div class="ctrl">
      <label for="search"><span>Search Titles, Terms &amp; Artifacts</span></label>
      <div style="display:flex;gap:.4rem">
        <input type="text" id="search" style="flex:1" placeholder="Filter by keyword, title, artifact…">
        <button type="button" class="btn" id="btn-reset" title="Reset all filters and clustering controls">Reset</button>
      </div>
    </div>
  </div>
  <div style="display:flex;flex-wrap:wrap;gap:.5rem;margin-top:.85rem;padding-top:.75rem;border-top:1px solid var(--line);align-items:center;justify-content:space-between">
    <div style="display:flex;gap:.5rem;flex-wrap:wrap">
      <button type="button" class="btn" id="btn-toggle-unclustered">Show Unclustered Chats</button>
      <button type="button" class="btn" id="btn-export-clusters">Export Active Clusters (JSON)</button>
      {f'<button type="button" class="btn" id="btn-download-repair" style="border-color:#d97706;color:#d97706">Download retry_chat_ids.json ({len(retry_payload["retry_ids"])} chats need repair)</button>' if retry_payload["retry_ids"] else ''}
    </div>
    <span class="muted" style="font-size:.8rem" id="active-filter-summary"></span>
  </div>
</section>

<section class="timeline-box" id="timeline-section" style="display:none">
  <div style="display:flex;justify-content:space-between;align-items:center">
    <strong style="font-size:.92rem">Topic Activity Timeline (click a month to filter)</strong>
    <span class="muted" style="font-size:.8rem" id="timeline-summary"></span>
  </div>
  <div class="heatmap-row" id="timeline-bars"></div>
</section>

<div id="groups-root">
<h2>Topic groups</h2>"""]
    if not groups:
        html_parts.append("<p>No pairs reached the selected threshold. Try lowering the Similarity Threshold slider above.</p>")
    for g in group_info:
        group = g["members"]
        terms = set()
        for e in edge_by_group[g["id"]][:12]:
            terms.update(e["shared_terms"][:4])
        med = sorted(edge_by_group[g["id"]], key=lambda e: -e["score"])
        sub_cls = " sub" if g["subclustered"] else ""
        sub_badge = f'<span class="badge-sub">Sub-cluster (threshold &ge; {g["effective_threshold"]:.2f})</span>' if g["subclustered"] else ""
        html_parts.append(f'<section class="group{sub_cls} searchable" data-search="{esc(" ".join([g["label"]] + [chats[i].title + " " + chats[i].source for i in group]))}">')
        html_parts.append(f'<div class="group-header"><h3>Group {esc(g["id"])}: {esc(g["label"])}{sub_badge}</h3><span class="muted">{len(group)} chats · {g["edge_count"]} internal links · min {g["min_link_score"]:.3f} · mean {g["mean_link_score"]:.3f}</span></div>')
        html_parts.append("<p>Shared clues: " + " ".join(f'<span class="tag">{esc(t)}</span>' for t in sorted(terms)[:18]) + "</p>")
        for i in group:
            c = chats[i]
            text = c.text[:240].strip()
            if len(c.text) > 240:
                text += "…"
            html_parts.append(f'<div class="chat"><b>{esc(c.title)}</b><br><span class="muted">{esc(c.source)}</span><p>{esc(text)}</p></div>')
        html_parts.append("<details><summary>Strongest matching pairs</summary><table><thead><tr><th>Similarity</th><th>Chat A</th><th>Chat B</th><th>Shared terms</th></tr></thead><tbody>")
        for e in med[:30]:
            html_parts.append(f'<tr><td class="score">{e["score"]:.3f}</td><td>{esc(chats[e["a"]].title)}<br><small>{esc(chats[e["a"]].source)}</small></td><td>{esc(chats[e["b"]].title)}<br><small>{esc(chats[e["b"]].source)}</small></td><td>{esc(", ".join(e["shared_terms"]))}</td></tr>')
        html_parts.append("</tbody></table></details></section>")
    html_parts.append("</div>")

    html_parts.append('<section class="group" id="branch-families"><h2>Related conversation branches</h2><p class="muted">These are high-confidence sibling candidates based on shared ordered transcript prefixes, not merely similar topics.</p>')
    if not branch_families:
        html_parts.append('<p class="muted">No high-confidence branch families found. This is normal when chats do not share long transcript prefixes.</p>')
    for family in branch_families:
        html_parts.append(f'<h3>{esc(family["id"])} · {len(family["members"])} chats · {family["pair_count"]} pair matches</h3><ul>')
        for member in family["members"]:
            html_parts.append(f'<li><b>{esc(member["title"])}</b> — {esc(Path(member["source"]).name)} (chat #{member["chat_id"]})</li>')
        html_parts.append('</ul>')
    if branch_matches:
        html_parts.append('<details><summary>Matched branch pairs (CSV available)</summary><table><thead><tr><th>Score</th><th>Shared turns</th><th>Shared prefix</th><th>Chat A</th><th>Chat B</th></tr></thead><tbody>')
        for m in branch_matches:
            html_parts.append(f'<tr><td>{m["score"]:.3f}</td><td>{m["shared_turns"]}</td><td>{m["shared_chars"]:,} chars</td><td>{esc(m["title_a"])}</td><td>{esc(m["title_b"])}</td></tr>')
        html_parts.append('</tbody></table></details>')
    html_parts.append('</section>')

    html_parts.append('<h2>Archive / download health</h2><p>Checks ZIP CRC integrity and, when present, backup manifest counts of saved, missing, and skipped attachments. A ZIP can pass CRC while some media downloads were missing at backup time.</p><table><thead><tr><th>Archive</th><th>ZIP status</th><th>Manifest chats</th><th>Saved</th><th>Missing</th><th>Skipped</th><th>Errors</th><th>Notes</th></tr></thead><tbody>')
    for h in health:
        html_parts.append(f'<tr><td>{esc(Path(h.archive).name)}</td><td>{esc(h.zip_status)}</td><td>{h.manifest_chats}</td><td>{h.files_saved}</td><td>{h.files_missing}</td><td>{h.files_skipped}</td><td>{h.manifest_errors}</td><td>{esc(h.notes)}</td></tr>')
    html_parts.append("</tbody></table><p class='muted'>Files created: topic_report.html, chat_index.csv, similar_pairs.csv, archive_health.csv, analysis.json, retry_chat_ids.json, index.sqlite</p>")

    html_parts.append(f"""
<div class="modal-backdrop" id="inspector-modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
  <div class="modal">
    <div class="modal-header">
      <h3 id="modal-title" style="margin:0">Conversation Inspector</h3>
      <button type="button" class="btn" id="modal-close">Close (Esc)</button>
    </div>
    <div class="modal-body" id="modal-body"></div>
  </div>
</div>

<script id="report-data" type="application/json">{interactive_payload}</script>
<script>
(() => {{
  const DATA = JSON.parse(document.getElementById('report-data').textContent);
  let reportLanguage = 'en';
  const reportPhrases = {report_phrases_json};
  const translateReport = value => reportLanguage === 'he' ? (reportPhrases.find(([en]) => en === value)?.[1] || value) : value;
  const applyReportLanguage = () => {{
    const he = reportLanguage === 'he';
    document.documentElement.lang = he ? 'he' : 'en';
    document.body.dir = he ? 'rtl' : 'ltr';
    const replacements = he ? reportPhrases : reportPhrases.map(([a,b]) => [b,a]);
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {{
      if (node.parentElement?.closest('script,style')) continue;
      let value = node.nodeValue;
      for (const [from,to] of replacements) value = value.split(from).join(to);
      node.nodeValue = value;
    }}
    const label = document.getElementById('lang-toggle-label');
    if (label) label.textContent = he ? 'English' : 'עברית';
    const search = document.getElementById('search');
    if (search) {{ search.placeholder = he ? 'סינון לפי מילת מפתח, כותרת או תוצר…' : 'Filter by keyword, title, artifact…'; search.dir = he ? 'rtl' : 'ltr'; }}
    for (const id of ['flt-from','flt-to']) {{ const input = document.getElementById(id); if (input) input.dir = he ? 'rtl' : 'ltr'; }}
  }};
  document.getElementById('lang-toggle').addEventListener('click', () => {{
    reportLanguage = reportLanguage === 'en' ? 'he' : 'en';
    applyReportLanguage();
  }});
  const CHATS = DATA.chats;
  const ALL_EDGES = DATA.edges;
  const INIT = DATA.config;

  const slTh = document.getElementById('sl-threshold');
  const slKnn = document.getElementById('sl-knn');
  const slMaxG = document.getElementById('sl-maxg');
  const inMinG = document.getElementById('in-ming');
  const fltSite = document.getElementById('flt-site');
  const fltLang = document.getElementById('flt-lang');
  const fltMedia = document.getElementById('flt-media');
  const fltFrom = document.getElementById('flt-from');
  const fltTo = document.getElementById('flt-to');
  const inSearch = document.getElementById('search');
  const btnReset = document.getElementById('btn-reset');
  const groupsRoot = document.getElementById('groups-root');
  const timelineSec = document.getElementById('timeline-section');
  const timelineBars = document.getElementById('timeline-bars');
  const timelineSum = document.getElementById('timeline-summary');
  const modal = document.getElementById('inspector-modal');
  const modalTitle = document.getElementById('modal-title');
  const modalBody = document.getElementById('modal-body');

  let selectedMonth = '';

  function escHtml(s) {{
    return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }}

  // Populate platform & code language dropdowns dynamically
  const sites = Array.from(new Set(CHATS.map(c => c.site).filter(s => s && s !== 'unknown'))).sort();
  sites.forEach(s => fltSite.appendChild(new Option(s.toUpperCase(), s)));
  const langs = Array.from(new Set(CHATS.flatMap(c => [...(c.langs || []), ...((c.artifacts || []).length ? ['has:artifact'] : [])]))).sort();
  langs.forEach(l => fltLang.appendChild(new Option(l === 'has:artifact' ? '★ Has Artifacts' : `Code: ${{l}}`, l)));

  function renderTimeline(activeChatIds) {{
    const counts = new Map();
    for (const id of activeChatIds) {{
      const m = CHATS[id]?.month;
      if (m) counts.set(m, (counts.get(m) || 0) + 1);
    }}
    const months = Array.from(counts.keys()).sort();
    if (!months.length) {{
      timelineSec.style.display = 'none';
      return;
    }}
    timelineSec.style.display = '';
    const maxC = Math.max(...counts.values(), 1);
    timelineSum.textContent = `${{months[0]}} to ${{months[months.length - 1]}} (${{months.length}} active month${{months.length > 1 ? 's' : ''}})`;
    timelineBars.innerHTML = months.map(m => {{
      const c = counts.get(m) || 0;
      const hPx = Math.round(6 + (c / maxC) * 42);
      const act = selectedMonth === m ? ' active' : '';
      return `<div class="hm-cell${{act}}" data-month="${{m}}" title="${{m}}: ${{c}} chat(s)">
        <span style="font-size:.7rem;font-weight:600">${{c}}</span>
        <div class="hm-bar" style="height:${{hPx}}px"></div>
        <span class="hm-lbl">${{m}}</span>
      </div>`;
    }}).join('');
  }}

  function highlightTerms(text, terms) {{
    let safe = escHtml(text || '(No text captured)');
    const clean = (terms || []).map(t => String(t).replace(/^(?:artifact|code|report):/, '').trim()).filter(t => t.length >= 2).sort((a, b) => b.length - a.length);
    if (!clean.length) return safe;
    const escaped = clean.map(t => escHtml(t).replace(/[.*+?^${{}}()|[\\]\\\\]/g, '\\\\$&'));
    try {{
      const re = new RegExp('(' + escaped.join('|') + ')', 'gi');
      return safe.replace(re, '<mark class="hl">$1</mark>');
    }} catch {{
      return safe;
    }}
  }}

  function filterMutualKnn(edges, k) {{
    if (k <= 0 || !edges.length) return edges.slice();
    const adj = new Map();
    for (const e of edges) {{
      if (!adj.has(e.a)) adj.set(e.a, []);
      if (!adj.has(e.b)) adj.set(e.b, []);
      adj.get(e.a).push([e.score, e.b]);
      adj.get(e.b).push([e.score, e.a]);
    }}
    const top = new Map();
    for (const [node, nbrs] of adj.entries()) {{
      nbrs.sort((x, y) => y[0] - x[0]);
      const cut = nbrs[Math.min(nbrs.length, k) - 1][0];
      const set = new Set();
      for (const [sc, nb] of nbrs) {{
        if (sc >= cut || sc >= 0.9999) set.add(nb);
      }}
      top.set(node, set);
    }}
    return edges.filter(e => e.score >= 0.9999 || (top.get(e.a)?.has(e.b) && top.get(e.b)?.has(e.a)));
  }}

  function rawComponents(nodes, edges, minSize) {{
    const list = Array.from(new Set(nodes)).sort((a, b) => a - b);
    if (list.length < minSize) return [];
    const nodeSet = new Set(list);
    const parent = new Map();
    const rank = new Map();
    for (const u of list) {{ parent.set(u, u); rank.set(u, 0); }}
    function find(x) {{
      while (parent.get(x) !== x) {{
        const p = parent.get(x);
        parent.set(x, parent.get(p));
        x = parent.get(x);
      }}
      return x;
    }}
    function union(x, y) {{
      let rx = find(x), ry = find(y);
      if (rx === ry) return;
      if (rank.get(rx) < rank.get(ry)) {{ const t = rx; rx = ry; ry = t; }}
      parent.set(ry, rx);
      if (rank.get(rx) === rank.get(ry)) rank.set(rx, rank.get(rx) + 1);
    }}
    const edgeMax = new Map();
    for (const e of edges) {{
      if (nodeSet.has(e.a) && nodeSet.has(e.b)) {{
        union(e.a, e.b);
        const k = Math.min(e.a, e.b) + ':' + Math.max(e.a, e.b);
        edgeMax.set(k, Math.max(edgeMax.get(k) || 0, e.score));
      }}
    }}
    const map = new Map();
    for (const u of list) {{
      const r = find(u);
      if (!map.has(r)) map.set(r, []);
      map.get(r).push(u);
    }}
    const comps = Array.from(map.values()).filter(g => g.length >= minSize);
    comps.sort((g1, g2) => {{
      if (g2.length !== g1.length) return g2.length - g1.length;
      let m1 = 0, m2 = 0;
      for (let i = 0; i < g1.length; i++) for (let j = i + 1; j < g1.length; j++) m1 = Math.max(m1, edgeMax.get(Math.min(g1[i], g1[j]) + ':' + Math.max(g1[i], g1[j])) || 0);
      for (let i = 0; i < g2.length; i++) for (let j = i + 1; j < g2.length; j++) m2 = Math.max(m2, edgeMax.get(Math.min(g2[i], g2[j]) + ':' + Math.max(g2[i], g2[j])) || 0);
      return m2 - m1;
    }});
    return comps;
  }}

  function subcluster(members, compEdges, baseTh, minSize, maxG, step, knn, depth = 0) {{
    if (maxG <= 0 || members.length <= maxG || depth >= 5) return [[members, baseTh]];
    const mSet = new Set(members);
    const local = compEdges.filter(e => mSet.has(e.a) && mSet.has(e.b));
    if (!local.length) return [[members, baseTh]];
    const tighterK = knn > 0 ? Math.max(3, Math.floor((knn * 2) / 3)) : 8;
    let split = [], chosenTh = baseTh;
    for (let att = 1; att <= 5; att++) {{
      const cTh = Math.min(0.95, baseTh + Math.max(0.02, step) * att);
      const above = filterMutualKnn(local.filter(e => e.score >= cTh), tighterK);
      const comps = rawComponents(members, above, minSize);
      if (comps.length >= 2 || (comps.length === 1 && comps[0].length <= maxG && comps[0].length >= minSize)) {{
        split = comps; chosenTh = cTh; break;
      }}
    }}
    if (!split.length || (split.length === 1 && split[0].length === members.length)) return [[members, baseTh]];
    const res = [];
    const assigned = new Set();
    for (const sub of split) {{
      sub.forEach(u => assigned.add(u));
      if (sub.length > maxG) res.push(...subcluster(sub, local, chosenTh, minSize, maxG, step, tighterK, depth + 1));
      else res.push([sub, chosenTh]);
    }}
    const left = members.filter(u => !assigned.has(u));
    if (left.length >= minSize) {{
      const lSet = new Set(left);
      const lEdges = local.filter(e => lSet.has(e.a) && lSet.has(e.b));
      for (const lc of rawComponents(left, lEdges, minSize)) res.push([lc, baseTh]);
    }}
    return res.length ? res : [[members, baseTh]];
  }}

  function computeGroupLabel(members) {{
    const totals = new Map();
    for (const i of members) {{
      for (const [term, w] of (CHATS[i]?.top_terms || [])) {{
        totals.set(term, (totals.get(term) || 0) + w);
      }}
    }}
    if (!totals.size) return 'Shared-topic group';
    const top = Array.from(totals.entries()).sort((a, b) => b[1] - a[1]).slice(0, 4).map(x => x[0]);
    const bi = top.filter(t => t.includes(' '));
    const uni = top.filter(t => !t.includes(' '));
    const chosen = [...bi.slice(0, 2), ...uni.slice(0, 2)].slice(0, 3);
    return chosen.length ? chosen.join(' · ') : 'Shared-topic group';
  }}

  function buildSvgGraph(members, groupEdges) {{
    const W = 440, H = 310, cx = W / 2, cy = H / 2;
    const deg = new Map();
    members.forEach(m => deg.set(m, 0));
    for (const e of groupEdges) {{
      deg.set(e.a, (deg.get(e.a) || 0) + e.score);
      deg.set(e.b, (deg.get(e.b) || 0) + e.score);
    }}
    const sorted = members.slice().sort((a, b) => (deg.get(b) || 0) - (deg.get(a) || 0));
    const hub = sorted[0];
    // Limit displayed graph nodes to top 28 by centrality to keep SVG crisp
    const shown = sorted.slice(0, 28);
    const shownSet = new Set(shown);
    const pos = new Map();
    if (shown.length === 1) {{
      pos.set(shown[0], {{ x: cx, y: cy }});
    }} else {{
      pos.set(hub, {{ x: cx, y: cy }});
      const others = shown.slice(1);
      const R1 = others.length <= 10 ? 105 : 82;
      const R2 = 128;
      others.forEach((u, idx) => {{
        const ring = others.length > 10 && idx >= 8 ? 2 : 1;
        const countInRing = ring === 1 ? Math.min(others.length, 8) : (others.length - 8);
        const idxInRing = ring === 1 ? idx : (idx - 8);
        const angle = (2 * Math.PI * idxInRing) / Math.max(1, countInRing) - Math.PI / 2;
        const r = ring === 1 ? R1 : R2;
        pos.set(u, {{ x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) }});
      }});
      // Quick spring relaxation so strongly linked pairs pull closer without overlapping
      for (let it = 0; it < 28; it++) {{
        for (let i = 1; i < shown.length; i++) {{
          for (let j = i + 1; j < shown.length; j++) {{
            const u = shown[i], v = shown[j];
            const pu = pos.get(u), pv = pos.get(v);
            let dx = pu.x - pv.x, dy = pu.y - pv.y;
            let d = Math.hypot(dx, dy) || 1;
            if (d < 42) {{
              const push = (42 - d) * 0.22;
              pu.x += (dx / d) * push; pu.y += (dy / d) * push;
              pv.x -= (dx / d) * push; pv.y -= (dy / d) * push;
            }}
          }}
        }}
        for (const e of groupEdges) {{
          if (!shownSet.has(e.a) || !shownSet.has(e.b) || e.a === hub || e.b === hub) continue;
          const pa = pos.get(e.a), pb = pos.get(e.b);
          const dx = pb.x - pa.x, dy = pb.y - pa.y;
          const d = Math.hypot(dx, dy) || 1;
          if (d > 75) {{
            const pull = (d - 75) * 0.04 * e.score;
            pa.x += (dx / d) * pull; pa.y += (dy / d) * pull;
            pb.x -= (dx / d) * pull; pb.y -= (dy / d) * pull;
          }}
        }}
        for (const u of shown.slice(1)) {{
          const p = pos.get(u);
          p.x = Math.max(36, Math.min(W - 36, p.x));
          p.y = Math.max(26, Math.min(H - 26, p.y));
        }}
      }}
    }}

    const maxDeg = Math.max(...Array.from(deg.values()), 0.1);
    const svgEdges = groupEdges
      .filter(e => shownSet.has(e.a) && shownSet.has(e.b))
      .slice(0, 75)
      .map(e => {{
        const pa = pos.get(e.a), pb = pos.get(e.b);
        const w = (1.2 + Math.min(3.5, e.score * 3.8)).toFixed(1);
        const op = (0.28 + Math.min(0.65, e.score * 0.7)).toFixed(2);
        return `<line class="g-edge" data-a="${{e.a}}" data-b="${{e.b}}" x1="${{pa.x.toFixed(1)}}" y1="${{pa.y.toFixed(1)}}" x2="${{pb.x.toFixed(1)}}" y2="${{pb.y.toFixed(1)}}" stroke="currentColor" stroke-opacity="${{op}}" stroke-width="${{w}}" style="cursor:pointer"><title>${{escHtml(CHATS[e.a].title)}} ↔ ${{escHtml(CHATS[e.b].title)}} (${{e.score.toFixed(3)}}) — Click to compare</title></line>`;
      }}).join('');

    const svgNodes = shown.map(u => {{
      const p = pos.get(u);
      const isHub = u === hub && members.length > 2;
      const r = isHub ? 10.5 : (6.5 + 3.5 * ((deg.get(u) || 0) / maxDeg));
      const fill = isHub ? 'var(--hub)' : 'var(--accent)';
      const shortTitle = CHATS[u].title.length > 20 ? CHATS[u].title.slice(0, 19) + '…' : CHATS[u].title;
      return `<g class="g-node" data-id="${{u}}" transform="translate(${{p.x.toFixed(1)}},${{p.y.toFixed(1)}})" style="cursor:pointer">
        <circle r="${{r.toFixed(1)}}" fill="${{fill}}" stroke="Canvas" stroke-width="2"></circle>
        <text y="${{(r + 11).toFixed(1)}}" text-anchor="middle" font-size="10" fill=" currentColor" style="pointer-events:none">${{escHtml(shortTitle)}}</text>
        <title>${{escHtml(CHATS[u].title)}}${{isHub ? ' (Central Hub)' : ''}} — Click to inspect</title>
      </g>`;
    }}).join('');

    return {{
      hub,
      deg,
      html: `<div class="graph-box">
        <svg viewBox="0 0 ${{W}} ${{H}}" role="img" aria-label="Topic cluster network diagram">${{svgEdges}}${{svgNodes}}</svg>
        <div class="graph-legend">
          <span><b style="color:var(--hub)">●</b> Central hub · <b style="color:var(--accent)">●</b> Member chat</span>
          <span>Click node = preview · Click link = diff</span>
        </div>
      </div>`
    }};
  }}

  function openChatModal(chatId, activeEdges) {{
    const c = CHATS[chatId];
    if (!c) return;
    modalTitle.textContent = `Chat #${{chatId + 1}}: ${{c.title}}`;
    const related = activeEdges
      .filter(e => e.a === chatId || e.b === chatId)
      .map(e => ({{ other: e.a === chatId ? e.b : e.a, score: e.score, terms: e.terms }}))
      .sort((a, b) => b.score - a.score)
      .slice(0, 12);
    const termsHtml = (c.top_terms || []).map(([t]) => `<span class="tag">${{escHtml(t)}}</span>`).join(' ') || '<span class="muted">None</span>';
    const metaBadges = [
      c.site && c.site !== 'unknown' ? `<span class="badge-site">${{escHtml(c.site.toUpperCase())}}</span>` : '',
      c.date ? `<span class="badge-site">📅 ${{escHtml(c.date)}}</span>` : '',
      c.tag ? `<span class="badge-site">📁 ${{escHtml(c.tag)}}</span>` : '',
      c.generated_media_only ? `<span class="badge-sub">${{escHtml(translateReport('Generated media only'))}} · ${{c.generated_media_count || 0}}</span>` : '',
      c.llm?.primary_topic ? `<span class="badge-sub">🧠 Topic: ${{escHtml(c.llm.primary_topic)}}</span>` : '',
      c.llm?.intent ? `<span class="badge-hub">🎯 Intent: ${{escHtml(c.llm.intent)}}</span>` : '',
      ...(c.langs || []).map(l => `<span class="badge-lang">${{escHtml(l)}}</span>`),
      ...(c.artifacts || []).map(a => `<span class="badge-sub">📄 ${{escHtml(a)}}</span>`),
    ].filter(Boolean).join(' ');

    const llmBoxHtml = c.llm ? `
      <div class="warn" style="margin:.6rem 0;border-left-color:var(--accent)">
        <b>Local LLM Report:</b> ${{escHtml(c.llm.summary || '')}}
        ${{(c.llm.segments || []).length > 1 ? `<div style="margin-top:.4rem"><b>Topic Segments in Chat:</b><ul style="margin:.25rem 0;padding-left:1.2rem">${{c.llm.segments.map(s => `<li><b>${{escHtml(s.part)}} — ${{escHtml(s.topic)}}:</b> ${{escHtml(s.summary)}}</li>`).join('')}}</ul></div>` : ''}}
        ${{(c.llm.cross_topic_grades || []).length ? `<div style="margin-top:.4rem"><b>Pass-2 External Topic Connections:</b><div style="margin-top:.2rem">${{c.llm.cross_topic_grades.map(g => `<span class="tag">${{escHtml(g.topic)}} (${{Math.round(g.score * 100)}}% · ${{escHtml(g.segment)}})</span>`).join(' ')}}</div></div>` : ''}}
        ${{(c.llm.subtopics || []).length ? `<div style="margin-top:.35rem"><b>Subtopics:</b> ${{c.llm.subtopics.map(s => `<span class="tag">${{escHtml(s)}}</span>`).join(' ')}}</div>` : ''}}
        ${{(c.llm.entities_and_tools || []).length ? `<div style="margin-top:.25rem"><b>Entities / Tools:</b> ${{c.llm.entities_and_tools.map(s => `<span class="tag">${{escHtml(s)}}</span>`).join(' ')}}</div>` : ''}}
        ${{(c.llm.canonical_keywords || []).length ? `<div style="margin-top:.25rem"><b>Canonical Keywords:</b> ${{c.llm.canonical_keywords.map(s => `<span class="tag">${{escHtml(s)}}</span>`).join(' ')}}</div>` : ''}}
      </div>
    ` : '';

    const relHtml = related.length
      ? `<table><thead><tr><th>Score</th><th>Related Conversation</th><th>Shared Terms</th><th>Action</th></tr></thead><tbody>` +
        related.map(r => `<tr>
          <td class="score">${{r.score.toFixed(3)}}</td>
          <td><b>${{escHtml(CHATS[r.other].title)}}</b><br><small class="muted">${{escHtml(CHATS[r.other].source)}}</small></td>
          <td>${{escHtml(r.terms.join(', '))}}</td>
          <td><button type="button" class="btn btn-compare-pair" data-a="${{chatId}}" data-b="${{r.other}}">Compare side-by-side</button></td>
        </tr>`).join('') + `</tbody></table>`
      : `<p class="muted">No links above the current threshold.</p>`;

    modalBody.innerHTML = `
      <p class="muted" style="margin-top:0"><code>${{escHtml(c.source)}}</code> · ${{c.chars.toLocaleString()}} chars · ${{c.tokens.toLocaleString()}} tokens</p>
      ${{metaBadges ? `<p>${{metaBadges}}</p>` : ''}}
      ${{llmBoxHtml}}
      <p><b>Top weighted terms:</b> ${{termsHtml}}</p>
      <div class="diff-grid">
        <div class="diff-col">
          <div class="turn-label">User Prompts / Context</div>
          <div class="turn-box">${{highlightTerms(c.user_preview, (c.top_terms || []).map(x => x[0]))}}</div>
        </div>
        <div class="diff-col">
          <div class="turn-label">Assistant Responses</div>
          <div class="turn-box">${{highlightTerms(c.asst_preview || '(No separate assistant turns recorded)', (c.top_terms || []).map(x => x[0]))}}</div>
        </div>
      </div>
      <h4 style="margin:1rem 0 .4rem">Connected Chats at Current Threshold (${{related.length}})</h4>
      ${{relHtml}}
    `;
    modal.classList.add('open');
  }}

  function openPairModal(aId, bId, activeEdges) {{
    const ca = CHATS[aId], cb = CHATS[bId];
    if (!ca || !cb) return;
    const edge = activeEdges.find(e => (e.a === aId && e.b === bId) || (e.a === bId && e.b === aId)) ||
                 ALL_EDGES.find(e => (e.a === aId && e.b === bId) || (e.a === bId && e.b === aId));
    const terms = edge ? edge.terms : [];
    const scoreStr = edge ? edge.score.toFixed(3) : 'N/A';
    const matchA = edge?.match_a || {{}};
    const matchB = edge?.match_b || {{}};
    modalTitle.textContent = `Side-by-Side Comparison (Similarity: ${{scoreStr}})`;
    const pills = terms.map(t => `<span class="tag">${{escHtml(t)}}</span>`).join(' ') || '<span class="muted">Exact hash or char-gram match</span>';
    const matchBlock = (label, value) => `
      <div class="turn-label">${{label}}</div>
      <div class="turn-box">${{value ? highlightTerms(value, terms) : '<span class="muted">No direct text match found in this section. The shared clue may come from code, artifact metadata, or an AI topic summary.</span>'}}</div>`;
    const matchingColumn = (chat, matches) => `
      <div class="diff-col">
        <h4 style="margin:0 0 .25rem">${{escHtml(chat.title)}}</h4>
        <div class="muted" style="font-size:.8rem;margin-bottom:.5rem"><code>${{escHtml(chat.source)}}</code></div>
        ${{matchBlock(translateReport('Matched user section'), matches.user)}}
        ${{matchBlock(translateReport('Matched assistant section'), matches.assistant)}}
        ${{matches.code ? matchBlock(translateReport('Matched code section'), matches.code) : ''}}
      </div>`;
    modalBody.innerHTML = `
      <p style="margin-top:0"><b>Highlighted shared clues:</b> ${{pills}}</p>
      <h4 style="margin:.4rem 0">${{escHtml(translateReport('Likely matching sections'))}}</h4>
      <p class="muted" style="margin:.2rem 0 .7rem">${{escHtml(translateReport('These excerpts are selected from the full conversation text where the shared clues occur. They are evidence for review, not a guarantee that both chats discuss the same idea.'))}}</p>
      <div class="diff-grid">
        ${{matchingColumn(ca, matchA)}}
        ${{matchingColumn(cb, matchB)}}
      </div>
      <details style="margin-top:1rem">
        <summary>${{escHtml(translateReport('Opening context (start of conversation)'))}}</summary>
        <div class="diff-grid" style="margin-top:.6rem">
          <div class="diff-col">
            <h4 style="margin:0 0 .25rem">${{escHtml(ca.title)}}</h4>
            <div class="turn-label">User Prompts</div>
            <div class="turn-box">${{highlightTerms(ca.user_preview, terms)}}</div>
            <div class="turn-label" style="margin-top:.65rem">Assistant Replies</div>
            <div class="turn-box">${{highlightTerms(ca.asst_preview || '(None)', terms)}}</div>
          </div>
          <div class="diff-col">
            <h4 style="margin:0 0 .25rem">${{escHtml(cb.title)}}</h4>
            <div class="turn-label">User Prompts</div>
            <div class="turn-box">${{highlightTerms(cb.user_preview, terms)}}</div>
            <div class="turn-label" style="margin-top:.65rem">Assistant Replies</div>
            <div class="turn-box">${{highlightTerms(cb.asst_preview || '(None)', terms)}}</div>
          </div>
        </div>
      </details>
    `;
    modal.classList.add('open');
  }}

  let currentActiveEdges = [];
  let currentRenderedGroups = [];
  let showUnclustered = false;
  const btnUnclustered = document.getElementById('btn-toggle-unclustered');
  const btnExportClusters = document.getElementById('btn-export-clusters');
  const btnDownloadRepair = document.getElementById('btn-download-repair');
  const filterSummaryEl = document.getElementById('active-filter-summary');

  function chatMatchesFilters(c) {{
    const siteVal = fltSite.value;
    if (siteVal && siteVal !== '__cross__' && c.site !== siteVal) return false;
    const langVal = fltLang.value;
    if (langVal === 'has:artifact' && !(c.artifacts && c.artifacts.length)) return false;
    if (langVal && langVal !== 'has:artifact' && !(c.langs && c.langs.includes(langVal))) return false;
    if (fltMedia.value === 'exclude' && c.generated_media_only) return false;
    if (fltMedia.value === 'only' && !c.generated_media_only) return false;
    if (selectedMonth && c.month !== selectedMonth) return false;
    if (fltFrom.value && (!c.date || c.date < fltFrom.value)) return false;
    if (fltTo.value && (!c.date || c.date > fltTo.value)) return false;
    return true;
  }}

  function renderInteractive() {{
    const th = parseFloat(slTh.value) || 0.20;
    const knn = parseInt(slKnn.value, 10) || 0;
    const maxG = parseInt(slMaxG.value, 10) || 0;
    const minG = Math.max(2, parseInt(inMinG.value, 10) || 2);
    const query = inSearch.value.trim().toLowerCase();
    const onlyCrossPlatform = fltSite.value === '__cross__';

    document.getElementById('lbl-threshold').textContent = th.toFixed(2);
    document.getElementById('lbl-knn').textContent = knn > 0 ? String(knn) : 'Off';
    document.getElementById('lbl-maxg').textContent = maxG > 0 ? String(maxG) : 'Off';
    document.getElementById('st-threshold').textContent = th.toFixed(2);
    document.getElementById('lbl-month-active').textContent = selectedMonth ? `Month: ${{selectedMonth}}` : 'All dates';

    const allowedNodes = new Set(CHATS.filter(chatMatchesFilters).map(c => c.id));
    renderTimeline(allowedNodes);

    const edgesAtTh = ALL_EDGES.filter(e => e.score >= th && allowedNodes.has(e.a) && allowedNodes.has(e.b));
    currentActiveEdges = edgesAtTh;
    const filteredEdges = filterMutualKnn(edgesAtTh, knn);
    const baseComps = rawComponents(allowedNodes, filteredEdges, minG);

    let groups = [];
    let subCount = 0;
    baseComps.forEach((comp, idx) => {{
      const pId = idx + 1;
      if (maxG > 0 && comp.length > maxG) {{
        const subs = subcluster(comp, filteredEdges, th, minG, maxG, INIT.subclusterStep || 0.08, knn);
        if (subs.length > 1 || (subs.length === 1 && subs[0][0].length < comp.length)) {{
          subCount += subs.length;
          subs.forEach(([subMembers, effTh], sIdx) => {{
            groups.push({{
              id: subs.length > 1 ? `${{pId}}.${{sIdx + 1}}` : String(pId),
              members: subMembers,
              subclustered: true,
              effTh
            }});
          }});
          return;
        }}
      }}
      groups.push({{ id: String(pId), members: comp, subclustered: false, effTh: th }});
    }});

    if (onlyCrossPlatform) {{
      groups = groups.filter(g => {{
        const distinctSites = new Set(g.members.map(i => CHATS[i]?.site).filter(s => s && s !== 'unknown'));
        return distinctSites.size >= 2;
      }});
    }}
    currentRenderedGroups = groups;

    const clusteredSet = new Set(groups.flatMap(g => g.members));
    const unclusteredIds = Array.from(allowedNodes).filter(id => !clusteredSet.has(id));
    document.getElementById('st-groups').textContent = String(groups.length);
    document.getElementById('st-groups-sub').textContent = subCount ? `topic groups (${{subCount}} sub-clustered)` : 'topic groups';
    document.getElementById('st-pairs').textContent = edgesAtTh.length.toLocaleString();
    document.getElementById('st-clustered').textContent = `${{clusteredSet.size}} / ${{allowedNodes.size}}`;
    if (filterSummaryEl) {{
      filterSummaryEl.textContent = `${{groups.length}} group(s) shown · ${{unclusteredIds.length}} unclustered chat(s)`;
    }}

    const htmlOut = ['<h2>Topic groups</h2>'];
    if (!groups.length) {{
      htmlOut.push('<p class="muted">No topic groups matched the current parameters. Try lowering the Similarity Threshold slider or clearing filters.</p>');
    }}
    for (const g of groups) {{
      const mSet = new Set(g.members);
      const gEdges = edgesAtTh.filter(e => mSet.has(e.a) && mSet.has(e.b)).sort((a, b) => b.score - a.score);
      const label = computeGroupLabel(g.members);
      g.label = label;
      const sharedSet = new Set();
      for (const e of gEdges.slice(0, 14)) for (const t of e.terms.slice(0, 4)) sharedSet.add(t);
      const sharedTerms = Array.from(sharedSet).slice(0, 18);

      const searchBlob = [label, ...sharedTerms, ...g.members.map(i => CHATS[i].title + ' ' + CHATS[i].source + ' ' + CHATS[i].snippet + ' ' + (CHATS[i].llm?.summary || '') + ' ' + (CHATS[i].llm?.primary_topic || '') + ' ' + (CHATS[i].artifacts || []).join(' ') + ' ' + (CHATS[i].langs || []).join(' '))].join(' ').toLowerCase();
      if (query && !searchBlob.includes(query)) continue;

      const minScore = gEdges.length ? gEdges[gEdges.length - 1].score : 0;
      const meanScore = gEdges.length ? (gEdges.reduce((s, e) => s + e.score, 0) / gEdges.length) : 0;
      const datesInGroup = g.members.map(i => CHATS[i].date).filter(Boolean).sort();
      const dateSpan = datesInGroup.length ? (datesInGroup[0] === datesInGroup[datesInGroup.length - 1] ? datesInGroup[0] : `${{datesInGroup[0]}} → ${{datesInGroup[datesInGroup.length - 1]}}`) : '';
      const subBadge = g.subclustered ? `<span class="badge-sub">Sub-cluster (threshold &ge; ${{g.effTh.toFixed(2)}})</span>` : '';
      const graph = buildSvgGraph(g.members, gEdges);

      const membersSorted = g.members.slice().sort((a, b) => (graph.deg.get(b) || 0) - (graph.deg.get(a) || 0));
      const chatsHtml = membersSorted.map(i => {{
        const c = CHATS[i];
        const isHub = i === graph.hub && g.members.length > 2;
        const badges = [
          isHub ? '<span class="badge-hub">Central Hub</span>' : '',
          c.llm?.primary_topic ? `<span class="badge-sub">🧠 ${{escHtml(c.llm.primary_topic)}}</span>` : '',
          c.site && c.site !== 'unknown' ? `<span class="badge-site">${{escHtml(c.site)}}</span>` : '',
          c.date ? `<span class="badge-site">${{escHtml(c.date)}}</span>` : '',
          ...(c.langs || []).slice(0, 3).map(l => `<span class="badge-lang">${{escHtml(l)}}</span>`),
          ...(c.artifacts || []).slice(0, 2).map(a => `<span class="badge-sub">📄 ${{escHtml(a)}}</span>`),
        ].filter(Boolean).join(' ');
        const displaySnippet = c.llm?.summary ? `🧠 ${{c.llm.summary}}` : c.snippet;
        return `<div class="chat" data-chat-id="${{i}}">
          <div class="chat-head"><b>${{escHtml(c.title)}}</b><div>${{badges}}</div></div>
          <div class="muted" style="font-size:.82rem">${{escHtml(c.source)}}</div>
          <p style="margin:.35rem 0 0;font-size:.9rem">${{highlightTerms(displaySnippet, query ? [query] : sharedTerms.slice(0, 5))}}</p>
        </div>`;
      }}).join('');

      const pairsHtml = gEdges.slice(0, 30).map(e => `<tr class="pair-row" data-a="${{e.a}}" data-b="${{e.b}}">
        <td class="score">${{e.score.toFixed(3)}}</td>
        <td><b>${{escHtml(CHATS[e.a].title)}}</b><br><small class="muted">${{escHtml(CHATS[e.a].source)}}</small></td>
        <td><b>${{escHtml(CHATS[e.b].title)}}</b><br><small class="muted">${{escHtml(CHATS[e.b].source)}}</small></td>
        <td>${{escHtml(e.terms.join(', '))}}</td>
      </tr>`).join('');

      htmlOut.push(`<section class="group${{g.subclustered ? ' sub' : ''}}">
        <div class="group-header">
          <h3>Group ${{escHtml(g.id)}}: ${{escHtml(label)}}${{subBadge}}</h3>
          <span class="muted">${{g.members.length}} chats · ${{gEdges.length}} internal links · min ${{minScore.toFixed(3)}} · mean ${{meanScore.toFixed(3)}}${{dateSpan ? ' · 📅 ' + escHtml(dateSpan) : ''}}</span>
        </div>
        <p style="margin:.3rem 0">Shared clues: ${{sharedTerms.map(t => `<span class="tag clickable" data-term="${{escHtml(t)}}">${{escHtml(t)}}</span>`).join(' ')}}</p>
        <div class="group-layout">
          <div class="chat-list">${{chatsHtml}}</div>
          ${{graph.html}}
        </div>
        <details><summary>Strongest matching pairs (${{gEdges.length}}) — click any row for side-by-side diff</summary>
          <table><thead><tr><th>Similarity</th><th>Chat A</th><th>Chat B</th><th>Shared terms</th></tr></thead><tbody>${{pairsHtml}}</tbody></table>
        </details>
      </section>`);
    }}

    if (showUnclustered && unclusteredIds.length) {{
      const filteredUnc = unclusteredIds.filter(i => {{
        if (!query) return true;
        const c = CHATS[i];
        return (c.title + ' ' + c.source + ' ' + c.snippet).toLowerCase().includes(query);
      }});
      const uncCards = filteredUnc.map(i => {{
        const c = CHATS[i];
        return `<div class="chat" data-chat-id="${{i}}">
          <div class="chat-head"><b>${{escHtml(c.title)}}</b><div>${{c.site && c.site !== 'unknown' ? `<span class="badge-site">${{escHtml(c.site)}}</span>` : ''}} ${{c.date ? `<span class="badge-site">${{escHtml(c.date)}}</span>` : ''}}</div></div>
          <div class="muted" style="font-size:.82rem">${{escHtml(c.source)}}</div>
          <p style="margin:.35rem 0 0;font-size:.9rem">${{highlightTerms(c.snippet, query ? [query] : (c.top_terms || []).slice(0, 3).map(x => x[0]))}}</p>
        </div>`;
      }}).join('');
      htmlOut.push(`<section class="group">
        <div class="group-header"><h3>Unclustered Conversations (${{filteredUnc.length}})</h3><span class="muted">Chats with no links above threshold ${{th.toFixed(2)}}</span></div>
        <div class="chat-list" style="max-height:420px">${{uncCards || '<p class="muted">No unclustered chats match your search query.</p>'}}</div>
      </section>`);
    }}

    groupsRoot.innerHTML = htmlOut.join('\\n');
    applyReportLanguage();
  }}

  if (btnUnclustered) {{
    btnUnclustered.addEventListener('click', () => {{
      showUnclustered = !showUnclustered;
      btnUnclustered.classList.toggle('active', showUnclustered);
      btnUnclustered.textContent = showUnclustered ? 'Hide Unclustered Chats' : 'Show Unclustered Chats';
      renderInteractive();
    }});
  }}
  if (btnExportClusters) {{
    btnExportClusters.addEventListener('click', () => {{
      const payload = {{
        exported: new Date().toISOString(),
        threshold: parseFloat(slTh.value) || 0.20,
        mutualKnn: parseInt(slKnn.value, 10) || 0,
        maxGroupSize: parseInt(slMaxG.value, 10) || 0,
        groups: currentRenderedGroups.map(g => ({{
          id: g.id,
          label: g.label || '',
          subclustered: g.subclustered,
          effectiveThreshold: g.effTh,
          members: g.members.map(i => ({{ id: i + 1, title: CHATS[i].title, source: CHATS[i].source, date: CHATS[i].date, site: CHATS[i].site }}))
        }}))
      }};
      const blob = new Blob([JSON.stringify(payload, null, 2)], {{ type: 'application/json' }});
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'custom_topic_clusters.json';
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 10000);
    }});
  }}
  if (btnDownloadRepair && DATA.repair) {{
    btnDownloadRepair.addEventListener('click', () => {{
      const blob = new Blob([JSON.stringify(DATA.repair, null, 2)], {{ type: 'application/json' }});
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'retry_chat_ids.json';
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 10000);
    }});
  }}

  [slTh, slKnn, slMaxG, inMinG, fltSite, fltLang, fltFrom, fltTo, inSearch].forEach(el => el.addEventListener('input', renderInteractive));
  timelineBars.addEventListener('click', e => {{
    const cell = e.target.closest('.hm-cell[data-month]');
    if (!cell) return;
    selectedMonth = selectedMonth === cell.dataset.month ? '' : cell.dataset.month;
    renderInteractive();
  }});
  btnReset.addEventListener('click', () => {{
    slTh.value = INIT.threshold;
    slKnn.value = INIT.mutualKnn;
    slMaxG.value = INIT.maxGroupSize;
    inMinG.value = INIT.minGroupSize;
    fltSite.value = '';
    fltLang.value = '';
    fltFrom.value = '';
    fltTo.value = '';
    selectedMonth = '';
    inSearch.value = '';
    renderInteractive();
  }});

  groupsRoot.addEventListener('click', e => {{
    const chatCard = e.target.closest('.chat[data-chat-id]');
    if (chatCard) return openChatModal(Number(chatCard.dataset.chatId), currentActiveEdges);
    const nodeEl = e.target.closest('.g-node[data-id]');
    if (nodeEl) return openChatModal(Number(nodeEl.dataset.id), currentActiveEdges);
    const edgeEl = e.target.closest('.g-edge[data-a]');
    if (edgeEl) return openPairModal(Number(edgeEl.dataset.a), Number(edgeEl.dataset.b), currentActiveEdges);
    const pairRow = e.target.closest('.pair-row[data-a]');
    if (pairRow) return openPairModal(Number(pairRow.dataset.a), Number(pairRow.dataset.b), currentActiveEdges);
    const tagEl = e.target.closest('.tag.clickable[data-term]');
    if (tagEl) {{
      inSearch.value = tagEl.dataset.term;
      renderInteractive();
    }}
  }});

  modalBody.addEventListener('click', e => {{
    const cmpBtn = e.target.closest('.btn-compare-pair');
    if (cmpBtn) openPairModal(Number(cmpBtn.dataset.a), Number(cmpBtn.dataset.b), currentActiveEdges);
  }});
  document.getElementById('modal-close').addEventListener('click', () => modal.classList.remove('open'));
  modal.addEventListener('mousedown', e => {{ if (e.target === modal) modal.classList.remove('open'); }});
  window.addEventListener('keydown', e => {{ if (e.key === 'Escape') modal.classList.remove('open'); }});

  renderInteractive();
}})();
</script></body></html>""")
    html_path.write_text("\n".join(html_parts), encoding="utf-8")
    return {
        "html": str(html_path),
        "chat_index_csv": str(outdir / "chat_index.csv"),
        "pairs_csv": str(outdir / "similar_pairs.csv"),
        "archive_health_csv": str(outdir / "archive_health.csv"),
        "json": str(outdir / "analysis.json"),
        "chat_reports_json": str(reports_json_path),
        "branch_matches_csv": str(outdir / "branch_matches.csv"),
        "branch_families_json": str(branches_json_path),
        "retry_ids_json": str(retry_path),
        "sqlite_db": str(outdir / "index.sqlite"),
    }
