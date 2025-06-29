import click
import os
import requests
import time
from xml.dom import minidom
from pathlib import Path
import pdb
import math
import json

import sys

def download_metadata(fmt,photo_id, output_dir):
    path = output_dir / f"{photo_id}.{fmt}"
    if path.exists():
        print(f"{fmt} file already exists: {path}")
        with open(path, 'r', encoding='utf-8') as f:
            data = f.read()
    else:
        url = f"http://www.gigapan.com/gigapans/{photo_id}.{fmt}"
        try:
            response = requests.get(url)
            data = response.content
            path.write_bytes(data)
            print(f"{fmt} saved to: {path}")
        except Exception as e:
            print(f"Failed to download {fmt}: {e}")
            return None

    # todo: error check when the json is empty
    if fmt=='json':
        if len(data) > 100:
            data = json.loads(data)
            data=data['gigapan']
        else:
            data=None

    return data

def parse_kml(kml_data):
    dom = minidom.parseString(str(kml_data))
    width = int(dom.getElementsByTagName("maxWidth")[0].firstChild.data)
    height = int(dom.getElementsByTagName("maxHeight")[0].firstChild.data)
    tile_width = int(dom.getElementsByTagName("tileSize")[0].firstChild.data)
    tile_height = int(dom.getElementsByTagName("tileSize")[0].firstChild.data)
    return width, height, tile_width, tile_height

def is_valid_jpeg(data):
    return data.startswith(b'\xff\xd8') and data.endswith(b'\xff\xd9')


def get_tile_dimensions(pano_width, pano_height, level,  max_level, tile_size=256):
    """
    Compute number of tiles in x and y directions at a specific quadtree zoom level.
    """
    
    scale = 2 ** (max_level - level)

    level_width = pano_width / scale
    level_height = pano_height / scale

    tiles_x = math.ceil(level_width / tile_size)
    tiles_y = math.ceil(level_height / tile_size)
    print(f'{pano_width=}, {pano_height=}, {level=}, {max_level=} {level_width=} {level_height=} {tiles_x=} {tiles_y=}')

    return tiles_x, tiles_y

def safe_request(url, retries=3, timeout=10):
    for attempt in range(retries):
        try:
            return requests.get(url, timeout=timeout)
        except requests.RequestException as e:
            print(f"Attempt {attempt + 1} failed for {url}: {e}")
            time.sleep(2 ** attempt)
    return None

def download_tile(photo_id, level, col, row, output_dir):
    # gigapan get_ge_tile format is http://gigapan.com/get_ge_tile/$[id]/$[level]/$[y]/$[x]
    # OSM is level/x/y.jpg
    # Read level/row/col write level/col/row.jpg
    tile_url = f"http://www.gigapan.com/get_ge_tile/{photo_id}/{level}/{row}/{col}"
    tile_path = Path(output_dir) / f"{level}/{col}/{row}.jpg"

    tile_path.parent.mkdir(parents=True, exist_ok=True)

    

    if tile_path.exists():
        print(f"Tile already exists: {tile_path}")
        return tile_path

    try:
        print(f"Downloading tile: {tile_url=}\t{tile_path}")
        response = safe_request(tile_url)
        content = response.content

        #if is_valid_jpeg(content) and len(content) > 1000:  # Basic size sanity check
        if is_valid_jpeg(content) :  # Basic size sanity check
            tile_path.parent.mkdir(parents=True, exist_ok=True)
            with open(tile_path, 'wb') as f:
                f.write(content)
        else:
            raise Exception(f"Invalid or too small JPEG file {tile_path}.")
    except Exception as e:
        print(f"Failed to download {tile_url}: {e}")
        missing_path = Path(output_dir) / "missing_tiles.txt"
        with open(missing_path, 'a') as f:
            f.write(f"{level}/{row}/{col}.jpg\n")

"""
cols and rows are reversed, but when I try and fetch in what I think is the right way
I get logs of not found tiles.

Not found:
http://www.gigapan.com/get_ge_tile/606/4/14/0

Flip it and it is found. but maybe I already broke/fixed this. I am in 100 monkeys programming territory now
http://www.gigapan.com/get_ge_tile/606/4/0/14
"""
def download_all_tiles(photo_id, output_dir, level=None):
    kml_data = download_metadata('kml',  photo_id, output_dir)
    json_data = download_metadata('json',photo_id, output_dir)

    if json_data is None:
        print(f"No json file for {photo_id=}")
        return

    if level is None:
        print('fetching all tiles')
        level=json_data['levels']-1
        for level in range(level+1):
            print(f'{level}')
            cols,rows = get_tile_dimensions(json_data['width'],json_data['height'],level,json_data['levels']-1)
            for row in range(rows):
                for col in range(cols):
                    download_tile(photo_id, level,  col,row,  output_dir)
        return

    if (level > json_data['levels']):
        level=json_data['levels']-1
        print(f'Passed level higher than this pano has, so level reset to {level}')
    
    cols,rows = get_tile_dimensions(json_data['width'],json_data['height'],level,json_data['levels']-1)
    print(f"{cols=} {rows=}")
    for row in range(rows):
        for col in range(cols):
            print(f"{col=} {row=} {output_dir=}")
            download_tile(photo_id, level, col, row,  output_dir)

@click.command()
@click.argument('photo_id', type=int)
@click.argument('zoom_level', required=False, type=int)
@click.option('-o', '--output', default='tiles', help='Output directory')

def main(photo_id, zoom_level, output):

    if output=='tiles':
        output=str(photo_id)

    output_dir = Path(output)

    output_dir.mkdir(parents=True, exist_ok=True)

    download_all_tiles(photo_id, output_dir, zoom_level)


main()

