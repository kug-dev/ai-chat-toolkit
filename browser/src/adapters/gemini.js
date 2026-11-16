  const gemini = {
    name: 'gemini',
    currentId: () => { const m = location.pathname.match(/\/app\/([0-9a-z]+)/i); return m ? 'c_' + m[1] : null; },
    async init() {
      if (this.at) return;
      this.base = (location.pathname.match(/^\/u\/\d+/) || [''])[0];
      const html = await (await request(`${this.base}/app`)).text();
      const pick = k => html.match(new RegExp(`"${k}":"([^"]+)"`))?.[1];
      this.at = pick('SNlM0e'); this.bl = pick('cfb2h'); this.sid = pick('FdrFJe');
      if (!this.at) throw new Error('Gemini auth token not found (page format changed?)');
    },
    async rpc(rpcid, args) {
      const q = new URLSearchParams({ rpcids: rpcid, 'source-path': `${this.base}/app`, bl: this.bl || '', 'f.sid': this.sid || '', hl: 'en', _reqid: String(Math.floor(Math.random() * 9e5) + 1e5), rt: 'c' });
      const body = new URLSearchParams({ 'f.req': JSON.stringify([[[rpcid, JSON.stringify(args), null, 'generic']]]), at: this.at });
      const r = await request(`${this.base}/_/BardChatUi/data/batchexecute?${q}`, { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8' }, body });
      for (const line of (await r.text()).split('\n')) {
        if (!line.startsWith('[')) continue;
        let arr; try { arr = JSON.parse(line); } catch { continue; }
        for (const e of arr) if (e[0] === 'wrb.fr' && e[1] === rpcid && e[2]) return JSON.parse(e[2]);
      }
      return null;
    },
    async list() {
      const out = new Map();
      for (const mode of [0, 1]) {
        let token = null;
        do {
          const res = await this.rpc('MaZiqc', [13, token, [mode, null, 1]]);
          token = res?.[1] || null;
          for (const r of res?.[2] || []) out.set(r[0], { id: r[0], title: r[1], updated: r[5]?.[0] ? toISO(r[5][0] * 1000) : '', tag: mode === 1 ? 'pinned' : '' });
          await sleep(CFG.delayMs);
        } while (token);
      }
      return [...out.values()];
    },
    async fetch(id) { return { id, data: await this.rpc('hNvQHb', [id, CFG.geminiMaxTurns, null, 1, [1], [4], null, 1]) }; },
    async media(u, kind = 'unknown') {
      const tries = [u];
      if (kind === 'image' && /(?:^|\.)googleusercontent\.com$/i.test(new URL(u).hostname)) {
        const base = u.replace(/=s\d+(?:-[a-z]+)?(?:-[a-z0-9-]+)?$/i, '');
        if (base !== u) tries.unshift(base + '=s0');
        else if (!/[?&]/.test(u)) tries.unshift(u + '=s0');
      }
      let last;
      for (const t of [...new Set(tries)]) {
        try {
          const blob = await getBlob(t);
          if (!blob || !blob.size) throw new Error('empty media response');
          if (/text\/html/i.test(blob.type)) throw new Error('server returned HTML instead of media');
          return blob;
        } catch (e) { last = e; }
      }
      throw last || new Error('media download failed');
    },
    normalize(raw) {
      const messages = [], files = [], seen = new Set(), tr = makeTracker();
      let snap = new Map();

      const isMediaUrl = (value, context = '') => {
        if (typeof value !== 'string' || value.length > 12000) return false;
        let u;
        try { u = new URL(value); } catch { return false; }
        if (u.protocol !== 'https:') return false;
        const host = u.hostname.toLowerCase();
        const trustedHost =
          host === 'googleusercontent.com' || host.endsWith('.googleusercontent.com') ||
          host === 'usercontent.google.com' || host.endsWith('.usercontent.google.com') ||
          host === 'lh3.google.com' || host.endsWith('.lh3.google.com') ||
          host === 'storage.googleapis.com' ||
          host === 'googlevideo.com' || host.endsWith('.googlevideo.com') ||
          host === 'googleapis.com' || host.endsWith('.googleapis.com') ||
          host === 'gstatic.com' || host.endsWith('.gstatic.com');
        if (!trustedHost || /\/a[-/]/.test(u.pathname)) return false;
        return /\.(?:png|jpe?g|webp|gif|avif|heic|mp4|webm|mov|m4v)(?:$|\/)/i.test(u.pathname) ||
          /googleusercontent\.com$/i.test(host) ||
          /(?:video|image|media|download|thumbnail|attachment)/i.test(u.pathname) ||
          /(?:filename|mime|type|format)=?(?:image|video|png|jpeg|webp|mp4|webm)/i.test(u.search) ||
          /(?:image|photo|picture|video|audio|media|download|thumbnail|attachment)/i.test(context);
      };

      const guessKind = (u, context = '') => {
        const z = `${u} ${context}`.toLowerCase();
        if (/(?:video|mp4|webm|quicktime|motion)/.test(z) || /\.(?:mp4|webm|mov|m4v)(?:$|[?#])/i.test(u)) return 'video';
        if (/(?:image|photo|picture|png|jpeg|jpg|webp|gif|avif)/.test(z) || /\.(?:png|jpe?g|webp|gif|avif)(?:$|[?#])/i.test(u)) return 'image';
        return 'unknown';
      };

      const addMedia = (url, origin, context = '') => {
        if (!isMediaUrl(url, context)) return;
        const kind = guessKind(url, context);
        const key = kind === 'image' ? url.replace(/=s\d+(?:-[a-z]+)?(?:-[a-z0-9-]+)?$/i, '') : url;
        if (seen.has(key)) return;
        seen.add(key);
        const index = files.length + 1;
        let name = `gemini_${kind === 'video' ? 'video' : kind === 'image' ? 'image' : 'media'}_${pad(index)}`;
        try {
          const u = new URL(url);
          const fn = u.searchParams.get('filename') || u.searchParams.get('name');
          if (fn) name = `${pad(index)}_${fn.replace(/[\\/:*?"<>|\x00-\x1f]+/g, '_')}`;
        } catch {}
        const ext = /\.(png|jpe?g|webp|gif|avif|heic|mp4|webm|mov|m4v)(?:$|[?#])/i.exec(url)?.[1];
        if (ext && !/\.[a-z0-9]{1,8}$/i.test(name)) name += `.${ext.toLowerCase()}`;
        files.push({ name, origin, load: () => this.media(url, kind) });
      };

      const urlRe = /https:\/\/[^\s"'<>\\\])}]+/g;
      const visited = new WeakSet();
      const walk = (value, origin, context = '', depth = 0, turnCits = null, turnNode = '') => {
        if (value == null || depth > 18) return;
        if (typeof value === 'string') {
          addMedia(value, origin, context);
          for (const match of value.matchAll(urlRe)) {
            const candidate = match[0].replace(/[.,;:!?]+$/, '');
            addMedia(candidate, origin, context);
          }
          const trimmed = value.trim();
          if (depth < 12 && ((trimmed.startsWith('[') && trimmed.endsWith(']')) ||
              (trimmed.startsWith('{') && trimmed.endsWith('}')))) {
            try { walk(JSON.parse(trimmed), origin, context, depth + 1, turnCits, turnNode); } catch {}
          }
          return;
        }
        if (typeof value !== 'object') return;
        if (visited.has(value)) return;
        visited.add(value);
        if (Array.isArray(value)) {
          // Detect Gemini Canvas / Immersive / Deep Research artifact tuples: [filename/title, content] or structured doc nodes
          if (origin === 'generated' && value.length >= 2 && typeof value[0] === 'string' && typeof value[1] === 'string') {
            const maybeTitle = value[0].trim(), maybeBody = value[1];
            if (maybeTitle.length >= 2 && maybeTitle.length <= 120 && !/^https?:\/\//i.test(maybeTitle) && !maybeTitle.includes('\n') && maybeBody.length >= 120 && (maybeBody.includes('\n') || /\.[a-z0-9]{1,6}$/i.test(maybeTitle))) {
              const ext = extOf(maybeTitle) || (maybeBody.trim().startsWith('<') ? 'html' : 'md');
              tr.apply(snap, { key: `canvas:${maybeTitle}`, title: maybeTitle, ext, content: maybeBody }, turnNode);
            }
          }
          // Detect grounding web citation tuples: [url, title, domain...]
          if (turnCits && CFG.citations && typeof value[0] === 'string' && /^https?:\/\//i.test(value[0]) && !isMediaUrl(value[0]) && typeof value[1] === 'string' && value[1].length >= 2 && value[1].length <= 160) {
            turnCits.push(`- [${value[1].trim()}](${value[0]})`);
          }
          value.forEach((child, i) => walk(child, origin, `${context} ${i}`, depth + 1, turnCits, turnNode));
        } else {
          for (const [key, child] of Object.entries(value)) {
            walk(child, origin, `${context} ${key}`, depth + 1, turnCits, turnNode);
          }
        }
      };

      const turns = raw?.data?.[0] || [];
      [...turns].reverse().forEach((t, i) => {
        const turnNode = `turn_${pad(i + 1)}`;
        snap = new Map(snap);
        const created = t?.[4]?.[0] ? toISO(t[4][0] * 1000) : '';
        const user = t?.[2]?.[0]?.[0];
        const cand = t?.[3]?.[0]?.[0];
        const model = cand?.[1]?.[0];
        // Gemini thinking / reasoning drafts often reside in cand?.[7] or cand?.[37]
        const thinkingRaw = cand?.[7]?.[0] || cand?.[37]?.[0]?.[0] || '';
        const turnCits = [];

        if (typeof user === 'string') messages.push({ role: 'user', created, text: user });
        walk(t?.[2], 'upload', `turn ${i} user`, 0, null, turnNode);
        walk(t?.[3], 'generated', `turn ${i} assistant`, 0, turnCits, turnNode);
        tr.commit(turnNode, snap);

        if (typeof model === 'string') {
          const parts = [];
          if (CFG.thinking && typeof thinkingRaw === 'string' && thinkingRaw.trim()) {
            parts.push(`<details><summary>Reasoning</summary>\n\n${thinkingRaw.trim()}\n</details>`);
          }
          parts.push(model);
          const uniqCits = [...new Set(turnCits)];
          if (uniqCits.length) parts.push(`### Sources\n${uniqCits.join('\n')}`);
          messages.push({ role: 'assistant', created, text: parts.join('\n\n') });
        }
      });

      return { messages, artifacts: tr.out, files, main: null, model: 'gemini' };
    }
  };

