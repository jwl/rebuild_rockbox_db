# rebuild_rockbox_db

Rebuild the Rockbox tagcache database for the **JOYEUSE** microSD card on a PC
instead of on the device, and audit the library for paths that exceed Rockbox's
`MAX_PATH` limit.

> **Nothing in this directory is installed yet.** The setup in
> [Step 1](#step-1-one-time-setup) has *not* been run. Read it first, then run
> it yourself when you're ready.

---

# TL;DR - What to run when adding new music to an existing device with pre-warmed tag cache
1. Sync contents of libraries using `FreeFileSync`
2. Back-up existing database:
```
  mkdir -p tcd-backup
  cp /run/media/jobias/JOYEUSE/.rockbox/*.tcd tcd-backup/
```
3. Verify path lengths:
```
  python3 check_path_lengths.py
```
4. Generate/Update database locally:
```
  mkdir -p testdb
  env HOME="$PWD/fakehome" ./venv/bin/ddm generate \
        --music-dir /run/media/jobias/JOYEUSE/Music \
        --output "$PWD/testdb" \
        --dap-root /run/media/jobias/JOYEUSE \
        --load-tags "$PWD/tags.msgpack" \
        --save-tags "$PWD/tags.msgpack" \
        --no-parallel
```
5. Verify database integrity:
```
  env HOME="$PWD/fakehome" ./venv/bin/ddm validate --db-dir "$PWD/testdb"
  python3 verify_db.py
```
6. Copy new database to device:
```
  cp testdb/*.tcd /run/media/jobias/JOYEUSE/.rockbox/
  sync
```
7. Verify that copy was successful:
```
  md5sum testdb/*.tcd | awk '{n=split($2,p,"/"); print $1, p[n]}' | sort > /tmp/src.md5
  md5sum /run/media/jobias/JOYEUSE/.rockbox/*.tcd | awk '{n=split($2,p,"/"); print $1, p[n]}' | sort > /tmp/dst.md5
  diff /tmp/src.md5 /tmp/dst.md5 && echo "MATCH"
```


## Why bother

On-device "Initialize now" takes ~20 minutes. Generating on the PC took **7m54s**
for 9,730 files.

That is only ~2.5x faster, not the "180x" the upstream tool advertises. The job is
**I/O-bound reading tags off the card**, not CPU-bound — CPU usage stayed around
5%. A faster desktop CPU barely helps. You would only approach the advertised
numbers if the library lived on a local SSD rather than on the microSD itself.

Decide accordingly: if you just added a handful of albums, on-device
"Update now" may be less hassle.

---

## Device facts (verified 2026-08-07)

These are specific to this setup. Check them again if anything about the player
or the card changes.

| Property | Value |
|---|---|
| Player | AIGO Eros Q Native |
| Rockbox target | `erosqnative`, target id 116 |
| Rockbox version | 4.0 |
| CPU | MIPS, `ingenic_x1000` (little-endian) |
| Card mount | `/run/media/jobias/JOYEUSE` |
| **Rockbox volume notation** | **`/<microSD0>`** |
| Tagcache magic | `0x54434810` |
| Tagcache version | 16 |
| Audio files | 9,730 |
| Filesystem | vfat |

Source for the target/version fields: `<card>/.rockbox/rockbox-info.txt`.

Both the device (MIPS little-endian) and the desktop (x86-64) are little-endian,
so the generated `.tcd` files need no byte-order conversion.

---

## The two gotchas

Read these before running anything. Both silently produce a *wrong* database
rather than an error.

### 1. The volume prefix costs 11 bytes

Rockbox does **not** address this card as `/`. Paths are stored as:

```
/<microSD0>/Music/Artist/Album/Track.m4a
```

You can confirm this yourself:

```bash
strings -a /run/media/jobias/JOYEUSE/.rockbox/database_4.tcd | head -3
```

That `/<microSD0>` prefix is 11 bytes counted against `MAX_PATH` (260). So the
real budget for the part you control (`/Music/...`) is **248 bytes**, not 259.

This is also why the *official* Rockbox PC tool (`tools/database/database.c` in
the Rockbox source) is not usable here: it takes no arguments and hardcodes the
scan root as `/`, so it emits `/Music/...` and every entry would point at a
nonexistent path.

### 2. Auto-detection cannot see `microSD0` and falls back silently

`ddm detect-mounts` matches the volume notation with this regex
(`src/dap_db_manager/database/mount_detector.py`):

```python
MOUNT_PATTERN = re.compile(r"^/<([A-Z]+\d+)>/")
```

Uppercase only. It **cannot** match `microSD0`. On failure it does not error —
it defaults to `/<HDD0>` and carries on, producing a database in which every
single path is wrong.

**Always set the notation manually with `--set-mount`**, which bypasses the
regex and performs no validation:

```bash
ddm detect-mounts --db-dir <card>/.rockbox --set-mount '/<microSD0>'
```

Verify it landed before generating (see Step 3).

---

## Step 1: One-time setup

**Not yet performed.** Review, then run.

Requires `python3` (>= 3.11; 3.14.6 works) and `git`. Note `pip` may not be on
your PATH — use `python3 -m pip` via the venv as shown.

```bash
cd ~/Projects/rebuild_rockbox_db

# Clone the upstream tool
git clone https://github.com/vakintosh/DAP-DB-Manager.git

# REQUIRED: fix two upstream bugs -- see patches/README.md
cd DAP-DB-Manager
git apply ../patches/0001-rockbox-tag-order-and-albumartist.patch
cd ..

# Create an isolated virtualenv
python3 -m venv venv
./venv/bin/python -m pip install --upgrade pip

# Install the tool (CLI only; the GUI extra pulls in wxPython and isn't needed)
./venv/bin/python -m pip install -e ./DAP-DB-Manager
```

**Do not skip the patch.** Unpatched, the tool produces a database that loads
and browses correctly but has lost all album track ordering and has album artist
collapsed into artist. See [patches/README.md](patches/README.md) for the full
diagnosis. The install is editable (`-e`), so patching before or after install
both work.

Dependencies this pulls in: `mutagen`, `tomli-w`, `rich`, `rich-argparse`,
`psutil`, `pydantic`, `msgpack`, plus `uv_build` as the build backend.

Confirm it works:

```bash
./venv/bin/ddm --help
```

You may see a `SyntaxWarning: 'break' in a 'finally' block` from the package on
Python 3.14. It is harmless.

### About `HOME`

`ddm` hardcodes its config location to `~/.ddm/.rdbm_config.toml` with no
environment override. Every command below is prefixed with
`env HOME="$PWD/fakehome"` to keep that config inside this project directory
instead of your real home. This is optional — drop it if you'd rather it live in
`~/.ddm` — but be consistent, because the mount notation is stored there.

### Shell compatibility

Every snippet in this file is written to run unmodified in **fish, zsh, bash, or
plain POSIX sh**, despite being tagged ```` ```bash ```` for syntax highlighting.
Verified under fish 4.8.1 on 2026-08-07.

This is deliberate, not luck. Preserve it when editing. The rules:

- **Set environment variables with `env VAR=value cmd`, never a bare
  `VAR=value cmd` prefix.** `env` is an external command, so it behaves
  identically everywhere. The bare prefix is a POSIX shell feature that fish only
  gained in 3.1.
- **Never use `export`.** Fish spells it `set -x`. Use the `env` prefix instead.
- **No `( cmd )` subshells.** Fish parses `(` in command position as command
  substitution and errors out with *"command substitutions not allowed in command
  position"*. Where you would reach for `(cd somewhere && cmd)` to avoid changing
  directory, just give `cmd` an absolute path instead.
- **No `$(...)`, `` `...` ``, `$?`, `[[ ]]`, heredocs, `for`/`if`/`while`, arrays,
  or `${var:-default}`.** Fish either lacks these or spells them differently. If a
  step ever needs real control flow, put it in a `.py` file next to
  `check_path_lengths.py` rather than inlining shell.

Two things that *look* like portability hazards here and are not:

- `'/<microSD0>'` — fish treats `<` as input redirection, but only when
  unquoted. Inside single quotes it is a literal, and the argument arrives
  intact.
- `grep -A2 '\[database\]'` — fish honors only `\'` and `\\` as escapes inside
  single quotes, so `\[` passes through untouched, exactly as in bash.

Both are safe *because* they are quoted. Keep the quotes.

---

## Step 2: Back up the current database

**Do not skip this.** It is your only rollback.

```bash
cd ~/Projects/rebuild_rockbox_db
mkdir -p tcd-backup
cp /run/media/jobias/JOYEUSE/.rockbox/*.tcd tcd-backup/
```

There should be 11 files.

---

## Step 3: Set the mount notation (first run only)

```bash
cd ~/Projects/rebuild_rockbox_db
mkdir -p fakehome
env HOME="$PWD/fakehome" ./venv/bin/ddm detect-mounts \
  --db-dir /run/media/jobias/JOYEUSE/.rockbox \
  --set-mount '/<microSD0>'
```

Verify — this must show `/<microSD0>` and `version = 16`:

```bash
grep -A2 '\[database\]' fakehome/.ddm/.rdbm_config.toml
```

---

## Step 4: Audit path lengths first

Fix over-length paths *before* generating, so the database reflects the final
names. See [PATH_LIMITS.md](PATH_LIMITS.md) for background and the history of
what was already fixed.

```bash
python3 check_path_lengths.py
```

No dependencies — plain stdlib, no venv needed. It reports any file whose full
device path reaches 260 bytes, plus near-miss bands.

If it flags anything, rename the offending album folder or filename, then re-run
until clean. Renaming a *directory* is usually the better lever: it fixes every
track in the album at once.

---

## Step 5: Generate into a scratch directory

Never generate straight onto the card. Build locally, verify, then copy.

There are two forms. Use the warm one whenever `tags.msgpack.gz` exists.

**Warm run — 2 seconds.** Requires an existing cache.

```bash
cd ~/Projects/rebuild_rockbox_db
mkdir -p testdb
env HOME="$PWD/fakehome" ./venv/bin/ddm generate \
  --music-dir /run/media/jobias/JOYEUSE/Music \
  --output "$PWD/testdb" \
  --dap-root /run/media/jobias/JOYEUSE \
  --load-tags "$PWD/tags.msgpack" \
  --save-tags "$PWD/tags.msgpack" \
  --no-parallel
```

**Cold run — ~8 minutes.** Only when there is no cache, or after a bulk re-tag.
Note this one *omits* `--no-parallel`.

```bash
env HOME="$PWD/fakehome" ./venv/bin/ddm generate \
  --music-dir /run/media/jobias/JOYEUSE/Music \
  --output "$PWD/testdb" \
  --dap-root /run/media/jobias/JOYEUSE \
  --save-tags "$PWD/tags.msgpack"
```

`--dap-root` strips the local mount path; the mount notation from Step 3 is then
prepended. Both are required to get `/<microSD0>/Music/...`. Expect one entry per
audio file with 0 failures.

### `--no-parallel` is what makes the cache work

This looks backwards and is the single least obvious thing in this workflow.

Tag reading normally happens in `ProcessPoolExecutor` workers. That executor is
constructed in `FileScanner.__init__`, which runs inside `Database.__init__` —
**before** `load_tags()`. The workers never see the parent's later-loaded cache,
so `read_single_file_tags` misses on every file and re-reads all of them.
`--no-parallel` takes the sequential path through `_add_file_internal`, which
runs in the parent process where the cache is actually populated.

Measured on the full 9,766-file library, both warm:

| | scan phase | total |
|---|---|---|
| parallel (default) | 7:24 | 446 s |
| `--no-parallel` | 0:00 | **2 s** |

The `--no-parallel` output was checked against the cold-run database: identical
path set, identical artist / album / title / album artist / composer / genre /
grouping strings, and an identical year/disc/track slot set. It is the same
database, built 200× faster.

Do **not** use `--no-parallel` for a cold run — with no cache it reads every file
sequentially and is far slower than the parallel path.

Keep `--save-tags` on warm runs too, so newly added files enter the cache.

These flags exist **only on `generate`**, not on `update`.

### Why not `ddm update`?

`update` looks like the right tool for adding a few albums, and at the database
level it is: it adds new entries, preserves existing ones, marks missing files
deleted, and detects renames to carry statistics across.

But its first step is `self._scanner.add_dir(music_dir, ...)`, which calls
`read_tags_batch` for **every** file before diffing paths. It re-reads the whole
library, so it costs the same as `generate` — and it has no `--load-tags` to
avoid that. Its one real advantage, preserving playcounts and ratings, is worth
nothing here because `gather runtime data` is off in `config.cfg`.

**If you do use it**, `--music-dir` must point at the *full* `Music` directory,
never at just the new album. The logic is
`paths_to_delete = existing_paths - new_paths`, so scoping it to one folder
marks the entire rest of the library `FLAG_DELETED`.

---

## Step 6: Verify before copying

```bash
env HOME="$PWD/fakehome" ./venv/bin/ddm validate --db-dir "$PWD/testdb"
python3 verify_db.py
```

`verify_db.py` performs the independent checks that actually matter — it does not
trust the tool's own validator.

Structural:

- magic is `0x54434810` and matches the backup
- the 11-file set matches the backup
- **every** stored path carries the `/<microSD0>/Music/` prefix
- the set of stored paths exactly equals the set of audio files on disk
- no stored path reaches 260 bytes

Semantic — a database can pass every structural check, load on the device, and
still be wrong:

- index slots 9–12 hold plausible year / disc / track / canonicalartist values
- album artist is not a byte-for-byte copy of artist

Those last two exist because that is exactly what happened on the first run:
the database passed all structural checks, browsed fine, and had silently lost
track ordering and album artist.

Do not proceed unless it prints `ALL CHECKS PASSED`.

The disk comparison only counts audio extensions, so embedded artwork files such
as `cover.jpg` are correctly ignored rather than reported as unindexed.

---

## Step 7: Copy to the card

```bash
cp testdb/*.tcd /run/media/jobias/JOYEUSE/.rockbox/
sync
```

Confirm the copy landed intact:

```bash
md5sum testdb/*.tcd | awk '{n=split($2,p,"/"); print $1, p[n]}' | sort > /tmp/src.md5
md5sum /run/media/jobias/JOYEUSE/.rockbox/*.tcd | awk '{n=split($2,p,"/"); print $1, p[n]}' | sort > /tmp/dst.md5
diff /tmp/src.md5 /tmp/dst.md5 && echo "MATCH"
```

The `awk` reduces each line to `hash basename`, so the two sides are compared
per file by name rather than as an unordered bag of hashes — a file copied under
the wrong name would still be caught.

Expect `database_0.tcd` and `database_12.tcd` to share a hash. That is artist and
canonicalartist being genuinely identical, not a bug. `database_7.tcd`
(album artist) must be **distinct** from `database_0.tcd`; if it is not, you are
looking at unpatched-tool output — see [patches/README.md](patches/README.md).

Unmount properly, then boot the player. Because `default browser: database` is
set in `config.cfg`, a bad database is obvious immediately on boot.

You do **not** need to run "Initialize now" on the device afterward. That is the
whole point.

---

## Rollback

```bash
cp tcd-backup/*.tcd /run/media/jobias/JOYEUSE/.rockbox/
sync
```

Then re-initialize on the device the slow way:
**Settings → General Settings → Database → Initialize now**

---

## Caveats

- **Upstream testing is narrow.** DAP-DB-Manager's author states it was tested
  only on an iPod Classic 7th Gen. The `erosqnative` target is not covered. The
  verification in Step 6 is *structural* — format, magic, version, path encoding,
  entry integrity. It cannot prove the device's parser accepts the file. The only
  real test is booting it, which is why Step 2 is mandatory.
- **Play counts and ratings are discarded** by `generate`. This currently costs
  nothing because `gather runtime data` is not enabled in `config.cfg`. If you
  ever turn it on, use `ddm update` instead, which preserves that data and also
  handles renames incrementally.
- **Album art is not indexed**, which is normal.
- Re-check the device facts table if you upgrade Rockbox — a tagcache version
  bump would invalidate this workflow.

---

## Upstream references

- [DAP-DB-Manager](https://github.com/vakintosh/DAP-DB-Manager) — the tool used here
- [Rockbox `tools/database/database.c`](https://git.rockbox.org/cgit/rockbox.git/tree/tools/database/database.c) — official PC tool; unusable here, see gotcha #1
- [FS#8499 — Building database from computer](https://www.rockbox.org/tracker/task/8499) — why the official tool is a skeleton
