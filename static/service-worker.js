const CACHE_NAME = "code-review-app-v1";

self.addEventListener("install", (event) => {
event.waitUntil(
caches.open(CACHE_NAME).then((cache) =>
cache.addAll(["/"])
)
);

self.skipWaiting();
});

self.addEventListener("activate", (event) => {
event.waitUntil(
caches.keys().then((keys) =>
Promise.all(
keys
.filter((key) => key !== CACHE_NAME)
.map((key) => caches.delete(key))
)
)
);

self.clients.claim();
});

self.addEventListener("fetch", (event) => {
const request = event.request;

if (
request.method !== "GET" ||
new URL(request.url).origin !== self.location.origin
) {
return;
}

event.respondWith(
fetch(request).catch(async () => {
const cached = await caches.match(request);

```
  if (cached) {
    return cached;
  }

  return new Response("You are offline. Please reconnect to use code review.", {
    status: 503,
    headers: { "Content-Type": "text/plain; charset=utf-8" }
  });
})
```

);
});
