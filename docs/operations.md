# Operations on TrueNAS

## Containers

| Container | Limit | Notes |
|---|---|---|
| `pricewatch` | 512 MB | API, UI, scheduler. Port 8086. Health check: `/healthz` |
| `pricewatch-browser` | 2 GB, `shm_size` 1 GB | Playwright Chromium server, one page per domain at a time |
| `changedetection` (optional) | 768 MB | Only if you use the bridge; see `docs/phase0-stopgap.md` |

Recycle the browser nightly (memory creep). TrueNAS, System, Advanced, Cron Jobs, add (user `root`, 04:00):

```bash
docker restart pricewatch-browser
```

## Datasets

Create two datasets and point `PRICEWATCH_DATA_PATH` at the first:

| Dataset | Properties | Holds |
|---|---|---|
| `shared_vol/apps/pricewatch/db` | recordsize=16K, compression=lz4, atime=off | `pricewatch.db`, `backups/`, `.secret_key` |
| `shared_vol/apps/pricewatch/artifacts` | recordsize=1M, compression=lz4 | screenshots (and proof packages from v0.4) |

```bash
sudo zfs create -o recordsize=16K -o compression=lz4 -o atime=off shared_vol/apps/pricewatch/db
sudo zfs create -o recordsize=1M -o compression=lz4 shared_vol/apps/pricewatch/artifacts
sudo chown -R 568:568 /mnt/shared_vol/apps/pricewatch
```

Check the pool name first (`zfs list`); measure twice before creating datasets.

## Backups

- PriceWatch writes `backups/pricewatch-YYYYMMDD.sqlite` with `VACUUM INTO` at 03:30 local (14 kept).
- `update.sh` takes an online backup before every update and restores it on rollback.
- TrueNAS, Data Protection, Periodic Snapshot Tasks on `shared_vol/apps/pricewatch` (recursive):
  hourly, keep 2 days (48); daily at 04:00, keep 30 days. The daily snapshot then contains the 03:30 copy.
- Replicate the daily snapshots off the box (the existing Backblaze cloud sync or a replication task).

## Access

- Do not expose port 8086 to the internet. Phone access over Tailscale (or WireGuard); set
  `PRICEWATCH_PUBLIC_URL` to that address so notification buttons work.
- Nginx Proxy Manager with TLS inside the LAN or tailnet; set `PRICEWATCH_COOKIE_SECURE=true` behind HTTPS.
- App login for people; the API token (Settings) for the iPhone Shortcut and scripts. Rotate it if a phone is lost.

## Code freeze

Nov 26 18:00 to Dec 1 23:59: bug fixes only. Before the freeze, run `scripts/smoke.sh --browser`, confirm a test
alert arrives, and check that the latest nightly backup restores (`sqlite3 backups/<file> "PRAGMA integrity_check"`).
