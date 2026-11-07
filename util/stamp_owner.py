"""
Stamp an 'owner' profile slug into each pano's <id>.json (gigapan dict), so
ownership travels with the pano itself rather than depending on which
profiles/<slug>/gigapan_list.json catalog it came from.

Usage:
    python3 util/stamp_owner.py --profile molly --list profiles/molly/gigapan_list.json
    python3 util/stamp_owner.py --profile jay   --list profiles/jay/gigapan_list.json
    python3 util/stamp_owner.py --profile rich  --all
"""
import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PANOS_DIR_DEFAULT = ROOT / "static" / "panos"
PROFILES_DIR = ROOT / "profiles"


def backup_json(json_path: Path):
    """Copy id.json -> id.bak, then id.bk1, id.bk2 ... if .bak already exists."""
    bak = json_path.with_suffix('.bak')
    if not bak.exists():
        shutil.copy2(json_path, bak)
        return
    n = 1
    while True:
        numbered = json_path.with_suffix(f'.bk{n}')
        if not numbered.exists():
            shutil.copy2(json_path, numbered)
            return
        n += 1


def other_profile_ids(exclude_slug):
    """IDs claimed by any profile's gigapan_list.json other than exclude_slug."""
    ids = set()
    for list_path in PROFILES_DIR.glob('*/gigapan_list.json'):
        if list_path.parent.name == exclude_slug:
            continue
        ids.update(g['id'] for g in json.load(list_path.open()))
    return ids


def stamp(pano_id, slug, panos_dir, force):
    json_path = panos_dir / str(pano_id) / f"{pano_id}.json"
    if not json_path.exists():
        return 'missing'
    with open(json_path) as f:
        data = json.load(f)
    gigapan = data.get('gigapan', data)
    if gigapan.get('owner') == slug:
        return 'already'
    if gigapan.get('owner') and not force:
        return 'skipped_other_owner'
    backup_json(json_path)
    gigapan['owner'] = slug
    with open(json_path, 'w') as f:
        json.dump(data, f, indent=2)
    return 'stamped'


def main():
    parser = argparse.ArgumentParser(description="Stamp owner slug into pano JSON files")
    parser.add_argument('--profile', required=True, help="Profile slug to stamp, e.g. molly")
    parser.add_argument('--list', help="Path to that profile's gigapan_list.json (restricts to its ids)")
    parser.add_argument('--all', action='store_true',
                         help="Stamp every dir in --panos-dir not claimed by another profile's list")
    parser.add_argument('--panos-dir', default=str(PANOS_DIR_DEFAULT))
    parser.add_argument('--force', action='store_true', help="Overwrite an existing owner field")
    args = parser.parse_args()

    if not args.list and not args.all:
        parser.error("Specify --list <gigapan_list.json> or --all")

    panos_dir = Path(args.panos_dir)

    if args.all:
        exclude = other_profile_ids(args.profile)
        ids = sorted(
            int(d.name) for d in panos_dir.iterdir()
            if d.is_dir() and d.name.isdigit() and int(d.name) not in exclude
        )
    else:
        ids = [g['id'] for g in json.load(open(args.list))]

    counts = {}
    for pano_id in ids:
        result = stamp(pano_id, args.profile, panos_dir, args.force)
        counts[result] = counts.get(result, 0) + 1

    print(f"profile={args.profile} total={len(ids)} " +
          " ".join(f"{k}={v}" for k, v in counts.items()))


if __name__ == '__main__':
    main()
