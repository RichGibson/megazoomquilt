# What thumbnail() does and why

##   The problem it solves

  A panorama can be 60,000 × 13,000 pixels. You can't serve that as a thumbnail. But the image isn't stored as a single
  file -- it's stored as a quadtree pyramid of 256×256 tiles. The thumbnail function has to assemble a small preview
  entirely from those tiles, on demand, without loading the full-resolution image.

  ---
##   Stage 1: Cache check (lines 271-276)

  Before doing any work, it looks for <id>_thumb.webp on disk. If it exists, serve it immediately -- all the expensive
  work below only happens once per pano. The legacy .jpg fallback handles thumbnails that were generated before the app
  switched to WebP.

  ---
## Stage 2: Zoom level selection (lines 282-300)

  This is the trickiest part. The tile pyramid has multiple zoom levels. At zoom 0 there's one tile covering the whole
  panorama -- low resolution but only 1 tile to fetch. At the maximum zoom level, there might be thousands of tiles. The
   function needs to find the sweet spot: enough resolution to be useful, few enough tiles to be fast.

  It walks up the zoom levels starting at 1, computing at each level:
  - scale = 2^(max_zoom - z) -- how many full-resolution pixels each tile pixel represents at this zoom
  - cw, ch -- the content dimensions in pixels at this zoom level
  - cols, rows -- how many tiles are needed to cover that content

  Two stopping conditions:
  1. Too many tiles: if cols * rows > THUMB_MAX_TILES (16), stop and use the previous level. Prevents fetching dozens of
   tiles for a huge pano.
  2. Good enough resolution: if the shorter side is at least THUMB_MIN_DIM (128px), stop here. No point going to a
  higher zoom than needed.

  The result is the shallowest zoom that's still usable, capped at 16 tiles total.

  ---
## Stage 3: Content bounds (lines 305-309)

  Tile pyramids are quadtrees. Each zoom level doubles in both dimensions, so the grid is always a power-of-two square.
  A panorama that's 4:1 aspect ratio still has a square tile grid -- the right portion is just black padding. The actual
   content width and height at the chosen zoom (content_w, content_h) are computed from the original pixel dimensions
  divided by the scale factor. This tells us how many columns and rows of tiles actually contain image data.

  ---
##  Stage 4: Tile assembly -- two paths (lines 313-365)

  Remote tiles (tile_base_url is set): The pano's tiles live on a remote server (e.g. the original Gigapan CDN). Each
  tile is fetched over HTTP with a proper User-Agent header. Tile (0,0) is fetched first to establish the actual tile
  dimensions in pixels -- the code can't assume 256×256 because some servers use different sizes. A blank canvas is
  created at cols * tile_w × rows * tile_h, and tiles are pasted into it. If tile (0,0) fails, there's nothing to do and
   we 404.

  Local tiles (no tile_base_url): Tiles are on disk at static/panos/<id>/<zoom>/<x>/<y>.ext. The extension is discovered
   by scanning the directory rather than assumed, because some panos use PNG (notably pano 190938 which was tiled with
  gdal2tiles). Same compositing approach: blank canvas, paste each tile at its grid position. Missing tiles are simply
  skipped rather than erroring -- they leave a black gap, which is acceptable.

  ---
##  Stage 5: Crop (lines 368-370)

  After compositing, the image is cols * tile_w × rows * tile_h -- which is slightly larger than the actual content
  because tile grid dimensions are rounded up to whole tiles. The crop trims it to content_w × content_h, removing the
  black quadtree padding on the right and bottom edges.

  ---
##  Stage 6: Save and serve (lines 373-380)

  The final image is saved to disk as WebP at quality 85. On the next request, Stage 1 catches it immediately. If the
  disk write fails for any reason (permissions, disk full), it falls back to writing into an in-memory BytesIO buffer
  and serving from there -- the thumbnail won't be cached for next time, but the request still succeeds.

