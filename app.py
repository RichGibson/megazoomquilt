from flask import Flask, render_template_string, abort, render_template, send_file, Response
import os
import io
import json
import math
import pdb
import statistics
from collections import defaultdict
from PIL import Image

app = Flask(__name__)
from pathlib import Path
# Directory where image folders (e.g., 590/, 591/) are stored
#BASE_DIR = os.path.join(os.path.dirname(__file__), "panos")
BASE_DIR = Path(__file__).resolve().parent / "static/panos"

# run: flask run --host=0.0.0.0 --port=5000
def collect_tile_stats(base_dir):
    base_dir = Path(base_dir)
    results=[]
    stats = defaultdict(lambda: {
        "sizes": [],
        "x_values": set(),
        "y_values": set()
    })

    for root, _, files in os.walk(base_dir):
        for file in files:
            if file.lower().endswith((".jpg", ".png")):
                full_path = Path(root) / file
                try:
                    size = full_path.stat().st_size
                except Exception as e:
                    print(f"Could not read {full_path}: {e}")
                    continue

                try:
                    rel_parts = full_path.relative_to(base_dir).parts
                    level = rel_parts[0]
                    x = rel_parts[1]
                    y = Path(rel_parts[2]).stem  # remove .jpg/.png
                except Exception as e:
                    print(f"Invalid path structure: {full_path} — {e}")
                    continue

                data = stats[level]
                data["sizes"].append(size)
                data["x_values"].add(int(x))
                data["y_values"].add(int(y))
    #print("\nTile Size Statistics by Level:")
    #print(f"{'Level':<6} {'Count':>6} {'Min (B)':>10} {'Max (B)':>10} {'Avg (B)':>10} {'Cols':>6} {'Rows':>6}")
    for level in sorted(stats.keys(), key=lambda x: int(x)):
        data = stats[level]
        sizes = data["sizes"]
        count = len(sizes)
        min_size = min(sizes)
        max_size = max(sizes)
        avg_size = int(statistics.mean(sizes))
        cols = len(data["x_values"])
        rows = len(data["y_values"])
        #print(f"{level:<6} {count:>6} {min_size:>10} {max_size:>10} {avg_size:>10} {cols:>6} {rows:>6}")
        results.append({
            "level": level,
            "count": count,
            "min_size": min_size,
            "max_size": max_size,
            "avg_size": avg_size,
            "cols": cols,
            "rows": rows
        })

    return results

def load_pano_data():
    panoramas = []
    for entry in BASE_DIR.iterdir():
        if entry.is_dir():
            json_path = entry / f"{entry.name}.json"
            if json_path.is_file():
                try:
                    with json_path.open() as f:
                        data = json.load(f)
                        data=data['gigapan']

                    panoramas.append(data)
                except Exception as e:
                    print(f"Error loading {json_path}: {e}")
    panoramas = sorted(panoramas, key=lambda p: p['id'])
    return panoramas

THUMB_MIN_DIM = 128   # target at least this many pixels on the shorter content side
THUMB_MAX_TILES = 16  # never composite more tiles than this

@app.route("/thumbnail/<pano_id>")
def thumbnail(pano_id):
    pano_json = BASE_DIR / pano_id / f"{pano_id}.json"
    if not pano_json.exists():
        abort(404)
    with pano_json.open() as f:
        meta = json.load(f)['gigapan']

    W = int(meta['width'])
    H = int(meta['height'])
    levels = int(meta.get('levels', 1))
    max_zoom = levels - 1

    # Pick the shallowest zoom level where content is at least THUMB_MIN_DIM
    # on its shorter side, without exceeding THUMB_MAX_TILES total tiles.
    zoom = 1
    for z in range(1, levels):
        scale = 2 ** (max_zoom - z)
        cw = max(1, int(W / scale))
        ch = max(1, int(H / scale))
        cols = math.ceil(cw / 256)
        rows = math.ceil(ch / 256)
        if cols * rows > THUMB_MAX_TILES:
            break
        zoom = z
        if min(cw, ch) >= THUMB_MIN_DIM:
            break

    pano_dir = BASE_DIR / pano_id / str(zoom)
    if not pano_dir.is_dir():
        abort(404)

    # Discover tile extension from existing files
    img_ext = None
    for x_dir in pano_dir.iterdir():
        if not x_dir.is_dir():
            continue
        for tile_file in x_dir.iterdir():
            if tile_file.suffix.lower() in ('.jpg', '.png'):
                img_ext = tile_file.suffix.lower()
                break
        if img_ext:
            break
    if img_ext is None:
        abort(404)

    # Compute content bounds at this zoom level
    scale = 2 ** (max_zoom - zoom)
    content_w = max(1, int(W / scale))
    content_h = max(1, int(H / scale))
    cols = math.ceil(content_w / 256)
    rows = math.ceil(content_h / 256)

    # Load one tile to get actual tile size
    sample = pano_dir / '0' / f'0{img_ext}'
    tile_w, tile_h = Image.open(sample).size

    composed = Image.new("RGB", (cols * tile_w, rows * tile_h))
    for x in range(cols):
        for y in range(rows):
            tile_path = pano_dir / str(x) / f"{y}{img_ext}"
            if tile_path.exists():
                composed.paste(Image.open(tile_path).convert("RGB"), (x * tile_w, y * tile_h))

    # Crop to actual content, removing black quadtree padding
    crop_w = min(content_w, composed.width)
    crop_h = min(content_h, composed.height)
    composed = composed.crop((0, 0, crop_w, crop_h))

    buf = io.BytesIO()
    composed.save(buf, format="JPEG", quality=85)
    buf.seek(0)
    return send_file(buf, mimetype="image/jpeg")


@app.route('/.well-known/appspecific/com.chrome.devtools.json')
def chrome_devtools_stub():
    return jsonify({}), 200

@app.route("/")
def home():
    panoramas = load_pano_data()
    p={}
    p['page_title']='Megazoomquilt'
    return render_template("index.html", panoramas=panoramas, p=p)

@app.route("/admin")
def admin():
    p={}
    p['page_title']='Admin'
    return render_template("admin.html", p=p)


@app.route("/view/<pano_id>")
def view_pano(pano_id):
    pano_json_path = BASE_DIR / pano_id / f"{pano_id}.json"
    if not pano_json_path.exists():
        return f"Metadata for panorama {pano_id} not found.", 404

    with open(pano_json_path) as f:
        pano_data = json.load(f)
    p={}
    p['page_title']='View '
    results=collect_tile_stats(f"{BASE_DIR}/{pano_id}")
    return render_template("view.html", pano_id=pano_id, pano=pano_data['gigapan'], p=p, results=results)

if __name__ == "__main__":
    # foo=load_pano_data()
    # pdb.set_trace()
    app.run(debug=True)
