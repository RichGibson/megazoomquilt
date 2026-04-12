"""
Generate thumbnails for panos with tile_base_url (R2-hosted tiles).
Saves to static/panos/{id}/{id}_thumb.jpg for later rclone upload.
"""
import io
import json
import math
import ssl
import sys
import urllib.request
from pathlib import Path
from PIL import Image

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

BASE_DIR = Path(__file__).resolve().parent.parent / "static/panos"
THUMB_MIN_DIM = 128
THUMB_MAX_TILES = 16


def fetch_tile(base_url, zoom, x, y, img_ext, timeout=15):
    url = f"{base_url}/{zoom}/{x}/{y}{img_ext}"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
            return Image.open(io.BytesIO(resp.read())).convert("RGB")
    except Exception as e:
        print(f"  WARN: failed to fetch {url}: {e}")
        return None


def generate_thumb(pano_id):
    json_path = BASE_DIR / str(pano_id) / f"{pano_id}.json"
    if not json_path.exists():
        print(f"  SKIP {pano_id}: no JSON")
        return False

    with json_path.open() as f:
        raw = json.load(f)
    meta = raw.get('gigapan', raw)

    tile_base_url = meta.get('tile_base_url')
    if not tile_base_url:
        print(f"  SKIP {pano_id}: no tile_base_url")
        return False

    cached_path = BASE_DIR / str(pano_id) / f"{pano_id}_thumb.jpg"
    if cached_path.exists():
        print(f"  SKIP {pano_id}: thumbnail already exists")
        return True

    W = int(meta['width'])
    H = int(meta['height'])
    levels = int(meta.get('levels', 1))
    max_zoom = levels - 1
    img_ext = '.' + meta.get('img_type', 'jpg')

    # Pick zoom level
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

    scale = 2 ** (max_zoom - zoom)
    content_w = max(1, int(W / scale))
    content_h = max(1, int(H / scale))
    cols = math.ceil(content_w / 256)
    rows = math.ceil(content_h / 256)

    print(f"  {pano_id}: zoom={zoom} grid={cols}x{rows} fetching {cols*rows} tiles...")

    sample = fetch_tile(tile_base_url, zoom, 0, 0, img_ext)
    if sample is None:
        print(f"  FAIL {pano_id}: could not fetch sample tile")
        return False

    tile_w, tile_h = sample.size
    composed = Image.new("RGB", (cols * tile_w, rows * tile_h))
    composed.paste(sample, (0, 0))

    for x in range(cols):
        for y in range(rows):
            if x == 0 and y == 0:
                continue
            tile = fetch_tile(tile_base_url, zoom, x, y, img_ext)
            if tile:
                composed.paste(tile, (x * tile_w, y * tile_h))

    crop_w = min(content_w, composed.width)
    crop_h = min(content_h, composed.height)
    composed = composed.crop((0, 0, crop_w, crop_h))
    composed.save(cached_path, format="JPEG", quality=85)
    print(f"  OK  {pano_id}: saved {cached_path.stat().st_size // 1024}KB")
    return True


if __name__ == "__main__":
    ids = [
        113947,114041,114133,116001,116002,116009,116057,116633,116700,116717,
        116723,116748,116781,116798,116799,116804,116811,116825,116828,116836,
        116841,116844,116845,117368,117413,121087,123168,123177,123179,123184,
        164459,164466,164478,164479,164480,164581,164588,164590,164591,164603,
        164614,164625,164626,164630,164631,164672,164673,164872,164905,164921,
        165124,165161,165171,165401,165480,165484,165530,165540,165544,165546,
        166144,166146,166158,166380,166496,166652,166655,166656,166659,166660,
        166663,166718,167128,167146,167157,167158,167166,167170,167171,167172,
        167174,167176,167216,167220,167239,167356,167604,167627,167684,167712,
        167784,167909,167927,167931,169086,169100,169195,169316,169318,169319,
        169321,169772,169774,170060,170182,170914,171019,171811,172115,172116,
        190938,194961
    ]

    ok = fail = skip = 0
    for pano_id in ids:
        print(f"[{pano_id}]")
        result = generate_thumb(pano_id)
        if result is True:
            ok += 1
        elif result is False:
            fail += 1
        else:
            skip += 1

    print(f"\nDone: {ok} generated, {fail} failed, {skip} skipped")
