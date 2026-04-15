#!/usr/bin/env python3
"""
Replace black background regions with a smooth extension of image content.

For each black pixel the nearest real-image boundary is found in each of the
four cardinal directions.  Content pixels along that boundary are averaged
within a sliding window to produce a fill color.  When a pixel is reachable
from multiple directions (e.g. corners) the fills are blended weighted by
inverse distance to each boundary.  A final Gaussian blur on the filled region
softens any remaining blockiness.

This is intentionally NOT reconstruction — it just extends edge colors inward
so that wide panoramas with quadtree padding look more balanced than solid black.

Usage:
    python3 util/fill_black.py static/panos/8585/8585_thumb.jpg
    python3 util/fill_black.py image.jpg --out /tmp/filled.jpg
    python3 util/fill_black.py image.jpg --window 80 --blur 15
    python3 util/fill_black.py image.jpg --threshold 20
    python3 util/fill_black.py --pano 8585            # fills pano thumbnail in-place
"""

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

BASE_DIR = Path(__file__).resolve().parent.parent / "static" / "panos"


# ── Helpers ───────────────────────────────────────────────────────────────────

def black_mask(arr, threshold):
    """Boolean (H,W) mask: True where all RGB channels ≤ threshold."""
    return (arr[:, :, 0] <= threshold) & \
           (arr[:, :, 1] <= threshold) & \
           (arr[:, :, 2] <= threshold)


def boundary_avg(pixels_1d, mask_1d, pos, window):
    """
    Average of non-masked pixels within ±window//2 of position `pos`
    along a 1-D slice.  pixels_1d: (N,3), mask_1d: (N,) bool.
    Returns (3,) float color.
    """
    N = len(pixels_1d)
    half = window // 2
    lo, hi = max(0, pos - half), min(N, pos + half + 1)
    good = pixels_1d[lo:hi][~mask_1d[lo:hi]]
    return good.mean(axis=0).astype(float) if len(good) else pixels_1d[pos].astype(float)


def sample_color(arr, mask, y_b, x, window, depth, depth_range, H, W, vertical=True):
    """
    Sample fill color for a boundary at y_b (vertical=True) or x_b (vertical=False).
    Skips `depth` pixels into the content before sampling, then averages
    `depth_range` rows/cols to get a stable, artifact-free color.
    """
    colors = []
    for d in range(depth, depth + depth_range):
        if vertical:
            sy = min(y_b + d, H - 1) if d >= 0 else max(y_b + d, 0)
            if mask[sy, x]:
                continue
            colors.append(boundary_avg(arr[sy, :], mask[sy, :], x, window))
        else:
            sx = min(y_b + d, W - 1) if d >= 0 else max(y_b + d, 0)
            if mask[x, sx]:
                continue
            colors.append(boundary_avg(arr[:, sx], mask[:, sx], x, window))
    if colors:
        return np.mean(colors, axis=0)
    # Fallback to exact boundary row
    if vertical:
        return boundary_avg(arr[y_b, :], mask[y_b, :], x, window)
    else:
        return boundary_avg(arr[:, y_b], mask[:, y_b], x, window)


# ── Per-edge fill ─────────────────────────────────────────────────────────────

def fill_top(arr, mask, window, depth, depth_range):
    H, W, _ = arr.shape
    fill = np.zeros((H, W, 3), dtype=float)
    dist = np.full((H, W), np.inf)

    content_exists = (~mask).any(axis=0)
    boundary = np.argmax(~mask, axis=0)
    boundary[~content_exists] = -1

    for x in range(W):
        y_b = boundary[x]
        if y_b <= 0:
            continue
        black_ys = np.where(mask[:y_b, x])[0]
        if len(black_ys) == 0:
            continue
        color = sample_color(arr, mask, y_b, x, window, depth, depth_range, H, W, vertical=True)
        fill[black_ys, x] = color
        dist[black_ys, x] = y_b - black_ys

    return fill, dist


def fill_bottom(arr, mask, window, depth, depth_range):
    H, W, _ = arr.shape
    fill = np.zeros((H, W, 3), dtype=float)
    dist = np.full((H, W), np.inf)

    content_exists = (~mask).any(axis=0)
    boundary = H - 1 - np.argmax(~mask[::-1, :], axis=0)
    boundary[~content_exists] = -1

    for x in range(W):
        y_b = boundary[x]
        if y_b < 0 or y_b >= H - 1:
            continue
        black_ys = np.where(mask[y_b + 1:, x])[0] + y_b + 1
        if len(black_ys) == 0:
            continue
        # For bottom, depth goes upward (negative direction)
        color = sample_color(arr, mask, y_b, x, window, -depth, depth_range, H, W, vertical=True)
        fill[black_ys, x] = color
        dist[black_ys, x] = black_ys - y_b

    return fill, dist


def fill_left(arr, mask, window, depth, depth_range):
    H, W, _ = arr.shape
    fill = np.zeros((H, W, 3), dtype=float)
    dist = np.full((H, W), np.inf)

    content_exists = (~mask).any(axis=1)
    boundary = np.argmax(~mask, axis=1)
    boundary[~content_exists] = -1

    for y in range(H):
        x_b = boundary[y]
        if x_b <= 0:
            continue
        black_xs = np.where(mask[y, :x_b])[0]
        if len(black_xs) == 0:
            continue
        color = sample_color(arr, mask, x_b, y, window, depth, depth_range, H, W, vertical=False)
        fill[y, black_xs] = color
        dist[y, black_xs] = x_b - black_xs

    return fill, dist


def fill_right(arr, mask, window, depth, depth_range):
    H, W, _ = arr.shape
    fill = np.zeros((H, W, 3), dtype=float)
    dist = np.full((H, W), np.inf)

    content_exists = (~mask).any(axis=1)
    boundary = W - 1 - np.argmax(~mask[:, ::-1], axis=1)
    boundary[~content_exists] = -1

    for y in range(H):
        x_b = boundary[y]
        if x_b < 0 or x_b >= W - 1:
            continue
        black_xs = np.where(mask[y, x_b + 1:])[0] + x_b + 1
        if len(black_xs) == 0:
            continue
        color = sample_color(arr, mask, x_b, y, window, -depth, depth_range, H, W, vertical=False)
        fill[y, black_xs] = color
        dist[y, black_xs] = black_xs - x_b

    return fill, dist


# ── Main fill ─────────────────────────────────────────────────────────────────

def fill_black_regions(img, threshold=15, window=120, blur=25, depth=8, depth_range=15):
    """
    Returns a new PIL Image with black regions filled.

    threshold   : per-channel max value considered black
    window      : sliding window half-width in pixels for boundary sampling
    blur        : Gaussian blur radius applied to filled regions (0 = no blur)
    depth       : rows/cols to skip inward from boundary before sampling
                  (avoids JPEG artifacts at the stitch edge)
    depth_range : number of rows/cols to average for the fill color
                  (more rows = more stable, smoother color estimate)
    """
    arr = np.array(img.convert("RGB"), dtype=np.uint8)
    H, W = arr.shape[:2]
    mask = black_mask(arr, threshold)

    total_black = int(mask.sum())
    if total_black == 0:
        print("  No black pixels found — nothing to fill.")
        return img

    print(f"  Black pixels: {total_black:,} of {H*W:,} ({100*total_black/(H*W):.1f}%)")

    edge_fns = [
        ('top',    fill_top),
        ('bottom', fill_bottom),
        ('left',   fill_left),
        ('right',  fill_right),
    ]

    fills, weights = [], []
    for name, fn in edge_fns:
        f, d = fn(arr, mask, window, depth, depth_range)
        w = np.where(np.isfinite(d), 1.0 / np.maximum(d, 0.5), 0.0)
        fills.append(f)
        weights.append(w)
        covered = int((np.isfinite(d) & mask).sum())
        print(f"  {name:6s}: {covered:,} black pixels covered")

    total_w = sum(weights)                    # (H, W)
    covered_mask = mask & (total_w > 0)

    uncovered = int((mask & ~covered_mask).sum())
    if uncovered:
        print(f"  WARNING: {uncovered:,} black pixels not reachable from any edge (left black)")

    # Inverse-distance weighted blend
    blended = np.zeros((H, W, 3), dtype=float)
    for f, w in zip(fills, weights):
        blended += f * w[:, :, np.newaxis]

    total_w3 = np.maximum(total_w[:, :, np.newaxis], 1e-9)
    blended  = np.clip(blended / total_w3, 0, 255).astype(np.uint8)

    result = arr.copy()
    result[covered_mask] = blended[covered_mask]

    out_img = Image.fromarray(result)

    # Blur filled region and feather it back into the original at the boundary
    if blur > 0:
        blurred_arr = np.array(out_img.filter(ImageFilter.GaussianBlur(radius=blur)))
        mask_img   = Image.fromarray((covered_mask * 255).astype(np.uint8))
        soft_mask  = np.array(mask_img.filter(ImageFilter.GaussianBlur(radius=blur // 2))) / 255.0
        soft_3d    = soft_mask[:, :, np.newaxis]
        result     = np.clip(blurred_arr * soft_3d + result * (1 - soft_3d), 0, 255).astype(np.uint8)
        out_img    = Image.fromarray(result)
        print(f"  Blur r={blur} applied to filled regions")

    return out_img


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Fill black panorama padding with a smooth extension of image content."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("image", nargs="?", type=Path,
                       help="Image file to process")
    group.add_argument("--pano", metavar="ID",
                       help="Process static/panos/<ID>/<ID>_thumb.jpg in-place")
    parser.add_argument("--out", type=Path, default=None,
                        help="Output path (default: overwrite input)")
    parser.add_argument("--threshold", type=int, default=15,
                        help="Per-channel max to be considered black (default: 15)")
    parser.add_argument("--window", type=int, default=120,
                        help="Sliding window half-width for boundary sampling in px (default: 120)")
    parser.add_argument("--blur", type=int, default=25,
                        help="Gaussian blur radius on filled regions (default: 25, 0=off)")
    parser.add_argument("--depth", type=int, default=8,
                        help="Rows/cols to skip inward from boundary before sampling (default: 8)")
    parser.add_argument("--depth-range", type=int, default=15,
                        help="Number of rows/cols to average for fill color (default: 15)")
    parser.add_argument("--quality", type=int, default=92,
                        help="JPEG output quality (default: 92)")
    args = parser.parse_args()

    if args.pano:
        in_path = BASE_DIR / args.pano / f"{args.pano}_thumb.jpg"
    else:
        in_path = args.image

    if not in_path.exists():
        print(f"ERROR: file not found: {in_path}", file=sys.stderr)
        return 1

    out_path = args.out or in_path
    print(f"Input:  {in_path}")
    print(f"Output: {out_path}")

    Image.MAX_IMAGE_PIXELS = None  # disable decompression bomb guard for large panos
    img = Image.open(in_path)
    print(f"Size: {img.width}×{img.height}")

    result = fill_black_regions(img, args.threshold, args.window, args.blur,
                                args.depth, args.depth_range)

    out_suffix = (args.out or in_path).suffix.lower()
    if out_suffix in (".jpg", ".jpeg"):
        result.save(out_path, format="JPEG", quality=args.quality)
    else:
        result.save(out_path)

    kb = out_path.stat().st_size // 1024
    print(f"Saved: {out_path} ({kb} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
