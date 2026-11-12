/* GEEKOVSKI · service worker
   Задача — не «офлайн-сайт целиком», а установка приложения и быстрый повторный
   запуск: HTML отдаём из сети (чтобы читатель всегда видел свежую версию),
   статику (шрифты, картинки, CSS) кэшируем надолго. */

const VERSION = "geekovski-v3";
const STATIC_CACHE = `${VERSION}-static`;
const PAGE_CACHE = `${VERSION}-pages`;

const OFFLINE_URL = "/offline.html";

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) =>
      cache.addAll([
        OFFLINE_URL,
        "/assets/theme.css",
        "/assets/brand.css",
        "/assets/fonts.css",
        "/assets/img/app-icon-512.png",
        "/assets/img/favicon.svg",
      ]).catch(() => undefined)
    ).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => !k.startsWith(VERSION)).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // статика: сначала кэш, потом сеть
  if (/\.(css|js|woff2?|ttf|png|jpe?g|webp|svg|ico)$/i.test(url.pathname)) {
    event.respondWith(
      caches.match(request).then((hit) =>
        hit ||
        fetch(request).then((res) => {
          const copy = res.clone();
          caches.open(STATIC_CACHE).then((c) => c.put(request, copy));
          return res;
        })
      )
    );
    return;
  }

  // страницы: сеть, при обрыве — последняя копия, при полном офлайне — заглушка
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((res) => {
          const copy = res.clone();
          caches.open(PAGE_CACHE).then((c) => c.put(request, copy));
          return res;
        })
        .catch(() =>
          caches.match(request).then((hit) => hit || caches.match(OFFLINE_URL))
        )
    );
  }
});
