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
     The rows are read from a narrow vertical strip, not across the screen: a band is a
     straight line on the panel but a slanted one in a hand-held photo, and round 14's
     frame slants by tens of rows from edge to edge, so sampling six-tenths of the width
     mixes the band into the gap beside it and no row ever wins a majority.
  2. rows are mapped back to framebuffer offsets through a projective fit rather than a
     linear one.  A photo of a panel taken at an angle squeezes the far end: round 13's
     frame is 18.5 rows per band pitch at the top and 21 to 24 at the bottom, which by
     the last third of the ladder is a whole band of error -- enough to name the wrong
     module.  The green and magenta stages fix two anchors, and what is left is searched:
     the fit kept is the one that puts the detected bands on slot centres and makes their
     colours agree with the driver's own table.
  3. the seven index bands are then sampled at the rows the fit predicts for them and
     decoded most-sign-bit-first, with the run detection printed alongside as a check,
     and the three mark bands under them are printed last: they say whether that number
     is live or whether the meter simply never matched a file to a load.

All three tables are parsed from CheckpointDxe.c, so the script cannot drift out of sync
with the firmware, and the ladder position of every band is derived from its offset rather
than from the order the tables appear in.

Usage:  scripts/read-clover-photo.py /path/to/photo.jpeg [--width 600]
        [--center 0.50] [--span 0.12] [--modules fv-order.txt] [--debug]
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
        out.append({"off": int(m.group(1), 16), "bit": int(m.group(2)),
                    "want": "yellow",
                    "name": "index bit %d, worth %d" % (int(m.group(2)), 1 << int(m.group(2)))})
    return out


def marks(path):
    """Parse the mark table: { 0xoffset, CLOVER_COLOR_X, "what it proves" }.  These bands
    are painted by the driver itself rather than by a protocol appearing, and they say
    whether the index above them is live or simply never matched anything."""
    out = []
    for m in re.finditer(r"\{\s*(0x[0-9a-fA-F]+)\s*,\s*(CLOVER_COLOR_\w+)\s*,\s*\"([^\"]+)\"",
                         path.read_text(encoding="utf-8")):
        out.append({"off": int(m.group(1), 16), "want": NAME_BY_COLOR[m.group(2)],
                    "name": m.group(3)})
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
    ap.add_argument("--center", type=float, default=0.50,
                    help="where across the frame to read the bands, as a fraction of the width")
    ap.add_argument("--span", type=float, default=0.12,
                    help="how wide that reading strip is, as a fraction of the width")
    ap.add_argument("--driver", default=str(DRIVER))
    ap.add_argument("--modules", help="text file of scripts/fv-order.py output, to name the "
                                      "index the bit bands decode to")
    ap.add_argument("--debug", action="store_true")
    a = ap.parse_args()

    slot_rows = slots(Path(a.driver))
    bit_rows = bits(Path(a.driver))
    mark_rows = marks(Path(a.driver))

    # Band numbers come from the offsets, not from the order the three tables happen to
    # be written in: slot 0 is the first protocol band and every band below it sits one
    # pitch lower, so a band inserted in the middle moves the rest instead of quietly
    # mislabelling the photograph.  All three tables share the ladder this way, which is
    # also what lets the fit use a lit mark or a lit index bit as evidence for its
    # geometry exactly as it uses a lit protocol slot.
    pitch = slot_rows[1]["off"] - slot_rows[0]["off"]
    base = slot_rows[0]["off"]
    ladder = {}
    for kind, rows, forced in (("slot", slot_rows, None), ("bit", bit_rows, "yellow"),
                               ("mark", mark_rows, None)):
        for entry in rows:
            if (entry["off"] - base) % pitch:
                raise SystemExit("the %s band at %#x is not on the %#x pitch the ladder uses"
                                 % (kind, entry["off"], pitch))
            index = (entry["off"] - base) // pitch
            if index in ladder:
                raise SystemExit("two bands claim ladder position %d" % index)
            ladder[index] = {"kind": kind, "off": entry["off"],
                             "want": forced or entry["want"], "name": entry["name"],
                             "bit": entry.get("bit")}

    grid, h, w = load(Path(a.photo), a.width)

    def read_strip(center, span):
        """Majority colour of each row inside a narrow strip, plus how blue each row is.

        Only the middle of the frame by default: the bezel, the desk and the Android
        footer are not part of the ladder.
        """
        cols = [int((center - span / 2.0) * w + i * (span * w) / 29.0) for i in range(30)]
        cols = [min(max(c, 0), w - 1) for c in cols]
        classes, blue = [], []
        for y in range(h):
            px = [grid[y][x] for x in cols]
            blue.append(sum(b - (r + g) / 2.0 for r, g, b in px) / len(px))
            votes = {}
            for r, g, b in px:
                c = classify(r, g, b)
                votes[c] = votes.get(c, 0) + 1
            best = max(votes, key=votes.get)
            classes.append(best if votes[best] * 2 >= len(px) else "mixed")
        return classes, blue

    def anchors_of(classes):
        found = {}
        for c, lo, hi in ranges(classes, {"green", "magenta"}):
            if hi - lo >= 1:
                found.setdefault(c, (lo + hi) / 2.0)
        return found

    # If the requested strip lands on the bezel or on a reflection, the anchors simply
    # are not there; slide across the panel a little at a time rather than giving up,
    # because a hand-held frame can put the ladder anywhere in it.
    rowcls, blueness, anchors = None, None, {}
    for center in [a.center] + [c for c in (0.50, 0.42, 0.58, 0.34, 0.66) if c != a.center]:
        rowcls, blueness = read_strip(center, a.span)
        anchors = anchors_of(rowcls)
        if "green" in anchors and "magenta" in anchors:
            if center != a.center:
                print("read from a strip centred at %.2f of the width, not %.2f" %
                      (center, a.center))
            break
    if "green" not in anchors or "magenta" not in anchors:
        raise SystemExit("no green and magenta bands in this frame: the ladder never reached "
                         "CheckpointDxe, so there is nothing to line the rest up against (or "
                         "every reading strip fell on the bezel -- try --center, with --debug "
                         "to see what the rows looked like)")
    yg, ym = anchors["green"], anchors["magenta"]
    runs = [r for r in ranges(rowcls, set(LIT)) if r[2] - r[1] <= 40]
    print("frame %dx%d   green row %.1f   magenta row %.1f   %d other lit runs" %
          (w, h, yg, ym, len(runs)))
    for c, lo, hi in runs:
        print("   %-7s rows %4d-%4d  h=%2d" % (c, lo, hi, hi - lo + 1))

    # Rows come from framebuffer offsets through y = yg + B*u/(1 - k*u), u in band
    # pitches from the green anchor and B set by the magenta anchor.  Invert it for u and
    # score every (squeeze, scale, shift) against the table's colour column.
    def pitches(k):
        """Each lit run's centre, in band pitches below the green anchor."""
        b = (ym - yg) * (1.0 - 2.0 * k) / 2.0
        out = []
        for _c, lo, hi in runs:
            y = (lo + hi) / 2.0
            den = b + k * (y - yg)
            out.append((y - yg) / den if den else 0.0)
        return out

    def indices(k, scale, shift):
        return [int(round(scale * u + shift)) - SLOT_ZERO_ABOVE_GREEN for u in pitches(k)]

    # Colour agreement alone cannot pick the fit: most of the ladder wants cyan, so sliding
    # the whole reading by one band scores exactly as well as the true one -- and round 14's
    # first search stopped on such a shifted fit, which put every sampled row in the gap
    # between two bands.  Being on the right slot is worth more than being on the right
    # colour, so the distance from a slot centre comes off the score and breaks the tie.
    best = None
    for k in [i / 2000.0 for i in range(61)]:
        us = pitches(k)
        for scale in [0.94 + i / 200.0 for i in range(25)]:
            for shift in range(0, 12):
                placed = [scale * u + shift for u in us]
                idx = [int(round(p)) - SLOT_ZERO_ABOVE_GREEN for p in placed]
                if len(set(idx)) != len(idx):
                    continue
                dev = sum(abs(p - SLOT_ZERO_ABOVE_GREEN - i) for p, i in zip(placed, idx))
                score = sum(2 if ladder.get(i, {}).get("want") == c else -1
                            for i, (c, _lo, _hi) in zip(idx, runs)) - 4.0 * dev
                if score > 0 and (best is None or score > best[0]):
                    best = (score, k, scale, shift)
    if best is None:
        raise SystemExit("no lit run could be placed on the ladder -- the anchors are lying, "
                         "or the frame is cropped through the middle of the ladder")

    score, k, scale, shift = best
    print("\nfit: squeeze k=%.4f  scale %.3f  shift %+d  score %.1f (colour %d of %d)" %
          (k, scale, shift, score,
           sum(2 for i, (c, _l, _h) in zip(indices(k, scale, shift), runs)
               if ladder.get(i, {}).get("want") == c), 2 * len(runs)))

    pitch_b = (ym - yg) * (1.0 - 2.0 * k) / 2.0

    def row_of(i):
        """The frame row the fit predicts for slot index i, or -1 if it is off the frame."""
        u = (i + SLOT_ZERO_ABOVE_GREEN - shift) / scale
        den = 1.0 - k * u
        if den <= 0:
            return -1
        return int(round(yg + pitch_b * u / den))

    def sample(i, half=3):
        """Vote the strip's colour at the predicted row of a slot, ignoring rows that
        merely came out mixed.  This is what tells a band painted black at entry (dark)
        from a place where the ladder never was (still the blue BootShim filled) and from
        a slot the fit put outside the photographed panel."""
        y = row_of(i)
        if y < 0 or y >= h:
            return y, "off-frame"
        votes = {}
        for yy in range(max(0, y - half), min(h, y + half + 1)):
            c = rowcls[yy]
            if c not in ("mixed",):
                votes[c] = votes.get(c, 0) + 1
        if not votes:
            return y, "mixed"
        return y, max(votes, key=votes.get)

    lit = {}
    for i, (c, lo, hi) in zip(indices(k, scale, shift), runs):
        if i in ladder:
            b = (ym - yg) * (1.0 - 2.0 * k) / 2.0
            y = (lo + hi) / 2.0
            u = (y - yg) / (b + k * (y - yg))
            dev = abs((scale * u + shift) - SLOT_ZERO_ABOVE_GREEN - i)
            if dev > 0.35:
                print("   note: %s at rows %d-%d sits %.2f pitches off band %d" % (c, lo, hi, dev, i))
            lit[i] = c

    def report(kind, label):
        """Print every band of one kind, decided by the fit and by what the strip shows at
        the row the fit predicts.  A band the run detection found and a band sampled on
        its own row usually agree; when they do not, both readings are printed."""
        print("\n%s" % label)
        print("%-11s %-7s %-10s %-9s %s" % ("offset", "expect", "state", "seen", "meaning"))
        out = []
        for i in sorted(ladder):
            s = ladder[i]
            if s["kind"] != kind:
                continue
            _y, seen = sample(i)
            got = lit.get(i) or (seen if seen in LIT else None)
            state = "dark" if not got else ("LIT" if got == s["want"] else "WRONG(%s)" % got)
            if kind == "slot" and not got:
                out.append((i, s["off"], s["name"]))
            print("%#011x %-7s %-10s %-9s %s" % (s["off"], s["want"], state, seen, s["name"]))
        return out

    dark = report("slot", "protocol slots:")
    if dark:
        print("\nfirst dark slot: index %d at %#011x  %s" % dark[0])
        lit_slots = [i for i in lit if i in ladder and ladder[i]["kind"] == "slot"]
        if lit_slots:
            print("deepest lit slot: index %d" % max(lit_slots))
    else:
        print("\nevery slot lit")

    if bit_rows:
        # Sample each band at the row the fit predicts for its offset and decide it on
        # the spot: a bit is a one-of-two question (yellow or not), so this does not
        # need the run detection to have found it, and the two readings printed side by
        # side show which one the frame is actually supporting.
        print("\nlast loaded image, as a number:")
        print("%-11s %-5s %-8s %-9s %-6s %s" %
              ("offset", "bit", "row", "sample", "value", "check"))
        index = 0
        for i in sorted(ladder):
            s = ladder[i]
            if s["kind"] != "bit":
                continue
            y, seen = sample(i)
            val = 1 if seen == "yellow" else 0
            det = 1 if lit.get(i) == "yellow" else 0
            index += val << s["bit"]
            print("%#011x bit %-3s %-8s %-9s %-6d %s" %
                  (s["off"], s["bit"], y, seen, val,
                   "" if val == det else "run detection says %d" % det))
        named = modules(Path(a.modules)) if a.modules else {}
        if index == 0:
            print("\nlast image loaded: nothing the meter could name -- read the marks below "
                  "before believing this")
        else:
            print("\nlast image loaded: FVMAIN file %d  %s" %
                  (index, named.get(index, "(run scripts/fv-order.py and pass --modules)")))

    if mark_rows:
        report("mark", "what the meter says about itself:")

    if a.debug:
        peak = max(blueness)
        dips = [(lo, hi) for _c, lo, hi in ranges(
            ["d" if blueness[y] < 0.72 * peak else "x" for y in range(h)], {"d"}) if hi - lo >= 1]
        print("\nblueness dips, candidates for empty slots (a vignette produces these too): %s" % dips)


if __name__ == "__main__":
    main()
