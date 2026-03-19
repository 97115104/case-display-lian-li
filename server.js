'use strict';

const express  = require('express');
const path     = require('path');
const http     = require('http');
const https    = require('https');
const { spawn }   = require('child_process');
const readline = require('readline');

const PORT = parseInt(process.env.PORT || '8008', 10);
const PYTHON = process.env.PYTHON || 'python3';

// ── Display service IPC ───────────────────────────────────────────────────────
// A persistent Python subprocess that owns all display/USB state.
// Hot-reloading server.js never kills it, so the LCD stays alive across reloads.

class DisplayService {
  constructor () {
    this._pending = new Map();   // id → callback
    this._nextId  = 1;
    this._start();
  }

  _start () {
    console.log('[display_service] starting Python subprocess...');
    this._proc = spawn(PYTHON, ['display_service.py'], {
      cwd:   __dirname,
      stdio: ['pipe', 'pipe', 'inherit'],  // stdin/stdout = protocol; stderr → console
    });

    const rl = readline.createInterface({ input: this._proc.stdout, crlfDelay: Infinity });
    rl.on('line', line => {
      if (!line.trim()) return;
      let msg;
      try { msg = JSON.parse(line); } catch { console.error('[display_service] bad JSON:', line); return; }
      const cb = this._pending.get(msg.id);
      if (cb) { this._pending.delete(msg.id); cb(msg); }
    });

    this._proc.on('exit', (code, signal) => {
      console.error(`[display_service] exited (code=${code} signal=${signal}), restarting in 2 s...`);
      for (const [id, cb] of this._pending) cb({ id, ok: false, error: 'display_service restarted' });
      this._pending.clear();
      setTimeout(() => this._start(), 2000);
    });
  }

  send (cmd, args = {}) {
    return new Promise((resolve, reject) => {
      const id    = this._nextId++;
      const timer = setTimeout(() => {
        this._pending.delete(id);
        reject(new Error('display_service timeout'));
      }, 30_000);

      this._pending.set(id, msg => {
        clearTimeout(timer);
        if (msg.ok) resolve(msg.result ?? {});
        else reject(new Error(msg.error ?? 'unknown error'));
      });

      this._proc.stdin.write(JSON.stringify({ id, cmd, args }) + '\n');
    });
  }
}

const display = new DisplayService();

// ── Ollama proxy target (kept in Node so the HTTP proxy works) ────────────────
let ollamaTarget = 'http://localhost:11434';

// ── Express app ───────────────────────────────────────────────────────────────
const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

// helper
function jsonErr (res, status, msg) {
  res.status(status).json({ error: msg });
}

// ── GET /api/diag ─────────────────────────────────────────────────────────────
app.get('/api/diag', async (req, res) => {
  try { res.json(await display.send('diag')); }
  catch (e) { jsonErr(res, 500, e.message); }
});

// ── GET /api/log ──────────────────────────────────────────────────────────────
app.get('/api/log', async (req, res) => {
  try { res.json(await display.send('get_log')); }
  catch (e) { jsonErr(res, 500, e.message); }
});

// ── GET /api/ollama/log ───────────────────────────────────────────────────────
app.get('/api/ollama/log', async (req, res) => {
  try { res.json(await display.send('ollama_get_log')); }
  catch (e) { jsonErr(res, 500, e.message); }
});

// ── POST /api/display ─────────────────────────────────────────────────────────
app.post('/api/display', async (req, res) => {
  const { text } = req.body || {};
  if (!text || !String(text).trim()) return jsonErr(res, 400, 'Missing text');
  try { res.json(await display.send('show_text', { text })); }
  catch (e) { jsonErr(res, 500, e.message); }
});

// ── POST /api/action ──────────────────────────────────────────────────────────
app.post('/api/action', async (req, res) => {
  const { action } = req.body || {};
  if (!action) return jsonErr(res, 400, 'Missing action');
  try { res.json(await display.send('action', { action })); }
  catch (e) { jsonErr(res, 500, e.message); }
});

// ── POST /api/ollama/start ────────────────────────────────────────────────────
app.post('/api/ollama/start', async (req, res) => {
  const target = (req.body?.target || '').trim();
  if (target) ollamaTarget = target.replace(/\/$/, '');
  try { res.json(await display.send('ollama_start', { target: ollamaTarget })); }
  catch (e) { jsonErr(res, 500, e.message); }
});

// ── POST /api/ollama/stop ─────────────────────────────────────────────────────
app.post('/api/ollama/stop', async (req, res) => {
  try { res.json(await display.send('ollama_stop')); }
  catch (e) { jsonErr(res, 500, e.message); }
});

// ── /ollama/* reverse proxy ───────────────────────────────────────────────────
function proxyOllama (req, res) {
  const ollamaPath = req.path.replace(/^\/ollama/, '') || '/';
  const parsed = new URL(ollamaTarget + ollamaPath);
  const isHttps = parsed.protocol === 'https:';
  const options = {
    hostname: parsed.hostname,
    port:     parsed.port || (isHttps ? 443 : 80),
    path:     parsed.pathname + (parsed.search || ''),
    method:   req.method,
    headers:  {},
  };

  for (const h of ['content-type', 'accept', 'authorization']) {
    if (req.headers[h]) options.headers[h] = req.headers[h];
  }

  const chunks = [];
  req.on('data', c => chunks.push(c));
  req.on('end', () => {
    const body = chunks.length ? Buffer.concat(chunks) : null;
    if (body?.length) options.headers['content-length'] = body.length;

    const startMs = Date.now();
    const entry   = {
      method: req.method,
      path:   ollamaPath,
      ip:     req.ip,
      model:  '',
      status: null,
      duration_ms: null,
      time:   new Date().toTimeString().slice(0, 8),
    };

    if (body) {
      try { entry.model = JSON.parse(body).model || ''; } catch { /* ignore */ }
    }

    const proto   = isHttps ? https : http;
    const proxyReq = proto.request(options, proxyRes => {
      entry.status      = proxyRes.statusCode;
      entry.duration_ms = Date.now() - startMs;

      // Strip hop-by-hop headers that must not be forwarded
      const fwdHeaders = Object.fromEntries(
        Object.entries(proxyRes.headers).filter(
          ([k]) => !['transfer-encoding', 'connection'].includes(k.toLowerCase())
        )
      );
      res.writeHead(proxyRes.statusCode, fwdHeaders);
      proxyRes.pipe(res);
      proxyRes.on('end', () => {
        display.send('ollama_log_request', { entry }).catch(() => {});
      });
    });

    proxyReq.on('error', err => {
      entry.status      = 502;
      entry.duration_ms = Date.now() - startMs;
      display.send('ollama_log_request', { entry }).catch(() => {});
      if (!res.headersSent) res.status(502).json({ error: err.message });
    });

    if (body) proxyReq.write(body);
    proxyReq.end();
  });
}

app.all('/ollama/*', proxyOllama);

// ── Start ─────────────────────────────────────────────────────────────────────
app.listen(PORT, '0.0.0.0', () => {
  console.log(`Dashboard:    http://localhost:${PORT}/`);
  console.log(`Ollama proxy: http://localhost:${PORT}/ollama/`);
});
