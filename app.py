from flask import Flask, render_template_string, abort, render_template, send_file, Response, request, jsonify, redirect, make_response, url_for
import os
import io
import json
import math
import statistics
from collections import defaultdict
from PIL import Image

app = Flask(__name__)
app.secret_key = 'mzq-dev-key-change-in-prod'
from pathlib import Path

SKINS = ['default', 'retro', 'amber', 'museum', 'blueprint', 'magazine', 'explorer']
GIGAPAN_LIST_PATH = Path(__file__).resolve().parent / "gigapan_list.json"
AUDIT_CACHE_PATH  = Path(__file__).resolve().parent / "static" / "audit_cache.json"

# Tag → suggested map center [lat, lng, zoom] for the edit page location picker
TAG_GEO_HINTS = {
    'burning_man':  [40.786, -119.203, 12],
    'vienna':       [48.208, 16.373,   13],
    'sebastopol':   [38.402, -122.824, 14],
    'london':       [51.507, -0.128,   12],
    'nasa_ames':    [37.408, -122.064, 14],
    'mendocino':    [39.305, -123.797, 12],
    'maker_faire':  [37.546, -122.305, 14],
    'hursley':      [51.024, -1.398,   14],
    'arizona':      [34.048, -111.094, 8],
    'florence_ave': [38.402, -122.829, 16],
    'mak_vienna':   [48.205, 16.373,   15],
    'q21':          [48.203, 16.359,   16],
    'geffrye':      [51.531, -0.076,   15],
    'siggraph':     [34.050, -118.260, 12],
    'wherecamp':    [37.422, -122.084, 13],
    'roboexotica':  [48.203, 16.366,   14],
    'sasha_shulgin':[37.927, -122.513, 14],
    'london':       [51.507, -0.128,   12],
}

@app.context_processor
def inject_skin():
    skin = request.cookies.get('skin', 'default')
    if skin not in SKINS:
        skin = 'default'
    return {'skin': skin}

@app.route('/skin/<name>')
def set_skin(name):
    if name not in SKINS:
        name = 'default'
    dest = request.referrer or url_for('home')
    resp = make_response(redirect(dest))
    resp.set_cookie('skin', name, max_age=60*60*24*365)
    return resp
# Directory where image folders (e.g., 590/, 591/) are stored
BASE_DIR = Path(__file__).resolve().parent / "static/panos"

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

def resolve_tile_base_url(meta):
    """Normalize tile_base_url (string or list) → first remote URL or None."""
    raw = meta.get('tile_base_url')
    if raw is None:
        return None
    if isinstance(raw, list):
        return raw[0] if raw else None
    return raw  # plain string



def check_has_local_tiles(pano_id):
    """Return True if zoom level 0 directory exists with at least one tile."""
    z0 = BASE_DIR / str(pano_id) / "0"
    if not z0.is_dir():
        return False
    for x_dir in z0.iterdir():
        if x_dir.is_dir():
            for f in x_dir.iterdir():
                if f.suffix.lower() in ('.jpg', '.png'):
                    return True
    return False

def load_pano_data():
    panoramas = []
    for entry in BASE_DIR.iterdir():
        if entry.is_dir():
            json_path = entry / f"{entry.name}.json"
            if json_path.is_file():
                try:
                    with json_path.open() as f:
                        data = json.load(f)
                        data = data['gigapan']
                    data['has_local_tiles'] = check_has_local_tiles(data['id'])
                    panoramas.append(data)
                except Exception as e:
                    print(f"Error loading {json_path}: {e}")
    panoramas = sorted(panoramas, key=lambda p: p['id'])
    return panoramas

THUMB_MIN_DIM = 128   # target at least this many pixels on the shorter content side
THUMB_MAX_TILES = 16  # never composite more tiles than this

@app.route("/thumbnail/<pano_id>")
def thumbnail(pano_id):
    # Serve cached thumbnail if it exists locally
    cached_path = BASE_DIR / pano_id / f"{pano_id}_thumb.jpg"
    if cached_path.exists():
        return send_file(cached_path, mimetype="image/jpeg")

    pano_json = BASE_DIR / pano_id / f"{pano_id}.json"
    if not pano_json.exists():
        abort(404)
    with pano_json.open() as f:
        raw = json.load(f)
    meta = raw.get('gigapan', raw)

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

    img_ext = '.' + meta.get('img_type', 'jpg')

    # Compute content bounds at this zoom level
    scale = 2 ** (max_zoom - zoom)
    content_w = max(1, int(W / scale))
    content_h = max(1, int(H / scale))
    cols = math.ceil(content_w / 256)
    rows = math.ceil(content_h / 256)

    tile_base_url = resolve_tile_base_url(meta)

    if tile_base_url:
        import urllib.request
        def fetch_tile(x, y):
            url = f"{tile_base_url}/{zoom}/{x}/{y}{img_ext}"
            try:
                with urllib.request.urlopen(url, timeout=10) as resp:
                    return Image.open(io.BytesIO(resp.read())).convert("RGB")
            except Exception:
                return None

        sample = fetch_tile(0, 0)
        if sample is None:
            abort(404)
        tile_w, tile_h = sample.size
        composed = Image.new("RGB", (cols * tile_w, rows * tile_h))
        composed.paste(sample, (0, 0))
        for x in range(cols):
            for y in range(rows):
                if x == 0 and y == 0:
                    continue
                tile = fetch_tile(x, y)
                if tile:
                    composed.paste(tile, (x * tile_w, y * tile_h))
    else:
        pano_dir = BASE_DIR / pano_id / str(zoom)
        if not pano_dir.is_dir():
            abort(404)

        # Discover tile extension from existing files
        found_ext = None
        for x_dir in pano_dir.iterdir():
            if not x_dir.is_dir():
                continue
            for tile_file in x_dir.iterdir():
                if tile_file.suffix.lower() in ('.jpg', '.png'):
                    found_ext = tile_file.suffix.lower()
                    break
            if found_ext:
                break
        if found_ext is None:
            abort(404)
        img_ext = found_ext

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

    # Save to cache then serve
    try:
        composed.save(cached_path, format="JPEG", quality=85)
        return send_file(cached_path, mimetype="image/jpeg")
    except Exception:
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
    sort = request.args.get('sort', 'id_asc')
    # For date sorts, nulls always sort last regardless of direction.
    # date_asc:  key=(0 if dated else 1, date), reverse=False  → earliest first, nulls last
    # date_desc: key=(1 if dated else 0, date), reverse=True   → latest first, nulls last
    sort_config = {
        'id_asc':    (lambda p: p['id'],                                              False),
        'id_desc':   (lambda p: p['id'],                                              True),
        'name_asc':  (lambda p: p['name'].lower(),                                    False),
        'name_desc': (lambda p: p['name'].lower(),                                    True),
        'date_asc':       (lambda p: (0 if p.get('taken_at') else 1,   p.get('taken_at') or ''),   False),
        'date_desc':      (lambda p: (1 if p.get('taken_at') else 0,   p.get('taken_at') or ''),   True),
        'uploaded_asc':   (lambda p: (0 if p.get('created_at') else 1, p.get('created_at') or ''), False),
        'uploaded_desc':  (lambda p: (1 if p.get('created_at') else 0, p.get('created_at') or ''), True),
        'size_asc':       (lambda p: p.get('width', 0) * p.get('height', 0),                        False),
        'size_desc':      (lambda p: p.get('width', 0) * p.get('height', 0),                        True),
    }
    key, reverse = sort_config.get(sort, sort_config['id_asc'])
    panoramas = sorted(panoramas, key=key, reverse=reverse)
    p={}
    p['page_title']='Megazoomquilt'
    return render_template("index.html", panoramas=panoramas, p=p, sort=sort)

@app.route("/tags")
def tags_page():
    panoramas = load_pano_data()
    counts = {}
    for pano in panoramas:
        for tag in pano.get('tags') or []:
            counts[tag] = counts.get(tag, 0) + 1
    tags = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    min_count = min(counts.values(), default=1)
    max_count = max(counts.values(), default=1)
    return render_template("tags.html", tags=tags,
                           min_count=min_count, max_count=max_count,
                           min_size=0.85, max_size=2.2,
                           p={'page_title': 'Tags'})

@app.route("/tag/<tag>")
def tag_view(tag):
    panoramas = load_pano_data()
    sort = request.args.get('sort', 'id_asc')
    sort_config = {
        'id_asc':       (lambda p: p['id'],                                              False),
        'id_desc':      (lambda p: p['id'],                                              True),
        'name_asc':     (lambda p: p['name'].lower(),                                    False),
        'name_desc':    (lambda p: p['name'].lower(),                                    True),
        'date_asc':     (lambda p: (0 if p.get('taken_at') else 1,   p.get('taken_at') or ''),   False),
        'date_desc':    (lambda p: (1 if p.get('taken_at') else 0,   p.get('taken_at') or ''),   True),
        'uploaded_asc': (lambda p: (0 if p.get('created_at') else 1, p.get('created_at') or ''), False),
        'uploaded_desc':(lambda p: (1 if p.get('created_at') else 0, p.get('created_at') or ''), True),
        'size_asc':     (lambda p: p.get('width', 0) * p.get('height', 0),              False),
        'size_desc':    (lambda p: p.get('width', 0) * p.get('height', 0),              True),
    }
    key, reverse = sort_config.get(sort, sort_config['id_asc'])
    filtered = [p for p in panoramas if tag in (p.get('tags') or [])]
    filtered = sorted(filtered, key=key, reverse=reverse)
    return render_template("index.html", panoramas=filtered, sort=sort,
                           active_tag=tag, p={'page_title': f'#{tag}'})

@app.route("/map")
def map_view():
    panoramas = load_pano_data()
    mapped = [p for p in panoramas
              if p.get('latitude') and p.get('longitude')
              and p['latitude'] != 0 and p['longitude'] != 0]

    # Pending: in gigapan_list.json but not yet downloaded, with coordinates
    downloaded_ids = {p['id'] for p in panoramas}
    pending_panos = []
    if GIGAPAN_LIST_PATH.exists():
        with open(GIGAPAN_LIST_PATH) as f:
            gigapan_list = json.load(f)
        pending_panos = [
            {
                'id':          g['id'],
                'name':        g['name'],
                'description': g.get('description') or '',
                'latitude':    g['latitude'],
                'longitude':   g['longitude'],
            }
            for g in gigapan_list
            if g.get('latitude') and g.get('longitude')
            and g['latitude'] != 0 and g['longitude'] != 0
            and g['id'] not in downloaded_ids
        ]

    return render_template("map.html", panoramas=mapped, pending_panos=pending_panos, p={'page_title': 'Map'})

@app.route("/admin/audit/refresh", methods=["POST"])
def admin_audit_refresh():
    import subprocess, sys
    script = Path(__file__).resolve().parent / "util" / "run_audit.py"
    subprocess.Popen([sys.executable, str(script)],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     close_fds=True)
    return redirect(url_for('admin') + '?audit=running')

@app.route("/admin")
def admin():
    local_panos = {p['id']: p for p in load_pano_data()}

    all_from_list = []
    if GIGAPAN_LIST_PATH.exists():
        with open(GIGAPAN_LIST_PATH) as f:
            all_from_list = json.load(f)

    seen = set()
    all_panos = []
    for g in all_from_list:
        pid = g['id']
        seen.add(pid)
        all_panos.append(local_panos[pid] if pid in local_panos else g)
    for p in local_panos.values():
        if p['id'] not in seen:
            all_panos.append(p)
    all_panos.sort(key=lambda x: x['id'])

    audit = {}
    if AUDIT_CACHE_PATH.exists():
        with open(AUDIT_CACHE_PATH) as f:
            audit = json.load(f)

    return render_template("admin.html", p={'page_title': 'Admin'},
                           panoramas=all_panos, audit=audit)


@app.route("/view/<pano_id>")
def view_pano(pano_id):
    pano_json_path = BASE_DIR / pano_id / f"{pano_id}.json"
    if not pano_json_path.exists():
        return f"Metadata for panorama {pano_id} not found.", 404

    with open(pano_json_path) as f:
        pano_data = json.load(f)
    pano_data['gigapan']['has_local_tiles'] = check_has_local_tiles(pano_id)
    # Normalize tile_base_url to a plain string for template use
    pano_data['gigapan']['tile_base_url'] = resolve_tile_base_url(pano_data['gigapan'])
    p={}
    p['page_title']='View '
    results=collect_tile_stats(f"{BASE_DIR}/{pano_id}")

    # Collect geo-located panos for the location mini-map
    geo_panos = [
        {'id': pg['id'], 'name': pg['name'],
         'lat': pg['latitude'], 'lng': pg['longitude'],
         'width': pg.get('width', 0), 'height': pg.get('height', 0),
         'tile_base_url': resolve_tile_base_url(pg) or ''}
        for pg in load_pano_data()
        if pg.get('latitude') and pg.get('longitude')
        and pg['latitude'] != 0 and pg['longitude'] != 0
    ]

    nav_tag = request.args.get('tag', '').strip()
    nav_q   = request.args.get('q',   '').strip().lower()

    all_panos = load_pano_data()  # sorted by id asc
    if nav_tag:
        all_panos = [p for p in all_panos if nav_tag in (p.get('tags') or [])]
    if nav_q:
        all_panos = [p for p in all_panos
                     if nav_q in p.get('name', '').lower()
                     or nav_q in (p.get('description') or '').lower()]

    ids = [p['id'] for p in all_panos]
    try:
        idx = ids.index(int(pano_id))
        prev_id = ids[(idx - 1) % len(ids)]
        next_id = ids[(idx + 1) % len(ids)]
    except ValueError:
        prev_id = next_id = None

    return render_template("view.html", pano_id=pano_id, pano=pano_data['gigapan'],
                           p=p, results=results, geo_panos=geo_panos,
                           prev_id=prev_id, next_id=next_id,
                           nav_tag=nav_tag, nav_q=nav_q)

def backup_json(json_path: Path):
    """Copy id.json → id.bak, then id.bk1, id.bk2 … if .bak already exists."""
    bak = json_path.with_suffix('.bak')
    if not bak.exists():
        import shutil
        shutil.copy2(json_path, bak)
        return
    n = 1
    while True:
        numbered = json_path.with_suffix(f'.bk{n}')
        if not numbered.exists():
            import shutil
            shutil.copy2(json_path, numbered)
            return
        n += 1


@app.route("/edit/<pano_id>", methods=["GET"])
def edit_pano(pano_id):
    json_path = BASE_DIR / pano_id / f"{pano_id}.json"
    if not json_path.exists():
        abort(404)
    with open(json_path) as f:
        data = json.load(f)
    pano = data['gigapan']
    tags_str = ', '.join(pano.get('tags') or [])

    # Build a geo hint: first tag that has a known centroid
    hint_center = None
    for tag in (pano.get('tags') or []):
        if tag in TAG_GEO_HINTS:
            hint_center = TAG_GEO_HINTS[tag]
            break

    geo_panos = [
        {'id': pg['id'], 'name': pg['name'],
         'lat': pg['latitude'], 'lng': pg['longitude']}
        for pg in load_pano_data()
        if pg.get('latitude') and pg.get('longitude')
        and pg['latitude'] != 0 and pg['longitude'] != 0
    ]

    return render_template("edit.html", pano=pano, pano_id=pano_id,
                           tags_str=tags_str, hint_center=hint_center,
                           geo_panos=geo_panos,
                           p={'page_title': f'Edit {pano.get("name", pano_id)}'})


@app.route("/edit/<pano_id>", methods=["POST"])
def edit_pano_post(pano_id):
    json_path = BASE_DIR / pano_id / f"{pano_id}.json"
    if not json_path.exists():
        abort(404)

    with open(json_path) as f:
        data = json.load(f)
    pano = data['gigapan']

    # Parse fields
    name        = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    tags_raw    = request.form.get('tags', '')
    tags = [
        t.strip().replace(' ', '_')
        for t in tags_raw.split(',')
        if t.strip()
    ]

    # Geo fields
    lat_str = request.form.get('latitude', '').strip()
    lng_str = request.form.get('longitude', '').strip()
    geo_precision = request.form.get('geo_precision', '').strip() or None
    geo_note      = request.form.get('geo_note', '').strip() or None

    # Apply changes
    if name:
        pano['name'] = name
    pano['description'] = description
    pano['tags'] = tags if tags else []

    # Apply geo if provided
    if lat_str and lng_str:
        try:
            pano['latitude']  = float(lat_str)
            pano['longitude'] = float(lng_str)
        except ValueError:
            pass
    elif lat_str == '' and lng_str == '':
        # Both cleared → remove coordinates
        if 'latitude' in pano:  del pano['latitude']
        if 'longitude' in pano: del pano['longitude']
        geo_precision = None
        geo_note = None

    if geo_precision is not None:
        pano['geo_precision'] = geo_precision
    elif 'geo_precision' in pano and not (lat_str or lng_str):
        del pano['geo_precision']

    if geo_note is not None:
        pano['geo_note'] = geo_note
    elif 'geo_note' in pano and not (lat_str or lng_str):
        del pano['geo_note']

    # Backup then write
    backup_json(json_path)
    with open(json_path, 'w') as f:
        json.dump(data, f, indent=2)

    from flask import flash
    flash(f'Saved — backup written.')
    return redirect(url_for('view_pano', pano_id=pano_id))


@app.route("/go")
def qr_redirect():
    dest = request.args.get('u', '').strip()
    if not dest.startswith(('http://', 'https://')):
        abort(400)
    return redirect(dest)


@app.route("/qr", methods=["GET", "POST"])
def qr_generator():
    qr_data_url = None
    dest = ''
    if request.method == "POST":
        dest = request.form.get('url', '').strip()
        if dest.startswith(('http://', 'https://')):
            import qrcode, base64
            from urllib.parse import urlencode
            target = request.host_url.rstrip('/') + '/go?' + urlencode({'u': dest})
            img = qrcode.make(target)
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            qr_data_url = 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()
    return render_template('qr.html', qr_data_url=qr_data_url, dest=dest)


if __name__ == "__main__":
    app.run(debug=True)
