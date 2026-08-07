#!/usr/bin/env python3
"""Audit a Rockbox music library for paths that exceed MAX_PATH.

Rockbox's MAX_PATH is 260 bytes. What counts is the path as the *device* sees
it, which on this card is prefixed with the volume notation `/<microSD0>` --
11 bytes that are easy to forget. Lengths are measured in UTF-8 *bytes*, not
characters: accented letters, guillemets and similar cost two bytes each, so a
name that looks short enough by character count can still overflow.

Stdlib only -- no virtualenv needed.

Usage:
    python3 check_path_lengths.py [card_mount_point]
"""

import os
import sys

CARD = sys.argv[1] if len(sys.argv) > 1 else "/run/media/jobias/JOYEUSE"
PREFIX = "/<microSD0>"   # Rockbox volume notation; see README gotcha #1
MAX_PATH = 260           # Rockbox MAX_PATH, in bytes

AUDIO_EXT = (".m4a", ".mp3", ".flac", ".ogg", ".opus", ".wav", ".wv", ".aac", ".m4b")

# Report bands: (label, low, high) in bytes
BANDS = [
    ("OVER LIMIT   (>= %d bytes)" % MAX_PATH, MAX_PATH, 10 ** 9),
    ("AT THE EDGE  (250-%d bytes)" % (MAX_PATH - 1), 250, MAX_PATH),
    ("TIGHT MARGIN (240-249 bytes)", 240, 250),
]


def device_paths(card):
    """Yield (byte_length, device_path) for every file under <card>/Music."""
    music = os.path.join(card, "Music")
    if not os.path.isdir(music):
        sys.exit("error: no Music directory under %s" % card)
    for dirpath, _, filenames in os.walk(music):
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            dev = PREFIX + "/" + os.path.relpath(full, card)
            yield len(dev.encode("utf-8")), dev


def main():
    rows = sorted(device_paths(CARD), reverse=True)
    audio = [r for r in rows if r[1].lower().endswith(AUDIO_EXT)]

    print("card:    %s" % CARD)
    print("prefix:  %s (%d bytes)" % (PREFIX, len(PREFIX)))
    print("files:   %d  (audio: %d)" % (len(rows), len(audio)))
    print("longest: %d bytes\n" % (rows[0][0] if rows else 0))

    over = 0
    for label, lo, hi in BANDS:
        sel = [r for r in rows if lo <= r[0] < hi]
        if lo == MAX_PATH:
            over = len(sel)
        print("== %s : %d files ==" % (label, len(sel)))
        for b, p in sel:
            print("  %3d  %s" % (b, p))
        print()

    if over:
        print("FAIL: %d file(s) over the %d-byte limit." % (over, MAX_PATH))
        print("Shorten an album directory name to fix a whole album at once.")
        return 1
    print("PASS: nothing over the %d-byte limit." % MAX_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
