"""
Download tiles and metadata for a single gigapan.

Usage:
    python3 util/gigapan_downloader.py 590 -o static/panos/590
    python3 util/gigapan_downloader.py 590 3 -o static/panos/590   # specific zoom level
    python3 util/gigapan_downloader.py 590 -o static/panos/590 -w 24
"""

import click
import json
import math
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from xml.dom import minidom

import requests

# ---------------------------------------------------------------------------
# Global rate-limit state.  When any thread hits a 429 or 503, it sets
# _rate_limit_until so every other thread pauses before its next request.
# ---------------------------------------------------------------------------
_rate_limit_until = 0.0
_rate_limit_lock  = threading.Lock()
_missing_lock     = threading.Lock()

REPORT_INTERVAL = 300   # seconds between progress lines (~5 minutes)
MAX_RETRIES     = 7     # attempts per tile before giving up
BASE_BACKOFF    = 2     # seconds; doubled on each retry


def ts():
    """Current time as HH:MM:SS string."""
    return datetime.now().strftime("%H:%M:%S")


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

def download_metadata(fmt, photo_id, output_dir):
    path = output_dir / f"{photo_id}.{fmt}"
    if path.exists():
        print(f"[{ts()}] {fmt} already on disk: {path}")
        with open(path, 'r', encoding='utf-8') as f:
            data = f.read()
    else:
        url = f"http://www.gigapan.com/gigapans/{photo_id}.{fmt}"
        for attempt in range(MAX_RETRIES):
            try:
                resp = requests.get(url, timeout=30)
                if resp.status_code == 200:
                    data = resp.content
                    path.write_bytes(data)
                    print(f"[{ts()}] {fmt} saved: {path}")
                    break
                else:
                    print(f"[{ts()}] {fmt} HTTP {resp.status_code} (attempt {attempt+1}/{MAX_RETRIES})")
                    time.sleep(BASE_BACKOFF * (2 ** attempt))
            except Exception as e:
                print(f"[{ts()}] {fmt} error attempt {attempt+1}/{MAX_RETRIES}: {e}")
                time.sleep(BASE_BACKOFF * (2 ** attempt))
        else:
            print(f"[{ts()}] ✗ Gave up fetching {fmt} for {photo_id}")
            return None

    if fmt == 'json':
        try:
            parsed = json.loads(data)
            return parsed['gigapan'] if len(data) > 100 else None
        except Exception as e:
            print(f"[{ts()}] ✗ Could not parse JSON for {photo_id}: {e}")
            return None

    return data


def parse_kml(kml_data):
    dom         = minidom.parseString(str(kml_data))
    width       = int(dom.getElementsByTagName("maxWidth")[0].firstChild.data)
    height      = int(dom.getElementsByTagName("maxHeight")[0].firstChild.data)
    tile_width  = int(dom.getElementsByTagName("tileSize")[0].firstChild.data)
    tile_height = int(dom.getElementsByTagName("tileSize")[0].firstChild.data)
    return width, height, tile_width, tile_height


# ---------------------------------------------------------------------------
# Tile geometry
# ---------------------------------------------------------------------------

def get_tile_dimensions(pano_width, pano_height, level, max_level, tile_size=256):
    scale        = 2 ** (max_level - level)
    level_width  = pano_width  / scale
    level_height = pano_height / scale
    tiles_x      = math.ceil(level_width  / tile_size)
    tiles_y      = math.ceil(level_height / tile_size)
    return tiles_x, tiles_y


# ---------------------------------------------------------------------------
# Completeness check
# ---------------------------------------------------------------------------

def check_completeness(pano_dir):
    """
    Count expected tiles vs tiles actually on disk.

    Returns:
        (missing, total, json_data)
        missing == -1  →  JSON not found or unreadable
        missing ==  0  →  fully complete
        missing  >  0  →  that many tiles are absent
    """
    pano_dir  = Path(pano_dir)
    pano_id   = pano_dir.name
    json_path = pano_dir / f"{pano_id}.json"

    if not json_path.exists():
        return -1, 0, None

    try:
        with json_path.open() as f:
            json_data = json.load(f)['gigapan']
    except Exception as e:
        print(f"[{ts()}]   Could not read {json_path}: {e}")
        return -1, 0, None

    max_level = json_data['levels'] - 1

    expected = sum(
        get_tile_dimensions(json_data['width'], json_data['height'], lvl, max_level)[0] *
        get_tile_dimensions(json_data['width'], json_data['height'], lvl, max_level)[1]
        for lvl in range(max_level + 1)
    )

    # Count actual tile files (named as digits, e.g. 0.jpg, 17.jpg)
    actual = sum(
        1 for _, _, files in os.walk(pano_dir)
        for f in files
        if Path(f).suffix.lower() in ('.jpg', '.png') and Path(f).stem.isdigit()
    )

    missing = max(0, expected - actual)
    return missing, expected, json_data


# ---------------------------------------------------------------------------
# HTTP with rate-limit awareness
# ---------------------------------------------------------------------------

def safe_request(url):
    global _rate_limit_until

    for attempt in range(MAX_RETRIES):
        # Honour any global pause set by another thread hitting a 429/503
        wait = _rate_limit_until - time.time()
        if wait > 0:
            time.sleep(wait)

        try:
            resp = requests.get(url, timeout=20)

            if resp.status_code == 429:
                retry_after = int(resp.headers.get('Retry-After', 60))
                print(f"[{ts()}]   ⚠ 429 Rate limited — all workers pausing {retry_after}s")
                with _rate_limit_lock:
                    _rate_limit_until = time.time() + retry_after
                time.sleep(retry_after)
                continue

            if resp.status_code == 503:
                wait_time = min(10 * (2 ** attempt), 120)
                print(f"[{ts()}]   ⚠ 503 Service unavailable — all workers pausing {wait_time}s")
                with _rate_limit_lock:
                    _rate_limit_until = time.time() + wait_time
                time.sleep(wait_time)
                continue

            if resp.status_code != 200:
                backoff = BASE_BACKOFF * (2 ** attempt)
                print(f"[{ts()}]   HTTP {resp.status_code} for {url} — retry {attempt+1}/{MAX_RETRIES} in {backoff}s")
                time.sleep(backoff)
                continue

            return resp

        except requests.RequestException as e:
            backoff = BASE_BACKOFF * (2 ** attempt)
            print(f"[{ts()}]   Network error attempt {attempt+1}/{MAX_RETRIES}: {e} — retry in {backoff}s")
            time.sleep(backoff)

    print(f"[{ts()}]   ✗ Gave up after {MAX_RETRIES} attempts: {url}")
    return None


def is_valid_jpeg(data):
    return data.startswith(b'\xff\xd8') and data.endswith(b'\xff\xd9')


# ---------------------------------------------------------------------------
# Single tile download
# ---------------------------------------------------------------------------

def download_tile(photo_id, level, col, row, output_dir):
    tile_url  = f"http://www.gigapan.com/get_ge_tile/{photo_id}/{level}/{row}/{col}"
    tile_path = Path(output_dir) / str(level) / str(col) / f"{row}.jpg"
    tile_path.parent.mkdir(parents=True, exist_ok=True)

    if tile_path.exists():
        return  # already have it

    resp = safe_request(tile_url)
    if resp is None:
        raise RuntimeError(f"No response after {MAX_RETRIES} attempts")

    content = resp.content
    if not is_valid_jpeg(content):
        raise RuntimeError(f"Invalid JPEG ({len(content)} bytes)")

    tile_path.write_bytes(content)


def record_missing(output_dir, level, col, row):
    missing_path = Path(output_dir) / "missing_tiles.txt"
    with _missing_lock:
        with open(missing_path, 'a') as f:
            f.write(f"{level}/{row}/{col}.jpg\n")


# ---------------------------------------------------------------------------
# Main download orchestration
# ---------------------------------------------------------------------------

def download_all_tiles(photo_id, output_dir, level=None, workers=16):
    kml_data  = download_metadata('kml',  photo_id, output_dir)
    json_data = download_metadata('json', photo_id, output_dir)

    if json_data is None:
        print(f"[{ts()}] ✗ No JSON metadata for {photo_id} — aborting")
        return

    max_level = json_data['levels'] - 1
    w = int(json_data['width'])
    h = int(json_data['height'])

    if level is None:
        levels_to_fetch = list(range(max_level + 1))
    else:
        if level > max_level:
            print(f"[{ts()}]   Level {level} exceeds max {max_level} — clamping")
            level = max_level
        levels_to_fetch = [level]

    print(f"[{ts()}] Pano {photo_id}: {w}×{h}px, {max_level+1} zoom levels, "
          f"fetching levels {levels_to_fetch[0]}–{levels_to_fetch[-1]}, {workers} workers")

    total_errors = 0

    with ThreadPoolExecutor(max_workers=workers) as executor:
        for lvl in levels_to_fetch:
            cols, rows = get_tile_dimensions(w, h, lvl, max_level)
            total = cols * rows
            print(f"[{ts()}] ── Level {lvl}: {cols} cols × {rows} rows = {total} tiles")

            futures = {
                executor.submit(download_tile, photo_id, lvl, col, row, output_dir): (lvl, col, row)
                for row in range(rows)
                for col in range(cols)
            }

            done        = 0
            errors      = 0
            level_start = time.time()
            last_report = level_start

            for future in as_completed(futures):
                done += 1

                try:
                    future.result()
                except Exception as e:
                    errors       += 1
                    total_errors += 1
                    lvl_, col_, row_ = futures[future]
                    print(f"[{ts()}]   ✗ Tile {lvl_}/{col_}/{row_}: {e}")
                    record_missing(output_dir, lvl_, col_, row_)

                now = time.time()
                if now - last_report >= REPORT_INTERVAL:
                    elapsed   = now - level_start
                    rate      = done / elapsed if elapsed > 0 else 0
                    remaining = (total - done) / rate if rate > 0 and done < total else 0
                    print(f"[{ts()}]   Progress level {lvl}: {done}/{total} tiles  "
                          f"({rate:.1f}/s  ~{remaining/60:.0f}m remaining  {errors} errors this level)")
                    last_report = now

            elapsed = time.time() - level_start
            print(f"[{ts()}] ── Level {lvl} done: {done} tiles in {elapsed/60:.1f}m  ({errors} errors)")

    # Final completeness verification
    missing, total_tiles, _ = check_completeness(output_dir)
    if missing == 0:
        print(f"[{ts()}] ✓ Pano {photo_id} verified complete: {total_tiles} tiles")
        (output_dir / '.complete').write_text(str(total_tiles))
    else:
        print(f"[{ts()}] ⚠ Pano {photo_id}: {missing}/{total_tiles} tiles missing "
              f"— check missing_tiles.txt")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.command()
@click.argument('photo_id', type=int)
@click.argument('zoom_level', required=False, type=int)
@click.option('-o', '--output',  default='tiles',  show_default=True, help='Output directory')
@click.option('-w', '--workers', default=16,        show_default=True, help='Concurrent tile downloads')
def main(photo_id, zoom_level, output, workers):
    if output == 'tiles':
        output = str(photo_id)
    output_dir = Path(output)
    output_dir.mkdir(parents=True, exist_ok=True)
    download_all_tiles(photo_id, output_dir, zoom_level, workers)


if __name__ == "__main__":
    main()
