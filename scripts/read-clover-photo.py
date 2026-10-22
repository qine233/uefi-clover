#!/usr/bin/env python3
"""Read the clover checkpoint ladder out of a photograph of the tablet screen.

The only output channel this unit has is the panel, and since round 13 the ladder is
positional: CheckpointDxe paints every band black at its own entry and recolours a slot
when the protocol it names exists.  What a boot answers is "which is the first dark
band", and since round 14 there is a second reading below the slots -- seven yellow bands
carrying the firmware volume file index of the last image the DXE core loaded.  Neither
is something that can be described aloud, so the reading comes from a photo.

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
  3. the seven index bands are then sampled at the rows the fit predicts for them and
     decoded most-sign-bit-first, with the run detection printed alongside as a check.

Both tables are parsed from CheckpointDxe.c, so the script cannot drift out of sync with
the firmware.

Usage:  scripts/read-clover-photo.py /path/to/photo.jpeg [--width 600]
        [--modules fv-order.txt] [--debug]
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


def bits(path):
    """Parse the index bit table: { 0xoffset, N }.  Each row is one bit of the last
    loaded image's firmware volume file index, painted yellow when set and left black
    when clear, so it can be read as a colour like every other band."""
    out = []
    for m in re.finditer(r"\{\s*(0x[0-9a-fA-F]+)\s*,\s*(\d+)\s*\}",
                         path.read_text(encoding="utf-8")):
        out.append({"off": int(m.group(1), 16), "bit": int(m.group(2))})
    return out


def modules(path):
    """Index to module name, from the text scripts/fv-order.py prints."""
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].startswith("0x"):
            out[int(parts[0])] = parts[-1]
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
    ap.add_argument("--modules", help="text file of scripts/fv-order.py output, to name the "
                                      "index the bit bands decode to")
    ap.add_argument("--debug", action="store_true")
    a = ap.parse_args()

    table = slots(Path(a.driver))
    bitrows = bits(Path(a.driver))
    nslots = len(table)
    # The index bands continue the same slot numbering: the pitch is constant, so an
    # offset is a slot number by arithmetic.  Giving them rows here lets the fit below
    # use a lit index bit as evidence for its geometry exactly as it uses a lit protocol
    # slot, and a clear bit (black) is simply a row no run was detected on, which costs
    # the score nothing.
    for row in bitrows:
        table.append({"guid": None, "off": row["off"], "want": "yellow",
                      "name": "index bit %d, value %d" % (row["bit"], 1 << row["bit"])})

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
    for i, s in enumerate(table[:nslots]):
        got = lit.get(i)
        state = "dark" if not got else ("LIT" if got == s["want"] else "WRONG(%s)" % got)
        if not got:
            dark.append((i, s["off"], s["name"]))
        print("%#011x %-7s %-10s %s" % (s["off"], s["want"], state, s["name"]))

    if dark:
        print("\nfirst dark slot: index %d at %#011x  %s" % dark[0])
        if lit:
            print("deepest lit slot: index %d" % max(i for i in lit if i < nslots))
    else:
        print("\nevery slot lit")

    if bitrows:
        # Sample each band at the row the fit predicts for its offset and decide it on
        # the spot: a bit is a one-of-two question (yellow or not), so this does not
        # need the run detection to have found it, and the two readings printed side by
        # side show which one the frame is actually supporting.
        b = (ym - yg) * (1.0 - 2.0 * k) / 2.0
        print("\n%-11s %-5s %-9s %-6s %s" % ("offset", "bit", "sample", "value", "check"))
        index = 0
        for j, row in enumerate(bitrows):
            i = nslots + j
            u = (i + SLOT_ZERO_ABOVE_GREEN - shift) / scale
            y = int(round(yg + b * u / (1.0 - k * u))) if (1.0 - k * u) > 0 else -1
            votes = {}
            for yy in range(max(0, y - 3), min(h, y + 4)):
                c = rowcls[yy]
                if c not in ("mixed", "background", "blue"):
                    votes[c] = votes.get(c, 0) + 1
            seen = max(votes, key=votes.get) if votes else "nothing"
            val = 1 if seen == "yellow" else 0
            det = 1 if lit.get(i) == "yellow" else 0
            index += val << row["bit"]
            print("%#011x bit %-3s %-9s %-6d %s" %
                  (row["off"], row["bit"], seen, val,
                   "" if val == det else "run detection says %d" % det))
        named = modules(Path(a.modules)) if a.modules else {}
        if index == 0:
            print("\nlast image loaded: none since CheckpointDxe, or its file was not in "
                  "the list built at entry")
        else:
            print("\nlast image loaded: FVMAIN file %d  %s" %
                  (index, named.get(index, "(run scripts/fv-order.py and pass --modules)")))

    if a.debug:
        peak = max(blueness)
        dips = [(lo, hi) for _c, lo, hi in ranges(
            ["d" if blueness[y] < 0.72 * peak else "x" for y in range(h)], {"d"}) if hi - lo >= 1]
        print("\nblueness dips, candidates for empty slots (a vignette produces these too): %s" % dips)


if __name__ == "__main__":
    main()
