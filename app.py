from flask import Flask, render_template_string, abort, render_template
import os
import json
import pdb
import statistics
from collections import defaultdict

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
