# change google maps level/y/x.jpg tiles to osm level/x/y.jpg format.

import click
import shutil
from pathlib import Path
import pdb

@click.command()
@click.argument('src', type=str)
@click.argument('dst', type=str)
def reorganize_tiles(src, dst):
    src_root = Path(src)
    dest_root = Path(dst)

    if not src_root.exists():
        print(f"Source directory does not exist: {src_root}")
        return

    for z_dir in src_root.iterdir():
        if not z_dir.is_dir():
            continue
        z = z_dir.name

        for y_dir in z_dir.iterdir():
            if not y_dir.is_dir():
                continue
            y = y_dir.name

            for tile_file in y_dir.iterdir():
                if tile_file.is_file() and tile_file.suffix in [".jpg", ".png"]:
                    x = tile_file.stem
                    new_tile_path = dest_root / z / x
                    new_tile_path.mkdir(parents=True, exist_ok=True)
                    dest_file = new_tile_path / f"{y}{tile_file.suffix}"
                    print(f"Moving {tile_file} → {dest_file}")
                    shutil.move(tile_file, dest_file)

    pdb.set_trace()

if __name__ == "__main__":
    reorganize_tiles()

