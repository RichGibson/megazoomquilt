from flask import Flask, render_template_string, abort, render_template
import os
import json
import pdb

app = Flask(__name__)
from pathlib import Path
# Directory where image folders (e.g., 590/, 591/) are stored
#BASE_DIR = os.path.join(os.path.dirname(__file__), "panos")
BASE_DIR = Path(__file__).resolve().parent / "static/panos"

# run: flask run --host=0.0.0.0 --port=5000


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
    return render_template("view.html", pano_id=pano_id, pano=pano_data['gigapan'], p=p)

if __name__ == "__main__":
    # foo=load_pano_data()
    # pdb.set_trace()
    app.run(debug=True)
