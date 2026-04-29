# app.py Refactor — Design Spec
**Date:** 2026-04-28
**Scope:** Single-file cleanup of app.py. No new files, no behavior changes.

---

## 1. Cache: list + dict

Replace the single `_pano_cache` list with two parallel structures:

```python
_pano_cache: list | None = None   # sorted list for iteration
_pano_index: dict | None = None   # id → pano for O(1) lookup
```

- `_get_pano_cache()` populates both from `load_pano_data()` on first call.
- `invalidate_pano_cache()` sets both to `None`.
- `get_pano(pano_id)` looks up via `_pano_index[pid]` instead of scanning the list.

No callers change. The returned pano objects are identical to today.

---

## 2. Module-level helpers

### `SORT_CONFIG`

Extract the sort key dict currently copy-pasted identically in `home()` and `tag_view()` into a module-level constant:

```python
SORT_CONFIG = {
    'id_asc':       (lambda p: p['id'],                                              False),
    'id_desc':      (lambda p: p['id'],                                              True),
    'name_asc':     (lambda p: p['name'].lower(),                                    False),
    'name_desc':    (lambda p: p['name'].lower(),                                    True),
    'date_asc':     (lambda p: (0 if p.get('taken_at') else 1,   p.get('taken_at') or ''),   False),
    'date_desc':    (lambda p: (1 if p.get('taken_at') else 0,   p.get('taken_at') or ''),   True),
    'uploaded_asc': (lambda p: (0 if p.get('created_at') else 1, p.get('created_at') or ''), False),
    'uploaded_desc':(lambda p: (1 if p.get('created_at') else 0, p.get('created_at') or ''), True),
    'size_asc':     (lambda p: p.get('width', 0) * p.get('height', 0),              False),
    'size_desc':    (lambda p: p.get('width', 0) * p.get('height', 0),              True),
}
```

Both `home()` and `tag_view()` replace their local definition with `key, reverse = SORT_CONFIG.get(sort, SORT_CONFIG['id_asc'])`.

### `geo_panos_from_cache()`

Replace the three near-identical geo-filtered list comprehensions in `view_pano`, `edit_pano`, and `map_view` with a single helper that returns the superset of all fields any route needs:

```python
def geo_panos_from_cache():
    return [
        {
            'id':            pg['id'],
            'name':          pg['name'],
            'lat':           pg['latitude'],
            'lng':           pg['longitude'],
            'width':         pg.get('width', 0),
            'height':        pg.get('height', 0),
            'tile_base_url': resolve_tile_base_url(pg) or '',
        }
        for pg in _get_pano_cache()
        if pg.get('latitude') and pg.get('longitude')
        and pg['latitude'] != 0 and pg['longitude'] != 0
    ]
```

All three routes call `geo_panos_from_cache()` directly. Extra fields are ignored by templates that don't use them.

---

## 3. Cleanup items

| # | Location | Change |
|---|---|---|
| 1 | `view_pano` line ~491 | `f"{BASE_DIR}/{pano_id}"` → `BASE_DIR / pano_id` |
| 2 | `collect_tile_stats` | Replace `os.walk` loop with `Path.rglob('*')`; filter to `f.is_file()`; drop `import os` |
| 3 | `collect_tile_stats` | Delete commented-out `print` statements (lines ~117-118, ~128) |
| 4 | Top-level flask import | Remove unused `render_template_string` |
| 5 | `edit_pano_post` | `flash(f'Saved — backup written.')` → `flash('Saved — backup written.')` |
| 6 | `view_pano` | `p={}` / `p['page_title']='View '` → `p = {'page_title': 'View'}` (fix trailing space too) |

---

## Success criteria

- `python3 -m py_compile app.py` passes
- App starts and all routes respond (manual smoke test)
- No behavior changes visible to the user
