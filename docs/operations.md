# Operations on TrueNAS

## Containers

| Container | Limit | Notes |
|---|---|---|
| `pricewatch` | 512 MB | API, UI, scheduler. Port 8086. Health check: `/healthz` |

Since 1.0 there is no browser sidecar. If you added a nightly `docker restart pricewatch-browser` cron job, remove
it (TrueNAS, System, Advanced, Cron Jobs). `update.sh` removes the old `pricewatch-browser` container.

## In-app updates

The upgrade agent is a TrueNAS cron job (System, Advanced, Cron Jobs, "PriceWatch upgrade agent"), created by
`sudo scripts/upgrade-agent.sh --install` (TrueNAS rewrites `/etc/cron.d` on upgrades, so it lives in the middleware).
It runs every minute as root, reads `upgrade/request.json` only if it is a small regular file with strict JSON,
and runs `update.sh` for a published release tag. Logs: `upgrade-status/upgrade.log` and `logs/update.log`.

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

Nov 26 18:00 to Dec 1 23:59: bug fixes only. Before the freeze, run `scripts/smoke.sh`, confirm a test
alert arrives, and check that the latest nightly backup restores (`sqlite3 backups/<file> "PRAGMA integrity_check"`).
