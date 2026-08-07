# Path length limits on JOYEUSE

Background for `check_path_lengths.py`, and a record of what was already fixed.

## The limit

Rockbox's `MAX_PATH` is **260 bytes**. Buffers are declared `char path[MAX_PATH]`,
so the usable string is 259 bytes plus a NUL terminator.

Two things make this stricter than it first appears.

**The volume prefix.** Rockbox addresses this card as `/<microSD0>`, not `/`.
Every stored path looks like `/<microSD0>/Music/Artist/Album/Track.m4a`. That
prefix is 11 bytes off the top, leaving **248 bytes** for the `/Music/...`
portion you actually control.

**Bytes, not characters.** The limit is bytes, and filenames are stored as UTF-8.
Any non-ASCII character costs two bytes or more. This is not hypothetical here —
see the Beethoven case below, where a 246-character name occupies 257 bytes.

## The `#` characters in filenames

Names across the library contain `#` where you would expect punctuation:
`No_Man#s_Sky`, `T#SQUARE`, `Claude#Michel_Schonberg`, and whole directories
named `####`.

These are **literal `0x23` bytes on disk**, not a mount-time substitution. Verified
with `hexdump` and by successfully listing inside those directories — a kernel
substitution would not round-trip and the paths would fail to open.

The pattern: every `#` replaces a character outside ISO-8859-1. Curly quotes
(`'`, `"`), en dashes (`-`), and all CJK get replaced; characters that *are* in
Latin-1 survive intact (`o`, `a`, `e`, `ss`, guillemets). Whatever tagged the
library restricted output to Latin-1.

Consequence: `####` directories are *shorter* than the names they stand in for,
so they help rather than hurt the byte budget. But they also mean you cannot
recover the original artist name from the path alone — the tags still have it.

## Fixes applied 2026-08-07

The audit found 6 files over 260 bytes. All were fixed by shortening two album
directories and one filename; no tags were modified, so full titles and credits
still display correctly on the device.

| | Before | After | Saved |
|---|---|---|---|
| Wajazz album dir | `WaJazz_Japanese_Jazz_Spectacle_Vol.I_-_Deep,_Heavy_and_Beautiful_Jazz_from_Japan_1968-1984_-_The_Nippon_Columbia_Masters_-_Selected_by_Yusuke_Ogawa_(Universounds)` | `WaJazz_Japanese_Jazz_Spectacle_Vol.I` | 147 B x 14 tracks |
| Plasma Cutter album dir | `III_Swords_And_Potions_And_Crystals_And_Sweet_Tea_And_Flowers_And_Spell_Scrolls_And_Drawings_Of_Dogs_And_Some_Songs` | `III_Swords_And_Potions` | 92 B x 11 tracks |
| Mustin track | `14_Dancing_Mad_feat._Eli_Bishop,_...,_Tony_Dickinson_&_Kyle_Sawaia.m4a` | `14_Dancing_Mad.m4a` | 200 B |

Both directory renames are true prefixes of the real album titles rather than
invented abbreviations. The Mustin filename now matches its siblings in that
album (`13_Gogo.m4a`, `11_Strago.m4a`).

Result: longest path in the library went from **299 bytes to 257 bytes**.

## Fixes applied 2026-08-07 (second pass, Triforce Quartet)

Adding `Triforce_Quartet/` brought in 3 files over the limit, all in
`Ultima_Phantasia/`. That directory is already short — 52 bytes with the volume
prefix — leaving a 207-byte filename budget, and the names were 216/216/250.
So the folder was not the lever here; the filenames had to come down.

Fixed by dropping the repeated `(From ''Final Fantasy N'')` annotations, which
are redundant when the medley title already says Final Fantasy. Every track
title inside the medleys was preserved.

| Track | Before | After |
|---|---|---|
| 02 Boss Medley | 268 B | 153 B |
| 08 Medley Pt. 1 | 268 B | 155 B |
| 09 Medley Pt. 2 | 302 B | 181 B |

Note track 09's original name ended `_-_A.m4a` — already truncated mid-title by
whatever produced it. That dangling fragment was dropped.

**Left inconsistent on purpose:** track 10 (`Medley, Pt. 3 of 3`) is 214 bytes,
under the limit, so it keeps its full `(From ''...'')` annotations while tracks
02/08/09 no longer have them. Normalising all four would be tidier but was not
required. Tags are untouched throughout, so full titles still display on device.

## Known remaining tight cases

Under the limit, but with little headroom. Worth remembering if you reorganize.

| Bytes | File |
|---|---|
| 257 | Beethoven `9_Symphonien/38_-_Symphonie_Nr._9 ... An_die_Freude.m4a` |
| 247 | Joe Hisaishi `A_Symphonic_Celebration.../19_-_Ponyo's_Sisters_Lend_a_Hand...m4a` |
| 241 | Beethoven `9_Symphonien/21_-_Symphonie_Nr._6 ... Allegro_ma_non_troppo.m4a` |
| 240 | OverClocked ReMix `TimeShift.../19_-_Children_of_Light...m4a` |
| 240 | OverClocked ReMix `Speeding_Towards_Adventures.../01_-_Gotta_Start_From_Somewhere...m4a` |

The Beethoven finale is the instructive one: **246 characters but 257 bytes**,
because the guillemets and umlauts each cost an extra byte. It is also hard to
shrink further — the 143-character filename is a legitimate movement title, and
its parent directory is already short.

## Rules of thumb

- Shorten the **album directory** first. One rename fixes every track in it.
- Truncate long `feat. ...` lists out of filenames. The credits live in the tags
  and still display on the device.
- Prefer truncating a real title to a prefix over inventing an abbreviation —
  it keeps sorting and recognition intact.
- Re-run `check_path_lengths.py` after any bulk re-tag or re-sync, and always
  before regenerating the database.
