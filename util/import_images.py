"""
Import images from a drop directory into static/images/{uuid}/.

Reads all available EXIF data (GPS, date, camera, lens, exposure).
Assigns a UUID, copies the original, writes JSON metadata, updates
static/images_index.json.

Usage:
    python3 util/import_images.py /path/to/drop/dir
    python3 util/import_images.py /path/to/drop/dir --move      # move instead of copy
    python3 util/import_images.py /path/to/drop/dir --dry-run   # show what would happen
    python3 util/import_images.py --reindex                     # rebuild index only
"""

import argparse
import json
import shutil
import sys
import uuid
from datetime import datetime
from pathlib import Path

from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS

BASE_DIR    = Path(__file__).resolve().parent.parent
IMAGES_DIR  = BASE_DIR / "static" / "images"
INDEX_PATH  = BASE_DIR / "static" / "images_index.json"
IMAGE_EXTS  = {'.jpg', '.jpeg', '.png', '.tif', '.tiff', '.webp', '.heic'}


# ── EXIF helpers ──────────────────────────────────────────────────────────────

def _rational_to_float(r):
    """Convert PIL IFDRational or (num, denom) tuple to float."""
    try:
        return float(r)
    except Exception:
        try:
            return r[0] / r[1] if r[1] else None
        except Exception:
            return None


def _dms_to_decimal(dms, ref):
    """Convert degrees/minutes/seconds + hemisphere ref to decimal degrees."""
    try:
        d = _rational_to_float(dms[0])
        m = _rational_to_float(dms[1])
        s = _rational_to_float(dms[2])
        val = d + m / 60 + s / 3600
        if ref in ('S', 'W'):
            val = -val
        return round(val, 7)
    except Exception:
        return None


def extract_exif(path):
    """Return a dict of all useful EXIF fields from an image file."""
    result = {}
    try:
        img = Image.open(path)
        raw = img._getexif()
        if not raw:
            return result

        named = {TAGS.get(k, k): v for k, v in raw.items()}

        # ── GPS ──────────────────────────────────────────────────────────────
        gps_raw = named.get('GPSInfo')
        if gps_raw:
            gps = {GPSTAGS.get(k, k): v for k, v in gps_raw.items()}
            result['gps_raw'] = {str(k): str(v) for k, v in gps.items()}
            lat = _dms_to_decimal(gps.get('GPSLatitude'), gps.get('GPSLatitudeRef', 'N'))
            lng = _dms_to_decimal(gps.get('GPSLongitude'), gps.get('GPSLongitudeRef', 'E'))
            alt = _rational_to_float(gps.get('GPSAltitude'))
            if lat is not None: result['latitude']  = lat
            if lng is not None: result['longitude'] = lng
            if alt is not None: result['altitude']  = round(alt, 2)

        # ── Date/time ─────────────────────────────────────────────────────────
        for tag in ('DateTimeOriginal', 'DateTimeDigitized', 'DateTime'):
            val = named.get(tag)
            if val:
                result[tag] = val
                break

        # ── Camera ────────────────────────────────────────────────────────────
        for tag in ('Make', 'Model', 'LensMake', 'LensModel', 'Software'):
            val = named.get(tag)
            if val:
                result[tag] = str(val).strip()

        # ── Exposure ──────────────────────────────────────────────────────────
        for tag in ('FNumber', 'ExposureTime', 'ISOSpeedRatings',
                    'FocalLength', 'FocalLengthIn35mmFilm',
                    'ExposureBiasValue', 'MeteringMode', 'Flash',
                    'WhiteBalance', 'ExposureMode', 'ExposureProgram'):
            val = named.get(tag)
            if val is not None:
                f = _rational_to_float(val)
                result[tag] = f if f is not None else str(val)

        # ── Image dimensions (from EXIF, may differ from file) ────────────────
        for tag in ('ExifImageWidth', 'ExifImageHeight',
                    'PixelXDimension', 'PixelYDimension'):
            val = named.get(tag)
            if val is not None:
                result[tag] = int(val)

        # ── Orientation ───────────────────────────────────────────────────────
        ori = named.get('Orientation')
        if ori:
            result['Orientation'] = int(ori)

    except Exception as e:
        result['_exif_error'] = str(e)

    return result


def image_dimensions(path):
    try:
        with Image.open(path) as img:
            return img.size  # (width, height)
    except Exception:
        return (None, None)


# ── Index ─────────────────────────────────────────────────────────────────────

def build_index():
    """Scan all image JSONs and write images_index.json."""
    by_pano = {}
    unassociated = []
    all_images = []

    for d in sorted(IMAGES_DIR.iterdir()):
        if not d.is_dir():
            continue
        jp = d / f'{d.name}.json'
        if not jp.exists():
            continue
        try:
            meta = json.load(open(jp))
        except Exception:
            continue

        uid = meta['id']
        lat = meta.get('latitude')
        lng = meta.get('longitude')
        pano_ids = meta.get('pano_ids', [])

        all_images.append({
            'id':        uid,
            'title':     meta.get('title', ''),
            'type':      meta.get('type', 'photo'),
            'latitude':  lat,
            'longitude': lng,
            'source_date': meta.get('source_date'),
            'pano_ids':  pano_ids,
        })

        if pano_ids:
            for pid in pano_ids:
                by_pano.setdefault(str(pid), []).append(uid)
        elif lat is not None and lng is not None:
            unassociated.append(uid)

    index = {
        'by_pano':       by_pano,
        'unassociated':  unassociated,
        'all':           all_images,
        '_generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
    tmp = INDEX_PATH.with_suffix('.tmp')
    with open(tmp, 'w') as f:
        json.dump(index, f, indent=2)
    tmp.replace(INDEX_PATH)
    return index


# ── Import ────────────────────────────────────────────────────────────────────

def import_image(src_path, move=False, dry_run=False):
    """Import one image file. Returns the new UUID or None on skip."""
    uid  = str(uuid.uuid4())
    dest_dir = IMAGES_DIR / uid
    ext  = src_path.suffix.lower()
    dest_file = dest_dir / f'{uid}{ext}'
    dest_json = dest_dir / f'{uid}.json'

    print(f'  {src_path.name} → {uid}{ext}')

    if dry_run:
        return uid

    dest_dir.mkdir(parents=True, exist_ok=True)

    if move:
        shutil.move(str(src_path), dest_file)
    else:
        shutil.copy2(str(src_path), dest_file)

    exif = extract_exif(dest_file)
    w, h = image_dimensions(dest_file)

    # Parse DateTimeOriginal into ISO format if present
    source_date = None
    dt_str = exif.get('DateTimeOriginal') or exif.get('DateTimeDigitized') or exif.get('DateTime')
    if dt_str:
        try:
            dt = datetime.strptime(dt_str, '%Y:%m:%d %H:%M:%S')
            source_date = dt.strftime('%Y-%m-%d')
        except ValueError:
            source_date = dt_str

    meta = {
        'id':           uid,
        'original_filename': src_path.name,
        'ext':          ext.lstrip('.'),
        'width':        w,
        'height':       h,
        'title':        src_path.stem,
        'type':         'photo',      # user can edit: photo|aerial|map|screenshot|drawing
        'source_date':  source_date,
        'imported_at':  datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'latitude':     exif.get('latitude'),
        'longitude':    exif.get('longitude'),
        'altitude':     exif.get('altitude'),
        'description':  '',
        'notes':        '',
        'attribution':  '',
        'tags':         [],
        'pano_ids':     [],
        'exif':         exif,
    }

    with open(dest_json, 'w') as f:
        json.dump(meta, f, indent=2)

    return uid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('drop_dir', nargs='?', help='Directory containing images to import')
    parser.add_argument('--move',    action='store_true', help='Move files instead of copying')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be imported')
    parser.add_argument('--reindex', action='store_true', help='Rebuild index only, no import')
    args = parser.parse_args()

    IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    if args.reindex:
        idx = build_index()
        print(f'Index rebuilt: {len(idx["all"])} images, '
              f'{len(idx["by_pano"])} pano associations, '
              f'{len(idx["unassociated"])} unassociated with GPS.')
        return

    if not args.drop_dir:
        parser.print_help()
        sys.exit(1)

    drop = Path(args.drop_dir)
    if not drop.is_dir():
        print(f'Error: {drop} is not a directory', file=sys.stderr)
        sys.exit(1)

    files = sorted(p for p in drop.iterdir()
                   if p.is_file() and p.suffix.lower() in IMAGE_EXTS)

    if not files:
        print(f'No image files found in {drop}')
        return

    print(f'Found {len(files)} image(s) in {drop}')
    imported = []
    for f in files:
        uid = import_image(f, move=args.move, dry_run=args.dry_run)
        if uid:
            imported.append(uid)

    if not args.dry_run:
        idx = build_index()
        print(f'\nImported {len(imported)} image(s). Index: {len(idx["all"])} total.')
    else:
        print(f'\nDry run: {len(imported)} would be imported.')


if __name__ == '__main__':
    main()
