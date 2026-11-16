  const chatgpt = {
    name: 'chatgpt',
    currentId: () => location.pathname.match(/\/c\/([0-9a-f-]{36})/)?.[1],
    async init() {
      if (this.headers) return;
      const s = await getJSON('/api/auth/session');
      if (!s.accessToken) throw new Error('Not logged in');
      this.headers = { Authorization: `Bearer ${s.accessToken}`, 'X-Authorization': `Bearer ${s.accessToken}` };
      try {
        const ws = getCookie('_account');
        if (ws) {
          const acc = await getJSON('/backend-api/accounts/check/v4-2023-04-27', { headers: this.headers });
          const id = acc.accounts?.[ws]?.account?.account_id;
          if (id) this.headers['Chatgpt-Account-Id'] = id;
        }
      } catch (e) { console.warn('[backup] workspace lookup failed', e); }
    },
    async list() {
      const out = new Map();
      for (const archived of [false, true]) {
        try {
          for (let o = 0; ; o += 100) {
            const p = await getJSON(`/backend-api/conversations?offset=${o}&limit=100&order=updated${archived ? '&is_archived=true' : ''}`, { headers: this.headers });
            (p.items || []).forEach(c => out.set(c.id, { id: c.id, title: c.title, updated: toISO(c.update_time), tag: archived ? 'archived' : '' }));
            if (!p.items?.length || o + 100 >= (p.total ?? 0)) break;
            await sleep(CFG.delayMs);
          }
        } catch (e) { if (!archived) throw e; console.warn('[backup] archived list failed', e); }
      }
      try {
        let cursor = null; const gizmos = [];
        do {
          const p = await getJSON(`/backend-api/gizmos/snorlax/sidebar?conversations_per_gizmo=0${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`, { headers: this.headers });
          (p.items || []).forEach(g => gizmos.push({ id: g.gizmo?.gizmo?.id, name: g.gizmo?.gizmo?.display?.name }));
          cursor = p.cursor || null;
        } while (cursor);
        for (const g of gizmos.filter(x => x.id)) {
          let cur = 0;
          do {
            const p = await getJSON(`/backend-api/gizmos/${g.id}/conversations?cursor=${cur}&limit=50`, { headers: this.headers });
            (p.items || []).forEach(c => out.set(c.id, { id: c.id, title: c.title, updated: toISO(c.update_time), tag: g.name || 'project' }));
            cur = p.cursor || null;
            await sleep(CFG.delayMs);
          } while (cur);
        }
      } catch (e) { console.warn('[backup] project list failed', e); }
      return [...out.values()];
    },
    fetch(id) { return getJSON(`/backend-api/conversation/${id}`, { headers: this.headers }); },
    async file(id, convId) {
      let last;
      for (const u of [
        `/backend-api/files/download/${id}?conversation_id=${convId}&inline=false`,
        `/backend-api/files/${id}/download`,
        `/backend-api/conversation/${convId}/attachment/${id}/download`,
      ]) {
        try { const j = await getJSON(u, { headers: this.headers }); if (j.download_url) return await getBlob(j.download_url, this.headers); }
        catch (e) { last = e; }
      }
      throw last || new Error('no download_url');
    },
    async sandbox(convId, msgId, path) {
      const j = await getJSON(`/backend-api/conversation/${convId}/interpreter/download?message_id=${msgId}&sandbox_path=${encodeURIComponent(path)}`, { headers: this.headers });
      if (!j.download_url) throw new Error(j.error_code || 'no download_url');
      return getBlob(j.download_url, this.headers);
    },
    normalize(raw, c) {
      const map = raw.mapping || {}, tr = makeTracker(), files = [], seen = new Set();
      const main = new Set(), path = [];
      let detectedModel = '';
      for (let id = raw.current_node; id && map[id]; id = map[id].parent) { main.add(id); if (map[id].message) path.push(map[id].message); }
      path.reverse();

      const addFile = (id, name, origin) => {
        if (!id) return;
        const value = String(id);
        if (/^https?:\/\//i.test(value)) {
          let u;
          try { u = new URL(value); } catch { return; }
          const host = u.hostname.toLowerCase();
          const trusted = host === 'chatgpt.com' || host.endsWith('.chatgpt.com') ||
            host === 'openai.com' || host.endsWith('.openai.com') ||
            host === 'oaiusercontent.com' || host.endsWith('.oaiusercontent.com') ||
            host === 'oaistatic.com' || host.endsWith('.oaistatic.com') ||
            host === 'oaidalleapiprodscus.blob.core.windows.net';
          if (u.protocol !== 'https:' || !trusted) return;
          const key = `url:${u.href}`;
          if (seen.has(key)) return;
          seen.add(key);
          let guessed = '';
          try { guessed = u.searchParams.get('filename') || u.searchParams.get('name') || decodeURIComponent(u.pathname.split('/').pop() || ''); } catch { guessed = ''; }
          const nm = name || guessed || `media_${pad(files.length + 1)}`;
          files.push({ name: nm, origin, load: async () => {
            const blob = await getBlob(u.href);
            if (blob.type && blob.type !== 'application/octet-stream') return blob;
            const ext = extOf(nm) || extOf(u.pathname);
            const mime = Object.entries(MIME_EXT).find(([, e]) => e === ext)?.[0];
            return mime ? new Blob([blob], { type: mime }) : blob;
          } });
          return;
        }
        if (seen.has(value)) return;
        seen.add(value);
        files.push({ name: name || `file_${value.slice(-8)}`, origin, load: () => this.file(value, c.id) });
      };

      const visit = (m, snap, nodeId) => {
        const role = m.author?.role, aname = m.author?.name || '', rec = m.recipient || '';
        if (!detectedModel && m.metadata?.model_slug) detectedModel = m.metadata.model_slug;
        (m.metadata?.attachments || []).forEach(a => addFile(a.id, a.name, 'upload'));
        for (const p of m.content?.parts || []) {
          if (!p || typeof p !== 'object') continue;
          if (p.asset_pointer) addFile(ptrId(p.asset_pointer), p.filename || p.name || null, role === 'user' ? 'upload' : 'generated');
          const mediaHint = /image|photo|picture|video|audio|media|attachment|file/i.test(`${p.type || ''} ${p.mime_type || ''} ${p.content_type || ''}`);
          if (mediaHint) {
            for (const key of ['image_url', 'video_url', 'audio_url', 'media_url', 'download_url', 'url']) {
              if (typeof p[key] === 'string' && p[key]) addFile(ptrId(p[key]), p.filename || p.name || null, role === 'user' ? 'upload' : 'generated');
            }
          }
        }
        for (const x of m.metadata?.aggregate_result?.messages || []) {
          const kind = String(x.message_type || x.type || '').toLowerCase();
          const mediaUrl = x.image_url || x.video_url || x.audio_url || x.media_url || x.download_url || (/(image|video|audio|file|media)/i.test(kind) ? x.url : null);
          if (mediaUrl) addFile(ptrId(mediaUrl), x.filename || x.name || null, 'generated');
        }

        if (role === 'assistant' && rec.startsWith('canmore.')) {
          try {
            const j = JSON.parse(m.content?.text ?? m.content?.parts?.[0]);
            if (rec === 'canmore.create_textdoc') {
              const t = String(j.type || '').split('/').pop();
              const key = j.name || 'canvas';
              const ext = j.type === 'document' ? 'md' : (LANG_EXT[t] || t || 'txt');
              tr.apply(snap, { key, title: key, ext, content: j.content }, nodeId);
              snap.set('\0last', { v: key });
            } else if (rec === 'canmore.update_textdoc') {
              const id = j.textdoc_id || m.metadata?.canvas?.textdoc_id;
              const key = (id && snap.get('\0a:' + id)?.v) || snap.get('\0last')?.v;
              if (key) tr.apply(snap, {
                key, edit: cur => {
                  for (const u of j.updates || []) { try { cur = cur.replace(new RegExp(u.pattern, u.multiple ? 'gs' : 's'), () => u.replacement); } catch {} }
                  return cur;
                },
              }, nodeId);
            }
          } catch (e) { console.warn('[backup] canvas parse failed', e); }
          return;
        }
        if (role === 'tool' && aname.startsWith('canmore.')) {
          const cv = m.metadata?.canvas, last = snap.get('\0last')?.v;
          if (cv?.textdoc_id && last) snap.set('\0a:' + cv.textdoc_id, { v: last });
          return;
        }
        if (role === 'assistant') {
          const text = (m.content?.parts || []).filter(p => typeof p === 'string').join('\n');
          for (const [, p] of text.matchAll(/sandbox:(\/[^\s)\]"'<>]+)/g)) {
            const k = m.id + p;
            if (seen.has(k)) continue;
            seen.add(k);
            let nm = baseName(p); try { nm = decodeURIComponent(nm); } catch {}
            files.push({ name: nm, origin: 'generated', load: () => this.sandbox(c.id, m.id, p) });
          }
        }
      };

      const roots = Object.keys(map).filter(id => !map[id].parent || !map[map[id].parent]);
      const stack = [...roots].reverse();
      while (stack.length) {
        const id = stack.pop(), node = map[id], snap = tr.fork(node.parent);
        if (node.message) visit(node.message, snap, id);
        tr.commit(id, snap);
        for (const ch of [...(node.children || [])].reverse()) stack.push(ch);
      }

      const messages = [];
      let pendingThoughts = [];
      let pendingScriptTool = null;
      for (const m of path) {
        const role = m.author?.role;
        const ctype = m.content?.content_type || '';
        const recipient = String(m.recipient || '');
        const authorTool = SCRIPT_TOOL_RE.test(String(m.author?.name || '')) ? String(m.author.name) : '';
        const guessedTool = recipient || authorTool || (role === 'tool' ? pendingScriptTool : (/^(?:code|code_cell|execution_input)$/i.test(ctype) ? 'python' : role)) || '';
        const toolIdentity = `${recipient} ${m.author?.name || ''} ${role || ''} ${ctype} ${pendingScriptTool || ''}`;
        const codeContent = /^(?:code|code_cell|execution_input)$/i.test(ctype);
        const isScriptCall = role === 'assistant' && ((recipient && recipient !== 'all' && SCRIPT_TOOL_RE.test(toolIdentity)) || codeContent);
        const isScriptResult = (role === 'tool' && !!pendingScriptTool) || (/^(?:execution_output|tool_result)$/i.test(ctype) && !!pendingScriptTool) || (!['user', 'assistant', 'system', 'tool'].includes(role) && SCRIPT_TOOL_RE.test(toolIdentity));
        if (CFG.toolRuns && (isScriptCall || isScriptResult) && (SCRIPT_TOOL_RE.test(toolIdentity) || !!pendingScriptTool)) {
          const body = payloadText(m.content?.parts || m.content?.text || m.content?.code || m.content);
          if (isScriptCall) pendingScriptTool = guessedTool || 'code tool';
          if (body.trim()) {
            const toolName = isScriptCall ? (guessedTool || 'code tool') : (guessedTool || pendingScriptTool || 'script tool');
            if (!isScriptCall) pendingScriptTool = null;
            const language = /python/i.test(toolName) ? 'python' : /bash|shell|terminal/i.test(toolName) ? 'bash' : /javascript|node/i.test(toolName) ? 'javascript' : '';
            messages.push({
              role: 'assistant',
              created: toISO(m.create_time),
              text: scriptMarkdownBlock(isScriptCall ? 'Script run' : 'Script result', toolName, body, isScriptCall ? language : ''),
            });
          }
          continue;
        }
        // Capture ChatGPT reasoning / thoughts blocks
        if (CFG.thinking && (ctype === 'thoughts' || ctype === 'reasoning_recap')) {
          const thoughtParts = (m.content?.thoughts || m.content?.parts || []).map(t => typeof t === 'string' ? t : (t?.content || t?.summary || '')).filter(Boolean);
          if (m.content?.content) thoughtParts.push(m.content.content);
          if (thoughtParts.length) pendingThoughts.push(thoughtParts.join('\n'));
          continue;
        }
        if (role === 'user') pendingScriptTool = null;
        if (!['user', 'assistant'].includes(role) || !m.content?.parts) continue;
        if (m.metadata?.is_visually_hidden_from_conversation || (m.recipient && m.recipient !== 'all')) continue;
        const text = m.content.parts.filter(p => typeof p === 'string').join('\n');
        const names = (m.metadata?.attachments || []).map(a => `[uploaded: ${a.name}]`);
        const thoughtBlock = (role === 'assistant' && pendingThoughts.length)
          ? [`<details><summary>Reasoning</summary>\n\n${pendingThoughts.join('\n\n')}\n</details>`]
          : [];
        if (role === 'assistant') pendingThoughts = [];

        // Capture web search citations from metadata.content_references / search_result_groups
        const cits = [];
        if (CFG.citations && role === 'assistant') {
          for (const ref of m.metadata?.content_references || []) {
            for (const item of ref.items || [ref]) {
              if (item?.url) cits.push(`- [${item.title || item.attribution || item.url}](${item.url})`);
            }
          }
          for (const grp of m.metadata?.search_result_groups || []) {
            for (const ent of grp.entries || []) {
              if (ent?.url) cits.push(`- [${ent.title || ent.url}](${ent.url})`);
            }
          }
        }
        const uniqCits = [...new Set(cits)];
        const citBlock = uniqCits.length ? `\n\n### Sources\n${uniqCits.join('\n')}` : '';
        const full = [...names, ...thoughtBlock, text].filter(s => s.trim()).join('\n\n') + citBlock;
        if (full.trim()) messages.push({ role, created: toISO(m.create_time), text: full });
      }
      const mainNodes = new Set([...main]);
      return { messages, artifacts: tr.out, files, main: mainNodes, model: detectedModel };
    },
  };

  // ════════════════════════════ Gemini ════════════════════════════
