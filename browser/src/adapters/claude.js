  const claude = {
    name: 'claude',
    projectsMap: new Map(),
    currentId: () => location.pathname.match(/\/chat\/([0-9a-f-]{36})/)?.[1],
    async init() {
      if (this.org) return;
      const orgs = await getJSON('/api/organizations');
      this.org = CFG.claudeOrgId || (orgs.find(o => (o.capabilities || []).includes('chat')) || orgs[0]).uuid;
    },
    async list() {
      const l = await getJSON(`/api/organizations/${this.org}/chat_conversations`);
      this.projectsMap.clear();
      try {
        const projs = await getJSON(`/api/organizations/${this.org}/projects`);
        for (const p of Array.isArray(projs) ? projs : (projs?.projects || [])) {
          if (p?.uuid && p?.name) this.projectsMap.set(p.uuid, { id: p.uuid, name: p.name, prompt: p.prompt_template || '' });
        }
      } catch (e) { console.warn('[backup] claude projects list failed', e); }
      return l.map(c => {
        const projId = c.project_uuid || c.project?.uuid || '';
        const projName = c.project?.name || this.projectsMap.get(projId)?.name || '';
        return { id: c.uuid, title: c.name, updated: c.updated_at, tag: projName, projectId: projId, model: c.model || '' };
      });
    },
    fetch(id) { return getJSON(`/api/organizations/${this.org}/chat_conversations/${id}?tree=True&rendering_mode=messages&render_all_tools=true`); },
    async fetchProjectDocs(projId) {
      if (!projId || !CFG.projectDocs) return [];
      const out = [];
      try {
        const proj = await getJSON(`/api/organizations/${this.org}/projects/${projId}`);
        if (proj?.prompt_template) {
          out.push({ path: `_project_knowledge/project_instructions.md`, content: `# Project Instructions: ${proj.name || projId}\n\n${proj.prompt_template}` });
        }
        const docs = await getJSON(`/api/organizations/${this.org}/projects/${projId}/docs`);
        for (const d of Array.isArray(docs) ? docs : []) {
          if (d?.content) {
            out.push({ path: `_project_knowledge/${safeName(d.file_name || d.uuid || 'doc', 'txt')}`, content: d.content });
          }
        }
      } catch (e) { console.warn('[backup] project docs fetch failed', e); }
      return out;
    },

    toolToArtifacts(b, snap) {
      const i = b.input || {}, n = String(b.name || '').split('__').pop(), arts = [];
      const last = snap.get('\0last')?.v;
      if (n === 'artifacts' && i.id) {
        const ext = i.type === 'application/vnd.ant.code' ? (LANG_EXT[i.language] || i.language || 'txt') : (ANT_EXT[i.type] || 'txt');
        if (i.command === 'update') arts.push({ key: i.id, edit: replaceEdit(i.old_str, i.new_str) });
        else arts.push({ key: i.id, title: i.title, ext, content: i.content });
      } else if (n === 'create_file' && i.path) {
        arts.push(fileArt(i.path, i.file_text));
      } else if (n === 'str_replace' && i.path) {
        arts.push({ key: i.path, edit: replaceEdit(i.old_str, i.new_str) });
      } else if (n === 'str_replace_based_edit_tool' && i.path) {
        if (i.command === 'create') arts.push(fileArt(i.path, i.file_text));
        else if (i.command === 'str_replace') arts.push({ key: i.path, edit: replaceEdit(i.old_str, i.new_str) });
        else if (i.command === 'insert') arts.push({ key: i.path, edit: c => { const L = c.split('\n'); L.splice(i.insert_line || 0, 0, i.insert_text ?? ''); return L.join('\n'); } });
      } else if (n === 'show_widget' && i.widget_code) {
        const svg = /^\s*<svg/i.test(i.widget_code);
        arts.push({ key: 'widget:' + (i.title || 'widget'), title: (i.title || 'widget') + (svg ? '.svg' : '.html'), ext: svg ? 'svg' : 'html', content: i.widget_code });
      } else if ((n === 'bash_tool' || n === 'bash') && typeof i.command === 'string') {
        for (const [, p, , body] of i.command.matchAll(/cat\s*>\s*(\S+)\s*<<\s*['"]?(\w+)['"]?\n([\s\S]*?)\n\2(?:\n|$)/g)) arts.push(fileArt(p, body));
      } else if (/Claude_Docs/.test(b.name || '')) {
        const cr = i.container?.create;
        if (n === 'batch' && cr?.doc?.markdown != null) {
          const key = 'doc:' + (cr.name || 'untitled');
          arts.push({ key, title: (cr.name || 'doc') + '.md', ext: 'md', content: cr.doc.markdown, setLast: key });
        } else if (n === 'update' && last && typeof i.payload === 'object') {
          for (const op of i.payload?.ops || []) {
            const c = op?.source?.from?.content;
            if (op.op === 'insert' && c != null && op.side === 'end') arts.push({ key: last, edit: p => p + '\n\n' + c });
          }
        }
      }
      return arts;
    },

    outputPaths(b) {
      const i = b.input || {}, n = String(b.name || '').split('__').pop(), ps = [];
      if (n === 'present_files') ps.push(...(i.filepaths || []));
      if (n === 'Artifact' && i.file_path) ps.push(i.file_path, ...(i.files || []));
      if (n === 'create_file' && typeof i.path === 'string' && i.path.startsWith('/mnt/user-data/outputs/') && !['code', 'text', 'web'].includes(typeOf(extOf(i.path)))) ps.push(i.path);
      return ps.filter(p => typeof p === 'string' && p.startsWith('/'));
    },
    async downloadOutput(convId, path) {
      let last;
      for (const p of [path, path.replace(/^\//, '')]) {
        try { return await getBlob(`/api/organizations/${this.org}/conversations/${convId}/wiggle/download-file?path=${encodeURIComponent(p)}`); }
        catch (e) { last = e; }
      }
      throw last;
    },

    normalize(raw, c) {
      const tr = makeTracker(), files = [], messages = [], seen = new Set(), outPaths = new Set(), byId = new Map();
      const scriptToolIds = new Map();
      const all = (raw.chat_messages || []).slice().sort((a, b) => (a.index ?? 0) - (b.index ?? 0));
      all.forEach(m => byId.set(m.uuid, m));
      const main = new Set();
      for (let id = raw.current_leaf_message_uuid || all[all.length - 1]?.uuid; id && byId.has(id) && !main.has(id); id = byId.get(id).parent_message_uuid) main.add(id);

      let imgN = 0;
      for (const m of all) {
        const snap = tr.fork(m.parent_message_uuid), parts = [], uploaded = [], citations = [];
        for (const b of m.content || []) {
          if (b.type === 'thinking' && CFG.thinking && b.thinking) {
            parts.push(`<details><summary>Reasoning</summary>\n\n${String(b.thinking).trim()}\n</details>`);
          } else if (b.type === 'text') {
            parts.push(b.text);
            if (CFG.citations && Array.isArray(b.citations)) {
              for (const cit of b.citations) {
                const u = cit.url || cit.source?.url;
                const t = cit.title || cit.source?.title || u;
                if (u) citations.push(`- [${t}](${u})`);
              }
            }
          } else if (b.type === 'tool_use') {
            for (const a of this.toolToArtifacts(b, snap)) {
              const ent = tr.apply(snap, a, m.uuid);
              if (a.setLast) snap.set('\0last', { v: a.setLast });
              if (ent && !a.edit) parts.push(`[artifact: ${ent.title} v${ent.v}]`);
            }
            const toolName = String(b.name || '');
            if (CFG.toolRuns && SCRIPT_TOOL_RE.test(toolName)) {
              if (b.id) scriptToolIds.set(b.id, toolName);
              const inputText = toolInputText(b.input || {});
              if (inputText.trim()) parts.push(scriptMarkdownBlock('Script run', toolName, inputText, /python/i.test(toolName) ? 'python' : /bash|shell|terminal/i.test(toolName) ? 'bash' : ''));
            }
            this.outputPaths(b).forEach(p => outPaths.add(p));
          } else if (b.type === 'image' && b.source?.type === 'base64' && b.source.data) {
            const type = b.source.media_type || 'image/png', k = ++imgN;
            files.push({ name: `${m.sender === 'human' ? 'uploaded' : 'generated'}_image_${pad(k)}.${MIME_EXT[type] || 'png'}`, origin: m.sender === 'human' ? 'upload' : 'generated', load: async () => b64Blob(b.source.data, type) });
          } else if (b.type === 'tool_result') {
            for (const x of (Array.isArray(b.content) ? b.content : [])) {
              if (x?.type === 'image' && x.source?.type === 'base64' && x.source.data) {
                const type = x.source.media_type || 'image/png', k = ++imgN;
                files.push({ name: `tool_image_${pad(k)}.${MIME_EXT[type] || 'png'}`, origin: 'generated', load: async () => b64Blob(x.source.data, type) });
              } else if (CFG.citations && x?.url && x?.title) {
                citations.push(`- [${x.title}](${x.url})`);
              }
            }
            const toolName = scriptToolIds.get(b.tool_use_id);
            const resultText = payloadText(b.content);
            if (CFG.toolRuns && toolName && resultText.trim()) parts.push(scriptMarkdownBlock('Script result', toolName, resultText));
          }
        }
        if (!parts.length && typeof m.text === 'string' && m.text.trim()) parts.push(m.text);
        tr.commit(m.uuid, snap);

        for (const f of [...(m.files_v2 || []), ...(m.files || [])]) {
          const id = f.file_uuid;
          if (!id || seen.has(id)) continue;
          seen.add(id);
          const urls = [f.document_asset?.url, f.preview_asset?.url, f.preview_url, f.thumbnail_asset?.url, f.thumbnail_url,
            `/api/${this.org}/files/${id}/contents`, `/api/${this.org}/files/${id}/preview`].filter(Boolean);
          uploaded.push(f.file_name || id);
          files.push({
            name: f.file_name || id, origin: m.sender === 'human' ? 'upload' : 'generated',
            load: async () => { let last; for (const u of urls) { try { return await getBlob(u); } catch (e) { last = e; } } throw last || new Error('no url in metadata'); },
          });
        }
        for (const a of m.attachments || []) {
          uploaded.push(a.file_name);
          if (a.extracted_content) files.push({ name: `${a.file_name || 'attachment'}.extracted.txt`, origin: 'upload', load: async () => new Blob([a.extracted_content], { type: 'text/plain' }) });
        }
        if (main.has(m.uuid)) {
          const uniqCits = [...new Set(citations)];
          const citBlock = uniqCits.length ? `\n\n### Sources\n${uniqCits.join('\n')}` : '';
          messages.push({ role: m.sender === 'human' ? 'user' : 'assistant', created: m.created_at, text: [...uploaded.map(x => `[uploaded: ${x}]`), ...parts].join('\n\n') + citBlock });
        }
      }
      for (const p of outPaths) files.push({ name: baseName(p), origin: 'generated', load: () => this.downloadOutput(c.id, p) });
      return { messages, artifacts: tr.out, files, main, model: raw.model || c.model || '' };
    },
  };

  // ════════════════════════════ ChatGPT ════════════════════════════
  const ptrId = p => { const s = String(p); return /^https?:\/\//i.test(s) ? s : s.replace(/^[\w-]+:\/\//, ''); };
