// ==UserScript==
// @name         AI Chat Backup (Claude / ChatGPT / Gemini)
// @namespace    http://tampermonkey.net/
// @version      6.3
// @description  Back up chats, script runs/results, artifacts and media with bilingual controls, streaming ZIPs, and bundled offline _viewer.html.
// @match        https://claude.ai/*
// @match        https://*.claude.ai/*
// @match        https://chatgpt.com/*
// @match        https://*.chatgpt.com/*
// @match        https://chat.openai.com/*
// @match        https://gemini.google.com/*
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_deleteValue
// @grant        GM_registerMenuCommand
// @grant        GM_xmlhttpRequest
// @connect      claude.ai
// @connect      *.claude.ai
// @connect      anthropic.com
// @connect      *.anthropic.com
// @connect      anthropicusercontent.com
// @connect      *.anthropicusercontent.com
// @connect      claudeusercontent.com
// @connect      *.claudeusercontent.com
// @connect      chatgpt.com
// @connect      *.chatgpt.com
// @connect      openai.com
// @connect      *.openai.com
// @connect      oaiusercontent.com
// @connect      *.oaiusercontent.com
// @connect      oaistatic.com
// @connect      *.oaistatic.com
// @connect      cdn.openai.com
// @connect      oaidalleapiprodscus.blob.core.windows.net
// @connect      googleusercontent.com
// @connect      *.googleusercontent.com
// @connect      *.usercontent.google.com
// @connect      google.com
// @connect      *.google.com
// @connect      googleapis.com
// @connect      *.googleapis.com
// @connect      storage.googleapis.com
// @connect      googlevideo.com
// @connect      *.googlevideo.com
// @connect      *.gstatic.com
// @run-at       document-idle
// ==/UserScript==

(() => {
  'use strict';

  const HOST = location.hostname.replace(/^www\./, '');
  const SITE = { 'claude.ai': 'claude', 'chatgpt.com': 'chatgpt', 'chat.openai.com': 'chatgpt', 'gemini.google.com': 'gemini' }[HOST];
  if (!SITE || window.top !== window.self) return;

  // ════════════════════════════ Config ════════════════════════════
  const MB = 1048576;
  const CFG_KEY = 'cfg5';
  const DEFAULTS = {
    json: true, md: true,
    thinking: true,       // Include model thinking / reasoning blocks in chat.md
    toolRuns: true,       // Include script/tool calls and their textual execution results
    language: 'en',       // UI language: 'en' | 'he'
    citations: true,      // Include web search citations & grounding sources in chat.md
    artifacts: true,      // Claude artifacts / created files, ChatGPT canvas, Gemini Canvas/Immersives
    snippets: true,       // every fenced code block in assistant replies
    uploads: true,        // files the user uploaded
    generated: true,      // files / images / video the AI produced (best effort)
    projectDocs: true,    // Save Claude Project instructions & knowledge docs
    bundleViewer: true,   // Bundle standalone _viewer.html inside each ZIP part
    compressText: true,   // Native CompressionStream('deflate-raw') for text/JSON/code
    directDisk: false,    // Stream directly to disk via showSaveFilePicker when available
    versions: 'all',      // 'all' | 'latest'
    latestCopy: true,     // also write latest version as a plain file
    types: { code: true, text: true, web: true, images: true, video: true, audio: true, documents: true, data: true, archives: true, other: true },
    extInclude: '', extExclude: '',
    maxFileMB: 100, zipMB: 250, zipChats: 150,
    timeoutSec: 60, retries: 4, delayMs: 400, fileConcurrency: 3,
    autoSelect: 'new',    // 'new' | 'all' | 'none' | 'failed'
    since: '', limit: 0,
    claudeOrgId: '', geminiMaxTurns: 100,
  };
  const CFG = (() => {
    let saved = {};
    try { saved = GM_getValue(CFG_KEY, {}) || {}; } catch {}
    return { ...DEFAULTS, ...saved, types: { ...DEFAULTS.types, ...(saved.types || {}) } };
  })();
  const saveCfg = () => { try { GM_setValue(CFG_KEY, CFG); } catch (e) { console.warn('[backup] cfg save failed', e); } };

  // ════════════════════════════ File types ════════════════════════════
  const TYPE_DEFS = {
    code:      { label: 'Code',       exts: 'py js mjs cjs ts tsx jsx java kt c h cpp cc hpp cs go rs rb php swift sh bash zsh bat ps1 sql css scss less lua pl r jl dart vue svelte tf ipynb' },
    text:      { label: 'Text / docs (md, txt)', exts: 'md markdown txt rst tex log mermaid' },
    web:       { label: 'Web pages (html)',      exts: 'html htm xhtml' },
    images:    { label: 'Images',     exts: 'png jpg jpeg gif webp svg bmp tif tiff heic heif avif ico' },
    video:     { label: 'Video',      exts: 'mp4 webm mov mkv avi m4v' },
    audio:     { label: 'Audio',      exts: 'mp3 wav ogg m4a flac aac opus' },
    documents: { label: 'Documents (pdf, office)', exts: 'pdf doc docx odt rtf ppt pptx odp xls xlsx ods epub' },
    data:      { label: 'Data (csv, json, xml…)',  exts: 'csv tsv json jsonl ndjson xml yaml yml toml parquet sqlite db ini' },
    archives:  { label: 'Archives',   exts: 'zip tar gz tgz 7z rar bz2 xz' },
    other:     { label: 'Everything else', exts: '' },
  };
  const EXT_TYPE = {};
  for (const [t, d] of Object.entries(TYPE_DEFS)) d.exts.split(' ').filter(Boolean).forEach(e => (EXT_TYPE[e] = t));

  const COMPRESSIBLE_EXTS = new Set([
    ...TYPE_DEFS.code.exts.split(' '),
    ...TYPE_DEFS.text.exts.split(' '),
    ...TYPE_DEFS.web.exts.split(' '),
    'json', 'jsonl', 'ndjson', 'csv', 'tsv', 'xml', 'yaml', 'yml', 'toml', 'ini', 'svg',
  ].filter(Boolean));

  const LANG_EXT = {
    python: 'py', py: 'py', javascript: 'js', js: 'js', typescript: 'ts', ts: 'ts', jsx: 'jsx', tsx: 'tsx', react: 'jsx', html: 'html', css: 'css', json: 'json',
    bash: 'sh', shell: 'sh', sh: 'sh', zsh: 'sh', markdown: 'md', md: 'md', yaml: 'yml', yml: 'yml', xml: 'xml', sql: 'sql', java: 'java', c: 'c', cpp: 'cpp', 'c++': 'cpp',
    csharp: 'cs', 'c#': 'cs', go: 'go', rust: 'rs', ruby: 'rb', php: 'php', swift: 'swift', kotlin: 'kt', lua: 'lua', r: 'r', powershell: 'ps1', toml: 'toml',
    plaintext: 'txt', text: 'txt', mermaid: 'mermaid', svg: 'svg', latex: 'tex',
  };
  const MIME_EXT = {
    'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp', 'image/gif': 'gif', 'image/svg+xml': 'svg', 'image/avif': 'avif', 'image/heic': 'heic', 'image/bmp': 'bmp', 'image/tiff': 'tiff', 'image/x-icon': 'ico',
    'video/mp4': 'mp4', 'video/webm': 'webm', 'video/quicktime': 'mov', 'video/x-matroska': 'mkv', 'video/x-msvideo': 'avi', 'audio/mpeg': 'mp3', 'audio/wav': 'wav', 'audio/x-wav': 'wav', 'audio/ogg': 'ogg', 'audio/mp4': 'm4a', 'audio/flac': 'flac', 'audio/aac': 'aac', 'audio/opus': 'opus',
    'application/pdf': 'pdf', 'application/zip': 'zip', 'application/json': 'json', 'text/plain': 'txt', 'text/csv': 'csv', 'text/html': 'html', 'text/markdown': 'md',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'pptx',
  };
  const ANT_EXT = { 'text/html': 'html', 'text/markdown': 'md', 'image/svg+xml': 'svg', 'application/vnd.ant.react': 'jsx', 'application/vnd.ant.mermaid': 'mermaid', 'text/plain': 'txt' };

  const extOf = n => { const m = /\.([A-Za-z0-9]{1,8})$/.exec(n || ''); return m ? m[1].toLowerCase() : ''; };
  const typeOf = ext => EXT_TYPE[ext] || 'other';
  const parseExts = s => new Set(String(s || '').split(/[\s,;]+/).map(x => x.replace(/^\./, '').toLowerCase()).filter(Boolean));
  const extAllowed = ext => {
    if (!CFG.types[typeOf(ext)]) return false;
    const inc = parseExts(CFG.extInclude), exc = parseExts(CFG.extExclude);
    if (inc.size && !inc.has(ext)) return false;
    return !exc.has(ext);
  };
  const withExt = (name, data) => {
    if (extOf(name)) return name;
    const e = MIME_EXT[(data?.type || '').split(';')[0]];
    return e ? `${name}.${e}` : name;
  };

  // ════════════════════════════ Helpers ════════════════════════════
  const ctl = { cancelled: false };
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const slug = s => (s || 'untitled').replace(/[^\p{L}\p{N}]+/gu, '_').replace(/^_|_$/g, '').slice(0, 60) || 'untitled';
  const safeName = (t, ext) => { let n = String(t || 'untitled').replace(/[\\/:*?"<>|\x00-\x1f]+/g, '_').slice(0, 100); if (ext && extOf(n) !== ext) n += '.' + ext; return n; };
  const toISO = v => (v == null ? '' : typeof v === 'number' ? new Date(v > 1e12 ? v : v * 1000).toISOString() : v);
  const day = v => (v ? toISO(v).slice(0, 10) : 'unknown');
  const pad = n => String(n).padStart(2, '0');
  const sizeOf = d => (d?.size ?? d?.length ?? 0);
  const baseName = p => String(p).split('/').pop();
  const shortHash = s => { let h = 5381; for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) >>> 0; return h.toString(16).padStart(8, '0'); };
  const getCookie = k => document.cookie.match(`(^|;)\\s*${k}\\s*=\\s*([^;]+)`)?.pop() || '';
  const withTimeout = (p, ms, label = 'operation') => new Promise((res, rej) => {
    const t = setTimeout(() => rej(new Error(`timeout: ${label}`)), ms);
    Promise.resolve(p).then(v => { clearTimeout(t); res(v); }, e => { clearTimeout(t); rej(e); });
  });
  async function pool(items, n, fn) {
    let i = 0;
    await Promise.all(Array.from({ length: Math.min(Math.max(1, n), items.length) }, async () => {
      while (i < items.length && !ctl.cancelled) { const k = i++; await fn(items[k], k); }
    }));
  }

  async function request(url, opts = {}) {
    let last;
    for (let i = 0; i <= CFG.retries; i++) {
      if (ctl.cancelled) throw new Error('cancelled');
      const ac = new AbortController();
      const timer = setTimeout(() => ac.abort(), CFG.timeoutSec * 1000);
      let r;
      try { r = await fetch(url, { credentials: 'include', ...opts, signal: ac.signal }); }
      catch (e) { last = e; clearTimeout(timer); await sleep(1000 * 2 ** i); continue; }
      clearTimeout(timer);
      if (r.ok) return r;
      last = new Error(`${r.status} ${String(url).slice(0, 90)}`);
      last.status = r.status;
      if (r.status !== 429 && r.status < 500) throw last;
      const ra = Number(r.headers.get('retry-after'));
      await sleep(ra > 0 ? Math.min(ra, 120) * 1000 : 1000 * 2 ** i);
    }
    throw last;
  }
  const getJSON = async (url, opts) => withTimeout((await request(url, opts)).json(), CFG.timeoutSec * 2000, 'json body');

  async function getBlob(url, headers = {}) {
    const u = new URL(url, location.origin);
    const maxBytes = CFG.maxFileMB * MB;
    if (u.origin === location.origin) {
      const r = await request(u.href, { headers });
      const len = Number(r.headers.get('content-length'));
      if (len > maxBytes) throw new Error(`over max file size (${(len / MB).toFixed(0)} MB)`);
      return withTimeout(r.blob(), CFG.timeoutSec * 3000, 'blob body');
    }
    if (u.protocol !== 'https:') throw new Error(`refusing insecure cross-origin download: ${u.host}`);
    return new Promise((res, rej) => GM_xmlhttpRequest({
      method: 'GET', url: u.href, responseType: 'blob', timeout: CFG.timeoutSec * 1000,
      onload: r => {
        if (r.status < 200 || r.status >= 300) return rej(new Error(`${r.status || 'HTTP error'} ${u.host}`));
        const blob = r.response;
        if (!blob || typeof blob.size !== 'number') return rej(new Error(`non-blob response from ${u.host}`));
        if (blob.size > maxBytes) return rej(new Error(`over max file size (${(blob.size / MB).toFixed(1)} MB)`));
        if (!blob.size) return rej(new Error(`empty response from ${u.host}`));
        res(blob);
      },
      onerror: () => rej(new Error(`network error ${u.host}`)),
      ontimeout: () => rej(new Error(`timeout ${u.host}`)),
    }));
  }
  const b64Blob = (b64, type) => { const bin = atob(b64), u8 = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i); return new Blob([u8], { type }); };

  const SCRIPT_TOOL_RE = /(?:python|code(?:_interpreter)?|interpreter|terminal|shell|bash|javascript|node|exec|powershell)/i;
  function payloadText(value, depth = 0) {
    if (value == null || depth > 8) return '';
    if (typeof value === 'string') return value;
    if (typeof value === 'number' || typeof value === 'boolean') return String(value);
    if (Array.isArray(value)) return value.map(v => payloadText(v, depth + 1)).filter(Boolean).join('\n');
    if (typeof value === 'object') {
      for (const key of ['text', 'content', 'parts', 'stdout', 'stderr', 'output', 'result', 'code', 'command', 'script']) {
        if (value[key] != null) {
          const result = payloadText(value[key], depth + 1);
          if (result) return result;
        }
      }
    }
    return '';
  }
  function markdownFence(value, language = '') {
    const text = String(value ?? '').slice(0, 120000);
    const longest = Math.max(0, ...[...text.matchAll(/`+/g)].map(m => m[0].length));
    const fence = '`'.repeat(Math.max(3, longest + 1));
    return `${fence}${language}\n${text}${text.endsWith('\n') ? '' : '\n'}${fence}`;
  }
  function scriptMarkdownBlock(kind, tool, value, language = '') {
    const name = String(tool || 'script tool').replace(/[<>\r\n]/g, '').slice(0, 64);
    const body = String(value || '').trim();
    const content = body ? markdownFence(body, language) : '_No textual content was provided._';
    return `<details><summary>${kind} — ${name}</summary>\n\n${content}\n</details>`;
  }
  function toolInputText(input) {
    if (typeof input === 'string') return input;
    if (input && typeof input === 'object') {
      for (const key of ['command', 'code', 'script', 'program', 'source']) {
        if (typeof input[key] === 'string') return input[key];
      }
      return JSON.stringify(input, null, 2);
    }
    return String(input ?? '');
  }

  // ════════════════════════════ Streaming ZIP writer (DEFLATE + Direct-to-Disk) ════════════════════════════
  //#region zip
  const TE = new TextEncoder();
  const HAS_DEFLATE_RAW = (() => {
    try { new CompressionStream('deflate-raw'); return true; } catch { return false; }
  })();
  const CRC_T = (() => { const t = new Uint32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
  const crcAdd = (crc, u8) => { for (let i = 0; i < u8.length; i++) crc = CRC_T[(crc ^ u8[i]) & 255] ^ (crc >>> 8); return crc; };
  const isBlob = d => !!d && typeof d === 'object' && typeof d.size === 'number' && typeof d.slice === 'function';
  const readBuf = b => (b.arrayBuffer ? b.arrayBuffer() : new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = () => rej(r.error); r.readAsArrayBuffer(b); }));
  const tick = () => new Promise(r => setTimeout(r, 0));
  const ZIP_CHUNK = 4 * 1048576;
  const ZIP_LIMIT = 4000000000;
  const ZIP_MAX_ENTRIES = 60000;

  async function deflateRawBytes(u8) {
    if (!HAS_DEFLATE_RAW || u8.length < 128) return null;
    try {
      const cs = new CompressionStream('deflate-raw');
      const writer = cs.writable.getWriter();
      writer.write(u8);
      writer.close();
      const buf = await new Response(cs.readable).arrayBuffer();
      const comp = new Uint8Array(buf);
      return comp.length < u8.length ? comp : null;
    } catch {
      return null;
    }
  }

  class ZipWriter {
    constructor(writableStream = null) {
      this.parts = [];
      this.cd = [];
      this.offset = 0;
      this.names = new Set();
      this.stream = writableStream; // Optional FileSystemWritableFileStream for near-zero RAM
    }
    get count() { return this.cd.length; }
    unique(path) {
      let p = path, i = 1;
      while (this.names.has(p)) { const m = /^(.*?)(\.[^./]+)?$/.exec(path); p = `${m[1]}_${++i}${m[2] || ''}`; }
      this.names.add(p);
      return p;
    }
    async add(path, data, date = new Date()) {
      const cleanPath = this.unique(path.replace(/\\/g, '/').replace(/^\/+/, ''));
      const name = TE.encode(cleanPath);
      const ext = extOf(cleanPath);
      let crc = 0xFFFFFFFF, uncompSize = 0, compSize = 0, method = 0, payload = data;

      if (isBlob(data)) {
        uncompSize = data.size;
        for (let o = 0; o < uncompSize; o += ZIP_CHUNK) {
          crc = crcAdd(crc, new Uint8Array(await readBuf(data.slice(o, o + ZIP_CHUNK))));
          await tick();
        }
        if (CFG.compressText && COMPRESSIBLE_EXTS.has(ext) && uncompSize <= 25 * MB) {
          const u8 = new Uint8Array(await readBuf(data));
          const deflated = await deflateRawBytes(u8);
          if (deflated) { payload = deflated; compSize = deflated.length; method = 8; }
        }
        if (!method) compSize = uncompSize;
      } else {
        const u8 = typeof data === 'string' ? TE.encode(data) : data;
        uncompSize = u8.length;
        crc = crcAdd(crc, u8);
        if (CFG.compressText && (typeof data === 'string' || COMPRESSIBLE_EXTS.has(ext))) {
          const deflated = await deflateRawBytes(u8);
          if (deflated) { payload = deflated; compSize = deflated.length; method = 8; }
          else { payload = u8; compSize = uncompSize; }
        } else {
          payload = u8;
          compSize = uncompSize;
        }
      }
      crc = (crc ^ 0xFFFFFFFF) >>> 0;
      const time = (date.getHours() << 11) | (date.getMinutes() << 5) | (date.getSeconds() >> 1);
      const dd = ((date.getFullYear() - 1980) << 9) | ((date.getMonth() + 1) << 5) | date.getDate();
      const lh = new Uint8Array(30 + name.length), v = new DataView(lh.buffer);
      v.setUint32(0, 0x04034b50, true); v.setUint16(4, 20, true); v.setUint16(6, 0x0800, true); v.setUint16(8, method, true);
      v.setUint16(10, time, true); v.setUint16(12, dd, true); v.setUint32(14, crc, true);
      v.setUint32(18, compSize, true); v.setUint32(22, uncompSize, true); v.setUint16(26, name.length, true); v.setUint16(28, 0, true);
      lh.set(name, 30);
      this.cd.push({ name, crc, compSize, uncompSize, method, time, dd, off: this.offset });
      if (this.stream) {
        await this.stream.write(lh);
        await this.stream.write(payload);
      } else {
        this.parts.push(lh, payload);
      }
      this.offset += lh.length + compSize;
    }
    async finish() {
      if (this.cd.length > 65535) throw new Error('too many entries for one ZIP');
      const cdParts = []; let cdSize = 0;
      for (const e of this.cd) {
        const b = new Uint8Array(46 + e.name.length), v = new DataView(b.buffer);
        v.setUint32(0, 0x02014b50, true); v.setUint16(4, 20, true); v.setUint16(6, 20, true); v.setUint16(8, 0x0800, true); v.setUint16(10, e.method, true);
        v.setUint16(12, e.time, true); v.setUint16(14, e.dd, true); v.setUint32(16, e.crc, true);
        v.setUint32(20, e.compSize, true); v.setUint32(24, e.uncompSize, true); v.setUint16(28, e.name.length, true);
        v.setUint32(42, e.off, true); b.set(e.name, 46);
        cdParts.push(b); cdSize += b.length;
      }
      const end = new Uint8Array(22), v = new DataView(end.buffer);
      v.setUint32(0, 0x06054b50, true); v.setUint16(8, this.cd.length, true); v.setUint16(10, this.cd.length, true);
      v.setUint32(12, cdSize, true); v.setUint32(16, this.offset, true);
      if (this.stream) {
        for (const p of cdParts) await this.stream.write(p);
        await this.stream.write(end);
        await this.stream.close();
        this.cd = []; this.names.clear();
        return null;
      }
      const blob = new Blob([...this.parts, ...cdParts, end], { type: 'application/zip' });
      this.parts = []; this.cd = []; this.names.clear();
      return blob;
    }
  }
  //#endregion zip

  async function saveBlob(blob, name) {
    if (!blob) return;
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = name; a.style.display = 'none';
    document.documentElement.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 180000);
    await sleep(1500);
  }

  // ════════════════════════════ Standalone _viewer.html Generator ════════════════════════════
  function buildStandaloneViewerHtml(manifestObj) {
    const embeddedJson = JSON.stringify(manifestObj).replace(/<\//g, '<\\/');
    return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI Chat Backup — Offline Archive Viewer</title>
<style>
:root{color-scheme:light dark;--bg:Canvas;--fg:CanvasText;--mut:GrayText;--bd:#8884;--ac:#10a37f;--panel:color-mix(in srgb,Canvas 96%,CanvasText)}
*{box-sizing:border-box}body{margin:0;font:14px/1.5 system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--fg);display:flex;height:100vh;overflow:hidden}
aside{width:340px;border-right:1px solid var(--bd);display:flex;flex-direction:column;background:var(--panel)}
header{padding:12px 14px;border-bottom:1px solid var(--bd)}
header h1{margin:0;font-size:16px}
.search{padding:8px 12px;border-bottom:1px solid var(--bd);display:flex;gap:6px}
.search input{flex:1;padding:6px 8px;border:1px solid var(--bd);border-radius:6px;background:var(--bg);color:var(--fg)}
.list{flex:1;overflow:auto;padding:6px}
.item{padding:8px 10px;border-radius:6px;cursor:pointer;border-bottom:1px solid var(--bd)}
.item:hover,.item.active{background:color-mix(in srgb,var(--bg) 85%,var(--ac))}
.item b{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.meta{font-size:12px;color:var(--mut);display:flex;gap:6px;flex-wrap:wrap;margin-top:2px}
main{flex:1;display:flex;flex-direction:column;overflow:hidden}
.toolbar{padding:10px 16px;border-bottom:1px solid var(--bd);display:flex;justify-content:space-between;align-items:center;gap:12px}
.content{flex:1;overflow:auto;padding:20px 28px;max-width:960px}
.turn{border:1px solid var(--bd);border-radius:8px;padding:12px 16px;margin-bottom:14px;background:var(--panel)}
.turn pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.45 ui-monospace,monospace;background:var(--bg);padding:10px;border-radius:6px;border:1px solid var(--bd)}
.pill{font-size:11px;padding:1px 7px;border-radius:8px;border:1px solid var(--bd)}
</style></head><body>
<aside>
  <header>
    <h1>AI Chat Backup Viewer</h1>
    <div class="meta" id="hdr-meta"></div>
  </header>
  <div class="search">
    <input id="q" placeholder="Filter conversations…">
  </div>
  <div style="padding:6px 12px;border-bottom:1px solid var(--bd);font-size:12px;color:var(--mut)">
    Tip: Open a chat below, or load extracted folder files: <input type="file" id="dir-pick" webkitdirectory multiple style="max-width:180px;font-size:11px">
  </div>
  <div class="list" id="chat-list"></div>
</aside>
<main>
  <div class="toolbar">
    <strong id="cur-title">Select a conversation</strong>
    <span class="meta" id="cur-links"></span>
  </div>
  <div class="content" id="viewer-body">
    <p style="color:var(--mut)">Select any conversation on the left to inspect its backup manifest summary, artifacts, saved attachments, or open its local <code>chat.md</code> transcript.</p>
  </div>
</main>
<script id="manifest-data" type="application/json">${embeddedJson}</script>
<script>
(() => {
  const MANIFEST = JSON.parse(document.getElementById('manifest-data').textContent);
  const chats = MANIFEST.chats || [];
  const fileMap = new Map();
  document.getElementById('hdr-meta').textContent = \`Site: \${MANIFEST.site || 'unknown'} · \${chats.length} chats · \${(MANIFEST.created || '').slice(0,10)}\`;
  const listEl = document.getElementById('chat-list');
  const qEl = document.getElementById('q');
  const bodyEl = document.getElementById('viewer-body');
  const titleEl = document.getElementById('cur-title');
  const linksEl = document.getElementById('cur-links');

  function slug(s) { return (s || 'untitled').replace(/[^\\p{L}\\p{N}]+/gu, '_').replace(/^_|_$/g, '').slice(0, 60) || 'untitled'; }
  function day(v) { return v ? String(v).slice(0, 10) : 'unknown'; }
  function folderFor(c) { return \`\${day(c.updated)}_\${slug(c.title)}_\${String(c.id).slice(0, 8)}\`; }
  function esc(s) { return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

  document.getElementById('dir-pick').addEventListener('change', e => {
    for (const f of e.target.files || []) {
      const rel = f.webkitRelativePath.replace(/^[^/]+\\//, '');
      fileMap.set(rel, f);
    }
  });

  async function selectChat(c, el) {
    document.querySelectorAll('.item.active').forEach(x => x.classList.remove('active'));
    if (el) el.classList.add('active');
    const dir = folderFor(c);
    titleEl.textContent = c.title || c.id;
    linksEl.innerHTML = \`<a href="./\${encodeURI(dir)}/chat.md" target="_blank">Open chat.md</a> · <a href="./\${encodeURI(dir)}/raw.json" target="_blank">raw.json</a>\`;
    let mdText = '';
    const localFile = fileMap.get(\`\${dir}/chat.md\`);
    if (localFile) {
      mdText = await localFile.text();
    } else {
      try {
        const r = await fetch(\`./\${encodeURI(dir)}/chat.md\`);
        if (r.ok) mdText = await r.text();
      } catch {}
    }
    const arts = (c.artifacts || []).map(a => \`<li><b>\${esc(a.title)}</b> (\${(a.versions || []).length} version(s))</li>\`).join('');
    const saved = (c.files_saved || []).map(f => \`<li><a href="./\${encodeURI(dir)}/generated/\${encodeURI(f)}" target="_blank">\${esc(f)}</a></li>\`).join('');
    const missing = (c.files_missing || []).map(m => \`<li style="color:#dc2626">\${esc(m.name)}: \${esc(m.reason)}</li>\`).join('');
    bodyEl.innerHTML = \`
      <div class="turn">
        <div class="meta">
          <span class="pill">ID: \${esc(c.id)}</span>
          <span class="pill">Updated: \${esc(day(c.updated))}</span>
          <span class="pill">Messages: \${c.messages ?? 0}</span>
          \${c.tag ? \`<span class="pill">Project: \${esc(c.tag)}</span>\` : ''}
          \${c.model ? \`<span class="pill">Model: \${esc(c.model)}</span>\` : ''}
        </div>
        \${arts ? \`<h4>Artifacts</h4><ul>\${arts}</ul>\` : ''}
        \${saved ? \`<h4>Saved Media / Files (\${c.files_saved.length})</h4><ul>\${saved}</ul>\` : ''}
        \${missing ? \`<h4>Missing Files (\${c.files_missing.length})</h4><ul>\${missing}</ul>\` : ''}
      </div>
      \${mdText ? \`<div class="turn"><h4>Transcript (chat.md)</h4><pre>\${esc(mdText)}</pre></div>\` : \`<div class="turn"><p>To view transcripts inline when opened via <code>file://</code>, use the folder picker at the top left to select the unzipped folder, or click <b>Open chat.md</b> in the top right.</p></div>\`}
    \`;
  }

  function render() {
    const q = qEl.value.toLowerCase();
    listEl.innerHTML = '';
    chats.filter(c => !q || (c.title || '').toLowerCase().includes(q) || (c.tag || '').toLowerCase().includes(q)).forEach(c => {
      const d = document.createElement('div');
      d.className = 'item';
      d.innerHTML = \`<b>\${esc(c.title || '(untitled)')}</b><div class="meta"><span>\${esc(day(c.updated))}</span><span>\${c.messages || 0} msgs</span>\${c.tag ? \`<span>📁 \${esc(c.tag)}</span>\` : ''}</div>\`;
      d.onclick = () => selectChat(c, d);
      listEl.appendChild(d);
    });
  }
  qEl.addEventListener('input', render);
  render();
  if (chats.length) selectChat(chats[0], listEl.firstChild);
})();
</script></body></html>`;
  }

  // ════════════════════════════ Version tracking ════════════════════════════
  function makeTracker() {
    const snaps = new Map(), out = [];
    return {
      out,
      fork: pid => new Map(snaps.get(pid) || []),
      commit: (id, snap) => snaps.set(id, snap),
      apply(snap, a, node) {
        const prev = snap.get(a.key);
        let content = a.content;
        if (a.edit) { if (!prev) return null; content = a.edit(prev.content); }
        if (content == null) return null;
        if (prev && prev.content === content) return prev;
        const ent = { v: (prev?.v || 0) + 1, content, title: a.title || prev?.title || a.key, ext: a.ext || prev?.ext || 'txt' };
        snap.set(a.key, ent);
        out.push({ key: a.key, ...ent, node });
        return ent;
      },
    };
  }
  const fileArt = (path, content) => ({ key: path, title: baseName(path), ext: extOf(path) || 'txt', content });
  const replaceEdit = (o, n) => c => (o != null && c.includes(o) ? c.replace(o, () => n ?? '') : null);

  function artifactFiles(out, mainSet) {
    const byKey = new Map();
    for (const a of out) {
      if (!extAllowed(a.ext)) continue;
      if (!byKey.has(a.key)) byKey.set(a.key, []);
      byKey.get(a.key).push(a);
    }
    const files = [], index = [];
    for (const [key, vs] of byKey) {
      const last = vs[vs.length - 1];
      const dir = `artifacts/${slug(last.title)}_${shortHash(key)}`;
      const main = vs.filter(a => !mainSet || mainSet.has(a.node));
      const latest = (main.length ? main : vs).slice(-1)[0];
      const keep = CFG.versions === 'all' ? vs : [latest];
      const rec = { key, title: last.title, versions: [] };
      for (const a of keep) {
        const path = `${dir}/v${pad(a.v)}_${String(a.node).slice(0, 8)}.${a.ext}`;
        files.push({ path, content: a.content });
        rec.versions.push({ v: a.v, path, node: a.node });
      }
      if (CFG.latestCopy) files.push({ path: `artifacts/_latest/${safeName(last.title, latest.ext)}`, content: latest.content });
      index.push(rec);
    }
    return { files, index };
  }

  function snippetFiles(messages) {
    if (!CFG.snippets) return [];
    const out = []; let turn = 0;
    for (const m of messages) {
      turn++;
      if (m.role !== 'assistant') continue;
      let b = 0;
      for (const [, lang, code] of m.text.matchAll(/```([\w+#.-]*)[^\n]*\n([\s\S]*?)```/g)) {
        b++;
        if (code.trim().length < 40) continue;
        const ext = LANG_EXT[(lang || '').toLowerCase()] || (lang || 'txt').toLowerCase();
        if (!extAllowed(ext)) continue;
        out.push({ path: `artifacts/_code_blocks/${pad(turn)}_${pad(b)}_${slug(lang || 'code')}.${ext}`, content: code });
      }
    }
    return out;
  }

  // ════════════════════════════ Claude ════════════════════════════
  /*__ADAPTER_CLAUDE__*/
  /*__ADAPTER_CHATGPT__*/
  /*__ADAPTER_GEMINI__*/
  const adapter = { claude, chatgpt, gemini }[SITE];
  if (window.__AICB_TEST__) window.__AICB_TEST__.api = { claude, chatgpt, gemini, artifactFiles, snippetFiles, CFG };

  // ════════════════════════════ Backup engine ════════════════════════════
  const toMarkdown = (title, msgs) => `# ${title}\n\n` + msgs.map(m => `## ${m.role}${m.created ? ` — ${m.created}` : ''}\n\n${m.text}`).join('\n\n---\n\n');
  const ui = { items: [], sel: new Set(), q: '', running: false, last: null, tab: 'backup', confirmClear: false };
  const logs = [];
  const log = msg => { logs.push(`${new Date().toLocaleTimeString()}  ${msg}`); if (logs.length > 600) logs.shift(); console.log('[backup]', msg); if (el.log) { el.log.value = logs.join('\n'); el.log.scrollTop = el.log.scrollHeight; } };
  const stateKey = `state:${SITE}`;
  const failedKey = `failed:${SITE}`;
  const getState = () => { try { return GM_getValue(stateKey, {}) || {}; } catch { return {}; } };
  const getFailedSet = () => { try { return new Set(GM_getValue(failedKey, []) || []); } catch { return new Set(); } };
  const saveFailedSet = s => { try { GM_setValue(failedKey, [...s]); } catch {} };

  async function openNewZipWriter(defaultName) {
    if (CFG.directDisk && typeof window.showSaveFilePicker === 'function') {
      try {
        const handle = await window.showSaveFilePicker({
          suggestedName: defaultName,
          types: [{ description: 'ZIP Archive', accept: { 'application/zip': ['.zip'] } }],
        });
        const writable = await handle.createWritable();
        return new ZipWriter(writable);
      } catch (e) {
        log(`Direct-to-disk picker skipped (${e.message}); falling back to browser download.`);
      }
    }
    return new ZipWriter(null);
  }

  async function run() {
    if (ui.running) return;
    let chosen = ui.items.filter(c => ui.sel.has(c.id));
    if (CFG.limit > 0) chosen = chosen.slice(0, CFG.limit);
    if (!chosen.length) return setStatus('Nothing selected.');
    ui.running = true; ctl.cancelled = false; refreshButtons();
    const onUnload = e => { e.preventDefault(); e.returnValue = ''; };
    window.addEventListener('beforeunload', onUnload);

    const state = getState();
    const failedSet = getFailedSet();
    const savedProjects = new Set();
    const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    const maxBytes = CFG.maxFileMB * MB;
    let part = 1;
    let zip = await openNewZipWriter(`backup_${SITE}_${stamp}_part${part}.zip`);
    let manifest = [], errors = [], pending = {}, cur = null, chatsInZip = 0, failed = 0, lock = Promise.resolve();
    const withLock = fn => { const p = lock.then(fn); lock = p.catch(() => {}); return p; };

    const flushInner = async (hasMore = false) => {
      if (!zip.count) {
        if (!hasMore && zip.stream) {
          try { await zip.stream.abort(); } catch { try { await zip.stream.close(); } catch {} }
          zip.stream = null;
        }
        return;
      }
      const manifestObj = { site: SITE, created: new Date().toISOString(), config: CFG, chats: manifest, errors };
      await zip.add('_manifest.json', JSON.stringify(manifestObj, null, 2));
      if (CFG.bundleViewer) {
        await zip.add('_viewer.html', buildStandaloneViewerHtml(manifestObj));
      }
      const name = `backup_${SITE}_${stamp}_part${part++}.zip`;
      setStatus(`Saving ${name}…`);
      const blob = await zip.finish();
      if (blob) await saveBlob(blob, name);
      if (hasMore && !ctl.cancelled) {
        zip = await openNewZipWriter(`backup_${SITE}_${stamp}_part${part}.zip`);
      } else {
        zip = new ZipWriter(null);
      }
      chatsInZip = 0; manifest = cur ? [cur] : []; errors = [];
      Object.assign(state, pending); pending = {};
      try { GM_setValue(stateKey, state); } catch {}
      saveFailedSet(failedSet);
      renderList();
    };
    const flush = (hasMore = false) => withLock(() => flushInner(hasMore));
    const put = (path, data) => withLock(async () => {
      if (typeof data === 'string') data = TE.encode(data);
      const need = sizeOf(data) + path.length * 2 + 2048;
      if (zip.count && (zip.offset + need > ZIP_LIMIT || zip.count >= ZIP_MAX_ENTRIES)) await flushInner(true);
      await zip.add(path, data);
    });

    try {
      await adapter.init();
      for (let i = 0; i < chosen.length && !ctl.cancelled; i++) {
        const c = chosen[i];
        setStatus(`${i + 1}/${chosen.length} — ${c.title || c.id}`); setProgress(i / chosen.length);
        const entry = {
          id: c.id,
          title: c.title,
          updated: c.updated,
          site: SITE,
          tag: c.tag || '',
          model: c.model || '',
          artifacts: [],
          files_saved: [],
          files_missing: [],
          files_skipped: [],
        };
        cur = entry; manifest.push(entry);
        try {
          const raw = await withTimeout(adapter.fetch(c.id), CFG.timeoutSec * 3000, 'conversation fetch');
          const n = adapter.normalize(raw, c);
          if (n.model) entry.model = n.model;
          const dir = `${day(c.updated)}_${slug(c.title)}_${String(c.id).slice(0, 8)}/`;
          if (CFG.json) await put(dir + 'raw.json', JSON.stringify(raw, null, 2));
          if (CFG.md) await put(dir + 'chat.md', toMarkdown(c.title || 'Untitled', n.messages));
          entry.messages = n.messages.length;

          // Save Claude Project instructions & knowledge docs once per project
          if (SITE === 'claude' && c.projectId && CFG.projectDocs && !savedProjects.has(c.projectId)) {
            savedProjects.add(c.projectId);
            const pDocs = await claude.fetchProjectDocs(c.projectId);
            for (const pd of pDocs) await put(`${dir}${pd.path}`, pd.content);
          }

          if (CFG.artifacts) {
            const { files, index } = artifactFiles(n.artifacts, n.main);
            for (const f of files) {
              if (sizeOf(f.content) > maxBytes) { entry.files_skipped.push({ name: f.path, reason: 'over max file size' }); continue; }
              await put(dir + f.path, f.content);
            }
            entry.artifacts = index;
          }
          for (const f of snippetFiles(n.messages)) await put(dir + f.path, f.content);

          const wanted = n.files.filter(f => CFG[f.origin === 'upload' ? 'uploads' : 'generated']);
          await pool(wanted, CFG.fileConcurrency, async (f, k) => {
            const pre = extOf(f.name);
            if (pre && !extAllowed(pre)) return void entry.files_skipped.push({ name: f.name, reason: 'type filter' });
            try {
              const data = await withTimeout(f.load(), CFG.timeoutSec * 3000, f.name);
              if (sizeOf(data) > maxBytes) throw new Error(`over max file size (${(sizeOf(data) / MB).toFixed(1)} MB)`);
              const nm = safeName(`${pad(k + 1)}_${withExt(f.name, data)}`);
              if (!extAllowed(extOf(nm))) return void entry.files_skipped.push({ name: nm, reason: 'type filter' });
              await put(`${dir}${f.origin === 'upload' ? 'uploads' : 'generated'}/${nm}`, data);
              entry.files_saved.push(nm);
            } catch (e) { entry.files_missing.push({ name: f.name, reason: e.message }); log(`  ✗ ${f.name}: ${e.message}`); }
          });
          if (!n.messages.length) throw new Error('0 messages parsed (raw.json kept; parser may need updating)');
          if (entry.files_missing.length > 0) {
            failedSet.add(c.id);
          } else {
            failedSet.delete(c.id);
            pending[c.id] = c.updated;
          }
        } catch (e) {
          if (e.message === 'cancelled') break;
          errors.push({ id: c.id, title: c.title, error: e.message }); failed++;
          failedSet.add(c.id);
          log(`✗ ${c.title || c.id}: ${e.message}`);
        }
        chatsInZip++;
        if (zip.offset >= CFG.zipMB * MB || chatsInZip >= CFG.zipChats) await flush(i + 1 < chosen.length);
        await sleep(CFG.delayMs);
      }
      cur = null;
      await flush(false);
      setProgress(1);
      setStatus(ctl.cancelled ? 'Cancelled — completed chats were saved.' : `Done. ${chosen.length - failed} ok, ${failed} failed. See _manifest.json or _viewer.html for details.`);
    } catch (e) {
      console.error(e); log('Error: ' + e.message);
      try { cur = null; await flush(false); } catch {}
      setStatus('Error: ' + e.message);
    } finally {
      window.removeEventListener('beforeunload', onUnload);
      ui.running = false; refreshButtons(); renderList();
    }
  }

  // ════════════════════════════ UI (Shadow DOM) ════════════════════════════
  const el = {};
  const h = (tag, props = {}, ...kids) => {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (k === 'class') e.className = v;
      else if (k === 'style') e.style.cssText = v;
      else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
      else if (['checked', 'value', 'disabled', 'textContent', 'indeterminate'].includes(k)) e[k] = v;
      else e.setAttribute(k, v);
    }
    for (const kid of kids.flat()) { if (kid == null || kid === false) continue; e.append(kid.nodeType ? kid : document.createTextNode(String(kid))); }
    return e;
  };

  const SVG_PATHS = {
    close: ['M18 6 6 18', 'm6 6 12 12'],
    download: ['M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4', 'm7 10 5 5 5-5', 'M12 15V3'],
    refresh: ['M20 7v5h-5', 'M4 17v-5h5', 'M5.6 9A7 7 0 0 1 18 6l2 6', 'M4 12l2 6a7 7 0 0 0 12.4-3'],
    play: ['m7 4 13 8-13 8z'],
    stop: ['M6 6h12v12H6z'],
    globe: ['M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z', 'M2 12h20', 'M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z'],
  };
  function svgIcon(name) {
    const ns = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('aria-hidden', 'true');
    for (const d of (SVG_PATHS[name] || [])) {
      const path = document.createElementNS(ns, 'path');
      path.setAttribute('d', d);
      svg.appendChild(path);
    }
    return h('span', { class: 'ico' }, svg);
  }
  function setButtonContent(button, icon, label) {
    if (!button) return;
    button.replaceChildren(svgIcon(icon), document.createTextNode(label));
    button.classList.add('icon-btn');
  }

  const CSS = `
    :host{all:initial;--bg:#fff;--bg2:#f6f7f9;--fg:#1f2328;--mut:#6b7280;--bd:#e5e7eb;--ac:#10a37f;--err:#dc2626}
    @media (prefers-color-scheme:dark){:host{--bg:#212121;--bg2:#2b2b2b;--fg:#ececec;--mut:#9ca3af;--bd:#3d3d3d}}
    *{box-sizing:border-box}
    .fab{position:fixed;right:18px;bottom:18px;z-index:2147483646;width:44px;height:44px;border-radius:50%;border:0;background:var(--ac);color:#fff;font:600 20px system-ui;cursor:pointer;box-shadow:0 4px 14px rgba(0,0,0,.3)}
    .ov{position:fixed;inset:0;z-index:2147483647;background:rgba(0,0,0,.5);display:flex;align-items:center;justify-content:center}
    .dlg{width:min(780px,95vw);height:min(700px,92vh);background:var(--bg);color:var(--fg);border-radius:12px;display:flex;flex-direction:column;font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif;box-shadow:0 12px 40px rgba(0,0,0,.4);overflow:hidden}
    header{display:flex;align-items:center;padding:12px 16px;border-bottom:1px solid var(--bd);gap:10px}
    header h2{margin:0;font-size:16px;flex:1}
    .x{background:none;border:0;color:var(--mut);font-size:20px;cursor:pointer}
    .tabs{display:flex;gap:4px;padding:0 12px;border-bottom:1px solid var(--bd)}
    .tab{background:none;border:0;border-bottom:2px solid transparent;color:var(--mut);padding:9px 12px;cursor:pointer;font:inherit}
    .tab.on{color:var(--fg);border-color:var(--ac);font-weight:600}
    .body{flex:1;overflow:auto;padding:12px 16px}
    .bar{display:flex;gap:8px;align-items:center;margin-bottom:8px;flex-wrap:wrap}
    .selection-header{position:sticky;top:-12px;z-index:20;background:var(--bg);margin:-12px -16px 10px;padding:12px 16px 8px;border-bottom:1px solid var(--bd);box-shadow:0 2px 6px rgba(0,0,0,.08)}
    .selection-header .hint{margin-top:2px}
    .icon-btn{display:inline-flex;align-items:center;justify-content:center;gap:6px}
    .ico{display:inline-flex;align-items:center;justify-content:center;flex:0 0 auto}
    .ico svg{width:16px;height:16px;stroke:currentColor;fill:none;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
    .x .ico svg{width:19px;height:19px}
    .fab .ico svg{width:21px;height:21px}
    input[type=text],input[type=number],input[type=date],select{background:var(--bg2);color:var(--fg);border:1px solid var(--bd);border-radius:6px;padding:6px 8px;font:inherit}
    input[type=text].grow{flex:1;min-width:140px}
    button.b{background:var(--bg2);color:var(--fg);border:1px solid var(--bd);border-radius:6px;padding:6px 12px;cursor:pointer;font:inherit}
    button.pri{background:var(--ac);color:#fff;border-color:var(--ac);font-weight:600}
    button.warn{background:var(--err);color:#fff;border-color:var(--err);font-weight:600}
    button:disabled{opacity:.5;cursor:default}
    .row{display:flex;align-items:center;gap:8px;padding:5px 6px;border-radius:6px;content-visibility:auto;contain-intrinsic-size:30px;cursor:pointer}
    .row:hover{background:var(--bg2)}
    .row .t{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .row .d{color:var(--mut);font-size:12px}
    .badge{font-size:11px;padding:1px 7px;border-radius:9px;border:1px solid var(--bd);color:var(--mut)}
    .badge.new{color:var(--ac);border-color:var(--ac)} .badge.upd{color:#d97706;border-color:#d97706} .badge.err{color:var(--err);border-color:var(--err)} .badge.tag{color:var(--mut)}
    footer{border-top:1px solid var(--bd);padding:10px 16px;display:flex;flex-direction:column;gap:8px}
    .prog{height:6px;background:var(--bg2);border-radius:3px;overflow:hidden}.prog i{display:block;height:100%;width:0;background:var(--ac);transition:width .2s}
    .st{color:var(--mut);font-size:12px;min-height:1.4em;word-break:break-word}
    .acts{display:flex;gap:8px;align-items:center}.acts .sp{flex:1}
    details summary{cursor:pointer;color:var(--mut);font-size:12px} textarea{width:100%;height:110px;background:var(--bg2);color:var(--fg);border:1px solid var(--bd);border-radius:6px;font:11px/1.4 ui-monospace,monospace}
    h3{margin:16px 0 6px;font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--mut)} h3:first-child{margin-top:0}
    .f{display:flex;align-items:center;gap:10px;padding:5px 0}.f label{flex:1}.f .h{display:block;color:var(--mut);font-size:12px}
    .f input[type=number]{width:90px}.f input[type=text]{width:220px}
    .grid{display:grid;grid-template-columns:1fr 1fr;gap:2px 16px;padding:4px 0}.grid label{display:flex;gap:6px;align-items:center}
    .hint{color:var(--mut);font-size:12px;margin:4px 0}
    .dlg[dir=rtl] input[type=text],.dlg[dir=rtl] textarea{direction:rtl;text-align:right}
    .dlg[dir=rtl] .row{direction:rtl}
    .dlg[dir=rtl] .selection-header{direction:rtl}
    .dlg[dir=rtl] .acts{direction:rtl}
  `;

  const SCHEMA = [
    { title: 'What to save', fields: [
      { k: 'json', t: 'bool', l: 'Raw JSON of each chat', h: 'Lossless; lets you re-parse later if a site changes its format' },
      { k: 'md', t: 'bool', l: 'Markdown transcript' },
      { k: 'thinking', t: 'bool', l: 'Include model thinking / reasoning blocks in Markdown', h: 'Rendered inside collapsible <details> blocks' },
      { k: 'toolRuns', t: 'bool', l: 'Include script runs and execution results in the chat transcript', h: 'Adds expandable Script run / Script result blocks for Python, shell, and compatible code tools' },
      { k: 'citations', t: 'bool', l: 'Include web search citations & grounding links in Markdown' },
      { k: 'artifacts', t: 'bool', l: 'Artifacts, canvas, Gemini Immersives, created files, widgets', h: 'Reconstructed from every create/update/rewrite in the chat' },
      { k: 'snippets', t: 'bool', l: 'Code blocks from replies', h: 'Every fenced block of 40+ characters, numbered by turn' },
      { k: 'uploads', t: 'bool', l: 'Files I uploaded' },
      { k: 'generated', t: 'bool', l: 'Files, images, video the AI generated', h: 'Best effort — only works while the site still serves them' },
      { k: 'bundleViewer', t: 'bool', l: 'Bundle standalone _viewer.html inside each ZIP part', h: 'Browse chats, Markdown, and artifacts offline' },
    ] },
    { title: 'Compression & Disk Streaming', fields: [
      { k: 'compressText', t: 'bool', l: 'DEFLATE-compress text, JSON, and code files', h: 'Uses native CompressionStream to shrink text/JSON by 75–85%' },
      { k: 'directDisk', t: 'bool', l: 'Stream ZIP directly to disk (Chromium showSaveFilePicker)', h: 'Near-zero RAM usage for massive media backups' },
    ] },
    { title: 'Versions', fields: [
      { k: 'versions', t: 'select', l: 'Artifact / canvas / code versions', o: [['all', 'Every version'], ['latest', 'Latest only']] },
      { k: 'latestCopy', t: 'bool', l: 'Also write the latest version as a plain file', h: 'artifacts/_latest/<name>.<ext>' },
    ] },
    { title: 'File types', fields: [
      { t: 'hint', l: 'Applies to artifacts, code blocks, uploads and generated files. Type is decided by file extension (or MIME type once downloaded).' },
      { k: 'types', t: 'types' },
      { k: 'extInclude', t: 'text', l: 'Only these extensions', h: 'Comma separated, empty = no restriction', p: 'py, md, png' },
      { k: 'extExclude', t: 'text', l: 'Never these extensions', p: 'mp4, zip' },
    ] },
    { title: 'Size limits', fields: [
      { k: 'maxFileMB', t: 'num', l: 'Max size per file (MB)', h: 'Bigger files are skipped and listed in the manifest', min: 1, max: 1500 },
      { k: 'zipMB', t: 'num', l: 'Max size per ZIP part (MB)', min: 20, max: 3000 },
      { k: 'zipChats', t: 'num', l: 'Max chats per ZIP part', min: 1, max: 5000 },
    ] },
    { title: 'Network', fields: [
      { k: 'timeoutSec', t: 'num', l: 'Request timeout (s)', h: 'Anything slower than this is abandoned instead of hanging', min: 5, max: 600 },
      { k: 'retries', t: 'num', l: 'Retries on 429 / 5xx / network error', min: 0, max: 10 },
      { k: 'delayMs', t: 'num', l: 'Pause between chats (ms)', min: 0, max: 10000 },
      { k: 'fileConcurrency', t: 'num', l: 'Parallel file downloads', min: 1, max: 8 },
    ] },
    { title: 'Conversation list', fields: [
      { k: 'autoSelect', t: 'select', l: 'Pre-select on load', o: [['new', 'New + updated since last backup'], ['failed', 'Chats with failed items from last run'], ['all', 'Everything'], ['none', 'Nothing']] },
      { k: 'since', t: 'date', l: 'Hide chats not updated since' },
      { k: 'limit', t: 'num', l: 'Max chats per run (0 = no limit)', min: 0, max: 100000 },
    ] },
    { title: 'Claude', site: 'claude', fields: [
      { k: 'claudeOrgId', t: 'text', l: 'Organization UUID', h: 'Empty = first chat-enabled organization' },
      { k: 'projectDocs', t: 'bool', l: 'Save Claude Project instructions & knowledge docs', h: 'Writes _project_knowledge/ inside project conversation folders' },
    ] },
    { title: 'Gemini', site: 'gemini', fields: [{ k: 'geminiMaxTurns', t: 'num', l: 'Turns requested per conversation', min: 1, max: 1000 }] },
  ];

  const HE_UI = /*__HE_TRANSLATIONS__*/;
  const t = value => CFG.language === 'he' ? (HE_UI[value] || value) : value;

  function fieldEl(f) {
    if (f.t === 'hint') return h('div', { class: 'hint' }, t(f.l));
    if (f.t === 'types') {
      return h('div', { class: 'grid' }, Object.entries(TYPE_DEFS).map(([k, d]) =>
        h('label', {}, h('input', { type: 'checkbox', checked: !!CFG.types[k], onchange: e => { CFG.types[k] = e.target.checked; saveCfg(); } }), t(d.label))));
    }
    let input;
    if (f.t === 'bool') input = h('input', { type: 'checkbox', checked: !!CFG[f.k], onchange: e => { CFG[f.k] = e.target.checked; saveCfg(); } });
    else if (f.t === 'select') input = h('select', { onchange: e => { CFG[f.k] = e.target.value; saveCfg(); } }, f.o.map(([v, l]) => h('option', { value: v, ...(CFG[f.k] === v ? { selected: '' } : {}) }, t(l))));
    else if (f.t === 'num') input = h('input', { type: 'number', value: CFG[f.k], min: f.min, max: f.max, onchange: e => { const v = Math.min(f.max, Math.max(f.min, Number(e.target.value) || 0)); e.target.value = v; CFG[f.k] = v; saveCfg(); } });
    else if (f.t === 'date') input = h('input', { type: 'date', value: CFG[f.k], onchange: e => { CFG[f.k] = e.target.value; saveCfg(); renderList(); } });
    else input = h('input', { type: 'text', value: CFG[f.k], placeholder: f.p || '', onchange: e => { CFG[f.k] = e.target.value.trim(); saveCfg(); } });
    const lab = h('label', {}, t(f.l), f.h ? h('span', { class: 'h' }, t(f.h)) : null);
    return h('div', { class: 'f' }, f.t === 'bool' ? [input, lab] : [lab, input]);
  }

  function exportHistoryJson() {
    const payload = { site: SITE, exported: new Date().toISOString(), state: getState(), failed: [...getFailedSet()] };
    saveBlob(new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' }), `backup_history_${SITE}_${new Date().toISOString().slice(0, 10)}.json`);
  }

  function importHistoryOrRepairFiles(fileList) {
    if (!fileList?.length) return;
    const state = getState();
    const failedSet = getFailedSet();
    let importedBackedUp = 0, importedRetry = 0;

    Promise.all([...fileList].map(f => f.text())).then(texts => {
      let clearedForRetry = false;
      for (const txt of texts) {
        try {
          const obj = JSON.parse(txt);
          // Case 1: retry_chat_ids.json from chat_topic_finder.py
          if (Array.isArray(obj.retry_ids)) {
            if (!clearedForRetry) { ui.sel.clear(); clearedForRetry = true; }
            obj.retry_ids.forEach(id => { failedSet.add(id); ui.sel.add(id); importedRetry++; });
          }
          // Case 2: _manifest.json from backup ZIP
          if (Array.isArray(obj.chats)) {
            for (const c of obj.chats) {
              if (c?.id && c?.updated && !(c.files_missing?.length)) {
                state[c.id] = c.updated;
                importedBackedUp++;
              } else if (c?.id && c.files_missing?.length) {
                failedSet.add(c.id);
              }
            }
          }
          // Case 3: exported backup_history JSON
          if (obj.state && typeof obj.state === 'object') {
            Object.assign(state, obj.state);
            importedBackedUp += Object.keys(obj.state).length;
          }
          if (Array.isArray(obj.failed)) obj.failed.forEach(id => failedSet.add(id));
        } catch (e) { log(`Import parse error: ${e.message}`); }
      }
      try { GM_setValue(stateKey, state); } catch {}
      saveFailedSet(failedSet);
      renderList();
      setStatus(`Imported ${importedBackedUp} backed-up record(s) and ${importedRetry} repair target(s).`);
    });
  }

  function renderSettings() {
    el.settings.replaceChildren();
    for (const s of SCHEMA) {
      if (s.site && s.site !== SITE) continue;
      el.settings.append(h('h3', {}, t(s.title)), ...s.fields.map(fieldEl));
    }
    const fileInput = h('input', { type: 'file', accept: '.json', multiple: 'multiple', style: 'display:none', onchange: e => importHistoryOrRepairFiles(e.target.files) });
    const clearBtn = h('button', {
      class: ui.confirmClear ? 'b warn' : 'b',
      onclick: () => {
        if (!ui.confirmClear) {
          ui.confirmClear = true;
          renderSettings();
          return;
        }
        ui.confirmClear = false;
        try { GM_setValue(stateKey, {}); GM_setValue(failedKey, []); } catch {}
        renderSettings();
        renderList();
        setStatus('Backup history cleared.');
      },
    }, ui.confirmClear ? t('Click again to confirm clearing history') : t('Forget backup history'));

    el.settings.append(
      h('h3', {}, t('History Sync & Repair List')),
      h('div', { class: 'hint' }, t('Sync backup state across browsers or import retry_chat_ids.json from Chat Topic Finder.')),
      h('div', { class: 'bar' },
        fileInput,
        h('button', { class: 'b', onclick: exportHistoryJson }, t('Export backup history')) ,
        h('button', { class: 'b', onclick: () => fileInput.click() }, t('Import _manifest.json / History / retry_chat_ids.json')),
      ),
      h('h3', {}, t('Maintenance')),
      h('div', { class: 'bar' },
        h('button', { class: 'b', onclick: () => { ui.confirmClear = false; Object.assign(CFG, structuredClone(DEFAULTS)); saveCfg(); renderSettings(); renderList(); applyLanguage(); } }, t('Reset settings')),
        clearBtn
      )
    );
  }

  const visible = () => {
    const q = ui.q.toLowerCase();
    return ui.items.filter(c => (!CFG.since || day(c.updated) >= CFG.since) && (!q || (c.title || '').toLowerCase().includes(q) || (c.tag || '').toLowerCase().includes(q)));
  };
  const statusOf = (c, st, failedSet) => {
    if (failedSet?.has(c.id)) return 'err';
    return st[c.id] === undefined ? 'new' : st[c.id] === c.updated ? 'done' : 'upd';
  };

  function renderList() {
    if (!el.list) return;
    const st = getState(), failedSet = getFailedSet(), vis = visible();
    el.list.replaceChildren(...vis.map((c, idx) => {
      const s = statusOf(c, st, failedSet);
      const cb = h('input', { type: 'checkbox', checked: ui.sel.has(c.id), onclick: e => {
        e.stopPropagation();
        if (e.shiftKey && ui.last != null) {
          const [a, b] = [Math.min(ui.last, idx), Math.max(ui.last, idx)];
          for (let i = a; i <= b; i++) (e.target.checked ? ui.sel.add(vis[i].id) : ui.sel.delete(vis[i].id));
          renderList();
        } else (e.target.checked ? ui.sel.add(c.id) : ui.sel.delete(c.id));
        ui.last = idx; refreshButtons();
      } });
      const badgeLabel = t(s === 'err' ? 'failed items' : s === 'new' ? 'new' : s === 'upd' ? 'updated' : 'backed up');
      return h('div', { class: 'row', onclick: e => { if (e.target !== cb) cb.click(); } },
        cb, h('span', { class: 't', title: c.title }, c.title || '(untitled)'),
        c.tag ? h('span', { class: 'badge tag' }, c.tag) : null,
        h('span', { class: 'd' }, day(c.updated)),
        h('span', { class: `badge ${s}` }, badgeLabel));
    }));
    refreshButtons();
  }

  function refreshButtons() {
    if (!el.run) return;
    el.run.disabled = ui.running || !ui.sel.size;
    setButtonContent(el.run, 'play', ui.running ? t('Working…') : `${t('Back up')} ${ui.sel.size} ${CFG.language === 'he' ? 'נבחרו' : 'selected'}`);
    el.cancel.style.display = ui.running ? '' : 'none';
    setButtonContent(el.cancel, 'stop', t('Cancel'));
    el.count.textContent = CFG.language === 'he' ? `${ui.sel.size} נבחרו מתוך ${ui.items.length}` : `${ui.sel.size} selected of ${ui.items.length}`;
  }
  const setStatus = value => { if (el.status) el.status.textContent = t(value); log(value); };
  const setProgress = f => { if (el.prog) el.prog.style.width = `${Math.round(f * 100)}%`; };

  function applySelect(mode) {
    const st = getState(), failedSet = getFailedSet(), vis = visible();
    if (mode === 'all') vis.forEach(c => ui.sel.add(c.id));
    else if (mode === 'none') ui.sel.clear();
    else if (mode === 'invert') vis.forEach(c => (ui.sel.has(c.id) ? ui.sel.delete(c.id) : ui.sel.add(c.id)));
    else if (mode === 'new') { ui.sel.clear(); vis.filter(c => statusOf(c, st, failedSet) !== 'done').forEach(c => ui.sel.add(c.id)); }
    else if (mode === 'failed') { ui.sel.clear(); vis.filter(c => failedSet.has(c.id)).forEach(c => ui.sel.add(c.id)); }
    else if (mode === 'current') { ui.sel.clear(); const id = adapter.currentId(); if (id) ui.sel.add(id); }
    renderList();
  }

  async function loadList() {
    el.reload.disabled = true;
    setStatus('Loading conversation list…');
    try {
      await adapter.init();
      ui.items = (await adapter.list()).sort((a, b) => String(b.updated).localeCompare(String(a.updated)));
      ui.sel.clear();
      applySelect(CFG.autoSelect || 'new');
      setStatus(`${ui.items.length} conversations loaded.`);
    } catch (e) {
      setStatus(`Failed to load list: ${e.status === 429 ? 'rate limited — wait a minute and retry' : e.message}`);
    } finally { el.reload.disabled = false; }
  }

  function updateSelectionOptions() {
    if (!el.sel) return;
    el.sel.replaceChildren(
      h('option', { value: '' }, t('Select…')),
      h('option', { value: 'all' }, t('All shown')), h('option', { value: 'none' }, t('None')),
      h('option', { value: 'new' }, t('New + updated')),
      h('option', { value: 'failed' }, t('Failed / missing items from last run')),
      h('option', { value: 'current' }, t('Current chat only')), h('option', { value: 'invert' }, t('Invert'))
    );
    el.sel.value = '';
  }
  function applyLanguage() {
    const he = CFG.language === 'he';
    if (el.dlg) el.dlg.dir = he ? 'rtl' : 'ltr';
    if (el.title) el.title.textContent = `${he ? 'גיבוי שיחות AI' : 'AI Chat Backup'} v6.2 — ${SITE}`;
    if (el.lang) setButtonContent(el.lang, 'globe', he ? 'English' : 'עברית');
    if (el.tabBackup) el.tabBackup.textContent = t('Back up');
    if (el.tabSettings) el.tabSettings.textContent = t('Settings');
    if (el.q) el.q.placeholder = t('Search title or project…');
    if (el.reload) setButtonContent(el.reload, 'refresh', t('Reload'));
    if (el.close) el.close.setAttribute('aria-label', he ? 'סגירה' : 'Close');
    if (el.fab) { el.fab.title = t('AI Chat Backup'); }
    if (el.tipLabel) el.tipLabel.textContent = t('Tip: Shift+click selects a range. ');
    if (el.status && el.status.dataset.baseText) el.status.textContent = t(el.status.dataset.baseText);
    updateSelectionOptions();
    renderSettings();
    renderList();
    refreshButtons();
  }

  function buildUI() {
    if (document.getElementById('ai-chat-backup-host')) return;
    const host = h('div', {
      id: 'ai-chat-backup-host',
      style: 'all:initial !important;position:fixed !important;right:0 !important;bottom:0 !important;width:0 !important;height:0 !important;overflow:visible !important;z-index:2147483646 !important;display:block !important;visibility:visible !important;opacity:1 !important;pointer-events:auto !important;',
    });
    const root = host.attachShadow({ mode: 'open' });
    root.append(h('style', {}, CSS));

    const showTab = t => {
      ui.tab = t;
      ui.confirmClear = false;
      el.tabBackup.classList.toggle('on', t === 'backup'); el.tabSettings.classList.toggle('on', t === 'settings');
      el.backupPane.style.display = t === 'backup' ? '' : 'none'; el.settings.style.display = t === 'settings' ? '' : 'none';
      if (t === 'settings') renderSettings();
    };
    el.q = h('input', { type: 'text', class: 'grow', placeholder: t('Search title or project…'), oninput: e => { ui.q = e.target.value; renderList(); } });
    el.reload = h('button', { class: 'b', onclick: loadList }, svgIcon('refresh'), t('Reload'));
    el.sel = h('select', { onchange: e => { if (e.target.value) applySelect(e.target.value); e.target.value = ''; } });
    el.count = h('span', { class: 'hint' });
    el.tipLabel = h('span', {}, t('Tip: Shift+click selects a range. '));
    el.tip = h('div', { class: 'hint' }, el.tipLabel, el.count);
    el.list = h('div', {});
    el.backupPane = h('div', {}, h('div', { class: 'selection-header' }, h('div', { class: 'bar' }, el.q, el.sel, el.reload), el.tip), el.list);
    el.settings = h('div', { style: 'display:none' });
    el.tabBackup = h('button', { class: 'tab on', onclick: () => showTab('backup') }, t('Back up'));
    el.tabSettings = h('button', { class: 'tab', onclick: () => showTab('settings') }, t('Settings'));
    el.status = h('div', { class: 'st' }, t('Ready.'));
    el.status.dataset.baseText = 'Ready.';
    el.prog = h('i');
    el.log = h('textarea', { readonly: '' });
    el.run = h('button', { class: 'b pri icon-btn', onclick: run }, svgIcon('play'), t('Back up'));
    el.cancel = h('button', { class: 'b icon-btn', style: 'display:none', onclick: () => { ctl.cancelled = true; setStatus('Cancelling after the current step…'); } }, svgIcon('stop'), t('Cancel'));
    el.lang = h('button', { class: 'b icon-btn', onclick: () => { CFG.language = CFG.language === 'he' ? 'en' : 'he'; saveCfg(); applyLanguage(); } }, svgIcon('globe'), CFG.language === 'he' ? 'English' : 'עברית');
    el.close = h('button', { class: 'x', onclick: close }, svgIcon('close'));
    el.title = h('h2', {}, `AI Chat Backup v6.2 — ${SITE}`);

    el.dlg = h('div', { class: 'dlg', dir: CFG.language === 'he' ? 'rtl' : 'ltr' },
      h('header', {}, el.title, h('span', { class: 'sp' }), el.lang, el.close),
      h('div', { class: 'tabs' }, el.tabBackup, el.tabSettings),
      h('div', { class: 'body' }, el.backupPane, el.settings),
      h('footer', {}, h('div', { class: 'prog' }, el.prog), el.status,
        h('div', { class: 'acts' }, h('details', {}, h('summary', {}, t('Log')), el.log), h('span', { class: 'sp' }), el.cancel, el.run)));
    el.ov = h('div', { class: 'ov', style: 'display:none', onmousedown: e => { if (e.target === el.ov && !ui.running) close(); } }, el.dlg);
    el.fab = h('button', { class: 'fab', title: t('AI Chat Backup'), onclick: open }, svgIcon('download'));
    root.append(el.fab, el.ov);
    (document.body || document.documentElement).appendChild(host);
    applyLanguage();
  }
  let loaded = false;
  function open() {
    if (!document.getElementById('ai-chat-backup-host')) buildUI();
    el.ov.style.display = 'flex';
    if (!loaded) { loaded = true; loadList(); }
  }
  function close() { if (el.ov) el.ov.style.display = 'none'; }

  window.addEventListener('keydown', e => { if (e.key === 'Escape' && el.ov && el.ov.style.display !== 'none' && !ui.running) close(); });
  try { GM_registerMenuCommand('Open AI Chat Backup', () => open()); } catch {}

  const boot = () => {
    try {
      if (!document.body && !document.documentElement) return;
      if (!document.getElementById('ai-chat-backup-host')) buildUI();
    } catch (e) {
      console.error('[backup] boot error:', e);
    }
  };
  boot();
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, { once: true });
  }
  window.addEventListener('load', boot, { once: true });
  setInterval(boot, 2000);
})();