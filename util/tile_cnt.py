# how many tiles at a given level assuming 
# we have a width x height

import math

width=22556
height=6000

w = math.ceil(width/256)
h = math.ceil(height/256)

print(f"{width/256=}")
print(f"{height/256=}")
print(f"{w=} {h=} total {h*w}")
