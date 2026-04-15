#!/usr/bin/env python3
"""
Reconstruct a full-resolution lossless image from a pano's tile set.

Uses GDAL (gdal_translate) as the primary path — fully streaming, handles any
image size without loading it into memory.  Falls back to Pillow row-by-row
compositing when GDAL is not available (see memory warning below).

Output format:
  TIFF with LZW compression (default) — lossless, BigTIFF mode when > 4 GB
  PNG — lossless but limited to ~4 GB uncompressed; avoid for large panos

The output is cropped to the actual image dimensions (W×H from the JSON),
removing the black quadtree padding that fills out the power-of-two tile grid.

Usage:
    python3 util/reconstruct.py <pano_id>
    python3 util/reconstruct.py <pano_id> --out /tmp/output.tif
    python3 util/reconstruct.py <pano_id> --format png
    python3 util/reconstruct.py <pano_id> --zoom 6        # lower zoom = smaller file
    python3 util/reconstruct.py <pano_id> --no-crop       # keep quadtree padding
    python3 util/reconstruct.py <pano_id> --compression deflate

Memory note (Pillow fallback):
    Without GDAL the script composites one tile-row at a time but must hold the
    final image in RAM before saving.  For images > ~1 GP (gigapixels) this can
    exceed 3 GB of RAM.  Install GDAL to avoid this: brew install gdal
"""

import argparse
import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BASE_DIR  = Path(__file__).resolve().parent.parent / "static" / "panos"
TILE_SIZE = 256
LARGE_MPIX_WARNING = 500   # warn when output exceeds this many megapixels


# ── Helpers ───────────────────────────────────────────────────────────────────

def has_gdal():
    return shutil.which("gdal_translate") is not None


def tile_grid(W, H, levels, zoom):
    """Return (cols, rows, full_w, full_h) for the given zoom level."""
    max_zoom = levels - 1
    scale    = 2 ** (max_zoom - zoom)
    full_w   = max(1, int(W / scale))
    full_h   = max(1, int(H / scale))
    cols     = math.ceil(full_w / TILE_SIZE)
    rows     = math.ceil(full_h / TILE_SIZE)
    return cols, rows, full_w, full_h


def count_existing_tiles(pano_dir, zoom, cols, rows, img_ext):
    total = cols * rows
    found = sum(
        1 for x in range(cols) for y in range(rows)
        if (pano_dir / str(zoom) / str(x) / f"{y}{img_ext}").exists()
    )
    return found, total


# ── GDAL path ─────────────────────────────────────────────────────────────────

def build_vrt(pano_dir, zoom, cols, rows, img_ext, vrt_path, crop_w, crop_h, no_crop):
    """
    Write a GDAL VRT file that mosaics all tiles at the given zoom level.
    Absolute tile paths are used so the VRT can sit anywhere.
    """
    vrt_W = cols * TILE_SIZE
    vrt_H = rows * TILE_SIZE

    lines = [
        f'<VRTDataset rasterXSize="{vrt_W}" rasterYSize="{vrt_H}">',
    ]

    band_labels = {1: "Red", 2: "Green", 3: "Blue"}
    for band in range(1, 4):
        lines.append(f'  <VRTRasterBand dataType="Byte" band="{band}">')
        lines.append(f'    <ColorInterp>{band_labels[band]}</ColorInterp>')

        for x in range(cols):
            for y in range(rows):
                tp = pano_dir / str(zoom) / str(x) / f"{y}{img_ext}"
                if not tp.exists():
                    continue
                lines += [
                    f'    <SimpleSource>',
                    f'      <SourceFilename relativeToVRT="0">{tp.resolve()}</SourceFilename>',
                    f'      <SourceBand>{band}</SourceBand>',
                    f'      <SourceProperties RasterXSize="{TILE_SIZE}" RasterYSize="{TILE_SIZE}"'
                    f' DataType="Byte" BlockXSize="{TILE_SIZE}" BlockYSize="{TILE_SIZE}" />',
                    f'      <SrcRect xOff="0" yOff="0" xSize="{TILE_SIZE}" ySize="{TILE_SIZE}" />',
                    f'      <DstRect xOff="{x*TILE_SIZE}" yOff="{y*TILE_SIZE}"'
                    f' xSize="{TILE_SIZE}" ySize="{TILE_SIZE}" />',
                    f'    </SimpleSource>',
                ]

        lines.append(f'  </VRTRasterBand>')

    lines.append('</VRTDataset>')

    vrt_path.write_text("\n".join(lines))
    print(f"  VRT written: {vrt_path}")


def reconstruct_gdal(pano_dir, zoom, cols, rows, img_ext,
                     W, H, out_path, fmt, compression, no_crop):
    """Reconstruct via GDAL VRT + gdal_translate."""
    with tempfile.TemporaryDirectory(prefix="mzq_recon_") as tmp:
        vrt_path = Path(tmp) / "mosaic.vrt"
        build_vrt(pano_dir, zoom, cols, rows, img_ext, vrt_path, W, H, no_crop)

        cmd = ["gdal_translate"]

        if not no_crop:
            # Crop to actual content dimensions, stripping quadtree padding
            cmd += ["-srcwin", "0", "0", str(W), str(H)]

        if fmt == "tiff":
            cmd += [
                "-of", "GTiff",
                "-co", f"COMPRESS={compression.upper()}",
                "-co", "TILED=YES",
                "-co", "BIGTIFF=IF_SAFER",
            ]
            if compression.lower() in ("lzw", "deflate"):
                cmd += ["-co", "PREDICTOR=2"]
        elif fmt == "png":
            cmd += ["-of", "PNG"]
        else:
            cmd += ["-of", fmt.upper()]

        cmd += [str(vrt_path), str(out_path)]

        print(f"  Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"gdal_translate failed (exit {result.returncode})")


# ── Pillow fallback ───────────────────────────────────────────────────────────

def reconstruct_pillow(pano_dir, zoom, cols, rows, img_ext,
                       W, H, out_path, fmt, no_crop):
    """
    Reconstruct via Pillow, compositing one tile-row at a time.
    Holds the complete output image in RAM — see memory warning in module docstring.
    """
    try:
        from PIL import Image
    except ImportError:
        raise RuntimeError("Pillow is required for the fallback path: pip install Pillow")

    Image.MAX_IMAGE_PIXELS = None  # disable decompression-bomb guard for large panos

    out_w = W  if not no_crop else cols * TILE_SIZE
    out_h = H  if not no_crop else rows * TILE_SIZE
    mpix  = out_w * out_h / 1e6

    if mpix > LARGE_MPIX_WARNING:
        print(f"  WARNING: output is {mpix:.0f} MP ({out_w*out_h*3/1e9:.1f} GB uncompressed).")
        print(f"  Consider installing GDAL for out-of-core processing: brew install gdal")

    print(f"  Compositing {cols}×{rows} tile grid into {out_w}×{out_h} image...")
    canvas = Image.new("RGB", (out_w, out_h))

    loaded = 0
    for row in range(rows):
        for col in range(cols):
            tp = pano_dir / str(zoom) / str(col) / f"{row}{img_ext}"
            if not tp.exists():
                continue
            tile = Image.open(tp).convert("RGB")
            dst_x = col * TILE_SIZE
            dst_y = row * TILE_SIZE
            # Crop tile to canvas bounds (edge tiles may overlap the content boundary)
            paste_w = min(tile.width,  out_w - dst_x)
            paste_h = min(tile.height, out_h - dst_y)
            if paste_w > 0 and paste_h > 0:
                canvas.paste(tile.crop((0, 0, paste_w, paste_h)), (dst_x, dst_y))
            loaded += 1
        if (row + 1) % 10 == 0 or row == rows - 1:
            print(f"    row {row+1}/{rows} ({loaded} tiles so far)")

    print(f"  Saving {out_path} ...")
    save_kwargs = {}
    if fmt == "tiff":
        save_kwargs = {"format": "TIFF", "compression": "tiff_lzw"}
    elif fmt == "png":
        save_kwargs = {"format": "PNG", "compress_level": 6}
    canvas.save(out_path, **save_kwargs)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Reconstruct a full-resolution lossless image from a pano's tiles."
    )
    parser.add_argument("pano_id", help="Pano ID")
    parser.add_argument(
        "--zoom", type=int, default=None,
        help="Zoom level to reconstruct (default: max zoom = full resolution)"
    )
    parser.add_argument(
        "--out", default=None,
        help="Output file path (default: static/panos/{id}/{id}_full.tif)"
    )
    parser.add_argument(
        "--format", choices=["tiff", "png"], default="tiff",
        help="Output format: tiff (default, lossless LZW) or png"
    )
    parser.add_argument(
        "--compression", choices=["lzw", "deflate", "none"], default="lzw",
        help="TIFF compression (default: lzw). Ignored for PNG."
    )
    parser.add_argument(
        "--no-crop", action="store_true",
        help="Keep quadtree black padding; do not crop to image dimensions"
    )
    parser.add_argument(
        "--force-pillow", action="store_true",
        help="Use Pillow even if GDAL is available (for testing)"
    )
    args = parser.parse_args()

    pano_dir  = BASE_DIR / args.pano_id
    json_path = pano_dir / f"{args.pano_id}.json"

    if not json_path.exists():
        print(f"ERROR: JSON not found at {json_path}", file=sys.stderr)
        return 1

    with open(json_path) as f:
        meta = json.load(f).get("gigapan", {})

    W       = int(meta["width"])
    H       = int(meta["height"])
    levels  = int(meta.get("levels", 1))
    img_ext = "." + meta.get("img_type", "jpg")
    zoom    = args.zoom if args.zoom is not None else levels - 1

    if zoom < 0 or zoom >= levels:
        print(f"ERROR: zoom {zoom} out of range 0–{levels-1}", file=sys.stderr)
        return 1

    cols, rows, full_w, full_h = tile_grid(W, H, levels, zoom)

    # At the requested zoom level, W/H scale proportionally
    scale = 2 ** ((levels - 1) - zoom)
    out_w = max(1, int(W / scale))
    out_h = max(1, int(H / scale))

    print(f"Pano {args.pano_id}: {W}×{H}, {levels} levels")
    print(f"Zoom {zoom}: {cols}×{rows} tile grid → {out_w}×{out_h} content px")

    # Check tiles exist locally
    found, total = count_existing_tiles(pano_dir, zoom, cols, rows, img_ext)
    if found == 0:
        print(f"ERROR: no local tiles found at zoom {zoom} in {pano_dir}", file=sys.stderr)
        print(f"  This tool requires local tiles; remote-only panos are not supported.", file=sys.stderr)
        return 1
    if found < total:
        print(f"  WARNING: only {found}/{total} tiles present — missing tiles will be black.")

    # Choose output path
    ext      = "tif" if args.format == "tiff" else "png"
    out_path = Path(args.out) if args.out else pano_dir / f"{args.pano_id}_full.{ext}"

    size_gb = out_w * out_h * 3 / 1e9
    print(f"Output: {out_path}  (~{size_gb:.1f} GB uncompressed before compression)")

    use_gdal = has_gdal() and not args.force_pillow
    print(f"Backend: {'GDAL (gdal_translate)' if use_gdal else 'Pillow (fallback)'}")

    if not use_gdal and size_gb > 3:
        print(f"  WARNING: {size_gb:.1f} GB image via Pillow will require ~{size_gb:.0f} GB RAM.")
        print(f"  Install GDAL for streaming out-of-core processing: brew install gdal")

    if use_gdal:
        reconstruct_gdal(
            pano_dir, zoom, cols, rows, img_ext,
            out_w, out_h, out_path, args.format, args.compression, args.no_crop
        )
    else:
        reconstruct_pillow(
            pano_dir, zoom, cols, rows, img_ext,
            out_w, out_h, out_path, args.format, args.no_crop
        )

    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"Done: {out_path}  ({size_mb:.1f} MB on disk)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
