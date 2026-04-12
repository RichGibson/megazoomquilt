 python  util/bulk_download.py --list util/gigapan_list.json --panos-dir static/panos --workers 2 --log-file dow --reverse

## Metadata reconciliation

`gigapan_list.json` is the authoritative source for gigapan.com metadata (IDs < 1,000,000).
To patch metadata (e.g. lat/lng) into gigapan.com pano JSON files after they've been imported:

1. Edit the relevant entries in `gigapan_list.json` directly.
2. Dry run to preview changes:
   ```
   python util/reconcile.py
   ```
3. Apply:
   ```
   python util/reconcile.py --apply
   ```
4. To reconcile a single pano:
   ```
   python util/reconcile.py --apply --id 38490
   ```

Only null/missing/zero fields in the pano JSON are updated — existing values are never overwritten.
Fields `source`, `source_path`, `img_type`, and `levels` are never touched (pano JSON is authoritative for those).

Local panos (IDs ≥ 1,000,000) are skipped — their `static/panos/{id}/{id}.json` is the authoritative record.

## Server / SSH notes

- Server IP: `95.216.142.119` (Hetzner CX33)
- `megazoomquilt.com` DNS is proxied through Cloudflare — SSH via the domain will not work.
- Always SSH directly to the IP: `ssh root@95.216.142.119`
- To avoid session timeouts, add to `~/.ssh/config`:
  ```
  Host 95.216.142.119
      ServerAliveInterval 60
      ServerAliveCountMax 10
  ```
