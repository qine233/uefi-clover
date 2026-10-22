#!/usr/bin/env python3
"""Read the clover checkpoint ladder out of a photograph of the tablet screen.

The only output channel this unit has is the panel, and since round 13 the ladder is
positional: CheckpointDxe paints every protocol slot black at its own entry and
recolours a slot when the module that owns it appears.  What a boot answers is "which is
the first dark band", and twenty-seven bands cannot be described aloud, so the reading
comes from a photo.

  1. the frame is resampled and every row given a majority colour.  Bright runs are the
     lit bands.  An empty slot keeps the black the entry point painted, which in a photo
     is only a dip in how blue the row looks, and a camera vignette dips the same way, so
     those dips are printed for a human to cross-check (--debug) and are never scored.
  2. rows are mapped back to framebuffer offsets through a projective fit rather than a
     linear one.  A photo of a panel taken at an angle squeezes the far end: round 13's
     frame is 18.5 rows per band pitch at the top and 21 to 24 at the bottom, which by
     the last third of the ladder is a whole band of error -- enough to name the wrong
     module.  The green and magenta stages fix two anchors, and what is left is searched:
     the fit kept is the one that puts the detected bands on slot centres and makes their
     colours agree with the driver's own table.

The slot table is parsed from CheckpointDxe.c, so the script cannot drift out of sync
with the firmware.

Usage:  scripts/read-clover-photo.py /path/to/photo.jpeg [--width 600] [--debug]
"""

import argparse
import re
import struct
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
DRIVER = HERE.parent / "Platforms/Xiaomi/cloverPkg/Drivers/CheckpointDxe/CheckpointDxe.c"

# Stage 1 green (MemoryMapLib) and stage 3 magenta (CheckpointDxe's entry point) are two
# band pitches apart, which is the calibration.  Slot 0 of the table sits four pitches
# below the green anchor.
SLOT_ZERO_ABOVE_GREEN = 4

NAME_BY_COLOR = {
    "CLOVER_COLOR_GREEN": "green",
    "CLOVER_COLOR_YELLOW": "yellow",
    "CLOVER_COLOR_MAGENTA": "magenta",
    "CLOVER_COLOR_WHITE": "white",
    "CLOVER_COLOR_CYAN": "cyan",
    "CLOVER_COLOR_RED": "red",
    "CLOVER_COLOR_BLACK": "black",
}
LIT = ("yellow", "cyan", "red", "white")


def classify(r, g, b):
    """Name a pixel.  The thresholds are for a dim photo of an emissive panel: a lit
    colour is decided by which two of the three channels are high, and the unlit window
    reads as blue or as flat-dark."""
    hi, lo = max(r, g, b), min(r, g, b)
    if lo > 140 and hi - lo < 45:
        return "white"
    if g > 150 and r < 130 and b < 130:
        return "green"
    if r > 150 and g > 150 and b < 130:
        return "yellow"
    if r > 150 and b > 150 and g < 130:
        return "magenta"
    if g > 150 and b > 150 and r < 130:
        return "cyan"
    if r > 150 and g < 130 and b < 160:
        return "red"
    if b > 150 and r < 130 and g < 130:
        return "blue"
    if hi < 95 and (b - lo) < 26:
        return "black"
    return "background"


def load(src, width):
    """Return (grid, height, width); grid[row][col] is (r, g, b), top row first."""
    with tempfile.TemporaryDirectory() as tmp:
        bmp = Path(tmp) / "frame.bmp"
        subprocess.run(
            ["sips", "-s", "format", "bmp", "--resampleWidth", str(width), str(src),
             "--out", str(bmp)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        data = bmp.read_bytes()
    if data[:2] != b"BM":
        raise SystemExit("sips did not produce a BMP")
    _, _, _, pixoff, _, w, h, planes, bpp = struct.unpack_from("<IHHIIiiHH", data, 2)
    if bpp not in (24, 32) or planes != 1:
        raise SystemExit("unsupported BMP: %d bpp, %d planes" % (bpp, planes))
    topdown = h < 0
    h = abs(h)
    rowsz = ((w * bpp // 8) + 3) // 4 * 4
    step = bpp // 8
    grid = []
    for y in range(h):
        # A negative biHeight means the file already starts at the top row.
        sy = y if topdown else h - 1 - y
        off = pixoff + sy * rowsz
        grid.append([(data[off + x * step + 2], data[off + x * step + 1], data[off + x * step])
                     for x in range(w)])
    return grid, h, w


def slots(path):
    """Parse the driver's own table: { &Guid, 0xoffset, CLOVER_COLOR_X, "meaning" }."""
    out = []
    for m in re.finditer(
        r"\{\s*&(\w+),\s*(0x[0-9a-fA-F]+)\s*,\s*(CLOVER_COLOR_\w+)\s*,\s*\"([^\"]+)\"",
        path.read_text(encoding="utf-8")
    ):
        out.append({"guid": m.group(1), "off": int(m.group(2), 16),
                    "want": NAME_BY_COLOR[m.group(3)], "name": m.group(4)})
    if not out:
        raise SystemExit("no slot table found in %s" % path)
    return out


def ranges(rowcls, keep):
    out, y, h = [], 0, len(rowcls)
    while y < h:
        if rowcls[y] in keep:
            s = y
            while y < h and rowcls[y] == rowcls[s]:
                y += 1
            out.append((rowcls[s], s, y - 1))
        else:
            y += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("photo")
    ap.add_argument("--width", type=int, default=600)
    ap.add_argument("--driver", default=str(DRIVER))
    ap.add_argument("--debug", action="store_true")
    a = ap.parse_args()

    table = slots(Path(a.driver))
    grid, h, w = load(Path(a.photo), a.width)
    # Only the middle of the frame: the bezel, the desk and the Android footer are not
    # part of the ladder.
    cols = [int(0.22 * w + i * (0.56 * w) / 29) for i in range(30)]

    rowcls, blueness = [], []
    for y in range(h):
        px = [grid[y][x] for x in cols]
        blueness.append(sum(b - (r + g) / 2.0 for r, g, b in px) / len(px))
        votes = {}
        for r, g, b in px:
            c = classify(r, g, b)
            votes[c] = votes.get(c, 0) + 1
        best = max(votes, key=votes.get)
        rowcls.append(best if votes[best] * 2 >= len(px) else "mixed")

    anchors = {}
    for c, lo, hi in ranges(rowcls, {"green", "magenta"}):
        if hi - lo >= 1:
            anchors.setdefault(c, (lo + hi) / 2.0)
    if "green" not in anchors or "magenta" not in anchors:
        raise SystemExit("no green and magenta bands in this frame: the ladder never reached "
                         "CheckpointDxe, so there is nothing to line the rest up against")
    yg, ym = anchors["green"], anchors["magenta"]
    runs = [r for r in ranges(rowcls, set(LIT)) if r[2] - r[1] <= 40]
    print("frame %dx%d   green row %.1f   magenta row %.1f   %d other lit runs" %
          (w, h, yg, ym, len(runs)))
    for c, lo, hi in runs:
        print("   %-7s rows %4d-%4d  h=%2d" % (c, lo, hi, hi - lo + 1))

    # Rows come from framebuffer offsets through y = yg + B*u/(1 - k*u), u in band
    # pitches from the green anchor and B set by the magenta anchor.  Invert it for u and
    # score every (squeeze, scale, shift) against the table's colour column.
    def indices(k, scale, shift):
        b = (ym - yg) * (1.0 - 2.0 * k) / 2.0
        out = []
        for _c, lo, hi in runs:
            y = (lo + hi) / 2.0
            den = b + k * (y - yg)
            u = (y - yg) / den if den else 0.0
            out.append(int(round(scale * u + shift)) - SLOT_ZERO_ABOVE_GREEN)
        return out

    best = None
    for k in [i / 2000.0 for i in range(61)]:
        for scale in [0.94 + i / 200.0 for i in range(25)]:
            for shift in range(0, 12):
                idx = indices(k, scale, shift)
                if len(set(idx)) != len(idx):
                    continue
                score = sum(2 if 0 <= i < len(table) and table[i]["want"] == c else -1
                            for i, (c, _lo, _hi) in zip(idx, runs))
                if score > 0 and (best is None or score > best[0]):
                    best = (score, k, scale, shift)
    if best is None:
        raise SystemExit("no lit run could be placed on the ladder -- the anchors are lying, "
                         "or the frame is cropped through the middle of the ladder")

    score, k, scale, shift = best
    print("\nfit: squeeze k=%.4f  scale %.3f  shift %+d  colour score %d of %d" %
          (k, scale, shift, score, 2 * len(runs)))

    lit = {}
    for i, (c, lo, hi) in zip(indices(k, scale, shift), runs):
        if 0 <= i < len(table):
            b = (ym - yg) * (1.0 - 2.0 * k) / 2.0
            y = (lo + hi) / 2.0
            u = (y - yg) / (b + k * (y - yg))
            dev = abs((scale * u + shift) - SLOT_ZERO_ABOVE_GREEN - i)
            if dev > 0.35:
                print("   note: %s at rows %d-%d sits %.2f pitches off slot %d" % (c, lo, hi, dev, i))
            lit[i] = c

    print("\n%-11s %-7s %-10s %s" % ("offset", "expect", "state", "meaning"))
    dark = []
    for i, s in enumerate(table):
        got = lit.get(i)
        state = "dark" if not got else ("LIT" if got == s["want"] else "WRONG(%s)" % got)
        if not got:
            dark.append((i, s["off"], s["name"]))
        print("%#011x %-7s %-10s %s" % (s["off"], s["want"], state, s["name"]))

    if dark:
        print("\nfirst dark slot: index %d at %#011x  %s" % dark[0])
        if lit:
            print("deepest lit slot: index %d" % max(lit))
    else:
        print("\nevery slot lit")
    if a.debug:
        peak = max(blueness)
        dips = [(lo, hi) for _c, lo, hi in ranges(
            ["d" if blueness[y] < 0.72 * peak else "x" for y in range(h)], {"d"}) if hi - lo >= 1]
        print("\nblueness dips, candidates for empty slots (a vignette produces these too): %s" % dips)


if __name__ == "__main__":
    main()
