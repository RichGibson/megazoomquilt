from flask import Flask, abort, render_template, send_file, Response, request, jsonify, redirect, make_response, url_for, flash
import io
import json
import math
import statistics
from collections import defaultdict
from PIL import Image
from pathlib import Path
import urllib.request
import subprocess, sys
import shutil
import qrcode, base64
import uuid as _uuid
from util.import_images import extract_exif, image_dimensions, build_index
from datetime import datetime as _dt

app = Flask(__name__)
app.secret_key = 'mzq-dev-key-change-in-prod'

SKINS = ['default', 'retro', 'amber', 'museum', 'blueprint', 'magazine', 'explorer']
GIGAPAN_LIST_PATH = Path(__file__).resolve().parent / "gigapan_list.json"
AUDIT_CACHE_PATH  = Path(__file__).resolve().parent / "static" / "audit_cache.json"
SETTINGS_PATH     = Path(__file__).resolve().parent / "static" / "settings.json"

IMAGES_DIR   = Path(__file__).resolve().parent / "static" / "images"
IMAGES_INDEX = Path(__file__).resolve().parent / "static" / "images_index.json"
IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.tif', '.tiff', '.webp', '.heic'}

# Directory where folders of image pyramids (e.g., 590/, 591/) are stored
BASE_DIR = Path(__file__).resolve().parent / "static/panos"

THUMB_MIN_DIM = 128   # target at least this many pixels on the shorter content side
THUMB_MAX_TILES = 16  # never composite more tiles than this

SETTINGS_DEFAULTS = {
    'cluster_max_radius':      40,
    'cluster_disable_at_zoom': 13,
}

SORT_CONFIG = {
    'id_asc':       (lambda p: p['id'],                                               False),
    'id_desc':      (lambda p: p['id'],                                               True),
    'name_asc':     (lambda p: p['name'].lower(),                                     False),
    'name_desc':    (lambda p: p['name'].lower(),                                     True),
    'date_asc':     (lambda p: (0 if p.get('taken_at') else 1,    p.get('taken_at') or ''),   False),
    'date_desc':    (lambda p: (1 if p.get('taken_at') else 0,    p.get('taken_at') or ''),   True),
    'uploaded_asc': (lambda p: (0 if p.get('created_at') else 1,  p.get('created_at') or ''), False),
    'uploaded_desc':(lambda p: (1 if p.get('created_at') else 0,  p.get('created_at') or ''), True),
    'size_asc':     (lambda p: p.get('width', 0) * p.get('height', 0),               False),
    'size_desc':    (lambda p: p.get('width', 0) * p.get('height', 0),               True),
}

def load_settings():
    """Load settings from disk, falling back to defaults for any missing keys."""
    if SETTINGS_PATH.exists():
        with open(SETTINGS_PATH) as f:
            s = json.load(f)
        return {**SETTINGS_DEFAULTS, **s}
    return dict(SETTINGS_DEFAULTS)

def save_settings(data):
    """Write settings dict to disk atomically via a temp file."""
    tmp = SETTINGS_PATH.with_suffix('.tmp')
    with open(tmp, 'w') as f:
        json.dump(data, f, indent=2)
    tmp.replace(SETTINGS_PATH)

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
}

def _is_local():
    """Return True if the request originates from localhost."""
    host = request.host.split(':')[0]
    return host in ('localhost', '127.0.0.1', '::1')

@app.context_processor
def inject_skin():
    """Inject skin name and is_local flag into every template context."""
    skin = request.cookies.get('skin', 'default')
    if skin not in SKINS:
        skin = 'default'
    return {'skin': skin, 'is_local': _is_local()}

@app.route('/skin/<name>')
def set_skin(name):
    """Set the active skin cookie and redirect back to the referring page."""
    if name not in SKINS:
        name = 'default'
    dest = request.referrer or url_for('home')
    resp = make_response(redirect(dest))
    resp.set_cookie('skin', name, max_age=60*60*24*365)
    return resp

def collect_tile_stats(base_dir):
    """Walk a pano tile directory and return per-zoom-level size and grid statistics."""
    base_dir = Path(base_dir)
    results=[]
    stats = defaultdict(lambda: {
        "sizes": [],
        "x_values": set(),
        "y_values": set()
    })

    for full_path in base_dir.rglob('*'):
        if not full_path.is_file():
            continue
        if full_path.suffix.lower() not in ('.jpg', '.png'):
            continue
        try:
            size = full_path.stat().st_size
        except Exception as e:
            print(f"Could not read {full_path}: {e}")
            continue
        try:
            rel_parts = full_path.relative_to(base_dir).parts
            level = rel_parts[0]
            x = rel_parts[1]
            y = Path(rel_parts[2]).stem
        except Exception as e:
            print(f"Invalid path structure: {full_path} — {e}")
            continue
        data = stats[level]
        data["sizes"].append(size)
        data["x_values"].add(int(x))
        data["y_values"].add(int(y))
    for level in sorted(stats.keys(), key=lambda x: int(x)):
        data = stats[level]
        sizes = data["sizes"]
        count = len(sizes)
        min_size = min(sizes)
        max_size = max(sizes)
        avg_size = int(statistics.mean(sizes))
        cols = len(data["x_values"])
        rows = len(data["y_values"])
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
    """Scan BASE_DIR for pano JSON files and return a sorted list of metadata dicts."""
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


_pano_cache = None   # sorted list for iteration
_pano_index = None   # id → pano for O(1) lookup

def _get_pano_cache():
    """Return the cached pano list, loading from disk on first call."""
    global _pano_cache, _pano_index
    if _pano_cache is None:
        _pano_cache = load_pano_data()
        _pano_index = {p['id']: p for p in _pano_cache}
    return _pano_cache

def invalidate_pano_cache():
    """Clear the pano list and index caches so the next request reloads from disk."""
    global _pano_cache, _pano_index
    _pano_cache = None
    _pano_index = None

def get_pano(pano_id):
    """Look up a single pano by id from the cache. Returns None if not found."""
    _get_pano_cache()  # ensure populated
    pid = int(pano_id) if str(pano_id).isdigit() else pano_id
    return _pano_index.get(pid)

def geo_panos_from_cache():
    """Return all geo-located panos as dicts with lat/lng/width/height/tile_base_url keys."""
    return [
        {
            'id':            pg['id'],
            'name':          pg['name'],
            'lat':           pg['latitude'],
            'lng':           pg['longitude'],
            'width':         pg.get('width', 0),
            'height':        pg.get('height', 0),
            'tile_base_url': resolve_tile_base_url(pg) or '',
        }
        for pg in _get_pano_cache()
        if pg.get('latitude') and pg.get('longitude')
        and pg['latitude'] != 0 and pg['longitude'] != 0
    ]


@app.route("/thumbnail/<pano_id>")
def thumbnail(pano_id):
    """Serve a WebP thumbnail for a pano, compositing from tiles if not yet cached."""
    # Serve cached thumbnail if it exists locally (WebP preferred, JPEG fallback)
    cached_path = BASE_DIR / pano_id / f"{pano_id}_thumb.webp"
    if cached_path.exists():
        return send_file(cached_path, mimetype="image/webp")
    legacy_path = BASE_DIR / pano_id / f"{pano_id}_thumb.jpg"
    if legacy_path.exists():
        return send_file(legacy_path, mimetype="image/jpeg")

    meta = get_pano(pano_id)
    if meta is None:
        abort(404)

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
        _HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; megazoomquilt-thumb/1.0)'}
        def fetch_tile(x, y):
            url = f"{tile_base_url}/{zoom}/{x}/{y}{img_ext}"
            try:
                req = urllib.request.Request(url, headers=_HEADERS)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return Image.open(io.BytesIO(resp.read())).convert("RGB")
            except Exception as e:
                app.logger.warning("fetch_tile failed %s: %s", url, e)
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
        composed.save(cached_path, format="WEBP", quality=85)
        return send_file(cached_path, mimetype="image/webp")
    except Exception:
        buf = io.BytesIO()
        composed.save(buf, format="WEBP", quality=85)
        buf.seek(0)
        return send_file(buf, mimetype="image/webp")


@app.route('/.well-known/appspecific/com.chrome.devtools.json')
def chrome_devtools_stub():
    """Return an empty JSON response to silence Chrome DevTools discovery requests."""
    return jsonify({}), 200

@app.route("/")
def home():
    """Render the main gallery index with sorting and full-text search."""
    panoramas = _get_pano_cache()
    sort = request.args.get('sort', 'id_asc')
    query = request.args.get('query', '').strip()
    key, reverse = SORT_CONFIG.get(sort, SORT_CONFIG['id_asc'])
    panoramas = sorted(panoramas, key=key, reverse=reverse)
    total_count = len(panoramas)
    if query:
        q = query.lower()
        panoramas = [p for p in panoramas
                     if q in p.get('name', '').lower()
                     or q in (p.get('description') or '').lower()
                     or any(q in t.lower() for t in (p.get('tags') or []))]
    p={}
    p['page_title']='Megazoomquilt'
    return render_template("index.html", panoramas=panoramas, p=p, sort=sort,
                           query=query, total_count=total_count)

@app.route("/tags")
def tags_page():
    """Render the tag cloud page with usage counts."""
    panoramas = _get_pano_cache()
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
    """Render the gallery filtered to a single tag, with sorting."""
    panoramas = _get_pano_cache()
    sort = request.args.get('sort', 'id_asc')
    key, reverse = SORT_CONFIG.get(sort, SORT_CONFIG['id_asc'])
    filtered = [p for p in panoramas if tag in (p.get('tags') or [])]
    filtered = sorted(filtered, key=key, reverse=reverse)
    return render_template("index.html", panoramas=filtered, sort=sort,
                           active_tag=tag, p={'page_title': f'#{tag}'})

@app.route("/map")
def map_view():
    """Render the Leaflet map with downloaded and pending panorama markers."""
    panoramas = _get_pano_cache()
    mapped = geo_panos_from_cache()

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

    return render_template("map.html", panoramas=mapped, pending_panos=pending_panos,
                           p={'page_title': 'Map'}, settings=load_settings())

@app.route("/list/audit/refresh", methods=["POST"])
def admin_audit_refresh():
    """Kick off a background audit run and redirect to the list page."""
    script = Path(__file__).resolve().parent / "util" / "run_audit.py"
    subprocess.Popen([sys.executable, str(script)],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     close_fds=True)
    return redirect(url_for('pano_list') + '?audit=running')

@app.route("/list")
def pano_list():
    """Render the full inventory list merging local panos with the gigapan_list.json catalogue."""
    local_panos = {p['id']: p for p in _get_pano_cache()}

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
        try:
            with open(AUDIT_CACHE_PATH) as f:
                audit = json.load(f)
        except (json.JSONDecodeError, ValueError):
            audit = {}  # corrupt/empty cache — will show "no audit" warning in template

    return render_template("list.html", p={'page_title': 'List'},
                           panoramas=all_panos, audit=audit)


@app.route("/admin", methods=["GET", "POST"])
def admin():
    """Render and handle the admin settings form (localhost only)."""
    if not _is_local():
        abort(403)
    if request.method == "POST":
        s = load_settings()
        for key in SETTINGS_DEFAULTS:
            val = request.form.get(key, '').strip()
            if val:
                s[key] = int(val)
        save_settings(s)
        return redirect(url_for('admin'))
    settings = load_settings()
    return render_template("admin.html", p={'page_title': 'Admin'}, settings=settings)


@app.route("/view/<pano_id>")
def view_pano(pano_id):
    """Render the full-screen viewer for a single panorama with tile stats and navigation."""
    pano = get_pano(pano_id)
    if pano is None:
        return f"Metadata for panorama {pano_id} not found.", 404

    pano = dict(pano)
    pano['has_local_tiles'] = check_has_local_tiles(pano_id)
    pano['tile_base_url'] = resolve_tile_base_url(pano)
    p = {'page_title': 'View'}
    results = collect_tile_stats(BASE_DIR / pano_id)

    geo_panos = geo_panos_from_cache()

    nav_tag = request.args.get('tag', '').strip()
    nav_q   = request.args.get('q',   '').strip().lower()

    all_panos = list(_get_pano_cache())
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

    # Load associated images
    associated_images = []
    idx_data = load_images_index()
    for uid in idx_data.get('by_pano', {}).get(pano_id, []):
        jp = IMAGES_DIR / uid / f'{uid}.json'
        if jp.exists():
            try:
                associated_images.append(json.load(open(jp)))
            except Exception:
                pass

    return render_template("view.html", pano_id=pano_id, pano=pano,
                           p=p, results=results, geo_panos=geo_panos,
                           prev_id=prev_id, next_id=next_id,
                           nav_tag=nav_tag, nav_q=nav_q,
                           associated_images=associated_images)

def backup_json(json_path: Path):
    """Copy id.json → id.bak, then id.bk1, id.bk2 … if .bak already exists."""
    bak = json_path.with_suffix('.bak')
    if not bak.exists():
        shutil.copy2(json_path, bak)
        return
    n = 1
    while True:
        numbered = json_path.with_suffix(f'.bk{n}')
        if not numbered.exists():
            shutil.copy2(json_path, numbered)
            return
        n += 1


@app.route("/edit/<pano_id>", methods=["GET"])
def edit_pano(pano_id):
    """Render the edit form for a panorama's metadata (localhost only)."""
    if not _is_local():
        abort(403)
    pano = get_pano(pano_id)
    if pano is None:
        abort(404)
    tags_str = ', '.join(pano.get('tags') or [])

    # Build a geo hint: first tag that has a known centroid
    hint_center = None
    for tag in (pano.get('tags') or []):
        if tag in TAG_GEO_HINTS:
            hint_center = TAG_GEO_HINTS[tag]
            break

    geo_panos = geo_panos_from_cache()

    return render_template("edit.html", pano=pano, pano_id=pano_id,
                           tags_str=tags_str, hint_center=hint_center,
                           geo_panos=geo_panos,
                           p={'page_title': f'Edit {pano.get("name", pano_id)}'})


@app.route("/edit/<pano_id>", methods=["POST"])
def edit_pano_post(pano_id):
    """Save submitted edits to a panorama's name, tags, and geo fields (localhost only)."""
    if not _is_local():
        abort(403)
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
    invalidate_pano_cache()

    flash('Saved — backup written.')
    return redirect(url_for('view_pano', pano_id=pano_id))


@app.route("/go")
def qr_redirect():
    """Redirect to the URL in the ?u= parameter; used as the QR code landing target."""
    dest = request.args.get('u', '').strip()
    if not dest.startswith(('http://', 'https://')):
        abort(400)
    return redirect(dest)


@app.route("/qr", methods=["GET", "POST"])
def qr_generator():
    """Render a QR code generator form and return the encoded PNG as a data URL."""
    qr_data_url = None
    dest = ''
    if request.method == "POST":
        dest = request.form.get('url', '').strip()
        if dest.startswith(('http://', 'https://')):
            img = qrcode.make(dest)
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            qr_data_url = 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()
    return render_template('qr.html', qr_data_url=qr_data_url, dest=dest)




def load_images_index():
    """Load and return the images index JSON, or an empty index if the file does not exist."""
    if IMAGES_INDEX.exists():
        with open(IMAGES_INDEX) as f:
            return json.load(f)
    return {'by_pano': {}, 'unassociated': [], 'all': []}


@app.route("/images/<uid>/thumb")
def image_thumb(uid):
    """Serve or generate a thumbnail for an image."""
    img_dir = IMAGES_DIR / uid
    for ext in ('jpg', 'jpeg', 'png', 'tif', 'tiff', 'webp'):
        src = img_dir / f'{uid}.{ext}'
        if src.exists():
            thumb = img_dir / f'{uid}_thumb.jpg'
            if not thumb.exists():
                im = Image.open(src)
                im.thumbnail((400, 400))
                im = im.convert('RGB')
                im.save(thumb, format='JPEG', quality=85)
            return send_file(thumb, mimetype='image/jpeg')
    abort(404)


@app.route("/images/<uid>/full")
def image_full(uid):
    """Serve the full-size original image."""
    img_dir = IMAGES_DIR / uid
    for ext in ('jpg', 'jpeg', 'png', 'tif', 'tiff', 'webp'):
        src = img_dir / f'{uid}.{ext}'
        if src.exists():
            return send_file(src)
    abort(404)


@app.route("/images/<uid>/associate", methods=["GET", "POST"])
def image_associate(uid):
    """Render and handle the form for associating an image with one or more panoramas (localhost only)."""
    if not _is_local():
        abort(403)
    json_path = IMAGES_DIR / uid / f'{uid}.json'
    if not json_path.exists():
        abort(404)
    img_meta = json.load(open(json_path))

    if request.method == "POST":
        pano_ids = [int(x) for x in request.form.getlist('pano_ids') if x.isdigit()]
        title    = request.form.get('title', img_meta.get('title', ''))
        itype    = request.form.get('type',  img_meta.get('type', 'photo'))
        notes       = request.form.get('notes',       img_meta.get('notes', ''))
        description = request.form.get('description', img_meta.get('description', ''))
        lat_str = request.form.get('latitude', '').strip()
        lng_str = request.form.get('longitude', '').strip()
        img_meta['pano_ids']    = pano_ids
        img_meta['title']       = title
        img_meta['type']        = itype
        img_meta['notes']       = notes
        img_meta['description'] = description
        img_meta['latitude']    = float(lat_str) if lat_str else None
        img_meta['longitude']   = float(lng_str) if lng_str else None
        with open(json_path, 'w') as f:
            json.dump(img_meta, f, indent=2)
        # Rebuild index
        script = Path(__file__).resolve().parent / "util" / "import_images.py"
        subprocess.Popen([sys.executable, str(script), '--reindex'],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return redirect(url_for('image_associate', uid=uid))

    all_panos = _get_pano_cache()

    # Determine map center: image GPS → first associated pano → None
    center_lat = img_meta.get('latitude')
    center_lng = img_meta.get('longitude')
    if center_lat is None and img_meta.get('pano_ids'):
        for p in all_panos:
            if p['id'] in img_meta['pano_ids'] and p.get('latitude') and p.get('longitude'):
                center_lat = p['latitude']
                center_lng = p['longitude']
                break

    # Filter to panos within ~100 km of center; always include already-associated ones
    RADIUS_DEG = 1.0  # ~111 km per degree — coarse but fast
    if center_lat is not None and center_lng is not None:
        associated_set = set(img_meta.get('pano_ids', []))
        panoramas = [
            p for p in all_panos
            if p.get('latitude') and p.get('longitude') and (
                p['id'] in associated_set or (
                    abs(p['latitude']  - center_lat) <= RADIUS_DEG and
                    abs(p['longitude'] - center_lng) <= RADIUS_DEG
                )
            )
        ]
    else:
        panoramas = [p for p in all_panos if p.get('latitude') and p.get('longitude')]

    return render_template('image_associate.html',
                           img=img_meta, uid=uid, panoramas=panoramas,
                           center_lat=center_lat, center_lng=center_lng)



@app.route("/images/upload", methods=["GET", "POST"])
def image_upload():
    """Handle image upload, extract EXIF metadata, and redirect to the associate form (localhost only)."""
    if not _is_local():
        abort(403)
    pano_id = request.args.get('pano_id') or request.form.get('pano_id', '')

    if request.method == "POST":
        f = request.files.get('file')
        if not f or not f.filename:
            return render_template('image_upload.html', pano_id=pano_id, error="No file selected.")

        ext = Path(f.filename).suffix.lower()
        if ext not in IMAGE_EXTS:
            return render_template('image_upload.html', pano_id=pano_id,
                                   error=f"Unsupported file type: {ext}")

        uid      = str(_uuid.uuid4())
        dest_dir = IMAGES_DIR / uid
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_file = dest_dir / f'{uid}{ext}'
        f.save(str(dest_file))

        # Extract EXIF
        exif    = extract_exif(dest_file)
        w, h    = image_dimensions(dest_file)

        source_date = None
        dt_str = exif.get('DateTimeOriginal') or exif.get('DateTimeDigitized') or exif.get('DateTime')
        if dt_str:
            try:
                source_date = _dt.strptime(dt_str, '%Y:%m:%d %H:%M:%S').strftime('%Y-%m-%d')
            except ValueError:
                source_date = dt_str

        title   = request.form.get('title', '').strip() or Path(f.filename).stem
        lat_str = request.form.get('latitude',  '').strip()
        lng_str = request.form.get('longitude', '').strip()
        lat     = float(lat_str) if lat_str else exif.get('latitude')
        lng     = float(lng_str) if lng_str else exif.get('longitude')

        pano_ids = [int(pano_id)] if pano_id and pano_id.isdigit() else []

        meta = {
            'id':                uid,
            'original_filename': f.filename,
            'ext':               ext.lstrip('.'),
            'width':             w,
            'height':            h,
            'title':             title,
            'type':              request.form.get('type', 'photo'),
            'source_date':       source_date,
            'imported_at':       _dt.now().strftime('%Y-%m-%d %H:%M:%S'),
            'latitude':          lat,
            'longitude':         lng,
            'altitude':          exif.get('altitude'),
            'description':       request.form.get('description', '').strip(),
            'notes':             '',
            'attribution':       '',
            'tags':              [],
            'pano_ids':          pano_ids,
            'exif':              exif,
        }
        with open(dest_dir / f'{uid}.json', 'w') as jf:
            json.dump(meta, jf, indent=2)
        build_index()
        return redirect(url_for('image_associate', uid=uid))

    return render_template('image_upload.html', pano_id=pano_id, error=None)


@app.route("/api/images")
def api_images():
    """JSON feed of images for the map."""
    idx = load_images_index()
    return jsonify(idx.get('all', []))


if __name__ == "__main__":
    app.run(debug=True)
