# Phase 0: Start Collecting Prices Today (changedetection.io)

Goal: get your top 10 wishlist URLs observed within the hour, while PriceWatch
CA is built. Takes about 20 minutes.

## 1. Pick a port

changedetection.io listens on 5000 inside the container. Use host port **8087**
(free in the registry). Check first on TrueNAS:

```bash
sudo ss -tlnp | grep -E ':8087\b' || echo "8087 is free"
```

Record it in `dev-sop/ports.md` as "changedetection.io (temporary, Phase 0)".

## 2. Deploy

```bash
sudo mkdir -p /mnt/shared_vol/AppConfigs/changedetection/datastore
cd /mnt/shared_vol/AppConfigs/changedetection
sudo tee docker-compose.yml >/dev/null <<'EOF'
services:
  changedetection:
    image: ghcr.io/dgtlmoon/changedetection.io:0.70.3
    container_name: changedetection
    restart: unless-stopped
    ports:
      - "8087:5000"
    volumes:
      - ./datastore:/datastore
    environment:
      - PLAYWRIGHT_DRIVER_URL=ws://cd-browser:3000
      - TZ=America/Toronto
    depends_on:
      - cd-browser
  cd-browser:
    image: dgtlmoon/sockpuppetbrowser:latest
    container_name: cd-browser
    restart: unless-stopped
    cap_add:
      - SYS_ADMIN
    environment:
      - SCREEN_WIDTH=1920
      - SCREEN_HEIGHT=1024
      - MAX_CONCURRENT_CHROME_PROCESSES=4
EOF
sudo docker compose up -d
```

Check the image tag on ghcr.io before running (pin the newest release you
see). `sockpuppetbrowser` is the browser the changedetection.io project
recommends.

## 3. Add your top 10 items

1. Open `http://192.168.2.15:8087`, set a password under Settings, General.
2. Settings, Fetching: default fetch method "Plain requests", recheck every 6 hours,
   add a jitter of 30 minutes.
3. For each URL: paste it, choose the tag `bf2026`, and under the watch's Edit,
   Request tab, pick "Playwright Chromium" only for sites that render prices with
   JavaScript (Best Buy Canada often needs it).
4. Under Edit, Filters & Triggers, choose **"Re-stock & Price detection for
   single product pages"**. It reads the schema.org price, which is the same data
   PriceWatch CA uses.
5. Notifications: add `ntfys://ntfy.sh/<your-private-topic>` (or your own ntfy
   server) with "price drop" only.

## 4. Verify (acceptance)

- Each watch shows a price and a "last checked" time after its first run.
- After 6 hours, each watch has a second history point.

## 5. Moving to PriceWatch CA

When PriceWatch CA v0.1.0 is running, add the same URLs there. Keep
changedetection.io running until Nov 30 as a cross-check, then export each
watch's price history (watch, History, download) for the Phase 3 CSV import,
and remove it:

```bash
cd /mnt/shared_vol/AppConfigs/changedetection && sudo docker compose down
```

Free port 8087 in the registry afterwards.

## Alternative: PriceBuddy

PriceBuddy (`jez500/pricebuddy`) groups several store URLs under one product,
which is closer to PriceWatch's model, but needs MySQL and per-store CSS
scrapers. For a one-hour stopgap, changedetection.io's built-in JSON-LD price
detection needs less setup.
