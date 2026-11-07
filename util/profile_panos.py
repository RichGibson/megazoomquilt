"""
List a profile's panos with dimensions, uncompressed size, and download status.
Writes profiles/<slug>/<slug>_panos.csv and .md.

Size MB = width x height x 3 bytes (24-bit RGB, uncompressed) / 1,000,000.

Usage:
    python3 util/profile_panos.py jay
"""
import csv, json, math, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def tile_counts(pid):
    d = ROOT / "static" / "panos" / str(pid)
    jp = d / f"{pid}.json"
    here = exp = 0
    if jp.exists():
        g = json.load(open(jp)).get("gigapan", {})
        W, H, L = int(g.get("width", 0)), int(g.get("height", 0)), int(g.get("levels", 0))
        if W and H and L:
            exp = sum(math.ceil(max(1, W // 2**(L-1-z)) / 256) * math.ceil(max(1, H // 2**(L-1-z)) / 256) for z in range(L))
    if d.is_dir():
        for e in os.scandir(d):
            if e.is_dir() and e.name.isdigit():
                for _, _, fs in os.walk(e.path):
                    here += sum(f.lower().endswith((".jpg", ".jpeg", ".png")) for f in fs)
    return here, exp

def main(slug):
    pdir = ROOT / "profiles" / slug
    panos = sorted(json.load(open(pdir / "gigapan_list.json")), key=lambda x: x["id"])
    rows = []
    for p in panos:
        w, h = int(p.get("width") or 0), int(p.get("height") or 0)
        here, exp = tile_counts(p["id"])
        status = "yes" if exp and here >= exp else ("partial" if here else "no")
        rows.append({"id": p["id"], "name": (p.get("name") or "").strip(),
                     "taken": (p.get("taken_at") or "")[:10], "width": w, "height": h,
                     "megapixels": round(w * h / 1e6, 1), "size_mb": round(w * h * 3 / 1e6, 1),
                     "downloaded": status, "tiles_here": here, "tiles_expected": exp})
    with open(pdir / f"{slug}_panos.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]))
        wr.writeheader(); wr.writerows(rows)
    n = {s: sum(r["downloaded"] == s for r in rows) for s in ("yes", "partial", "no")}
    tot = sum(r["size_mb"] for r in rows)
    md = [f"# {slug}'s panos", "",
          f"{len(rows)} panos — downloaded: {n['yes']} yes, {n['partial']} partial, {n['no']} no. "
          f"Total uncompressed size: {tot:,.0f} MB ({tot/1000:,.1f} GB).", "",
          "Size MB = width × height × 3 bytes (uncompressed 24-bit RGB) ÷ 1,000,000.", "",
          "| ID | Name | Taken | Dimensions | MP | Size MB | Downloaded | Tiles |",
          "|---|---|---|---|---:|---:|---|---|"]
    for r in rows:
        name = r["name"].replace("|", "\\|")
        tiles = f"{r['tiles_here']:,}/{r['tiles_expected']:,}" if r["tiles_expected"] else "—"
        md.append(f"| {r['id']} | {name} | {r['taken']} | {r['width']:,} × {r['height']:,} | "
                  f"{r['megapixels']:,} | {r['size_mb']:,} | {r['downloaded']} | {tiles} |")
    (pdir / f"{slug}_panos.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "jay")
