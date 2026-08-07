# Patches for DAP-DB-Manager

Four bugs in upstream DAP-DB-Manager (commit `627cf1d`, 2026-01-15), all found
on 2026-08-07. Bugs 1 and 2 produce a database that loads and browses fine but
is semantically wrong. Bug 3 makes `--save-tags` a silent no-op. Bug 4 stops the
cache from ever being used; it is not patched, but has a one-flag workaround.

The patch file covers bugs 1–3. Bug 4 is handled by adding `--no-parallel` to
warm runs — see below.

Apply with:

```bash
cd DAP-DB-Manager
git apply ../patches/0001-rockbox-tag-order-and-albumartist.patch
```

The install is `pip install -e`, so no reinstall is needed after patching.

Verify it applied:

```bash
git -C DAP-DB-Manager diff --stat
# 3 files changed, 93 insertions(+), 29 deletions(-)
```

---

## Bug 1 — index slots rotated, destroying track ordering

**Symptom on device:** albums play and display in alphabetical order instead of
track order. Tracks appear prefixed with the release year and disc number.

**Cause:** `constants.py` builds the index entry as `TAGS = FILE_TAGS +
EMBEDDED_TAGS`. Because `FILE_TAGS` ends with `canonicalartist`, that lands at
slot 9 and pushes year/disc/track to 10/11/12. Rockbox reads:

| Slot | Rockbox expects | Unpatched writes |
|---|---|---|
| 9 | year | canonicalartist offset |
| 10 | discnumber | year |
| 11 | **tracknumber** | discnumber |
| 12 | canonicalartist | tracknumber |

So Rockbox reads the disc number as the track number — nearly always `0` or `1`,
so every track ties and the browser falls back to sorting by title.

The file's own header comment documents the correct Rockbox order
(`tag_year=9, tag_discnumber=10, tag_tracknumber=11`, `canonicalartist=12`) and
contradicts the array built directly below it.

**Fix:** add an explicit `INDEX_ORDER` in true Rockbox order and serialise
against it in `indexfile.py` (`IndexEntry.to_file` / `from_file`), branching on
whether a field is a tag-file offset or a raw number. `FILE_TAGS` still governs
which tag files exist and their names via `FILE_TAG_INDICES` — only the
index-entry slot order changes.

## Bug 2 — album artist silently replaced by artist

**Symptom on device:** browsing by Album Artist is identical to browsing by
Artist. `database_7.tcd` is byte-for-byte identical to `database_0.tcd`.

**Cause:** `database/cache.py` lists `"albumartist"` (no space) in
`essential_fields`, but the tag registry key is `"album artist"` (with a space),
as used in `constants.FILE_TAGS` and `tagging/titleformat/field.py`. The lookup
raises `KeyError`, which the surrounding `except (KeyError, AttributeError):
pass` swallows, so the field never reaches the worker.

The worker then evaluates `%album artist%` against tags that no longer contain
it, and the fallback chain in `tagging/titleformat/field.py:128` —

```python
"album artist": ["album artist", "albumartist", "artist", "composer", "performer"],
```

— quietly substitutes `artist`. No warning is emitted.

Note the tag layer itself is fine. Verified directly against a real `.m4a`:
`tagging.read(f).get_string("album artist")` returns `['Agatha All Along -
Cast']`, while `get_string("albumartist")` raises `KeyError`.

**Fix:** one word — use `"album artist"` in `essential_fields`.

## Bug 3 — `--save-tags` silently writes an empty cache

**Symptom:** `ddm generate --save-tags tags.msgpack` reports `Saved 0 tags` and
writes a 34-byte file (one msgpack integer: zero). Every later run is a cold
run, so the tag cache never helps.

**Cause:** `TagCache.save` filters with

```python
valid_paths = [p for p in paths_set if p in cls._cache]
```

`_cache` is keyed on **lowercased** absolute paths (`_add_file_internal` and
`read_single_file_tags` both do `path.lower()`), but `paths_set` holds paths in
their **original case**. Any path containing an uppercase character misses, so
on a normally-named library `valid_paths` is empty.

**A second, latent bug sits behind it.** `TagCache.load` does
`paths_set.add(lowerpath)` while the directory scan adds original-case paths. So
once save actually works, load re-adds a lowercase duplicate of every file —
a 36-file album generated 72 entries. This never showed upstream because save
always wrote nothing, so load always loaded nothing.

**Fix:** case-fold only the *lookup*, never the stored path.

- `save`: `[p for p in paths_set if p.lower() in cls._cache]`, then read the
  entry via `cls._cache[path_entry.lower()]`. The record keeps original case.
- `load`: keep `cls._cache[lowerpath]`, but `paths_set.add(file_path)`.

The warm database is not byte-identical to the cold one — set iteration order
differs — but the contents match exactly. Rockbox navigates via the sorted tag
files and does not depend on index entry order.

**This fix alone is not enough to make the cache useful — see bug 4.**

## Bug 4 — worker processes never see the loaded cache (NOT patched)

**Symptom:** even with bug 3 fixed and a valid 9,766-entry cache on disk,
`--load-tags` gives no speedup at all. Full library, warm: 446 s, with 7:24 of
that in the scan phase — indistinguishable from cold.

**Cause:** tag reading runs in `ProcessPoolExecutor` workers via
`read_single_file_tags`, which checks `TagCache.contains()`. That executor is
constructed eagerly in `FileScanner.__init__`:

```python
self._executor = ProcessPoolExecutor(max_workers=self.max_workers)
```

`FileScanner.__init__` is called from `Database.__init__`, which happens
**before** `db.load_tags()` in `cli/commands/generate.py` (line ~115 vs ~193).
The workers therefore never observe the cache the parent loads afterwards, so
every lookup misses and every file is re-read.

**Not patched** — fixing it properly means either deferring executor creation
until after `load_tags`, or shipping the cache to the workers. Neither is
needed, because the workaround is strictly better:

**Workaround: add `--no-parallel` to warm runs.** The sequential path in
`add_dir` calls `_add_file_internal` in the parent process, where the cache is
populated. Full library, warm:

| | scan phase | total |
|---|---|---|
| parallel (default) | 7:24 | 446 s |
| `--no-parallel` | 0:00 | **2 s** |

Verified equivalent to the cold-run database: identical path set, identical
artist / album / title / album artist / composer / genre / grouping string sets,
identical year/disc/track slot set, and all 8 `verify_db.py` checks pass.

Since a warm run does no tag I/O, parallelism buys nothing — sequential is the
right mode whenever the cache is valid. Use the parallel default for cold runs
only.

**Measurement caveat worth recording:** an early 336-file test showed cold 14 s →
warm 2 s and was initially read as proof the cache worked. It was not — those
files had been read seconds earlier, so the speedup came from the OS page cache.
Only the full-library run, where the working set exceeds what stays resident,
exposed the real behaviour. Benchmark cache changes on the whole library.

---

## Verification

`verify_db.py` checks 6 and 7 exist specifically to catch these two. Against an
unpatched database every structural check passes and those two fail:

```
[FAIL] index slots 9-12 are year/disc/track/canonicalartist
         -- slot9 not year-like (0.4%); slot10 not disc-like (0.1%)
[FAIL] album artist is not a copy of artist  -- both 47620 bytes, identical
```

After patching, a single-album smoke test gives correct slots and a distinct
album artist file:

```
entry   slot9(yr) slot10(dsc) slot11(trk) slot12(ca)
0            2024          1          1        100
1            2024          1          2         12
```

## Upstream status

Not yet reported. All four are worth filing at
<https://github.com/vakintosh/DAP-DB-Manager/issues>. None is device-specific:
the slot order (1), the registry key name (2), the case-folding (3) and the
executor-before-load ordering (4) are all target-independent. Every user hits
bugs 1 and 2; anyone with uppercase characters in their paths — nearly everyone —
hits bug 3; and bug 4 makes the advertised cache speedup unreachable on the
default code path for everyone.
