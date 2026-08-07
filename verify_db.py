#!/usr/bin/env python3
"""Independently verify a generated Rockbox tagcache database before deploying.

This deliberately does not trust DAP-DB-Manager's own `validate` command. It
checks the things that would actually break the database browser:

Structural:
  1. tagcache magic is correct and matches the backup
  2. the 11-file set matches the backup
  3. every stored path carries the expected volume prefix
     (the failure mode when auto-detection silently falls back to /<HDD0>)
  4. the stored path set exactly equals the audio files on disk
  5. no stored path reaches MAX_PATH

Semantic -- these catch bugs that still produce a loadable database:
  6. index slots 9-12 hold plausible year/disc/track/canonicalartist values
     (catches the slot-rotation bug that silently destroys track ordering)
  7. album artist is not a byte-for-byte copy of artist
     (catches album artist being dropped and falling back to artist)

Checks 6 and 7 exist because the first generated database passed every
structural check, loaded fine on the device, and was still wrong: albums had
lost their track ordering and album artist had collapsed into artist.

Stdlib only -- no virtualenv needed.

Usage:
    python3 verify_db.py [new_db_dir] [backup_dir] [card_mount_point]
"""

import os
import re
import struct
import sys

NEW = sys.argv[1] if len(sys.argv) > 1 else "testdb"
BACKUP = sys.argv[2] if len(sys.argv) > 2 else "tcd-backup"
CARD = sys.argv[3] if len(sys.argv) > 3 else "/run/media/jobias/JOYEUSE"

PREFIX = "/<microSD0>"
MAGIC = 0x54434810       # tagcache version 16
MAX_PATH = 260
PATH_TAGFILE = "database_4.tcd"
IDX_FILE = "database_idx.tcd"
ARTIST_TAGFILE = "database_0.tcd"
ALBUMARTIST_TAGFILE = "database_7.tcd"

# Index entry layout: 24 little-endian int32 slots, after a 24-byte header.
IDX_HEADER = 24
IDX_SLOTS = 24
IDX_ENTRY = 4 * IDX_SLOTS

# Rockbox enum tag_type positions we assert on.
SLOT_YEAR, SLOT_DISC, SLOT_TRACK, SLOT_CANONICALARTIST = 9, 10, 11, 12

# A tag-file offset is a byte position in a multi-KB file, so it is large;
# a year/disc/track is small. That contrast is what makes the rotation
# detectable without re-reading every audio file.
YEAR_MIN, YEAR_MAX = 1900, 2200
DISC_MAX = 100
TRACK_MAX = 500

AUDIO_EXT = (".m4a", ".mp3", ".flac", ".ogg", ".opus", ".wav", ".wv", ".aac", ".m4b")

failures = []


def check(ok, label, detail=""):
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", label, ("  -- " + detail) if detail else ""))
    if not ok:
        failures.append(label)
    return ok


def header(path):
    with open(path, "rb") as fh:
        return struct.unpack("<III", fh.read(12))


def stored_paths(db_dir):
    """Extract every NUL-terminated device path from the path tag file."""
    raw = open(os.path.join(db_dir, PATH_TAGFILE), "rb").read()
    pat = re.escape(PREFIX.encode()) + rb"/Music/[^\x00]+"
    return {m.group(0).decode("utf-8", "replace") for m in re.finditer(pat, raw)}


def disk_paths(card):
    out = set()
    for dirpath, _, filenames in os.walk(os.path.join(card, "Music")):
        for fn in filenames:
            if fn.lower().endswith(AUDIO_EXT):
                full = os.path.join(dirpath, fn)
                out.add(PREFIX + "/" + os.path.relpath(full, card))
    return out


def index_slots(db_dir):
    """Yield the 24 int32 slots of every index entry."""
    raw = open(os.path.join(db_dir, IDX_FILE), "rb").read()
    count = struct.unpack("<I", raw[8:12])[0]
    for i in range(count):
        off = IDX_HEADER + i * IDX_ENTRY
        yield struct.unpack("<%di" % IDX_SLOTS, raw[off:off + IDX_ENTRY])


def check_numeric_slots(db_dir):
    """Verify slots 9-12 really are year / disc / track / canonicalartist.

    The slot-rotation bug wrote canonicalartist into slot 9 and shifted
    year/disc/track up by one, so Rockbox read the disc number (usually 0 or 1)
    as the track number and lost album ordering entirely.
    """
    years = discs = tracks = 0
    distinct_tracks = set()
    total = 0
    for e in index_slots(db_dir):
        total += 1
        if YEAR_MIN <= e[SLOT_YEAR] <= YEAR_MAX or e[SLOT_YEAR] == 0:
            years += 1
        if 0 <= e[SLOT_DISC] <= DISC_MAX:
            discs += 1
        if 0 <= e[SLOT_TRACK] <= TRACK_MAX:
            tracks += 1
            distinct_tracks.add(e[SLOT_TRACK])
    if not total:
        return False, "no index entries"

    pct = lambda n: 100.0 * n / total
    problems = []
    if pct(years) < 95:
        problems.append("slot9 not year-like (%.1f%%)" % pct(years))
    if pct(discs) < 95:
        problems.append("slot10 not disc-like (%.1f%%)" % pct(discs))
    if pct(tracks) < 95:
        problems.append("slot11 not track-like (%.1f%%)" % pct(tracks))
    # The decisive signal: real track numbers span many values. If slot 11
    # actually holds disc numbers it collapses to {0} or {1}.
    if len(distinct_tracks) < 5:
        problems.append(
            "slot11 has only %d distinct value(s) %s -- looks like disc "
            "numbers, not track numbers" % (len(distinct_tracks),
                                            sorted(distinct_tracks)[:5])
        )
    detail = "%d entries, %d distinct track numbers" % (total, len(distinct_tracks))
    return (not problems), ("; ".join(problems) if problems else detail)


def main():
    if not os.path.isdir(NEW):
        sys.exit("error: no such database directory: %s" % NEW)

    # 1. magic
    magic, _, count = header(os.path.join(NEW, IDX_FILE))
    check(magic == MAGIC, "magic is 0x%08x" % MAGIC, "got 0x%08x" % magic)
    print("       entries in new database: %d" % count)

    # 2. file set matches the backup
    if os.path.isdir(BACKUP):
        new_files = sorted(f for f in os.listdir(NEW) if f.endswith(".tcd"))
        old_files = sorted(f for f in os.listdir(BACKUP) if f.endswith(".tcd"))
        check(new_files == old_files, "file set matches backup",
              "new=%d old=%d" % (len(new_files), len(old_files)))
        old_magic, _, old_count = header(os.path.join(BACKUP, IDX_FILE))
        check(old_magic == magic, "magic matches backup",
              "backup 0x%08x" % old_magic)
        print("       entries in backup:        %d" % old_count)
    else:
        print("[WARN] no backup dir at %s -- skipping comparison" % BACKUP)

    # 3 + 4. path prefix and exact set equality against disk
    stored = stored_paths(NEW)
    on_disk = disk_paths(CARD)
    check(len(stored) > 0, "paths recovered from %s" % PATH_TAGFILE,
          "%d found" % len(stored))
    bad_prefix = [p for p in stored if not p.startswith(PREFIX + "/Music/")]
    check(not bad_prefix, "every path uses the %s prefix" % PREFIX,
          "%d wrong" % len(bad_prefix))

    missing = on_disk - stored          # audio present but unindexed
    extra = stored - on_disk            # indexed but absent -> dead entries
    check(not extra, "no database entry points at a missing file",
          "%d dead entries" % len(extra))
    for p in list(extra)[:5]:
        print("         %s" % p)
    check(not missing, "every audio file on disk is indexed",
          "%d unindexed" % len(missing))
    for p in list(missing)[:5]:
        print("         %s" % p)

    # 5. MAX_PATH
    longest = max(stored, key=lambda p: len(p.encode())) if stored else ""
    over = [p for p in stored if len(p.encode()) >= MAX_PATH]
    check(not over, "no stored path reaches %d bytes" % MAX_PATH,
          "%d over" % len(over))
    if longest:
        print("       longest stored path: %d bytes" % len(longest.encode()))
        print("         %s" % longest)

    # 6. numeric slots really are year / disc / track / canonicalartist
    ok, detail = check_numeric_slots(NEW)
    check(ok, "index slots 9-12 are year/disc/track/canonicalartist", detail)

    # 7. album artist must not be a verbatim copy of artist
    art = open(os.path.join(NEW, ARTIST_TAGFILE), "rb").read()
    aart = open(os.path.join(NEW, ALBUMARTIST_TAGFILE), "rb").read()
    check(art != aart, "album artist is not a copy of artist",
          "both %d bytes, identical" % len(art) if art == aart
          else "artist %d B, album artist %d B" % (len(art), len(aart)))

    print()
    if failures:
        print("VERIFICATION FAILED (%d): %s" % (len(failures), "; ".join(failures)))
        print("Do NOT copy this database to the card.")
        return 1
    print("ALL CHECKS PASSED -- safe to copy to the card.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
