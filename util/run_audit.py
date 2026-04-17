"""
Audit all panos: check JSON, thumbnail, local tile count, R2 status.
Writes results progressively to static/audit_cache.json.
Skips panos whose directory mtime hasn't changed since last run.

Usage:
    python3 util/run_audit.py
"""

import json
import math
import os
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR          = Path(__file__).resolve().parent.parent / "static" / "panos"
GIGAPAN_LIST_PATH = Path(__file__).resolve().parent.parent / "gigapan_list.json"
AUDIT_CACHE_PATH  = Path(__file__).resolve().parent.parent / "static" / "audit_cache.json"
WRITE_EVERY       = 20   # flush cache to disk every N changed panos


def dir_mtime(d):
    """Max mtime across the pano dir itself and its direct children."""
    try:
        entries = [d] + list(d.iterdir())
        return max(p.stat().st_mtime for p in entries)
    except (OSError, ValueError):
        return 0.0


def count_local_tiles(d):
    """Count image files inside zoom-level subdirectories only."""
    total = 0
    for entry in d.iterdir():
        if entry.is_dir() and entry.name.isdigit():
            for _, _, files in os.walk(entry):
                for f in files:
                    if '.' in f and f.rsplit('.', 1)[-1].lower() in ('jpg', 'jpeg', 'png'):
                        total += 1
    return total


def compute_entry(pano_id, cached):
    d         = BASE_DIR / str(pano_id)
    mtime     = dir_mtime(d)
    json_path  = d / f'{pano_id}.json'
    thumb_path = d / f'{pano_id}_thumb.jpg'

    # Skip if nothing changed since last audit
    if cached and cached.get('mtime', 0) >= mtime and mtime > 0:
        return None  # unchanged

    has_json  = json_path.exists()
    has_thumb = thumb_path.exists()
    on_r2     = False
    local     = 0
    expected  = 0

    if has_json:
        try:
            meta = json.load(open(json_path)).get('gigapan', {})
            on_r2 = bool(meta.get('tile_base_url'))
            W     = int(meta.get('width',  0))
            H     = int(meta.get('height', 0))
            lvls  = int(meta.get('levels', 0))
            if W and H and lvls:
                mz = lvls - 1
                for z in range(lvls):
                    scale     = 2 ** (mz - z)
                    expected += math.ceil(max(1, W // scale) / 256) * math.ceil(max(1, H // scale) / 256)
            if (d / '0').is_dir():
                local = count_local_tiles(d)
        except Exception:
            pass

    return {
        'has_json':  has_json,
        'has_thumb': has_thumb,
        'on_r2':     on_r2,
        'local':     local,
        'expected':  expected,
        'mtime':     mtime,
    }


def flush(cache):
    cache['_generated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    tmp = AUDIT_CACHE_PATH.with_suffix('.tmp')
    with open(tmp, 'w') as f:
        json.dump(cache, f)
    tmp.replace(AUDIT_CACHE_PATH)


def main():
    cache = {}
    if AUDIT_CACHE_PATH.exists():
        try:
            cache = json.load(open(AUDIT_CACHE_PATH))
        except Exception:
            pass

    all_ids = []
    if GIGAPAN_LIST_PATH.exists():
        all_ids = [p['id'] for p in json.load(open(GIGAPAN_LIST_PATH))]
    seen = set(all_ids)
    for entry in BASE_DIR.iterdir():
        if entry.is_dir() and entry.name.isdigit():
            pid = int(entry.name)
            if pid >= 1_000_000 and pid not in seen:
                all_ids.append(pid)

    changed = skipped = 0
    for pano_id in all_ids:
        key    = str(pano_id)
        result = compute_entry(pano_id, cache.get(key))
        if result is None:
            skipped += 1
        else:
            cache[key] = result
            changed += 1
            if changed % WRITE_EVERY == 0:
                flush(cache)
                print(f"  {changed} changed, {skipped} skipped so far…", flush=True)

    flush(cache)
    print(f"Done: {changed} changed, {skipped} skipped, {len(all_ids)} total.")


if __name__ == '__main__':
    main()
