// PriceWatch service worker: Web Push only (no offline caching, so the app never shows stale prices).
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = { title: "PriceWatch", body: event.data ? event.data.text() : "" };
  }
  const actions = [{ action: "open", title: "Open store" }];
  if (data.bought_url) actions.push({ action: "bought", title: "Bought" });
  if (data.snooze_url) actions.push({ action: "snooze", title: "Snooze 7 days" });
  event.waitUntil(
    self.registration.showNotification(data.title || "PriceWatch", {
      body: data.body || "",
      icon: "/icon.svg",
      badge: "/icon.svg",
      tag: data.tag || "pricewatch",
      renotify: true,
      data,
      actions,
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  const data = event.notification.data || {};
  event.notification.close();
  if (event.action === "bought" && data.bought_url) {
    event.waitUntil(fetch(data.bought_url, { method: "POST", credentials: "same-origin" }).catch(() => {}));
    return;
  }
  if (event.action === "snooze" && data.snooze_url) {
    event.waitUntil(fetch(data.snooze_url, { method: "POST", credentials: "same-origin" }).catch(() => {}));
    return;
  }
  const target = event.action === "open" ? data.url || data.item_url || "/" : data.item_url || data.url || "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((wins) => {
      const local = target.startsWith("/");
      if (local) {
        for (const w of wins) {
          if ("focus" in w) {
            w.navigate(target).catch(() => {});
            return w.focus();
          }
        }
      }
      return self.clients.openWindow(target);
    }),
  );
});
