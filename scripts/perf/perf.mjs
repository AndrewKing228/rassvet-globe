#!/usr/bin/env node
// Замеры карты: частота кадров в разных видах, дыры в ближнем виде при быстром приближении, время загрузки новых мест.
// Поднимает свой HTTP/2-сервер (тот же лимит частоты запросов к тайлам, что на сервере: 60/с, запас 400) и браузер без окна.
//
// Запуск из корня репозитория (Node 22+, Chrome или Edge):
//   node scripts/perf/perf.mjs                      — все сценарии
//   node scripts/perf/perf.mjs fps holes            — выбранные: fps, holes, load
//   node scripts/perf/perf.mjs --save base.json     — сохранить результат
//   node scripts/perf/perf.mjs --compare base.json  — сравнить с сохранённым
// Тайлы ближнего вида: берутся из scripts/perf/.tilecache; недостающие — с сайта TILE_ORIGIN (например
// TILE_ORIGIN=https://ваш-сайт), иначе сценарии ближнего вида пропускаются. Браузер — BROWSER=путь или стандартные места.
// PAGE=файл.html — отдать вместо index.html другую версию страницы (сравнить до и после правки).
// Код выхода 1, если в сценарии holes остались дыры.
import http2 from 'node:http2'; import https from 'node:https'; import fs from 'node:fs'; import path from 'node:path';
import { execFileSync, spawn } from 'node:child_process'; import os from 'node:os'; import { fileURLToPath } from 'node:url';

const args = process.argv.slice(2), opt = n => { const i = args.indexOf(n); return i >= 0 ? args.splice(i, 2)[1] : null; };
const SAVE = opt('--save'), COMPARE = opt('--compare');
if (process.env.PAGE && !fs.existsSync(process.env.PAGE)) { console.error(`PAGE: нет файла ${path.resolve(process.env.PAGE)}`); process.exit(2); }
const ONLY = args.length ? args : ['fps', 'holes', 'load'];
const ROOT = process.cwd(), HERE = path.dirname(fileURLToPath(import.meta.url));
const CACHE = path.join(HERE, '.tilecache'), ORIGIN = process.env.TILE_ORIGIN || '';
const PRIVATE = fs.existsSync(path.join(ROOT, 'web/template/rassvet-tracker.html'));
const sleep = ms => new Promise(r => setTimeout(r, ms));

// ---------- сервер ----------
// раскладка путей: открытый репозиторий — как есть, приватный — шаблон, web/static, vendor, vendor/globe, models
function fileFor(p) {
  if (p === '/') p = '/index.html';
  if (p === '/index.html' && process.env.PAGE) return path.resolve(process.env.PAGE);   // сравнение с другой версией страницы
  if (!PRIVATE) return path.join(ROOT, p);
  if (p === '/index.html') return process.env.PAGE ? path.resolve(process.env.PAGE) : path.join(ROOT, 'web/template/rassvet-tracker.html');
  if (p.startsWith('/globe/')) return path.join(ROOT, 'vendor', p);
  for (const d of ['/vendor/', '/models/']) if (p.startsWith(d)) return path.join(ROOT, p);
  return path.join(ROOT, 'web/static', p);
}
const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.json': 'application/json', '.css': 'text/css', '.png': 'image/png', '.jpg': 'image/jpeg',
  '.webp': 'image/webp', '.glb': 'model/gltf-binary', '.woff2': 'font/woff2', '.ico': 'image/x-icon', '.webmanifest': 'application/manifest+json' };
const TILE = /^\/tiles\/(img|dem|night)\/\d+\/\d+\/\d+\.(jpg|png)$/;
const srvState = { limit: false, delay: 0, budget: 400, last: Date.now(), r429: 0 };
const take = () => { const n = Date.now(); srvState.budget = Math.min(400, srvState.budget + (n - srvState.last) * 0.06); srvState.last = n; if (srvState.budget < 1) return false; srvState.budget--; return true; };
function cert() {
  const dir = path.join(os.tmpdir(), 'rassvet-perf'); fs.mkdirSync(dir, { recursive: true });
  const key = path.join(dir, 'key.pem'), crt = path.join(dir, 'cert.pem');
  if (!fs.existsSync(crt)) execFileSync('openssl', ['req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', key, '-out', crt, '-days', '365', '-subj', '/CN=localhost'], { stdio: 'ignore' });
  return { key: fs.readFileSync(key), cert: fs.readFileSync(crt) };
}
let originBusy = 0; const originWait = [];
function originQueue(job) {
  const run = () => { originBusy++; job(() => { originBusy--; const n = originWait.shift(); if (n) n(); }); };
  if (originBusy < 6) run(); else originWait.push(run);
}
function startServer(port) {
  const srv = http2.createSecureServer({ ...cert(), allowHTTP1: true });
  srv.on('request', (req, res) => {
    const p = decodeURIComponent(req.url.split('?')[0]);
    const send = (f, delay = 0) => fs.readFile(f, (e, d) => { if (e) { res.writeHead(404); res.end(); return; }
      setTimeout(() => { res.writeHead(200, { 'content-type': TYPES[path.extname(f)] || 'application/octet-stream' }); res.end(d); }, delay); });
    if (TILE.test(p)) {
      if (srvState.limit && !take()) { srvState.r429++; res.writeHead(429); res.end(); return; }
      const f = path.join(CACHE, p);
      if (fs.existsSync(f)) return send(f, srvState.delay);
      if (!ORIGIN) { res.writeHead(404); res.end(); return; }
      // к сайту — не больше 6 запросов разом, чтобы не упереться в его лимит; 429 и 5xx отдаются странице как есть (она повторит)
      originQueue(done => https.get(ORIGIN + p, { headers: { 'user-agent': 'rassvet-perf' } }, r => { const b = []; r.on('data', c => b.push(c)); r.on('end', () => { done();
        if (r.statusCode !== 200) { res.writeHead(r.statusCode === 404 ? 404 : r.statusCode); res.end(); return; }
        fs.mkdirSync(path.dirname(f), { recursive: true }); fs.writeFileSync(f, Buffer.concat(b)); send(f, srvState.delay); }); })
        .on('error', () => { done(); res.writeHead(502); res.end(); }));
      return;
    }
    send(fileFor(p));
  });
  return new Promise(r => srv.listen(port, '127.0.0.1', () => r(srv)));
}

// ---------- браузер (Chrome DevTools Protocol) ----------
function findBrowser() {
  const c = [process.env.BROWSER, 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', 'C:/Program Files/Google/Chrome/Application/chrome.exe',
    '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'].filter(Boolean);
  const b = c.find(x => fs.existsSync(x)); if (!b) throw new Error('не найден Chrome/Edge — укажите BROWSER=путь'); return b;
}
async function startBrowser(port) {
  const prof = fs.mkdtempSync(path.join(os.tmpdir(), 'rassvet-perf-prof-'));
  const p = spawn(findBrowser(), ['--headless=new', `--remote-debugging-port=${port}`, '--enable-gpu', '--ignore-gpu-blocklist', '--ignore-certificate-errors',
    ...(process.platform === 'win32' ? ['--use-angle=d3d11'] : []), `--user-data-dir=${prof}`, '--no-first-run', 'about:blank'], { stdio: 'ignore' });
  for (let k = 0; k < 60; k++) { try { await (await fetch(`http://127.0.0.1:${port}/json/version`)).json(); return { proc: p, prof }; } catch { await sleep(250); } }
  throw new Error('браузер не запустился');
}
async function tab(port, dev) {
  const t = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: 'PUT' })).json();
  const ws = new WebSocket(t.webSocketDebuggerUrl); await new Promise(r => ws.onopen = r);
  let id = 0; const pend = new Map(), handlers = [];
  ws.onmessage = e => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); } else handlers.forEach(h => h(m)); };
  const send = (method, params = {}) => new Promise(r => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
  const ev = async x => { const r = await send('Runtime.evaluate', { expression: x, awaitPromise: true, returnByValue: true }); return r.result?.exceptionDetails ? null : r.result?.result?.value; };
  for (const d of ['Page', 'Runtime', 'Network']) await send(d + '.enable');
  await send('Security.setIgnoreCertificateErrors', { ignore: true });
  await send('Network.setBypassServiceWorker', { bypass: true }); await send('Network.setCacheDisabled', { cacheDisabled: true });
  await send('Emulation.setDeviceMetricsOverride', dev.metrics);
  if (dev.metrics.mobile) await send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 5 });
  await send('Emulation.setCPUThrottlingRate', { rate: dev.cpu });
  return { send, ev, on: h => handlers.push(h), close: () => fetch(`http://127.0.0.1:${port}/json/close/${t.id}`) };
}
async function openPage(T, url) {
  await T.send('Page.navigate', { url });
  let ok = false;
  for (let k = 0; k < 240 && !ok; k++) { ok = await T.ev('!!(window.__rassvet && __rassvet.deck && __rassvet.deck())') === true; if (!ok) await sleep(250); }
  if (!ok) throw new Error('на странице нет __rassvet.deck() — замеры работают со страницей версии 1.7.1 и новее');
  await sleep(8000);   // догрузка Starlink, регионов, текстур
  await T.ev(`(()=>{ const b=[...document.querySelectorAll('button')].find(b=>/Пропустить|Skip/.test(b.textContent)); b&&b.click(); const x=document.querySelector('#bannerClose'); x&&x.click(); return 1 })()`);
}
const NEAR_STATE = `(()=>{ const L=__rassvet.deck().layerManager.getLayers().filter(l=>l.state&&l.state.tileset&&/^near-/.test(l.id));
  const d=L.find(l=>l.id==='near-terrain-tiles'); return { loaded:L.every(l=>l.isLoaded), tiles:d?d.state.tileset.selectedTiles.length:0,
  holes:d?d.state.tileset.selectedTiles.filter(t=>t.isLoaded&&!t.content).length:0,
  holeIds:d?d.state.tileset.selectedTiles.filter(t=>t.isLoaded&&!t.content).map(t=>t.index.z+'/'+t.index.x+'/'+t.index.y):[] }; })()`;
async function waitNear(T, ms = 30000) { const t0 = Date.now(); await sleep(400); while (Date.now() - t0 < ms) { const s = await T.ev(NEAR_STATE); if (s && s.loaded) return { ...s, ms: Date.now() - t0 }; await sleep(150); } return { ...(await T.ev(NEAR_STATE)), ms: null }; }
const FPS = ms => `new Promise(r=>{ let n=0, t0=performance.now(); function f(t){ n++; if(t-t0<${ms}) requestAnimationFrame(f); else r(+(n/((t-t0)/1000)).toFixed(1)); } requestAnimationFrame(f); })`;

// ---------- сценарии ----------
const DEVICES = {
  pc: { name: 'ПК 1600×1000', cpu: 1, metrics: { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false } },
  phone: { name: 'телефон (CPU ×4, 412×915)', cpu: 4, metrics: { width: 412, height: 915, deviceScaleFactor: 2.625, mobile: true } },
};
const VIEWS = { globe: { longitude: 30, latitude: 40, zoom: 1.8 }, z5: { longitude: 40, latitude: 48, zoom: 5.1 }, z7: { longitude: 39.7, latitude: 47.2, zoom: 7.2 },
  mountains: { longitude: 42.5, latitude: 43.2, zoom: 9.5, pitch: 55, bearing: 30 } };
const near = !!ORIGIN || fs.existsSync(CACHE);
const result = {};
async function fps(port, url) {
  for (const [dk, dev] of Object.entries(DEVICES)) {
    const T = await tab(port, dev); await openPage(T, url);
    for (const [vk, v] of Object.entries(VIEWS)) {
      if (vk !== 'globe' && !near) continue;
      await T.ev(`__rassvet.view(${JSON.stringify({ pitch: 0, bearing: 0, ...v })}); 1`);
      if (vk !== 'globe') await waitNear(T);
      await sleep(5000);   // установившийся режим: частота сразу после загрузки занижена
      result[`fps.${dk}.${vk}`] = await T.ev(FPS(3000));
      // рисуется ли под ближним видом сфера глобуса (её шейдер считает каждый пиксель экрана)
      if (vk !== 'globe') result[`sphere.${dk}.${vk}`] = await T.ev(`(()=>{ const e=__rassvet.deck().layerManager.getLayers().find(l=>l.id==='earth'); return e ? e.props.visible : null })()`);
    }
    await T.close();
  }
}
async function holes(port, url) {
  if (!near) return console.log('holes: пропущено — нет тайлов (TILE_ORIGIN или .tilecache)');
  srvState.limit = true; srvState.delay = 120; srvState.r429 = 0;
  const T = await tab(port, DEVICES.pc); await openPage(T, url);
  for (const [lon, lat, z] of [[40.5, 43.3, 5], [40.7, 43.2, 6], [40.9, 43.1, 7], [41, 43.1, 8], [41.1, 43.05, 9], [41.2, 43.05, 10], [41.3, 43.05, 10.5], [41.6, 43.1, 10.5], [41.9, 43.2, 10.5], [42.2, 43.3, 10.5], [42.5, 43.3, 10.5]]) {
    await T.ev(`__rassvet.view({longitude:${lon},latitude:${lat},zoom:${z}}); 1`); await sleep(700);
  }
  const s = await waitNear(T, 40000);
  result['holes.holes'] = s.holes; if (s.holes) result['holes.ids'] = s.holeIds; result['holes.tiles'] = s.tiles; result['holes.r429'] = srvState.r429;
  srvState.limit = false; srvState.delay = 0; await T.close();
}
async function load(port, url) {
  if (!near) return console.log('load: пропущено — нет тайлов (TILE_ORIGIN или .tilecache)');
  srvState.delay = 150;
  const T = await tab(port, DEVICES.pc); await openPage(T, url);
  const times = [];
  for (const [lon, lat] of [[37.6, 55.75], [30.3, 59.9], [44.0, 43.3], [82.9, 55.0]]) {
    await T.ev(`__rassvet.view({longitude:${lon},latitude:${lat},zoom:7.5,pitch:0,bearing:0}); 1`);
    times.push((await waitNear(T)).ms); await sleep(1500);
  }
  result['load.ms'] = times.filter(Number.isFinite).sort((a, b) => a - b); srvState.delay = 0; await T.close();
}

// ---------- запуск ----------
const SPORT = 8790, BPORT = 9350, url = `https://127.0.0.1:${SPORT}/?lang=ru`;
const srv = await startServer(SPORT), br = await startBrowser(BPORT);
try {
  for (const s of ONLY) await ({ fps, holes, load })[s](BPORT, url);
} finally { srv.close(); br.proc.kill(); try { fs.rmSync(br.prof, { recursive: true, force: true }); } catch {} }

const prev = COMPARE ? JSON.parse(fs.readFileSync(COMPARE, 'utf8')) : null;
const fmt = v => Array.isArray(v) ? v.join(' / ') : String(v);
console.log('\nПоказатель'.padEnd(26) + 'Сейчас'.padEnd(26) + (prev ? 'Было' : ''));
for (const [k, v] of Object.entries(result)) console.log(k.padEnd(25) + fmt(v).padEnd(26) + (prev && k in prev ? fmt(prev[k]) : ''));
if (SAVE) fs.writeFileSync(SAVE, JSON.stringify(result, null, 1));
if (result['holes.holes'] > 0) { console.log('\nОШИБКА: в ближнем виде остались дыры'); process.exit(1); }
