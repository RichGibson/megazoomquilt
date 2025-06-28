import os
from pathlib import Path
from collections import defaultdict
import statistics
import pdb

def collect_tile_stats(base_dir):
    base_dir = Path(base_dir)
    results=[]
    stats = defaultdict(lambda: {
        "sizes": [],
        "x_values": set(),
        "y_values": set()
    })

    for root, _, files in os.walk(base_dir):
        for file in files:
            if file.lower().endswith((".jpg", ".png")):
                full_path = Path(root) / file
                try:
                    size = full_path.stat().st_size
                except Exception as e:
                    print(f"Could not read {full_path}: {e}")
                    continue

                try:
                    rel_parts = full_path.relative_to(base_dir).parts
                    level = rel_parts[0]
                    x = rel_parts[1]
                    y = Path(rel_parts[2]).stem  # remove .jpg/.png
                except Exception as e:
                    print(f"Invalid path structure: {full_path} — {e}")
                    continue

                data = stats[level]
                data["sizes"].append(size)
                data["x_values"].add(int(x))
                data["y_values"].add(int(y))

    print("\nTile Size Statistics by Level:")
    print(f"{'Level':<6} {'Count':>6} {'Min (B)':>10} {'Max (B)':>10} {'Avg (B)':>10} {'Cols':>6} {'Rows':>6}")
    for level in sorted(stats.keys(), key=lambda x: int(x)):
        data = stats[level]
        sizes = data["sizes"]
        count = len(sizes)
        min_size = min(sizes)
        max_size = max(sizes)
        avg_size = int(statistics.mean(sizes))
        cols = len(data["x_values"])
        rows = len(data["y_values"])
        print(f"{level:<6} {count:>6} {min_size:>10} {max_size:>10} {avg_size:>10} {cols:>6} {rows:>6}")
        results.append({
            "level": level,
            "count": count,
            "min_size": min_size,
            "max_size": max_size,
            "avg_size": avg_size,
            "cols": cols,
            "rows": rows
        })

    return results


# Example usage
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python tile_stats.py <directory>")
    else:
        results = collect_tile_stats(sys.argv[1])

    pdb.set_trace()
