# MegaZoomQuilt

MegaZoomQuilt is a Flask-based viewer for high-resolution, zoomable panoramas using OpenStreetMap-style tile sets. It supports Gigapan imagery, self-tiled imagery (via `gdal2tiles.py`), and includes card thumbnails, minimap, and tile statistics.

---

## Features

- Browse panoramas as a card grid with auto-composed thumbnails
- View tiled panoramas interactively using Leaflet.js with minimap
- OSM-style tile layout (z/x/y)
- Metadata parsed from Gigapan JSON (dimensions, zoom levels, location, views)
- Tile statistics table per panorama
- Utilities to download, reformat, reorganize, and flip tiles

---

## Quickstart

```bash
git clone https://github.com/RichGibson/megazoomquilt.git
cd megazoomquilt

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

flask run --host=0.0.0.0 --port=5001
```

Browse to [http://localhost:5001](http://localhost:5001)

> **Note:** Port 5000 is on Chrome's restricted ports list and will be blocked. Use 5001 or higher.

---

## Downloading From Gigapan.com

### Fetch your full gigapan list

```bash
python3 util/fetch_gigapan_list.py --user rich --output gigapan_list.json
```

* Paginates the gigapan.com API and saves full metadata for all your panoramas
* Reports how many are already downloaded vs still missing

```bash
# Print only IDs not yet downloaded
python3 util/fetch_gigapan_list.py --missing-only
```

### Download a single panorama

```bash
python3 util/gigapan_downloader.py 590 -o static/panos/590
```

* Downloads all tiles to `static/panos/590/z/x/y.jpg`
* Saves JSON metadata to `static/panos/590/590.json`
* Defaults to the highest available zoom level

Failed tiles are logged to `static/panos/590/missing_tiles.txt`.

### Bulk download

```bash
python3 util/fetch_gigapan_list.py --missing-only | \
  xargs -I{} python3 util/gigapan_downloader.py {} -o static/panos/{}
```

---

## Creating Tiles From an Existing Image

Convert any large image into zoomable tiles using [gdal2tiles.py](https://gdal.org/programs/gdal2tiles.html):

```bash
gdal2tiles.py -t "My Panorama" -w leaflet input.jpg static/panos/my_pano/
```

**Important:** `gdal2tiles.py` outputs tiles in TMS convention (y=0 at bottom). Run `flip_y_axis.py` afterward to convert to the XYZ convention this viewer expects:

```bash
python3 util/flip_y_axis.py static/panos/my_pano static/panos/my_pano_fixed
```

Create a JSON metadata file at `static/panos/my_pano/my_pano.json`:

```json
{
  "gigapan": {
    "id": "my_pano",
    "name": "My Panorama",
    "levels": 5,
    "width": 12345,
    "height": 6789,
    "description": "Converted from a large image using GDAL",
    "img_type": "jpg"
  }
}
```

---

## Thumbnails

The `/thumbnail/<pano_id>` route dynamically composites tiles into a card thumbnail:

- Selects the optimal zoom level: goes deeper until the shorter content dimension reaches 128px, capped at 16 tiles total
- Crops black quadtree padding using the JSON width/height metadata
- The card grid uses `object-fit: cover` to center-crop any aspect ratio

---

## Tile Y-Axis Convention

This viewer uses XYZ convention (y=0 at top), matching Leaflet's default. Gigapan's tile server also uses XYZ. `gdal2tiles.py` defaults to TMS (y=0 at bottom) — use `flip_y_axis.py` to correct this.

| Source         | Convention | Action needed      |
|----------------|------------|--------------------|
| gigapan.com    | XYZ        | None               |
| gdal2tiles.py  | TMS        | Run flip_y_axis.py |

---

## Utilities

All utilities live in `util/`.

### `gigapan_downloader.py`

Downloads tiles and metadata from gigapan.com.

```bash
python3 util/gigapan_downloader.py 694 -o static/panos/694
python3 util/gigapan_downloader.py 694 3 -o static/panos/694  # specific zoom level only
```

### `fetch_gigapan_list.py`

Fetches your full panorama list from gigapan.com.

```bash
python3 util/fetch_gigapan_list.py --user rich
python3 util/fetch_gigapan_list.py --missing-only
```

### `flip_y_axis.py`

Converts TMS tiles (y=0 at bottom) to XYZ tiles (y=0 at top).

```bash
python3 util/flip_y_axis.py input_dir output_dir
```

### `move_tiles.py`

Reorganizes tiles from `z/y/x` layout to `z/x/y`.

```bash
python3 util/move_tiles.py input_dir output_dir
```

### `tile_stats.py` / `tile_cnt.py` / `layer_to_tile_count.py`

Utilities for inspecting tile counts and sizes per zoom level.

---

## Project Vision

MegaZoomQuilt is an archival viewer for ultra-resolution panoramic imagery, especially Gigapan archives that may be at risk of disappearing.

---

## License

MIT License. See `LICENSE` file for details.
