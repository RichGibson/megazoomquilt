# how many tiles per zoom level? And size of resulting image. For a square image

for l in range(11):
    tile_cnt=4**l
    pixels=tile_cnt*256**2
    gigapixels=pixels/2**30
    print(f"{l=} tile_cnt={tile_cnt:,} pixels={pixels:,}\tgigapixels={gigapixels:,}")


