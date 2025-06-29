
````markdown
# 🧵 MegaZoomQuilt

MegaZoomQuilt is a Flask-based viewer for high-resolution, zoomable panoramas using OpenStreetMap-style tile sets. It supports Gigapan imagery, self-tiled imagery (via `gdal2tiles.py`), and includes minimap and metadata features.

---

## 🔥 Features

- View tiled panoramas interactively using Leaflet.js
- Support for OpenStreetMap tile layout (z/x/y)
- Optional conversion support for Google Earth tile format (z/y/x)
- Includes metadata parsing from Gigapan JSON
- Minimap support for overview navigation
- Utilities to reformat, reorganize, and flip tiles

---

## 🚀 Quickstart

```bash
# Clone and enter project
git clone https://github.com/YOURUSER/megazoomquilt.git
cd megazoomquilt

# Create virtual environment and install requirements
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run the server
export FLASK_APP=app
flask run
````

Your panoramas should now be browsable at: [http://localhost:5000](http://localhost:5000)

---

## ⬇️ Downloading From Gigapan.com

You can download tiles and metadata from [gigapan.com](http://gigapan.com) using the included `gigapanDownloader.py`.

```bash
python gigapanDownloader.py 590 -o panos/590
```

* Downloads tiles to `panos/590/z/x/y.jpg`
* Saves the JSON metadata to `panos/590/590.json`
* If a zoom level is not specified, it will automatically fetch the highest available

### ⚠️ Retry Support

If some tiles fail to download, they are recorded in:

```
panos/590/missing_tiles.txt
```

Use this to re-attempt or troubleshoot incomplete panoramas.

---

## 🧱 Creating Tiles From an Existing Image

You can convert any large image into zoomable tiles using [GDAL’s gdal2tiles.py](https://gdal.org/programs/gdal2tiles.html):

```bash
gdal2tiles.py -t "Wonders" -w leaflet -s EPSG:3857 input.jpg output_directory/
```

This generates a tile structure compatible with OpenStreetMap viewers.

You should also create a matching JSON metadata file manually, for example:

```json
{
  "levels": 5,
  "width": 12345,
  "height": 67890,
  "description": "Converted from a satellite image using GDAL",
  "img_type": "jpg"
}
```

Save this file as: `output_directory/output_directory.json`

---

## 🧭 Tile Format Note

Gigapan.com uses Google Earth tile layout (`z/y/x.jpg`) while this project defaults to OSM-style (`z/x/y.jpg`).

This line in `templates/view.html` controls the format:

```javascript
const tileUrlTemplate = `/static/panos/{{ pano_id }}/{z}/{x}/{y}.{{ pano.img_type }}`;
```

If you want to use the Google Earth layout, simply flip `x` and `y`:

```javascript
const tileUrlTemplate = `/static/panos/{{ pano_id }}/{z}/{y}/{x}.{{ pano.img_type }}`;
```

---

## 🛠️ Utilities

### `gigapanDownloader.py`

Downloads tiles and JSON from gigapan.com using the gigapan photo ID.

```bash
python gigapanDownloader.py 694 -o panos/694
```

### `move_tiles.py`

Reorganizes tiles from `z/y/x.jpg` to `z/x/y.jpg` layout.

```bash
python move_tiles.py input_dir output_dir
```

### `flip_y_axis.py`

Corrects inverted Y tiles by flipping rows vertically within each zoom level.

```bash
python flip_y_axis.py path/to/tileset/
```

---

## 🧪 Tile Layout Summary

| Format        | Path Structure | Axis Inversion  | Compatible Viewer |
| ------------- | -------------- | --------------- | ----------------- |
| OpenStreetMap | z/x/y.jpg      | No              | Leaflet (default) |
| Google Earth  | z/y/x.jpg      | Yes (Y flipped) | Google Earth, KML |

---

## 🌱 Project Vision

MegaZoomQuilt is intended as a fast, simple viewer and archival tool for ultra-resolution panoramic imagery, especially Gigapan archives that may be at risk of disappearing.

### Contributing

Feel free to open issues or pull requests! You can also email feature requests if you'd like.

---

## 🖼️ Screenshot

*(Add a screenshot here once available)*

---

## 📄 License

MIT License. See `LICENSE` file for details.

