# Utilities

All scripts run from the **project root** unless noted. Requires Python 3.10+ and the packages in `requirements.txt`. GDAL (`brew install gdal`) is needed for `tile_image.py` and `reconstruct.py`.

---

## Downloading from gigapan.com

### `fetch_gigapan_list.py`

Fetches your full panorama list from gigapan.com and saves it as JSON.

```bash
python util/fetch_gigapan_list.py --user YOUR_USERNAME
python util/fetch_gigapan_list.py --user YOUR_USERNAME --output util/gigapan_list.json
python util/fetch_gigapan_list.py --missing-only   # IDs not yet in static/panos/
```

### `bulk_download.py`

Bulk download all panoramas not yet fully present. Verifies completeness of existing directories and re-queues any with missing tiles. Safe to stop and resume.

```bash
python util/bulk_download.py
python util/bulk_download.py --workers 24 --delay 0.5
python util/bulk_download.py --skip-verify   # trust existing directories, no tile count check
```

| Flag | Default | Description |
|------|---------|-------------|
| `--list` | `gigapan_list.json` | JSON list from `fetch_gigapan_list.py` |
| `--panos-dir` | `static/panos` | Where to save panoramas |
| `--workers` | `16` | Concurrent tile downloads |
| `--delay` | `1.0` | Seconds between panoramas |
| `--log-file` | `download.log` | Log output path |

### `gigapan_downloader.py`

Download a single panorama by ID, optionally a specific zoom level only.

```bash
python util/gigapan_downloader.py 694 -o static/panos/694
python util/gigapan_downloader.py 694 3 -o static/panos/694 -w 24
```

---

## Adding local panoramas

### `tile_image.py`

Tiles a large image into MegaZoomQuilt XYZ format using gdal2tiles. Handles TIFF, PSD, PSB, JPG, PNG. Automatically flips Y axis from TMS to XYZ convention and writes the metadata JSON. Requires `gdal2tiles.py` in PATH (`brew install gdal`).

```bash
python util/tile_image.py path/to/panorama.tif
python util/tile_image.py --name "My Panorama" path/to/image.tif
python util/tile_image.py --id 1000300 path/to/image.tif
python util/tile_image.py --project path/to/foo.gigapan path/to/foo_stitched.tif
python util/tile_image.py --dry-run path/to/image.tif
python util/tile_image.py --from-file list.txt          # batch: size TAB path per line
```

### `flip_y_axis.py`

Converts TMS tiles (y=0 at bottom, gdal2tiles default) to XYZ tiles (y=0 at top). Run after gdal2tiles if you tile manually rather than using `tile_image.py`.

```bash
python util/flip_y_axis.py input_dir output_dir
```

### `move_tiles.py`

Reorganises tiles from `z/y/x` layout to `z/x/y`.

```bash
python util/move_tiles.py input_dir output_dir
```

---

## Thumbnail generation

### `gen_thumb.py`

Generates or regenerates a thumbnail for a single pano. Pipeline: composite tiles → trim tile-grid padding → **fill black regions** (default on) → crop borders → aspect crop. Falls back to fetching tiles from `tile_base_url` (Cloudflare) if local tiles are not present.

```bash
python3 util/gen_thumb.py <pano_id>
python3 util/gen_thumb.py <pano_id> --out /tmp/test.jpg
python3 util/gen_thumb.py <pano_id> --zoom 2
python3 util/gen_thumb.py <pano_id> --no-fill              # skip black-fill pass
python3 util/gen_thumb.py <pano_id> --no-crop-sides
python3 util/gen_thumb.py <pano_id> --aspect 16:9
python3 util/gen_thumb.py <pano_id> --no-crop-bg
python3 util/gen_thumb.py <pano_id> --bg-tolerance 20
python3 util/gen_thumb.py <pano_id> --black-crop edge      # strip black border rows/cols
python3 util/gen_thumb.py <pano_id> --black-crop tight     # crop to exact content bbox
python3 util/gen_thumb.py <pano_id> --black-crop tight --black-threshold 80
python3 util/gen_thumb.py <pano_id> --quality 90
```

**Fill tuning flags** (used when `--no-fill` is not set):

| Flag | Default | Description |
|------|---------|-------------|
| `--fill-threshold` | 15 | Per-channel max considered black |
| `--fill-window` | 60 | Sliding window half-width in px |
| `--fill-blur` | 15 | Gaussian blur radius on filled regions |
| `--fill-depth` | 4 | Rows/cols to skip inward before sampling |
| `--fill-depth-range` | 8 | Rows/cols to average for fill color |

The defaults are tuned for thumbnail-scale images (smaller than the `fill_black.py` defaults which target full-resolution output).

**Black crop modes** — useful for portrait-style panos with large black backgrounds:

| Mode | Behaviour |
|------|-----------|
| `edge` | Strip rows/cols from each edge where ≥95% of pixels are black |
| `tight` | Find the exact bounding box of all pixels above `--black-threshold` |

`--black-threshold` (default 15) controls the per-channel brightness below which a pixel counts as black. Raise to ~80 for images where JPEG artefacts in "black" areas fool the default threshold.

### `generate_r2_thumbs.py`

Batch-generate thumbnails for panos hosted on Cloudflare R2 (those with `tile_base_url` set). Fetches tiles over HTTP and uploads the result.

---

## Image processing

### `reconstruct.py`

Reconstructs a full-resolution lossless image from a pano's local tile set. Uses GDAL (`gdal_translate`) for fully streaming out-of-core processing — no RAM limit. Falls back to Pillow row-by-row compositing if GDAL is not available (memory warning for large images).

Output is a LZW-compressed TIFF with BigTIFF mode enabled for files > 4 GB.

```bash
python3 util/reconstruct.py <pano_id>
python3 util/reconstruct.py <pano_id> --out /tmp/output.tif
python3 util/reconstruct.py <pano_id> --format png
python3 util/reconstruct.py <pano_id> --zoom 6           # lower zoom = smaller file
python3 util/reconstruct.py <pano_id> --no-crop          # keep quadtree black padding
python3 util/reconstruct.py <pano_id> --compression deflate
```

**Note:** requires local tiles. Remote-only (Cloudflare) panos must have tiles downloaded first.

### `fill_black.py`

Fills black background regions in an image with a smooth extension of the real image content. For each black pixel, samples content pixels along the nearest boundary within a sliding window and fills with their average. Designed for wide panoramas where quadtree padding leaves large black areas that look less distracting filled with extended sky/ground colour than left as solid black.

```bash
python3 util/fill_black.py <image_path>
python3 util/fill_black.py <image_path> --out /tmp/filled.jpg
python3 util/fill_black.py --pano 8585                   # fills pano thumbnail in-place
python3 util/fill_black.py <image_path> --threshold 20
python3 util/fill_black.py <image_path> --window 120
python3 util/fill_black.py <image_path> --blur 25
python3 util/fill_black.py <image_path> --depth 8        # skip N px from boundary before sampling
python3 util/fill_black.py <image_path> --depth-range 15 # average N rows for fill colour
```

| Flag | Default | Description |
|------|---------|-------------|
| `--threshold` | 15 | Per-channel max considered black |
| `--window` | 120 | Horizontal/vertical sample window half-width (px) |
| `--blur` | 25 | Gaussian blur radius on filled regions |
| `--depth` | 8 | Rows/cols to skip inward before sampling (avoids JPEG edge artefacts) |
| `--depth-range` | 15 | Number of rows/cols to average for fill colour |
| `--quality` | 92 | JPEG output quality |

**Tip:** for very large images `fill_black.py` loads the entire file into RAM. Use `fill_black_tiles.py` instead.

### `fill_black_tiles.py`

Memory-efficient version of `fill_black` that works directly on tile sets rather than a reconstructed full image. Composites only a small reference zoom for fill-colour computation, then applies the fill tile-by-tile at every zoom level. Handles images of any size.

```bash
python3 util/fill_black_tiles.py <pano_id>
python3 util/fill_black_tiles.py <pano_id> --dry-run      # report changes without writing
python3 util/fill_black_tiles.py <pano_id> --backup       # copy tiles to .bak before modifying
python3 util/fill_black_tiles.py <pano_id> --zoom 7       # one zoom level only
python3 util/fill_black_tiles.py <pano_id> --ref-zoom 3   # force reference zoom level
```

Accepts all the same fill tuning flags as `fill_black.py` (`--threshold`, `--window`, `--blur`, `--depth`, `--depth-range`, `--quality`).

**Typical workflow:**

```bash
# Preview first
python3 util/fill_black_tiles.py 8585 --dry-run

# Apply with backup
python3 util/fill_black_tiles.py 8585 --backup

# If results look good, clean up backups
find static/panos/8585 -name "*.bak" -delete
```

---

## Cloud storage

### `upload_all_r2.py`

Uploads local tile sets to Cloudflare R2 and sets `tile_base_url` in the pano's JSON on success. Skips panos that already have `tile_base_url` set. Safe to stop and resume.

```bash
python util/upload_all_r2.py
python util/upload_all_r2.py --dry-run
python util/upload_all_r2.py --log dow --upload-log upload_r2.log
```

---

## Inventory and inspection

### `inventory.py`

Full inventory report: dimensions, tile counts, missing tiles, local vs remote, geo-tagged status.

### `reconcile.py`

Cross-checks JSON metadata against actual tile directories; reports mismatches.

### `tile_stats.py`

Tile counts and file sizes per zoom level for a single pano.

```bash
python util/tile_stats.py static/panos/570
```

### `tile_cnt.py` / `layer_to_tile_count.py`

Quick helpers: count tiles or compute expected tile count from zoom level.
