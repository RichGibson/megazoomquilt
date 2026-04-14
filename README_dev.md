 python  util/bulk_download.py --list util/gigapan_list.json --panos-dir static/panos --workers 2 --log-file dow --reverse

## TODO

- [ ] **Non-rectangular images.** Some panoramas have irregular/non-rectangular content
  surrounded by black fill. Investigate smarter thumbnail cropping — detect content
  bounding box, consider how to present these in the viewer. See `README_thumbnail.md`.
- [ ] **Move `app.secret_key` out of source code.** Currently hardcoded in `app.py` line 11.
  Replace with `app.secret_key = os.environ.get('SECRET_KEY', 'mzq-dev-key-change-in-prod')` and set
  `SECRET_KEY` in the production environment (e.g. systemd unit file or `.env`). Required before
  this app handles any real user sessions or auth.

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

## Rclone / R2 sync

Remote name: `r2`, bucket: `megazoomquilt-panos`

**Upload tiles for a single pano:**
```bash
rclone copy static/panos/{id}/ r2:megazoomquilt-panos/panos/{id}/ \
  --transfers 32 --checkers 16 --s3-upload-concurrency 8 \
  --progress
```

**Upload thumbnails only:**
```bash
rclone copy static/panos/ r2:megazoomquilt-panos/panos/ \
  --include "*_thumb.jpg" \
  --transfers 16 --progress
```

**Upload all tiles (slow — millions of files):**
```bash
rclone copy static/panos/ r2:megazoomquilt-panos/panos/ \
  --exclude "*_thumb.jpg" --exclude "*.json" \
  --transfers 32 --checkers 16 --s3-upload-concurrency 8 \
  --progress
```

Note: R2 is object storage — you cannot tar/untar on the remote side.
Each tile must be uploaded as an individual object.

## Deploying

```bash
# 1. Pull latest code (as webapps)
su - webapps
cd /var/www/megazoomquilt
git pull

# 2. Restart the app (as root)
exit
systemctl restart megazoomquilt

# 3. Restart nginx (only needed if nginx config changed)
systemctl restart nginx
```

Check status:
```bash
systemctl status megazoomquilt
systemctl status nginx
journalctl -u megazoomquilt -n 50   # app logs
```

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
