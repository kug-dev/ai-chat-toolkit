"""App module for Chat Topic Finder."""
from __future__ import annotations
from .common import *
from .indexing import search_fts_database
from .ingest import discover_inputs, load_loose, load_zip
from .llm import export_online_ai_bundle, generate_llm_reports, import_online_ai_reports
from .reports import export_grouped_archive, generate_reports
from .similarity import compare_chats, connected_groups
from .text import log_msg
from .i18n import load_locale

def analyze(
    paths: Iterable[str | Path],
    outdir: str | Path,
    threshold: float = 0.20,
    min_group_size: int = 2,
    mutual_knn: int = 12,
    max_group_size: int = 25,
    subcluster_step: float = 0.08,
    export_grouped_zip: bool = False,
    llm_model: str = "",
    llm_url: str = DEFAULT_LLM_URL,
    llm_provider: str = DEFAULT_LLM_PROVIDER,
    llm_api_key: str = "",
    llm_max_chars: int = DEFAULT_LLM_MAX_CHARS,
    llm_mode: str = "hybrid",
    llm_pass2: bool = False,
    export_online_bundle: bool = False,
    import_reports_path: str | Path | None = None,
    branch_matching: bool = True,
    log=None,
) -> dict:
    t0 = time.time()
    out_path = Path(outdir)
    out_path.mkdir(parents=True, exist_ok=True)
    zip_paths, loose_paths = discover_inputs(paths)
    if not zip_paths and not loose_paths:
        raise ValueError("No supported ZIP, chat.md, raw.json, Markdown, or text files found.")
    log_msg(log, f"Input scan: {len(zip_paths)} ZIP(s), {len(loose_paths)} loose text file(s).")
    health: list[ArchiveHealth] = []
    repair_entries: list[dict] = []
    chats: list[Chat] = []
    for p in zip_paths:
        chats.extend(load_zip(p, health, log, repair_entries=repair_entries))
    loose_set = set(loose_paths)
    filtered_loose = []
    for p in loose_paths:
        if p.name.casefold() == "raw.json" and (p.parent / "chat.md") in loose_set:
            continue
        filtered_loose.append(p)
    for p in filtered_loose:
        c = load_loose(p, log)
        if c and c.text.strip():
            chats.append(c)
    if not chats:
        raise ValueError("No readable conversations found. Expected conversation-folder chat.md files or raw.json files inside the ZIPs.")
    db_path = out_path / "index.sqlite"
    if import_reports_path:
        import_online_ai_reports(chats, Path(import_reports_path), log=log)
    if llm_model and llm_model.strip():
        resolved_key = llm_api_key.strip() or os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY") or os.environ.get("GEMINI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY") or ""
        generate_llm_reports(
            chats,
            db_path=db_path,
            model=llm_model.strip(),
            base_url=llm_url.strip() or DEFAULT_LLM_URL,
            provider=llm_provider,
            max_chars=llm_max_chars,
            run_pass2=llm_pass2,
            api_key=resolved_key,
            log=log,
        )
    log_msg(log, f"Preparing topic features for {len(chats)} conversations…")
    interactive_pool: list[dict] = []
    edges = compare_chats(chats, threshold, log, interactive_pool=interactive_pool, db_path=db_path, llm_mode=llm_mode)
    groups = connected_groups(
        len(chats),
        edges,
        min_size=min_group_size,
        mutual_knn=mutual_knn,
        max_group_size=max_group_size,
        threshold=threshold,
        subcluster_step=subcluster_step,
        log=log,
    )
    log_msg(log, f"Built {len(groups)} group(s) with at least {min_group_size} chats.")
    paths_out = generate_reports(
        out_path,
        chats,
        edges,
        groups,
        health,
        threshold,
        mutual_knn=mutual_knn,
        max_group_size=max_group_size,
        min_group_size=min_group_size,
        subcluster_step=subcluster_step,
        interactive_edges=interactive_pool,
        repair_entries=repair_entries,
        branch_matching=branch_matching,
    )
    if export_grouped_zip:
        grouped_zip_path = export_grouped_archive(out_path / "grouped_chats.zip", chats, groups, log=log)
        paths_out["grouped_zip"] = grouped_zip_path
    if export_online_bundle:
        bundle_paths = export_online_ai_bundle(chats, out_path, log=log)
        paths_out["online_ai_bundle"] = ", ".join(bundle_paths)
    log_msg(log, f"Done in {time.time()-t0:.1f}s. Report: {paths_out['html']}")
    branch_match_count = 0
    if branch_matching:
        try:
            branch_payload = json.loads(Path(paths_out["branch_families_json"]).read_text(encoding="utf-8"))
            branch_match_count = len(branch_payload.get("matches", []))
        except (OSError, json.JSONDecodeError, KeyError):
            pass
    return {"chat_count": len(chats), "pair_count": len(edges), "group_count": len(groups), "branch_match_count": branch_match_count, "output": paths_out, "health": health}

def gui() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title(f"{APP_NAME} {VERSION}")
    root.geometry("940x740")
    paths_var = tk.StringVar()
    output_var = tk.StringVar(value=str(Path.home() / "ChatTopicReport"))
    threshold_var = tk.StringVar(value="0.20")
    min_group_var = tk.StringVar(value="2")
    mutual_knn_var = tk.StringVar(value="12")
    max_group_var = tk.StringVar(value="25")
    export_zip_var = tk.BooleanVar(value=False)
    llm_model_var = tk.StringVar(value="")
    llm_provider_var = tk.StringVar(value=DEFAULT_LLM_PROVIDER)
    branch_match_var = tk.BooleanVar(value=True)
    llm_url_var = tk.StringVar(value=DEFAULT_LLM_URL)
    llm_key_var = tk.StringVar(value="")
    llm_chars_var = tk.StringVar(value=str(DEFAULT_LLM_MAX_CHARS))
    llm_mode_var = tk.StringVar(value="hybrid")
    llm_pass2_var = tk.BooleanVar(value=True)
    export_bundle_var = tk.BooleanVar(value=False)
    import_reports_var = tk.StringVar(value="")
    fts_query_var = tk.StringVar()
    q: queue.Queue[str] = queue.Queue()
    language_var = tk.StringVar(value="en")
    from .i18n import load_locale
    hebrew_text = load_locale("he").get("python_gui", {})
    widget_english: dict[object, str] = {}

    def walk_widgets(widget):
        for child in widget.winfo_children():
            yield child
            yield from walk_widgets(child)

    def translate_ui(value: str) -> str:
        return hebrew_text.get(value, value) if language_var.get() == "he" else value

    def apply_language():
        hebrew = language_var.get() == "he"
        root.title(f"מאתר נושאים לשיחות {VERSION}" if hebrew else f"{APP_NAME} {VERSION}")
        for widget in walk_widgets(root):
            if widget is language_button:
                continue
            try:
                current = widget.cget("text")
                if widget not in widget_english:
                    widget_english[widget] = current
                base = widget_english[widget]
                if base:
                    widget.configure(text=hebrew_text.get(base, base) if hebrew else base)
                if widget.winfo_class() in ("TLabel", "TCheckbutton"):
                    widget.configure(anchor="e" if hebrew else "w")
                if widget.winfo_class() in ("TEntry", "Entry"):
                    widget.configure(justify="right" if hebrew else "left")
            except Exception:
                pass
        language_button.configure(text="English" if hebrew else "עברית")

    def toggle_language():
        language_var.set("he" if language_var.get() == "en" else "en")
        apply_language()

    top = ttk.Frame(root, padding=12)
    top.pack(fill="x")
    ttk.Label(top, text="Analyze backup ZIPs or exported conversations", font=("Segoe UI", 13, "bold")).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
    language_button = ttk.Button(top, text="עברית", command=toggle_language)
    language_button.grid(row=0, column=3, sticky="e", padx=(8, 0), pady=(0, 10))
    ttk.Label(top, text="Input file or folder").grid(row=1, column=0, sticky="w")
    ttk.Entry(top, textvariable=paths_var).grid(row=2, column=0, sticky="ew", padx=(0, 6))

    def choose_file():
        selected = filedialog.askopenfilenames(title="Choose backup ZIPs or chat files", filetypes=[("Chat backups and text", "*.zip *.md *.txt *.json"), ("All files", "*.*")])
        if selected:
            paths_var.set(";".join(selected))

    def choose_folder():
        selected = filedialog.askdirectory(title="Choose a folder containing backup ZIPs")
        if selected:
            paths_var.set(selected)

    ttk.Button(top, text="Choose files…", command=choose_file).grid(row=2, column=1, padx=3)
    ttk.Button(top, text="Choose folder…", command=choose_folder).grid(row=2, column=2)
    ttk.Label(top, text="Output folder").grid(row=3, column=0, sticky="w", pady=(10, 0))
    ttk.Entry(top, textvariable=output_var).grid(row=4, column=0, sticky="ew", padx=(0, 6))

    def choose_output():
        selected = filedialog.askdirectory(title="Choose report output folder")
        if selected:
            output_var.set(selected)

    ttk.Button(top, text="Browse…", command=choose_output).grid(row=4, column=1, sticky="w")
    opts = ttk.Frame(top)
    opts.grid(row=5, column=0, columnspan=3, sticky="w", pady=10)
    ttk.Label(opts, text="Similarity threshold (0–1)").pack(side="left")
    ttk.Entry(opts, textvariable=threshold_var, width=6).pack(side="left", padx=(6, 14))
    ttk.Label(opts, text="Min group").pack(side="left")
    ttk.Entry(opts, textvariable=min_group_var, width=4).pack(side="left", padx=(6, 14))
    ttk.Label(opts, text="Mutual k-NN").pack(side="left")
    ttk.Entry(opts, textvariable=mutual_knn_var, width=4).pack(side="left", padx=(6, 14))
    ttk.Label(opts, text="Max group").pack(side="left")
    ttk.Entry(opts, textvariable=max_group_var, width=4).pack(side="left", padx=(6, 14))
    ttk.Checkbutton(opts, text="Export deduplicated grouped_chats.zip", variable=export_zip_var).pack(side="left")
    ttk.Checkbutton(opts, text="Enable automatic branch matching", variable=branch_match_var).pack(side="left", padx=(8, 0))

    llm_bar = ttk.Frame(top)
    llm_bar.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(0, 6))
    ttk.Label(llm_bar, text="AI Model (local/online):").pack(side="left")
    ttk.Entry(llm_bar, textvariable=llm_model_var, width=14).pack(side="left", padx=(6, 8))
    ttk.Label(llm_bar, text="Provider:").pack(side="left")
    ttk.Combobox(llm_bar, textvariable=llm_provider_var, values=["auto", "ollama", "openai-compatible", "anthropic"], width=18, state="readonly").pack(side="left", padx=(4, 8))
    ttk.Label(llm_bar, text="URL:").pack(side="left")
    ttk.Entry(llm_bar, textvariable=llm_url_var, width=20).pack(side="left", padx=(4, 8))
    ttk.Label(llm_bar, text="API Key:").pack(side="left")
    ttk.Entry(llm_bar, textvariable=llm_key_var, width=12, show="*").pack(side="left", padx=(4, 8))
    ttk.Label(llm_bar, text="Max chars:").pack(side="left")
    ttk.Entry(llm_bar, textvariable=llm_chars_var, width=7).pack(side="left", padx=(4, 8))
    ttk.Label(llm_bar, text="Mode:").pack(side="left")
    ttk.Combobox(llm_bar, textvariable=llm_mode_var, values=["hybrid", "report-only"], width=10, state="readonly").pack(side="left", padx=(4, 8))
    ttk.Checkbutton(llm_bar, text="Pass 2", variable=llm_pass2_var).pack(side="left")

    ttk.Label(llm_bar, text="Remote providers receive conversation text. Use only a provider you trust.", foreground="#9a5b00").pack(side="left", padx=(6, 0))

    online_bar = ttk.Frame(top)
    online_bar.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(0, 6))
    ttk.Checkbutton(online_bar, text="Export online_ai_bundle.md (for Gemini/NotebookLM/Claude upload)", variable=export_bundle_var).pack(side="left", padx=(0, 12))
    ttk.Label(online_bar, text="Import Online AI JSON:").pack(side="left")
    ttk.Entry(online_bar, textvariable=import_reports_var, width=24).pack(side="left", padx=(4, 4), fill="x", expand=True)

    def choose_import_json():
        selected = filedialog.askopenfilename(title="Choose Online AI JSON Reports", filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
        if selected:
            import_reports_var.set(selected)

    ttk.Button(online_bar, text="Browse…", command=choose_import_json).pack(side="left")

    fts_bar = ttk.Frame(top)
    fts_bar.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(2, 4))
    ttk.Label(fts_bar, text="Full-Text Search (SQLite FTS5):").pack(side="left")
    ttk.Entry(fts_bar, textvariable=fts_query_var).pack(side="left", fill="x", expand=True, padx=6)

    def run_fts():
        db_file = Path(output_var.get().strip()) / "index.sqlite"
        if not db_file.exists():
            messagebox.showinfo(APP_NAME, "Run 'Analyze chats' first to build index.sqlite in the output folder.")
            return
        hits = search_fts_database(db_file, fts_query_var.get().strip())
        text.delete("1.0", "end")
        text.insert("end", f"FTS5 Search for '{fts_query_var.get().strip()}' — {len(hits)} match(es):\n\n")
        for h in hits:
            text.insert("end", f"[#{h['chat_id']}] {h['title']} ({h['chat_date'] or 'no date'})\n  Source: {h['source']}\n  Snippet: {h['snippet']}\n\n")

    ttk.Button(fts_bar, text="Search Inside Chats", command=run_fts).pack(side="left")
    top.columnconfigure(0, weight=1)

    actions = ttk.Frame(root, padding=(12, 0, 12, 8))
    actions.pack(fill="x")
    status = ttk.Label(actions, text="Analysis runs locally by default. Optional configured AI providers receive conversation text.")
    status.pack(side="left", fill="x", expand=True)
    text = tk.Text(root, height=18, wrap="word", font=("Consolas", 10))
    text.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    def append(msg):
        q.put(msg)

    def run_analysis():
        if not paths_var.get().strip():
            messagebox.showwarning(APP_NAME, "Choose at least one ZIP, text file, or input folder.")
            return
        try:
            th = float(threshold_var.get())
            mg = int(min_group_var.get())
            knn = int(mutual_knn_var.get())
            maxg = int(max_group_var.get())
            lchars = int(llm_chars_var.get() or DEFAULT_LLM_MAX_CHARS)
            if not 0 <= th <= 1 or mg < 2 or knn < 0 or maxg < 0 or lchars < 2000:
                raise ValueError
        except ValueError:
            messagebox.showerror(APP_NAME, "Threshold must be 0–1; min group >= 2; mutual k-NN and max group >= 0; max chars >= 2000.")
            return
        paths = [x.strip() for x in paths_var.get().split(";") if x.strip()]
        out = output_var.get().strip()
        exp_zip = bool(export_zip_var.get())
        lmodel = llm_model_var.get().strip()
        lprovider = llm_provider_var.get().strip() or DEFAULT_LLM_PROVIDER
        lurl = llm_url_var.get().strip() or DEFAULT_LLM_URL
        lkey = llm_key_var.get().strip()
        lmode = llm_mode_var.get().strip() or "hybrid"
        lpass2 = bool(llm_pass2_var.get())
        exp_bundle = bool(export_bundle_var.get())
        imp_reports = import_reports_var.get().strip() or None
        button.configure(state="disabled")
        status.configure(text="Analyzing…")
        text.delete("1.0", "end")

        def worker():
            try:
                res = analyze(
                    paths,
                    out,
                    th,
                    mg,
                    mutual_knn=knn,
                    max_group_size=maxg,
                    export_grouped_zip=exp_zip,
                    llm_model=lmodel,
                    llm_url=lurl,
                    llm_provider=lprovider,
                    llm_api_key=lkey,
                    branch_matching=bool(branch_match_var.get()),
                    llm_max_chars=lchars,
                    llm_mode=lmode,
                    llm_pass2=lpass2,
                    export_online_bundle=exp_bundle,
                    import_reports_path=imp_reports,
                    log=append,
                )
                append("RESULT: " + json.dumps(res["output"], ensure_ascii=False))
                append(f"SUMMARY: {res['chat_count']} chats, {res['group_count']} groups, {res['pair_count']} matching pairs.")
            except Exception as e:
                append("ERROR: " + str(e))
            finally:
                q.put("__DONE__")

        threading.Thread(target=worker, daemon=True).start()

    button = ttk.Button(actions, text="Analyze chats", command=run_analysis)
    button.pack(side="right")

    def poll():
        done = False
        while True:
            try:
                msg = q.get_nowait()
            except queue.Empty:
                break
            if msg == "__DONE__":
                done = True
            else:
                text.insert("end", msg + "\n")
                text.see("end")
                if msg.startswith("Done in") or msg.startswith("SUMMARY:"):
                    status.configure(text=msg)
        if done:
            button.configure(state="normal")
            report = Path(output_var.get()) / "topic_report.html"
            if report.exists() and messagebox.askyesno(APP_NAME, f"Analysis complete. Open report?\n\n{report}"):
                webbrowser.open(report.resolve().as_uri())
        root.after(120, poll)

    apply_language()
    root.after(120, poll)
    root.mainloop()

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=f"{APP_NAME}: offline-first conversation topic analysis with optional local or remote LLM enrichment.")
    parser.add_argument("--input", "-i", action="append", help="ZIP, chat.md/raw.json, Markdown/text file, or folder; may be repeated")
    parser.add_argument("--output", "-o", default="ChatTopicReport", help="Report output folder (default: ./ChatTopicReport)")
    parser.add_argument("--threshold", type=float, default=0.20, help="Cosine similarity threshold between 0 and 1 (default: 0.20)")
    parser.add_argument("--min-group-size", type=int, default=2, help="Minimum number of chats in a topic group (default: 2)")
    parser.add_argument("--mutual-knn", type=int, default=12, help="Mutual k-NN filter size to prune weak bridge edges; 0 disables (default: 12)")
    parser.add_argument("--max-group-size", type=int, default=25, help="Auto sub-cluster groups larger than this size; 0 disables (default: 25)")
    parser.add_argument("--subcluster-step", type=float, default=0.08, help="Threshold increment when splitting oversized groups (default: 0.08)")
    parser.add_argument("--llm-model", default="", help="Optional local or hosted model identifier for structured chat summaries and semantic links")
    parser.add_argument("--llm-provider", choices=["auto", "ollama", "openai-compatible", "anthropic"], default=DEFAULT_LLM_PROVIDER, help="LLM API provider; auto-detects from URL")
    parser.add_argument("--llm-url", default=DEFAULT_LLM_URL, help=f"Provider base URL; e.g. Ollama http://localhost:11434 or OpenAI-compatible https://api.openai.com/v1 (default: {DEFAULT_LLM_URL})")
    parser.add_argument("--llm-max-chars", type=int, default=DEFAULT_LLM_MAX_CHARS, help=f"Approximate character budget per chat sent to the configured model (default: {DEFAULT_LLM_MAX_CHARS})")
    parser.add_argument("--llm-mode", choices=["hybrid", "report-only"], default="hybrid", help="How to connect chats when --llm-model is used: 'hybrid' (report + lexical) or 'report-only'")
    parser.add_argument("--llm-api-key", default="", help="Optional provider API key; environment variables LLM_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY / ANTHROPIC_API_KEY are also checked")
    parser.add_argument("--no-branch-matching", action="store_true", help="Disable conservative shared-prefix detection of sibling conversation branches")
    parser.add_argument("--llm-pass2", action="store_true", help="Run a 2nd LLM pass grading how each chat segment connects to external topics (excluding topics sourced only from the same chat)")
    parser.add_argument("--export-grouped-zip", action="store_true", help="Export a deduplicated grouped_chats.zip organized by topic folder")
    parser.add_argument("--export-online-bundle", action="store_true", help="Export compact online_ai_bundle.md file(s) ready to upload to Gemini, NotebookLM, Claude, or ChatGPT")
    parser.add_argument("--import-reports", default="", help="Import a JSON categorization file generated by an online AI into the report and SQLite index")
    parser.add_argument("--search", "-s", help="Search full conversation bodies in an existing output folder's index.sqlite (FTS5)")
    parser.add_argument("--no-open", action="store_true", help="Do not open HTML report automatically")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    args = parser.parse_args(argv)
    if args.search:
        db_file = Path(args.output) / "index.sqlite"
        if not db_file.exists():
            print(f"ERROR: SQLite index not found at {db_file}. Run an analysis first.", file=sys.stderr)
            return 2
        hits = search_fts_database(db_file, args.search)
        print(f"Found {len(hits)} full-text match(es) for '{args.search}':\n")
        for h in hits:
            print(f"[#{h['chat_id']}] {h['title']} ({h['chat_date'] or 'unknown date'}) — {h['source']}\n    {h['snippet']}\n")
        return 0
    if not args.input:
        gui()
        return 0
    if not 0 <= args.threshold <= 1:
        parser.error("--threshold must be between 0 and 1")
    if args.min_group_size < 2:
        parser.error("--min-group-size must be at least 2")
    if args.mutual_knn < 0:
        parser.error("--mutual-knn must be >= 0")
    if args.max_group_size < 0:
        parser.error("--max-group-size must be >= 0")
    try:
        result = analyze(
            args.input,
            args.output,
            args.threshold,
            args.min_group_size,
            mutual_knn=args.mutual_knn,
            max_group_size=args.max_group_size,
            subcluster_step=args.subcluster_step,
            export_grouped_zip=args.export_grouped_zip,
            llm_model=args.llm_model,
            llm_url=args.llm_url,
            llm_provider=args.llm_provider,
            llm_api_key=args.llm_api_key,
            branch_matching=not args.no_branch_matching,
            llm_max_chars=args.llm_max_chars,
            llm_mode=args.llm_mode,
            llm_pass2=args.llm_pass2,
            export_online_bundle=args.export_online_bundle,
            import_reports_path=args.import_reports or None,
            log=print,
        )
        print("\nReports written:")
        for key, path in result["output"].items():
            print(f"  {key:18s} {path}")
        print(f"\nSummary: {result['chat_count']} chats; {result['group_count']} topic groups; {result['pair_count']} topic pairs; {result.get('branch_match_count', 0)} branch matches.")
        if not args.no_open:
            webbrowser.open(Path(result["output"]["html"]).resolve().as_uri())
        return 0
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
