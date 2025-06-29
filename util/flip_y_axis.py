import os
from pathlib import Path
import shutil

def flip_y_tiles(input_dir, output_dir):
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for z_dir in input_dir.iterdir():
        if not z_dir.is_dir():
            continue
        z = z_dir.name

        # Find max Y per zoom level
        max_y = 0
        for x_dir in z_dir.iterdir():
            if not x_dir.is_dir():
                continue
            for tile_file in x_dir.glob("*.png"):
                try:
                    y = int(tile_file.stem)
                    if y > max_y:
                        max_y = y
                except ValueError:
                    continue
            for tile_file in x_dir.glob("*.jpg"):
                try:
                    y = int(tile_file.stem)
                    if y > max_y:
                        max_y = y
                except ValueError:
                    continue

        # Flip tiles
        for x_dir in z_dir.iterdir():
            if not x_dir.is_dir():
                continue
            x = x_dir.name
            for tile_file in x_dir.glob("*.*"):
                ext = tile_file.suffix
                try:
                    y = int(tile_file.stem)
                except ValueError:
                    continue
                new_y = max_y - y
                dest_dir = output_dir / z / x
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest_path = dest_dir / f"{new_y}{ext}"
                print(f"Moving {tile_file} → {dest_path}")
                shutil.copy2(tile_file, dest_path)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Flip Y-axis in tile sets")
    parser.add_argument("input_dir", help="Input tileset directory")
    parser.add_argument("output_dir", help="Output directory for corrected tiles")
    args = parser.parse_args()

    flip_y_tiles(args.input_dir, args.output_dir)

