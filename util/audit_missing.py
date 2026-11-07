import json, math, os, sys
from pathlib import Path
base = Path(sys.argv[1])
rows, nojson = [], []
for d in sorted(base.iterdir()):
    if not (d.is_dir() and d.name.isdigit()): continue
    pid = d.name; jp = d / f"{pid}.json"
    if not jp.exists(): nojson.append(pid); continue
    try:
        m = json.load(open(jp)).get("gigapan", {})
        W, H, L = int(m.get("width", 0)), int(m.get("height", 0)), int(m.get("levels", 0))
    except Exception:
        nojson.append(pid + " (bad json)"); continue
    if not (W and H and L): continue
    exp = sum(math.ceil(max(1, W // 2**(L-1-z)) / 256) * math.ceil(max(1, H // 2**(L-1-z)) / 256) for z in range(L))
    here = 0
    for e in d.iterdir():
        if e.is_dir() and e.name.isdigit():
            for _, _, fs in os.walk(e):
                here += sum(1 for f in fs if f.rsplit(".",1)[-1].lower() in ("jpg","jpeg","png"))
    if here < exp: rows.append((int(pid), here, exp - here))
rows.sort(key=lambda r: -r[2])
print("pano_id,tiles_here,tiles_missing")
for r in rows: print(f"{r[0]},{r[1]},{r[2]}")
print(f"# {len(rows)} panos missing {sum(r[2] for r in rows)} tiles; no JSON: {', '.join(nojson) or 'none'}", file=sys.stderr)
