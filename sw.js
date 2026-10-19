/* Tabellone Carburanti — service worker.
 *
 * Strategie:
 *  - guscio dell'app (pagina, manifest, icone): prima la cache, poi la rete;
 *  - data/prezzi.json: prima la rete; se manca, la copia in cache, marcata
 *    con l'intestazione X-Tabellone-Cache: 1 perché la pagina lo segnali;
 *  - caratteri Google Fonts: copia in cache aggiornata in background.
 *
 * Autore: Biagio Raucci — Licenza MIT.
 */
'use strict';
const VERSIONE = '1.1.0';
const CACHE = `tabellone-${VERSIONE}`;
const GUSCIO = [
  './',
  'index.html',
  'manifest.webmanifest',
  'icone/icona-192.png',
  'icone/icona-512.png',
  'icone/apple-touch-icon.png',
];

self.addEventListener('install', (evento) => {
  evento.waitUntil(caches.open(CACHE).then((c) => c.addAll(GUSCIO)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (evento) => {
  evento.waitUntil(
    caches.keys()
      .then((nomi) => Promise.all(nomi.filter((n) => n.startsWith('tabellone-') && n !== CACHE).map((n) => caches.delete(n))))
      .then(() => self.clients.claim())
  );
});

async function datiPrimaLaRete(richiesta) {
  const cache = await caches.open(CACHE);
  try {
    const risposta = await fetch(richiesta, { cache: 'no-store' });
    if (risposta.ok) await cache.put(richiesta, risposta.clone());
    return risposta;
  } catch (errore) {
    const copia = await cache.match(richiesta, { ignoreSearch: true });
    if (!copia) throw errore;
    const intestazioni = new Headers(copia.headers);
    intestazioni.set('X-Tabellone-Cache', '1');
    return new Response(await copia.blob(), { status: 200, headers: intestazioni });
  }
}

async function cacheAggiornata(richiesta) {
  const cache = await caches.open(CACHE);
  const copia = await cache.match(richiesta);
  const rete = fetch(richiesta)
    .then((r) => { if (r.ok || r.type === 'opaque') cache.put(richiesta, r.clone()); return r; })
    .catch(() => copia);
  return copia || rete;
}

async function primaLaCache(richiesta) {
  const copia = await caches.match(richiesta, { ignoreSearch: true });
  if (copia) return copia;
  try {
    return await fetch(richiesta);
  } catch (errore) {
    if (richiesta.mode === 'navigate') {
      const pagina = await caches.match('index.html');
      if (pagina) return pagina;
    }
    throw errore;
  }
}

self.addEventListener('fetch', (evento) => {
  const richiesta = evento.request;
  if (richiesta.method !== 'GET') return;
  const url = new URL(richiesta.url);
  if (url.origin === self.location.origin && url.pathname.endsWith('/data/prezzi.json')) {
    evento.respondWith(datiPrimaLaRete(richiesta));
  } else if (url.hostname === 'fonts.googleapis.com' || url.hostname === 'fonts.gstatic.com') {
    evento.respondWith(cacheAggiornata(richiesta));
  } else if (url.origin === self.location.origin) {
    evento.respondWith(primaLaCache(richiesta));
  }
});
