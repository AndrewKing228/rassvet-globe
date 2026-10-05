/* Service worker трекера «Рассвет»: сайт открывается и без сети — с последними данными, позиции спутников
   всё равно считаются в браузере по SGP4. Когда менять: новые пути на сайте или стратегия кэша; при правке
   поднять V — старые кэши удалятся при активации.
   Страница — сначала сеть (свежие данные), без сети — сохранённая копия.
   Файлы с версией или хешем в имени (/vendor/, текстуры глобуса, data-*.json, geo-detail.*.json) — из кэша, они не меняются.
   Тайлы ближнего вида — из кэша, не больше MAX_TILES штук. Остальное — из кэша с обновлением в фоне. */
const V = 'rassvet-v3', SHELL = V + '-shell', STATIC = V + '-static', TILES = V + '-tiles', MAX_TILES = 600;

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil((async () => {
  for (const k of await caches.keys()) if (!k.startsWith(V + '-')) await caches.delete(k);
  await self.clients.claim();
})()));

self.addEventListener('fetch', e => {
  const r = e.request;
  if (r.method !== 'GET') return;
  const u = new URL(r.url);
  if (u.origin !== location.origin) return;
  const p = u.pathname;
  if (r.mode === 'navigate' || p === '/' || p === '/index.html') return e.respondWith(page(r));
  if (p.startsWith('/vendor/') || /^\/globe\/.+\.(webp|jpg)$/.test(p) || /^\/(data-|geo-detail\.).+\.json$/.test(p)) return e.respondWith(cacheFirst(r, STATIC));
  if (p.startsWith('/tiles/')) return e.respondWith(cacheFirst(r, TILES, MAX_TILES));
  if (p === '/globe/globe.json' || p.startsWith('/clouds/') || p.startsWith('/models/') || /\.(png|ico|webmanifest)$/.test(p)) return e.respondWith(fresh(r, STATIC));
});

async function page(r) {
  const c = await caches.open(SHELL);
  try {
    const res = await fetch(r);
    if (res.ok) await c.put('/', res.clone());
    return res;
  } catch (e) {
    return (await c.match('/')) || Response.error();
  }
}

async function cacheFirst(r, name, max) {
  const c = await caches.open(name);
  const hit = await c.match(r);
  if (hit) return hit;
  const res = await fetch(r);
  if (res.ok) {
    await c.put(r, res.clone());
    const keys = await c.keys();
    const fam = r.url.match(/\/(data-[a-z0-9-]+|geo-detail)\.[^/]+\.json$/);   // вчерашние версии того же файла больше не нужны
    if (fam)
      for (const k of keys) if (k.url !== r.url && k.url.includes('/' + fam[1] + '.') && /\.json$/.test(k.url)) await c.delete(k);
    if (max && keys.length > max) for (const k of keys.slice(0, keys.length - max)) await c.delete(k);
  }
  return res;
}

async function fresh(r, name) {   // из кэша сразу, свежая копия — в фоне
  const c = await caches.open(name);
  const hit = await c.match(r);
  const net = fetch(r).then(res => { if (res.ok) c.put(r, res.clone()); return res; }).catch(() => null);
  return hit || (await net) || Response.error();
}
