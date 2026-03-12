# MegaZoomQuilt

A self-hosted viewer for ultra-high-resolution zoomable panoramas, built as a personal archive for [Gigapan.com](https://gigapan.com) imagery. Browse your collection as a card grid, search and sort, and explore each panorama interactively with a Leaflet.js viewer and minimap.

---

## Features

- Card grid homepage with auto-generated thumbnails, resolution badges, and live search
- Sort by ID, name, date taken, or date uploaded
- Full Leaflet.js viewer with minimap, zoom info, and field-of-view metadata
- Rich metadata display: dimensions, megapixels, field of view, heading, altitude, GPS, views
- Tile statistics table per panorama (collapsible)
- Admin page with full inventory table
- Resilient bulk downloader with parallel tile fetching and completeness verification

---

## Quickstart

```bash
git clone https://github.com/RichGibson/megazoomquilt.git
cd megazoomquilt

conda create -n myenv python=3.12   # or: python3 -m venv venv && source venv/bin/activate
conda activate myenv

pip install flask pillow requests click
```

Start the server:

```bash
flask run --host=0.0.0.0 --port=5001
```

Browse to [http://localhost:5001](http://localhost:5001)

> **Note:** Port 5000 is on Chrome's blocked ports list. Use 5001 or higher.

---

## Getting Your Gigapan Content

If you have panoramas on [gigapan.com](https://gigapan.com), follow these steps to archive them locally. Run all commands from the **project root**.

### Step 1 — Fetch your panorama list

```bash
python util/fetch_gigapan_list.py --user YOUR_USERNAME --output util/gigapan_list.json
```

This paginates the gigapan.com API and saves full metadata for every panorama in your account to `util/gigapan_list.json`. It also reports how many are already downloaded vs still missing.

```bash
# See only IDs not yet downloaded
python util/fetch_gigapan_list.py --user YOUR_USERNAME --missing-only
```

### Step 2 — Bulk download everything

```bash
python util/bulk_download.py \
  --list util/gigapan_list.json \
  --panos-dir static/panos \
  --workers 16 \
  --log-file download.log
```

This will:
- Scan every existing directory and verify it has all expected tiles
- Queue incomplete or missing panoramas for download
- Download tiles in parallel (16 concurrent connections by default)
- Automatically pause if gigapan.com rate-limits you (HTTP 429) and resume
- Verify completeness after each panorama and log the result
- Write progress to `download.log` and print it to the terminal

Resume safely at any time — already-complete panoramas are skipped.

#### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--list` | `gigapan_list.json` | JSON list from `fetch_gigapan_list.py` |
| `--panos-dir` | `static/panos` | Where to save downloaded panoramas |
| `--workers` | `16` | Concurrent tile downloads |
| `--delay` | `1.0` | Seconds to wait between panoramas |
| `--log-file` | `download.log` | Log file path |
| `--skip-verify` | off | Skip tile count check (trust directory existence) |

### Step 3 — View your panoramas

Restart the Flask server and browse to [http://localhost:5001](http://localhost:5001). Each downloaded panorama will appear as a card with a thumbnail.

---

## Downloading a Single Panorama

```bash
python util/gigapan_downloader.py 590 -o static/panos/590
```

Downloads all zoom levels for panorama ID 590. To download only a specific zoom level:

```bash
python util/gigapan_downloader.py 590 3 -o static/panos/590
```

#### Options

| Flag | Default | Description |
|------|---------|-------------|
| `-o` / `--output` | `tiles/` | Output directory |
| `-w` / `--workers` | `16` | Concurrent tile downloads |

Progress is printed every 5 minutes showing zoom level, tiles completed, download rate, and estimated time remaining. Failed tiles are logged to `missing_tiles.txt` in the panorama directory.

---

## Adding Panoramas From Other Sources

Any large image can be tiled and viewed using [gdal2tiles.py](https://gdal.org/programs/gdal2tiles.html):

```bash
gdal2tiles.py -t "My Panorama" -w leaflet input.jpg static/panos/my_pano/
```

`gdal2tiles.py` outputs tiles in TMS convention (y=0 at bottom). Convert to the XYZ convention this viewer expects:

```bash
python util/flip_y_axis.py static/panos/my_pano static/panos/my_pano_fixed
```

Create a metadata file at `static/panos/my_pano/my_pano.json`:

```json
{
  "gigapan": {
    "id": "my_pano",
    "name": "My Panorama",
    "levels": 5,
    "width": 12345,
    "height": 6789,
    "description": "Optional description",
    "img_type": "jpg",
    "views": 0
  }
}
```

| Source | Tile convention | Action needed |
|--------|----------------|---------------|
| gigapan.com | XYZ (y=0 at top) | None |
| gdal2tiles.py | TMS (y=0 at bottom) | Run `flip_y_axis.py` |

---

## Tile Layout

Tiles are stored in OSM/XYZ format:

```
static/panos/
  <pano_id>/
    <pano_id>.json    ← metadata
    .complete         ← written after verified download
    missing_tiles.txt ← any tiles that failed (if applicable)
    0/                ← zoom level
      0/
        0.jpg         ← tile at x=0, y=0
        1.jpg
      1/
        ...
    1/
    2/
    ...
```

---

## Utilities

All utilities live in `util/`. Run from the **project root**.

### `fetch_gigapan_list.py`

Fetches your full panorama list from gigapan.com and saves it as JSON.

```bash
python util/fetch_gigapan_list.py --user YOUR_USERNAME
python util/fetch_gigapan_list.py --user YOUR_USERNAME --output util/gigapan_list.json
python util/fetch_gigapan_list.py --missing-only   # print IDs not yet in static/panos/
```

### `bulk_download.py`

Bulk download all panoramas not yet fully present. Checks completeness of existing directories and re-queues any with missing tiles.

```bash
python util/bulk_download.py
python util/bulk_download.py --workers 24 --delay 0.5
python util/bulk_download.py --skip-verify   # fast mode, trust existing directories
```

### `gigapan_downloader.py`

Download a single panorama by ID.

```bash
python util/gigapan_downloader.py 694 -o static/panos/694
python util/gigapan_downloader.py 694 3 -o static/panos/694 -w 24
```

### `flip_y_axis.py`

Converts TMS tiles (y=0 at bottom) to XYZ tiles (y=0 at top). Use this after `gdal2tiles.py`.

```bash
python util/flip_y_axis.py input_dir output_dir
```

### `move_tiles.py`

Reorganizes tiles from `z/y/x` layout to `z/x/y`.

```bash
python util/move_tiles.py input_dir output_dir
```

### `tile_stats.py` / `tile_cnt.py` / `layer_to_tile_count.py`

Inspect tile counts and file sizes per zoom level.

---

## Project Vision

MegaZoomQuilt is a personal archival viewer for ultra-resolution panoramic imagery — particularly Gigapan archives that may be at risk of disappearing. The goal is a simple, self-hosted tool that preserves your collection and makes it enjoyable to explore.

---

## License

MIT License. See `LICENSE` for details.
