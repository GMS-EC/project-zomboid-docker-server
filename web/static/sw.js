// Service Worker para PZ Server Manager (PWA) - Cache Buster v0.2.0
const CACHE_NAME = 'pz-manager-cache-v0.2.0';

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => caches.delete(key))
      );
    }).then(() => self.clients.claim())
  );
});

// Network-only para APIs, WebSockets y activos dinámicos con query string
self.addEventListener('fetch', (event) => {
  // Dejar pasar directamente todas las peticiones a la red para que no se congele el código
  return;
});
