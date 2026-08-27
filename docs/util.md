# MegaZoomQuilt — util/ Reference

All scripts run from the **project root** unless noted. Python 3.10+. GDAL (`brew install gdal`) is required for `tile_image.py` and `reconstruct.py`.

---

## Deprecated scripts

These files should not be used for new work. They are kept because deleting them is low priority, not because they are correct or safe to run.

| File | Why deprecated |
|---|---|
| `tile_stats.py` | Superseded by `collect_tile_stats()` in `app.py`. Has `pdb.set_trace()` left in and uses `os.walk` instead of `Path.rglob`. |
| `tile_cnt.py` | One-off calculation with hardcoded dimensions (`width=22556, height=6000`). Not a general tool. |
| `layer_to_tile_count.py` | One-off loop printing tile counts per zoom level for a square image. No arguments. |
| `move_tiles.py` | One-time conversion from Google Maps `z/y/x` layout to OSM `z/x/y`. Has `pdb.set_trace()` left in. |
| `generate_r2_thumbs.py` | Its `__main__` block has a hardcoded list of pano IDs from a one-time batch run. Superseded by `app.py`'s on-demand thumbnail route. The `generate_thumb()` function it exports is still called by `upload_all_r2.py`. |

---

## Downloading from gigapan.com

### `fetch_gigapan_list.py`

Fetches the full panorama list for a gigapan.com user via the JSON API and writes it to `gigapan_list.json`. Run this first before `bulk_download.py`.

```bash
python util/fetch_gigapan_list.py
python util/fetch_gigapan_list.py --user rich --output gigapan_list.json
python util/fetch_gigapan_list.py --print-ids          # print all IDs
python util/fetch_gigapan_list.py --missing-only       # print IDs not yet in static/panos/
```

Paginates the API at 50 per page. Prints a count of already-downloaded vs missing panos at the end.

---

### `gigapan_downloader.py`

Download tiles and metadata for a **single** panorama by ID. Supports concurrent tile workers, per-tile retry with exponential backoff, and rate-limit handling (backs off on 429/503). Also exports `check_completeness()` used by `bulk_download.py`.

```bash
python util/gigapan_downloader.py 590 -o static/panos/590
python util/gigapan_downloader.py 590 3 -o static/panos/590   # zoom level 3 only
python util/gigapan_downloader.py 590 -o static/panos/590 -w 24
```

---

### `bulk_download.py`

Batch wrapper around `gigapan_downloader.py`. Reads `gigapan_list.json`, scans existing directories for completeness (missing tile count via `check_completeness()`), and re-queues any pano with missing tiles. Safe to stop and resume.

```bash
python util/bulk_download.py
python util/bulk_download.py --workers 24 --delay 0.5
python util/bulk_download.py --skip-verify    # trust existing directories, skip tile count
python util/bulk_download.py --reverse        # start from end of list
```

| Flag | Default | Description |
|---|---|---|
| `--list` | `gigapan_list.json` | Source list |
| `--panos-dir` | `static/panos` | Download destination |
| `--workers` | `16` | Concurrent tile threads |
| `--delay` | `1.0` | Seconds between panos |
| `--log-file` | `download.log` | Progress log |

---

## Adding local panoramas

### `tile_image.py`

Tiles a large local image into MegaZoomQuilt XYZ format using `gdal2tiles.py`. Handles TIFF, PSD, PSB, JPG, PNG. Runs gdal2tiles (which outputs TMS convention), then automatically flips the Y axis to XYZ. Writes the pano's `<id>.json` metadata file. Assigns a synthetic ID ≥ 1,000,001 unless `--id` is specified.

```bash
python util/tile_image.py path/to/panorama.tif
python util/tile_image.py --name "WhereCamp 2009" path/to/image.tif
python util/tile_image.py --project path/to/foo.gigapan path/to/foo_stitched.tif
python util/tile_image.py --id 1000300 path/to/image.tif
python util/tile_image.py --dry-run path/to/image.tif
python util/tile_image.py --from-file list.txt    # size TAB path per line
```

Requires `gdal2tiles.py` in PATH (`brew install gdal`).

---

### `gigapan_import.py`

Imports panoramas that were stitched locally with the Gigapan Stitcher desktop app. The Stitcher saves tiles in a quadtree naming scheme (`r.jpg`, `r0.jpg`, `r00.jpg`, …). This script converts them to the XYZ `z/x/y.jpg` layout and writes the metadata JSON.

```bash
python util/gigapan_import.py path/to/name.gigapan
python util/gigapan_import.py path/to/name.data       # .data directory directly
python util/gigapan_import.py --batch path/to/dir/    # all .gigapan files in a directory
python util/gigapan_import.py --symlink path/to/name.gigapan  # symlink instead of copy
python util/gigapan_import.py --id 1000001 path/to/name.gigapan
python util/gigapan_import.py --dry-run path/to/name.gigapan
```

---

### `flip_y_axis.py`

Converts TMS tiles (y=0 at bottom, the gdal2tiles default) to XYZ tiles (y=0 at top, as expected by Leaflet and this app). Only needed if you ran gdal2tiles manually instead of using `tile_image.py` (which calls this automatically).

```bash
python util/flip_y_axis.py input_dir output_dir
```

Walks the input directory, computes `new_y = max_y - y` for each zoom level, and copies tiles to the output directory. Does not modify the source.

---

## Thumbnail generation

### `gen_thumb.py`

Standalone thumbnail generator for iterating on thumbnail quality. More options than the app's built-in `GET /thumbnail/<id>` route; intended for one-off experimentation and batch pre-generation, not for serving thumbnails to the browser.

Pipeline: composite tiles → trim quadtree padding → fill black regions (default on) → detect and crop solid-color borders → aspect crop.

```bash
python3 util/gen_thumb.py <pano_id>
python3 util/gen_thumb.py <pano_id> --zoom 2
python3 util/gen_thumb.py <pano_id> --out /tmp/test.jpg
python3 util/gen_thumb.py <pano_id> --no-fill
python3 util/gen_thumb.py <pano_id> --aspect 16:9
python3 util/gen_thumb.py <pano_id> --black-crop edge     # strip black border rows/cols
python3 util/gen_thumb.py <pano_id> --black-crop tight    # crop to exact content bbox
python3 util/gen_thumb.py <pano_id> --black-crop tight --black-threshold 80
```

Falls back to fetching tiles from `tile_base_url` if no local tiles are present.

---

## Image processing

### `fill_black.py`

Fills black background regions by extending edge content inward. For each black pixel, samples real-image pixels along the nearest content boundary in each cardinal direction within a sliding window, averages them for a fill color, then blends fills from multiple directions at corners. Applies a Gaussian blur to the filled region to smooth the transition.

Intended to make wide panoramas with quadtree padding look less harsh — it extends sky/ground colors rather than leaving solid black.

```bash
python3 util/fill_black.py path/to/image.jpg
python3 util/fill_black.py path/to/image.jpg --out /tmp/filled.jpg
python3 util/fill_black.py --pano 8585            # fills pano thumbnail in-place
python3 util/fill_black.py path/to/image.jpg --threshold 20 --window 120 --blur 25
```

| Flag | Default | Description |
|---|---|---|
| `--threshold` | 15 | Per-channel max considered black |
| `--window` | 120 | Sample window half-width (px) |
| `--blur` | 25 | Gaussian blur radius on filled region |
| `--depth` | 8 | Skip N px inward before sampling (avoids JPEG edge artefacts) |
| `--depth-range` | 15 | Average N rows/cols for fill color |
| `--quality` | 92 | JPEG output quality |

**Note:** loads the full image into RAM. For very large images use `fill_black_tiles.py`.

---

### `fill_black_tiles.py`

Memory-efficient variant of `fill_black.py` that works directly on tile sets. Composites a small reference zoom to compute fill colors, then walks every tile at every zoom level and applies fill tile-by-tile. Handles images of any size.

```bash
python3 util/fill_black_tiles.py <pano_id>
python3 util/fill_black_tiles.py <pano_id> --dry-run
python3 util/fill_black_tiles.py <pano_id> --backup       # copy tiles to .bak first
python3 util/fill_black_tiles.py <pano_id> --zoom 7       # one zoom level only
python3 util/fill_black_tiles.py <pano_id> --ref-zoom 3
```

Accepts the same fill tuning flags as `fill_black.py`.

**Typical workflow:**
```bash
python3 util/fill_black_tiles.py <id> --dry-run
python3 util/fill_black_tiles.py <id> --backup
find static/panos/<id> -name "*.bak" -delete   # if results look good
```

---

### `crop_bounds.py`

Detects the tight content bounding box at a reference zoom level (composites tiles, finds all pixels above a brightness threshold), scales the detected bounds back to original resolution, and updates `width`/`height` in the pano's JSON. This hides right-edge and bottom-edge black padding from the Leaflet viewer without touching any tiles.

Optionally deletes tiles that are provably useless: out-of-bounds tiles (whose top-left pixel is outside the new content size) and all-black tiles.

```bash
python3 util/crop_bounds.py <pano_id>
python3 util/crop_bounds.py <pano_id> --dry-run
python3 util/crop_bounds.py <pano_id> --delete-black      # also delete all-black tiles
python3 util/crop_bounds.py <pano_id> --ref-zoom 3
python3 util/crop_bounds.py <pano_id> --threshold 20
```

**Note:** only corrects right-edge and bottom-edge black. If black is detected on the left or top the script warns but does not fix it (fixing those edges would require re-indexing all tile coordinates).

---

### `reconstruct.py`

Reconstructs a full-resolution lossless image from a pano's local tile set. Primary path uses `gdal_translate` for streaming, out-of-core processing with no RAM limit. Falls back to Pillow row-by-row compositing if GDAL is not available (can exceed 3 GB RAM for large panos). Output is LZW-compressed TIFF with BigTIFF mode for files > 4 GB.

```bash
python3 util/reconstruct.py <pano_id>
python3 util/reconstruct.py <pano_id> --out /tmp/output.tif
python3 util/reconstruct.py <pano_id> --format png
python3 util/reconstruct.py <pano_id> --zoom 6        # lower zoom = smaller file
python3 util/reconstruct.py <pano_id> --no-crop       # keep quadtree padding
python3 util/reconstruct.py <pano_id> --compression deflate
```

Requires local tiles. Remote-only panos must be downloaded first.

---

## Metadata and tagging

### `reconcile.py`

Merges fields from `gigapan_list.json` into local `static/panos/<id>/<id>.json` files. Only fills in missing or empty values — never overwrites fields that are already set. Fields `source`, `source_path`, `img_type`, and `levels` are always left as-is (the local JSON is authoritative for those).

```bash
python util/reconcile.py              # dry run — show what would change
python util/reconcile.py --apply
python util/reconcile.py --apply --id 38490
```

---

### `apply_tag_rules.py` + `tag_rules.json`

Applies declarative tagging rules to all pano JSON files. Each rule in `tag_rules.json` specifies patterns to match (regex against `name`/`description`/other fields), optional geo bounding box, and tags to add. Tags are additive — existing tags are never removed. Supports `exclude_patterns` and optional `year_tag_prefix` to auto-generate year tags like `bm_2008`.

```bash
python util/apply_tag_rules.py
python util/apply_tag_rules.py --dry-run
```

---

### `apply_geo_rules.py` + `geo_rules.json`

Sets GPS coordinates on panos that match name/description patterns but have no coordinates yet. Reads `geo_rules.json`, which maps patterns to a `[lat, lng]`. Only writes to panos where coordinates are currently missing.

```bash
python util/apply_geo_rules.py
python util/apply_geo_rules.py --dry-run
```

---

### `backfill_tags.py`

Scrapes the tag list from `gigapan.com/gigapans/<id>` for each pano and writes them into the local JSON. Also creates stub JSON files for panos in `gigapan_list.json` that have not been downloaded yet.

```bash
python3 util/backfill_tags.py
python3 util/backfill_tags.py --force          # re-fetch panos that already have tags
python3 util/backfill_tags.py --dry-run
python3 util/backfill_tags.py --id 568
python3 util/backfill_tags.py --downloaded-only
python3 util/backfill_tags.py --delay 0.75
```

Requires `requests` and `beautifulsoup4`. Note that gigapan.com is intermittently down; check connectivity before running.

---

## Cloud storage

### `upload_all_r2.py`

Uploads local tile sets to Cloudflare R2 (`r2:megazoomquilt-panos/panos/<id>/`) using `rclone`. Sets `tile_base_url` to `https://tiles.megazoomquilt.com/panos/<id>` in the pano's JSON after a successful upload. Skips panos that already have `tile_base_url` set. After uploading, calls `generate_thumb()` from `generate_r2_thumbs.py` to pre-generate and upload a thumbnail.

Reads the active download log to skip any pano currently being downloaded.

```bash
python3 util/upload_all_r2.py
python3 util/upload_all_r2.py --dry-run
python3 util/upload_all_r2.py --log dow --upload-log upload_r2.log
```

Requires `rclone` configured with an R2 remote named `r2`.

---

## Inventory and auditing

### `run_audit.py`

Audits all panos and writes results to `static/audit_cache.json`. Checks: JSON validity, thumbnail presence, local tile count, R2 status. Uses directory mtime to skip panos unchanged since the last run. Results are flushed to disk every 20 changed panos so partial results are available immediately.

Called automatically by the `POST /list/audit/refresh` route as a background subprocess. Can also be run directly.

```bash
python3 util/run_audit.py
```

---

### `inventory.py`

Scans a drive for local panorama source files: `.gigapan` (Gigapan Stitcher), `.pano` (Autopano Giga), and large images (TIF/TIFF/PSD/PSB ≥ 50 MB). For each, reports whether it has already been imported into MegaZoomQuilt, whether tiles exist, and whether the source images referenced inside the project file are on disk.

```bash
python util/inventory.py /Volumes/bigeneration
python util/inventory.py --output inventory.json /Volumes/bigeneration
python util/inventory.py --summary /Volumes/bigeneration
python util/inventory.py --importable /Volumes/bigeneration
python util/inventory.py --needs-stitching /Volumes/bigeneration
```

---

### `import_images.py`

Imports ancillary images (non-panorama photos) from a drop directory into `static/images/<uuid>/`. Extracts EXIF metadata (GPS, capture date, camera/lens/exposure), assigns a UUID, copies the original, writes `<uuid>.json`, and updates `static/images_index.json`.

Also used as a module by `app.py`: `extract_exif()`, `image_dimensions()`, and `build_index()` are imported directly for use in the image upload route.

```bash
python3 util/import_images.py /path/to/drop/dir
python3 util/import_images.py /path/to/drop/dir --move    # move instead of copy
python3 util/import_images.py /path/to/drop/dir --dry-run
python3 util/import_images.py --reindex                   # rebuild index only
```

---

## Data files

| File | Description |
|---|---|
| `gigapan_list.json` | Local copy of the gigapan.com catalogue (older snapshot; the canonical copy used by the app is at the project root). |
| `tag_rules.json` | Declarative tag rules read by `apply_tag_rules.py`. |
| `geo_rules.json` | Declarative ge rules read by `apply_geo_rules.py`. |
