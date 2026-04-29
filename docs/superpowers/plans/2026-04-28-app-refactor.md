# app.py Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clean up app.py by adding a dict-based pano index for O(1) lookup, extracting two duplicated helpers, and fixing six minor code-quality issues — no behavior changes.

**Architecture:** All changes are within `app.py`. Three sequential tasks: cache structure, module-level helpers, then cleanup. Each task ends with a compile check and commit.

**Tech Stack:** Python 3, Flask, Pathlib

---

### Task 1: Dual cache structure (`_pano_cache` list + `_pano_index` dict)

**Files:**
- Modify: `app.py:192-207`

- [ ] **Step 1: Replace the cache globals and `_get_pano_cache`**

Find and replace this block (lines 192-207):

```python
_pano_cache = None

def _get_pano_cache():
    global _pano_cache
    if _pano_cache is None:
        _pano_cache = load_pano_data()
    return _pano_cache

def invalidate_pano_cache():
    global _pano_cache
    _pano_cache = None

def get_pano(pano_id):
    """Look up a single pano by id from the cache. Returns None if not found."""
    pid = int(pano_id) if str(pano_id).isdigit() else pano_id
    return next((p for p in _get_pano_cache() if p['id'] == pid), None)
```

With:

```python
_pano_cache = None   # sorted list for iteration
_pano_index = None   # id → pano for O(1) lookup

def _get_pano_cache():
    global _pano_cache, _pano_index
    if _pano_cache is None:
        _pano_cache = load_pano_data()
        _pano_index = {p['id']: p for p in _pano_cache}
    return _pano_cache

def invalidate_pano_cache():
    global _pano_cache, _pano_index
    _pano_cache = None
    _pano_index = None

def get_pano(pano_id):
    """Look up a single pano by id from the cache. Returns None if not found."""
    _get_pano_cache()  # ensure populated
    pid = int(pano_id) if str(pano_id).isdigit() else pano_id
    return _pano_index.get(pid)
```

- [ ] **Step 2: Verify syntax**

```bash
python3 -m py_compile app.py && echo OK
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "perf: O(1) pano lookup via dict index alongside list cache"
```

---

### Task 2: Module-level `SORT_CONFIG` constant

**Files:**
- Modify: `app.py` — add constant after `SETTINGS_DEFAULTS` block; remove local dicts from `home()` and `tag_view()`

- [ ] **Step 1: Add `SORT_CONFIG` after `SETTINGS_DEFAULTS`**

Find:

```python
SETTINGS_DEFAULTS = {
    'cluster_max_radius':      40,
    'cluster_disable_at_zoom': 13,
}
```

Add immediately after:

```python
SORT_CONFIG = {
    'id_asc':       (lambda p: p['id'],                                               False),
    'id_desc':      (lambda p: p['id'],                                               True),
    'name_asc':     (lambda p: p['name'].lower(),                                     False),
    'name_desc':    (lambda p: p['name'].lower(),                                     True),
    'date_asc':     (lambda p: (0 if p.get('taken_at') else 1,    p.get('taken_at') or ''),   False),
    'date_desc':    (lambda p: (1 if p.get('taken_at') else 0,    p.get('taken_at') or ''),   True),
    'uploaded_asc': (lambda p: (0 if p.get('created_at') else 1,  p.get('created_at') or ''), False),
    'uploaded_desc':(lambda p: (1 if p.get('created_at') else 0,  p.get('created_at') or ''), True),
    'size_asc':     (lambda p: p.get('width', 0) * p.get('height', 0),               False),
    'size_desc':    (lambda p: p.get('width', 0) * p.get('height', 0),               True),
}
```

- [ ] **Step 2: Update `home()` — remove local `sort_config`, use `SORT_CONFIG`**

In `home()`, find:

```python
    # For date sorts, nulls always sort last regardless of direction.
    # date_asc:  key=(0 if dated else 1, date), reverse=False  → earliest first, nulls last
    # date_desc: key=(1 if dated else 0, date), reverse=True   → latest first, nulls last
    sort_config = {
        'id_asc':    (lambda p: p['id'],                                              False),
        'id_desc':   (lambda p: p['id'],                                              True),
        'name_asc':  (lambda p: p['name'].lower(),                                    False),
        'name_desc': (lambda p: p['name'].lower(),                                    True),
        'date_asc':       (lambda p: (0 if p.get('taken_at') else 1,   p.get('taken_at') or ''),   False),
        'date_desc':      (lambda p: (1 if p.get('taken_at') else 0,   p.get('taken_at') or ''),   True),
        'uploaded_asc':   (lambda p: (0 if p.get('created_at') else 1, p.get('created_at') or ''), False),
        'uploaded_desc':  (lambda p: (1 if p.get('created_at') else 0, p.get('created_at') or ''), True),
        'size_asc':       (lambda p: p.get('width', 0) * p.get('height', 0),                        False),
        'size_desc':      (lambda p: p.get('width', 0) * p.get('height', 0),                        True),
    }
    key, reverse = sort_config.get(sort, sort_config['id_asc'])
```

Replace with:

```python
    key, reverse = SORT_CONFIG.get(sort, SORT_CONFIG['id_asc'])
```

- [ ] **Step 3: Update `tag_view()` — remove local `sort_config`, use `SORT_CONFIG`**

In `tag_view()`, find:

```python
    sort_config = {
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
    key, reverse = sort_config.get(sort, sort_config['id_asc'])
```

Replace with:

```python
    key, reverse = SORT_CONFIG.get(sort, SORT_CONFIG['id_asc'])
```

- [ ] **Step 4: Verify syntax**

```bash
python3 -m py_compile app.py && echo OK
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add app.py
git commit -m "refactor: extract SORT_CONFIG to module-level constant"
```

---

### Task 3: Module-level `geo_panos_from_cache()` helper

**Files:**
- Modify: `app.py` — add helper after cache functions; update `view_pano`, `edit_pano`, `map_view`

- [ ] **Step 1: Add `geo_panos_from_cache()` after `get_pano()`**

Find:

```python
def get_pano(pano_id):
    """Look up a single pano by id from the cache. Returns None if not found."""
    _get_pano_cache()  # ensure populated
    pid = int(pano_id) if str(pano_id).isdigit() else pano_id
    return _pano_index.get(pid)
```

Add immediately after:

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

- [ ] **Step 2: Update `view_pano()` — replace inline comprehension**

In `view_pano()`, find:

```python
    all_panos = _get_pano_cache()

    # Collect geo-located panos for the location mini-map
    geo_panos = [
        {'id': pg['id'], 'name': pg['name'],
         'lat': pg['latitude'], 'lng': pg['longitude'],
         'width': pg.get('width', 0), 'height': pg.get('height', 0),
         'tile_base_url': resolve_tile_base_url(pg) or ''}
        for pg in all_panos
        if pg.get('latitude') and pg.get('longitude')
        and pg['latitude'] != 0 and pg['longitude'] != 0
    ]
```

Replace with:

```python
    geo_panos = geo_panos_from_cache()
```

Then find and remove the now-unused `all_panos` assignment two lines later:

```python
    all_panos = list(all_panos)
```

Replace with:

```python
    all_panos = list(_get_pano_cache())
```

- [ ] **Step 3: Update `edit_pano()` — replace inline comprehension**

In `edit_pano()`, find:

```python
    geo_panos = [
        {'id': pg['id'], 'name': pg['name'],
         'lat': pg['latitude'], 'lng': pg['longitude']}
        for pg in _get_pano_cache()
        if pg.get('latitude') and pg.get('longitude')
        and pg['latitude'] != 0 and pg['longitude'] != 0
    ]
```

Replace with:

```python
    geo_panos = geo_panos_from_cache()
```

- [ ] **Step 4: Update `map_view()` — replace inline comprehension**

In `map_view()`, find:

```python
    mapped = [p for p in panoramas
              if p.get('latitude') and p.get('longitude')
              and p['latitude'] != 0 and p['longitude'] != 0]
```

Replace with:

```python
    mapped = geo_panos_from_cache()
```

Then remove the now-unused `panoramas` assignment at the top of `map_view()`:

```python
    panoramas = _get_pano_cache()
```

Note: `downloaded_ids` still needs the full pano list. Replace the removed line with:

```python
    panoramas = _get_pano_cache()
```

(Keep it — it's still used two lines later for `downloaded_ids = {p['id'] for p in panoramas}`.)

- [ ] **Step 5: Verify syntax**

```bash
python3 -m py_compile app.py && echo OK
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add app.py
git commit -m "refactor: extract geo_panos_from_cache() helper, replace three inline comprehensions"
```

---

### Task 4: Six cleanup items

**Files:**
- Modify: `app.py` — scattered small edits

- [ ] **Step 1: Remove `render_template_string` from flask import**

Find:

```python
from flask import Flask, render_template_string, abort, render_template, send_file, Response, request, jsonify, redirect, make_response, url_for, flash
```

Replace with:

```python
from flask import Flask, abort, render_template, send_file, Response, request, jsonify, redirect, make_response, url_for, flash
```

- [ ] **Step 2: Remove `import os`**

Find and delete:

```python
import os
```

- [ ] **Step 3: Rewrite `collect_tile_stats` to use `Path.rglob` instead of `os.walk`**

Find the entire walk block in `collect_tile_stats`:

```python
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
```

Replace with:

```python
    for full_path in base_dir.rglob('*'):
        if not full_path.is_file():
            continue
        if full_path.suffix.lower() not in ('.jpg', '.png'):
            continue
        try:
            size = full_path.stat().st_size
        except Exception as e:
            print(f"Could not read {full_path}: {e}")
            continue
        try:
            rel_parts = full_path.relative_to(base_dir).parts
            level = rel_parts[0]
            x = rel_parts[1]
            y = Path(rel_parts[2]).stem
        except Exception as e:
            print(f"Invalid path structure: {full_path} — {e}")
            continue
        data = stats[level]
        data["sizes"].append(size)
        data["x_values"].add(int(x))
        data["y_values"].add(int(y))
```

- [ ] **Step 4: Delete commented-out print statements in `collect_tile_stats`**

Find and delete both of these lines:

```python
    #print("\nTile Size Statistics by Level:")
    #print(f"{'Level':<6} {'Count':>6} {'Min (B)':>10} {'Max (B)':>10} {'Avg (B)':>10} {'Cols':>6} {'Rows':>6}")
```

And:

```python
        #print(f"{level:<6} {count:>6} {min_size:>10} {max_size:>10} {avg_size:>10} {cols:>6} {rows:>6}")
```

- [ ] **Step 5: Fix `collect_tile_stats` call site — use `Path` not f-string**

In `view_pano()`, find:

```python
    results=collect_tile_stats(f"{BASE_DIR}/{pano_id}")
```

Replace with:

```python
    results = collect_tile_stats(BASE_DIR / pano_id)
```

- [ ] **Step 6: Fix `p={}` two-liner in `view_pano()`**

Find:

```python
    p={}
    p['page_title']='View '
```

Replace with:

```python
    p = {'page_title': 'View'}
```

- [ ] **Step 7: Fix f-string with no interpolation in `edit_pano_post()`**

Find:

```python
    flash(f'Saved — backup written.')
```

Replace with:

```python
    flash('Saved — backup written.')
```

- [ ] **Step 8: Verify syntax**

```bash
python3 -m py_compile app.py && echo OK
```

Expected: `OK`

- [ ] **Step 9: Commit**

```bash
git add app.py
git commit -m "chore: cleanup — remove unused imports, drop os.walk, fix minor style issues"
```

---

### Final verification

- [ ] **Start the app and confirm it loads**

```bash
python3 app.py
```

Expected: Flask starts on port 5000 with no import errors.

- [ ] **Push**

```bash
git push
```
