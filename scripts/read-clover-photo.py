#!/usr/bin/env python3
"""Read the clover checkpoint ladder out of a photograph of the tablet screen.

The only output channel this unit has is the panel, and since round 13 the ladder is
positional: CheckpointDxe paints every band black at its own entry and recolours a slot
when the protocol it names exists.  What a boot answers is "which is the first dark
band", and since round 14 there is a second reading below the slots -- seven yellow bands
carrying the firmware volume file index of the last image the DXE core loaded, and since
round 15 three marks under them saying whether that number is live.  None of it is
something that can be described aloud, so the reading comes from a photo.

  1. the frame is turned so that the ladder runs top to bottom.  On the panel the bars are
     stripes across the short axis, so a tablet lying on a desk and photographed the way a
     phone is held puts them across the long one -- round 15's frame did.  Every
     orientation is tried and the one that explains the most bands wins, which means the
     photo can be sent exactly as it came out of the phone.
  2. the frame is resampled and every row given a majority colour, inside a narrow
     vertical strip rather than across the screen: a band is a straight line on the panel
     but a slanted one in a hand-held photo, and round 14's frame slants by tens of rows
     from edge to edge, so averaging over six-tenths of the width mixes each band into the
     gap beside it and no row ever wins a majority.
  3. the bands are lined up with the driver's table.  What makes this reliable is that the
     entry-point black pass paints the slots that never lit as well: a dark band is a
     *marked position* on the ladder rather than an absence, so the black runs are used as
     evidence for the geometry exactly like the coloured ones.  Round 14 fitted only the
     lit runs against a colour column and could land one band out; round 15's frame has
     twenty-six consecutive bands, lit and black together, and they pin the spacing by
     themselves.  The spacing is not constant -- across a hand-held frame the pitch grows
     by about a tenth of a band from the top of the ladder to the bottom -- so the model
     is row = green + p0 * (n + g*n*(n-1)/2), n being pitches below the green stage, p0
     fixed by the magenta anchor and the growth g searched.
  4. every band is then read twice, once from the run it belongs to and once at the row
     the geometry predicts for its offset, and both are printed, so a fit that had drifted
     shows up as the two columns disagreeing rather than as a confident wrong name.

All three tables are parsed from CheckpointDxe.c, so the script cannot drift out of sync
with the firmware, and the ladder position of every band is derived from its offset rather
than from the order the tables appear in.

Usage:  scripts/read-clover-photo.py /path/to/photo.jpeg [--width 600] [--rotate 90]
        [--center 0.50] [--span 0.12] [--modules fv-order.txt] [--debug]
"""

import argparse
import math
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
# The stage bands are not in the table; they are what the geometry is anchored to, and
# the only two of them that can be identified before the fit is known.
STAGES = {-4: "green", -2: "magenta"}
# A slot the entry point painted and nothing recoloured is a band like any other, and the
# camera shows it as a short dark run between two stretches of the blue BootShim fill.
BAND = set(LIT) | {"green", "magenta", "black"}


def classify(r, g, b):
    """Name a pixel.  The thresholds are for a dim photo of an emissive panel: a lit
    colour is decided by which two of the three channels are high, and the unlit window
    reads as blue or as flat-dark."""
    hi, lo = max(r, g, b), min(r, g, b)
    # White is the only band with no dead channel: yellow paints blue off, cyan paints red
    # off, magenta paints green off.  The old test asked for three channels that agree to
    # within 45, which is what a *dim* white looks like, and this camera does not always
    # render white dim -- round 15's own-file mark measured (92,235,254) and only read as
    # lit because the want-based fallback rescued it from "cyan", while the round-17 frame
    # measures (150,250,250) at the same brightness and fell all the way through to
    # "background", which cost the reading of the handler mark.  So: three channels high
    # with no dead one, which a yellow-over-blue blend at (100,180,190) still is not.
    if (lo > 140 and hi - lo < 45) or (lo > 120 and hi > 180):
        return "white"
    # Yellow is the one colour this camera renders dim: the panel paints 0xFFFF00 and the
    # round-16 frame measures (134,255,23) to (141,251,33) on the index bands, so an
    # r > 150 test called them "background" and the meter read zero while its own marks
    # said it was live.  What separates yellow from every other band here is a high G
    # with a mid-to-high R and a dead blue, so that is the test -- and it has to come
    # *before* green, because the run's darker rows (124,255,14) would otherwise be
    # claimed by green, whose own anchor is (0,228,79) with essentially no red in it.
    if g > 150 and r > 100 and b < 130:
        return "yellow"
    if g > 150 and r < 130 and b < 130:
        return "green"
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


def load(src, width, rotate=0):
    """Return (grid, height, width); grid[row][col] is (r, g, b), top row first.

    sips turns the frame before resampling it, into a temporary copy.  Everything below
    reads the picture only through this function, so asking for an orientation here is what
    lets the row and column fractions mean the same thing however the photo was held.
    """
    with tempfile.TemporaryDirectory() as tmp:
        cur = Path(src)
        if rotate:
            turned = Path(tmp) / "turned.png"
            subprocess.run(
                ["sips", "--rotate", str(rotate), str(src), "--out", str(turned)],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            cur = turned
        bmp = Path(tmp) / "frame.bmp"
        subprocess.run(
            ["sips", "-s", "format", "bmp", "--resampleWidth", str(width), str(cur),
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


def blob_map(path, page):
    """The halt sites scripts/scan-clover-spins.py found on one page of a loaded blob.

    A page number is only worth the listing behind it: page 11 of `ClockDxe` is not a
    count, it is `HALclkHuayraPLLTemplate.c:622` and the twenty-one other self-branches
    sharing that page.  Absence is an answer too, and a different one -- a tick that
    lands on a page the scan lists no sites for is inside a loop that has an exit, not
    inside a halt, so say that rather than complaining about the file.
    """
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except (IOError, OSError) as exc:
        return ["  cannot read %s: %s" % (path, exc)]

    want = "PAGE %2d " % page
    start = next((k for k, l in enumerate(lines) if l.startswith(want)), None)
    if start is None:
        row = next((l for l in lines if l.startswith("pages this module can paint:")), "")
        pages = re.findall(r"\d+", row.split(":", 1)[1]) if row else []
        if pages:
            return ["\npage %d lists no sites in %s, whose sites are on pages %s -- so the tick "
                    "is not on a `b .` halt or a counter-free poll of this blob. That is a loop "
                    "with an exit, or code outside the module; it is not the assert halt the "
                    "other pages name." % (page, path, ", ".join(pages))]
        return ["\nno PAGE %d entry in %s -- regenerate it with scripts/scan-clover-spins.py"
                % (page, path)]

    out = ["\n%s line %d:" % (path, start + 1), lines[start]]
    for l in lines[start + 1:]:
        if not l.startswith("    0x"):
            break
        out.append(l)
    # The polls live in their own section at the foot of the file, keyed by the same
    # page marker, and they are the sites a tick can be caught in mid-loop rather than
    # at a halt, so they belong under the same answer.
    polls = [l for l in lines if l.startswith("    0x") and want in l]
    if polls:
        out.append("    counter-free hardware bit polls on this page:")
        out.extend(polls)
    if any("[no signature]" in l for l in out):
        out.append("    one row above has no ASSERT() signature, which is what CpuDeadLoop() "
                   "compiles to -- so a tick on this page is also consistent with an assert "
                   "having parked the CPU, and the five bits cannot tell that halt from the "
                   "page's other sites")
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


def read_strip(grid, h, w, center, span):
    """Majority colour of each row inside a narrow strip, plus how blue each row is.

    Only a slice of the frame: the bezel, the desk and the fastboot footer are not part of
    the ladder, and a band slanted across the frame has to be crossed at one place rather
    than averaged over.
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


def bands_of(classes):
    """Every band in the frame, lit or painted black, as (centre row, colour).

    The height window is what keeps the reading honest: a band is half a pitch, so a run
    one or two rows tall is slant noise at an edge and a run of sixty is the bezel or the
    black outside the panel.  Neither belongs on the ladder.
    """
    out = []
    for c, lo, hi in ranges(classes, BAND):
        if 3 <= hi - lo + 1 <= 40:
            out.append(((lo + hi) / 2.0, c))
    return out


def faults(path, table="mFaultBits"):
    """Parse one of the borrowed-row tables: { N, CLOVER_COLOR_X, "what it says" }, where
    N is a row of the protocol slot table rather than an offset.

    Round 17 borrows the seven slot rows below the clock, because a boot that stops inside
    a driver never reaches those protocols and their bands are dark on every screen that
    can carry a fault.  So a fault row has no offset of its own and no ladder position: it
    is read where its slot band already sits, and the name printed for that band is the
    protocol *and* the fault, with the mark at the bottom of the ladder saying which of the
    two meanings the photograph is showing.  Green and magenta never appear here, and that
    is not a coincidence -- those two colours are what the fit is anchored on, and a second
    band of either would move the geometry.

    Round 18 borrows the same seven rows a third time, for a timer tick's program counter,
    and says so in `mTickBits`.  Which of the two a photograph shows is decided by colour
    rather than by assumption: the fault layer's first row is red and the tick's page bits
    are yellow, and the row at +0x4C0000 is white for the tick and cyan for a translation
    fault.  Both tables are parsed here and the reader picks.
    """
    rows = slots(path)
    src = path.read_text(encoding="utf-8")
    head = src.find(table + "[] = {")
    if head < 0:
        return []
    body = src[head:src.find("\n};", head)]
    out = []
    for m in re.finditer(r"\{\s*(\d+)\s*,\s*(CLOVER_COLOR_\w+)\s*,\s*\"([^\"]+)\"", body):
        row = int(m.group(1))
        if row >= len(rows):
            raise SystemExit("a %s row names slot %d and the table has %d" % (table, row, len(rows)))
        out.append({"off": rows[row]["off"], "row": row,
                    "want": NAME_BY_COLOR[m.group(2)], "name": m.group(3)})
    return out


def build_ladder(driver):
    """Number the bands from their offsets, for all three tables at once: slot 0 is the
    first protocol band and every band below it sits one pitch lower, so a band inserted in
    the middle moves the rest instead of quietly mislabelling the photograph.  This is also
    what lets the fit use a lit mark or a lit index bit as evidence for its geometry
    exactly as it uses a lit protocol slot.
    """
    slot_rows = slots(Path(driver))
    bit_rows = bits(Path(driver))
    mark_rows = marks(Path(driver))
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
    for entry in faults(Path(driver)):
        index = (entry["off"] - base) // pitch
        band = ladder.get(index)
        if band is None or band["kind"] != "slot":
            raise SystemExit("a fault row points at %#x, which is not a slot band" % entry["off"])
        band["fault"] = entry["name"]
        band["fault_want"] = entry["want"]
    for entry in faults(Path(driver), "mTickBits"):
        index = (entry["off"] - base) // pitch
        band = ladder.get(index)
        if band is None or band["kind"] != "slot":
            raise SystemExit("a tick row points at %#x, which is not a slot band" % entry["off"])
        band.setdefault("tick", []).append(entry)
    return ladder, pitch


def quad_fit(points):
    """Least squares for row = A + B*i + C*i**2 over (i, row) pairs, without a numerics
    dependency: three normal equations, solved by hand."""
    n = 3
    x = [[1.0 * i ** k for k in range(n)] for i, _row in points]
    y = [float(row) for _i, row in points]
    m = [[sum(x[j][r] * x[j][c] for j in range(len(x))) for c in range(n)] for r in range(n)]
    v = [sum(x[j][r] * y[j] for j in range(len(x))) for r in range(n)]
    for r in range(n):
        p = max(range(r, n), key=lambda q: abs(m[q][r]))
        if abs(m[p][r]) < 1e-9:
            return None
        m[r], m[p] = m[p], m[r]
        v[r], v[p] = v[p], v[r]
        for q in range(r + 1, n):
            f = m[q][r] / m[r][r]
            for c in range(r, n):
                m[q][c] -= f * m[r][c]
            v[q] -= f * v[r]
    sol = [0.0] * n
    for r in range(n - 1, -1, -1):
        sol[r] = (v[r] - sum(m[r][c] * sol[c] for c in range(r + 1, n))) / m[r][r]
    return sol


def assign(bands, index_of):
    """Claim a ladder index for every band under this geometry.

    Two runs can round to the same index -- a band whose edge the row classifier cut in
    two, or a shadow the entry point's black pass imitates -- and then the coloured band
    wins and the closer claim beats the further one, because a band named by its colour is
    the evidence while a dark run only marks a position.  Round 14's frame does this: it
    reads cleanly with the coloured bands alone and rejects every candidate geometry as
    soon as one dark run overlaps a lit one, which is why a collision drops a band here
    instead of dropping the fit.

    Bands above the slots are the stage bands, and only the two anchors among them are
    kept: a dark run sitting above the green stage is the desk, not a ladder position.
    """
    claims = []
    for y, col in bands:
        i = index_of(y)
        if i is None:
            continue
        r = int(round(i))
        if r < 0 and STAGES.get(r) != col:
            continue
        claims.append((col == "black", abs(i - r), y, col, float(i), r))
    claims.sort()
    rows, taken = [], set()
    for _dark, _dev, y, col, i, r in claims:
        if r in taken:
            continue
        taken.add(r)
        rows.append((y, col, i, r))
    rows.sort()
    return rows


def score_of(rows, ladder):
    """How well a placement explains the frame: a band on the slot whose colour it has is
    worth three, one the entry point painted black is worth two because it is still a band
    in the right place, and being off centre by a fraction of a pitch costs six apiece --
    which is what keeps a fit that slid by a whole band from winning on colour alone."""
    score = 0.0
    for _y, c, i, r in rows:
        if r < 0:
            continue
        want = ladder.get(r)
        if want is None:
            score -= 3.0
        elif c == want["want"]:
            score += 3.0
        elif c == "black":
            score += 2.0
        else:
            score -= 2.0
        score -= 6.0 * abs(i - r)
    return score


def model_coef(yg, p0, g):
    """The search's model, row = yg + p0 * (n + g*n*(n-1)/2) for n pitches below green,
    written in the same i-squared form the refinement uses, so one row_of() serves both."""
    return (yg + p0 * (4.0 + 6.0 * g), p0 * (1.0 + 3.5 * g), p0 * g / 2.0)


def quad_index(coef):
    """Invert row = A + B i + C i^2, taking the root nearest the straight-line answer.

    The sign of C decides which of the two roots is the real one, and picking by the
    quadratic formula's plus sign gets it wrong for a frame whose pitch shrinks: round 15's
    first refinement landed on the far branch, fitted a parabola that turned over halfway
    down the ladder, and reported six bands out of twenty-nine.
    """
    a, b, c = coef

    def index_of(y):
        if abs(c) < 1e-9:
            return None if abs(b) < 1e-9 else (y - a) / b
        disc = b * b - 4.0 * c * (a - y)
        if disc < 0:
            return None
        root = math.sqrt(disc)
        guess = (y - a) / b if abs(b) > 1e-9 else 0.0
        return min(((-b + root) / (2.0 * c), (-b - root) / (2.0 * c)),
                   key=lambda v: abs(v - guess))
    return index_of


def fit(deg, center, h, w, rowcls, anchors, ladder):
    """Line the frame's bands up with the table.  Returns (score, rows, geometry) or None.

    The starting geometry comes from a model, row = green + p0 * (n + g*n*(n-1)/2) with n
    the pitches below the green stage: the first term is a constant pitch and the second
    lets it grow down the frame, which is what a photo of a panel that is not square to the
    camera does.  p0 is set by the magenta anchor being two pitches below green, so only g
    is searched, and the anchors fix the top of the ladder by construction -- which is why a
    stray band above the green stage can be dropped instead of vetoing every candidate.

    Then the bands themselves are fitted, because the model is only an approximation of a
    perspective view.  Round 15's frame placed its last two bands four and six rows off the
    searched g: three tenths of a pitch, which changes no reading, but enough to sample the
    bottom of the ladder in the blue gap beside the band rather than on it -- and whether a
    dark band is the black the entry point painted or blue nobody wrote over is exactly what
    the marks are there to answer, so it has to be sampled where the band is.  A quadratic
    through the placed bands fits the frame to under a row everywhere.  The refinement is
    only kept when it places at least as many bands and scores at least as well, so a frame
    too poor to re-fit is still read by the model.
    """
    yg, ym = anchors["green"], anchors["magenta"]
    bands = [b for b in bands_of(rowcls) if b[1] != "black" or b[0] > yg]
    if len(bands) < 6:
        return None

    best = None
    for gi in range(0, 61):
        g = gi / 1000.0
        p0 = (ym - yg) / (2.0 + g)
        rows = assign(bands, quad_index(model_coef(yg, p0, g)))
        s = score_of(rows, ladder)
        if best is None or s > best[0]:
            best = (s, model_coef(yg, p0, g))
    if best is None or best[0] <= 0:
        return None
    score, coef = best
    rows = assign(bands, quad_index(coef))

    for _round in range(3):
        cand = quad_fit([(r, row) for row, _c, _i, r in rows] + [(-4, yg), (-2, ym)])
        if cand is None:
            break
        again = assign(bands, quad_index(cand))
        if len(again) < len(rows):
            break
        s2 = score_of(again, ladder)
        if s2 < score:
            break
        score, coef, rows = s2, cand, again
    if score <= 0:
        return None
    return score, rows, (deg, center, coef, yg, ym, bands)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("photo")
    ap.add_argument("--width", type=int, default=600)
    ap.add_argument("--rotate", type=int, choices=(0, 90, 180, 270), default=None,
                    help="turn the frame this many degrees clockwise first; by default all "
                         "four are tried and the one that explains the most bands is kept")
    ap.add_argument("--center", type=float, default=0.50,
                    help="where across the frame to read the bands, as a fraction of the width")
    ap.add_argument("--span", type=float, default=0.12,
                    help="how wide that reading strip is, as a fraction of the width")
    ap.add_argument("--driver", default=str(DRIVER))
    ap.add_argument("--modules", help="text file of scripts/fv-order.py output, to name the "
                                      "index the bit bands decode to")
    ap.add_argument("--blob-map", help="text file of scripts/scan-clover-spins.py output, so a "
                                       "tick page prints the sites inside it")
    ap.add_argument("--debug", action="store_true")
    a = ap.parse_args()

    ladder, _pitch = build_ladder(a.driver)

    # A hand-held frame can put the ladder anywhere, so when the requested strip lands on
    # the bezel or a reflection the reading slides across the panel a little at a time
    # rather than giving up.  The orientation is the outer loop because in the wrong one
    # there is no strip that works at all.
    degrees = [a.rotate] if a.rotate is not None else [0, 90, 270, 180]
    best, notes = None, []
    for deg in degrees:
        grid, h, w = load(Path(a.photo), a.width, deg)
        for center in [a.center] + [c for c in (0.50, 0.42, 0.58, 0.34, 0.66) if c != a.center]:
            rowcls, blueness = read_strip(grid, h, w, center, a.span)
            anchors = anchors_of(rowcls)
            if "green" not in anchors or "magenta" not in anchors:
                notes.append("rotate %-3d strip %.2f  no green and magenta anchors" % (deg, center))
                continue
            found = fit(deg, center, h, w, rowcls, anchors, ladder)
            if found is None:
                notes.append("rotate %-3d strip %.2f  bands found, none lined up on the table"
                             % (deg, center))
                continue
            if best is None or found[0] > best[0]:
                best = (found[0], found[1], found[2], rowcls, blueness, h, w)
            if best and best[0] >= 2.8 * len(bands_of(rowcls)):
                break       # this frame is read as well as it can be
        if best and best[0] >= 2.8 * len(bands_of(rowcls)):
            break

    if best is None:
        raise SystemExit("the ladder could not be read out of this frame.\n  " +
                         "\n  ".join(notes or ["no strip in any orientation had both anchors"]))
    report(best, ladder, a)


def report(best, ladder, a):
    _score, rows, (deg, center, coef, yg, ym, bands), rowcls, blueness, h, w = best
    ca, cb, cc = coef

    def row_of(i):
        return int(round(ca + cb * i + cc * i * i))

    def sample(i, half=3):
        """Vote the strip's colour at the predicted row of a band, ignoring rows that
        merely came out mixed.  This is what tells a band painted black at entry (dark)
        from a place where the ladder never was (still the blue BootShim filled) and from
        a band the fit put outside the photographed panel."""
        y = row_of(i)
        if y < 0 or y >= h:
            return y, "off-frame"
        votes = {}
        for yy in range(max(0, y - half), min(h, y + half + 1)):
            c = rowcls[yy]
            if c != "mixed":
                votes[c] = votes.get(c, 0) + 1
        if not votes:
            return y, "mixed"
        return y, max(votes, key=votes.get)

    print("frame %dx%d  turned %d degrees  read at %.2f of the width" % (w, h, deg, center))
    print("anchors: green row %.1f, magenta row %.1f  ->  row = %.1f %+.2f i %+.4f i^2, "
          "pitch %.2f rows at slot 0 and %.2f at the last mark" %
          (yg, ym, ca, cb, cc, cb + 2 * cc, cb + 2 * cc * max(ladder)))
    print("%d bands in this strip (%d of them lit), %d placed on the ladder, score %.1f" %
          (len(bands), sum(1 for _y, c in bands if c != "black"), len(rows), _score))
    for y, c, n, i in rows:
        dev = abs(n - i)
        if dev > 0.35:
            print("   note: %s at row %.0f sits %.2f pitches off band %d" % (c, y, dev, i))

    lit = dict((i, c) for _y, c, _n, i in rows if i >= 0 and c != "black")

    def state_of(s, got):
        """A white band next to a saturated blue field photographs cyan: the blue and
        green channels blow out and the red one does not, so it lands in the cyan window.
        Say which band that is rather than calling it wrong, because the alternative
        reading -- that the stage never painted -- would send a round after a colour
        artefact."""
        if not got:
            return "dark"
        if got == s["want"]:
            return "LIT"
        if s["want"] == "white" and got == "cyan":
            return "LIT(white)"
        return "WRONG(%s)" % got

    def report_kind(kind, label):
        print("\n%s" % label)
        print("%-11s %-7s %-12s %-9s %s" % ("offset", "expect", "state", "seen", "meaning"))
        dark = []
        for i in sorted(ladder):
            s = ladder[i]
            if s["kind"] != kind:
                continue
            _y, seen = sample(i)
            got = lit.get(i) or (seen if seen in LIT else None)
            state = state_of(s, got)
            if kind == "slot" and not got:
                dark.append((i, s["off"], s["name"]))
            print("%#011x %-7s %-12s %-9s %s" % (s["off"], s["want"], state, seen, s["name"]))
        return dark

    dark = report_kind("slot", "protocol slots:")
    if dark:
        print("\nfirst dark slot: index %d at %#011x  %s" % dark[0])
        lit_slots = [i for i in lit if i in ladder and ladder[i]["kind"] == "slot"]
        if lit_slots:
            print("deepest lit slot: index %d" % max(lit_slots))
    else:
        print("\nevery slot lit")

    if any(s["kind"] == "bit" for s in ladder.values()):
        # Decide each bit at the row the fit predicts for its offset rather than from the
        # run detection: a bit is a one-of-two question (yellow or not), so the sample
        # needs no help from the fit having found the band, and printing both readings side
        # by side shows which one the frame actually supports.
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

    report_kind("mark", "what the meter says about itself:")

    fault_rows = [(i, ladder[i]) for i in sorted(ladder) if ladder[i].get("fault")]
    if fault_rows:
        # The fourth mark is the switch that makes these rows mean anything: without a
        # registered handler a fault goes to the default one, out to a serial port nobody
        # can read, and the seven borrowed bands stay exactly as dark as a boot that never
        # faulted.  Print the legend either way, but say plainly which of the two readings
        # the photograph supports.
        handler = [i for i in sorted(ladder)
                   if ladder[i]["kind"] == "mark" and ladder[i]["off"] == 0x007C0000]
        live = bool(handler) and bool(lit.get(handler[0]))

        # Round 18 shares these seven rows, and which layer a photograph is showing is read
        # off the band rather than assumed: the tick layer's "the slot is ours" row wants
        # white where the fault layer's translation-fault row wants cyan.  A frame from
        # before round 18 has no tick table at all and lands in the fault branch, which is
        # what an old photograph means.
        tick_rows = [(i, s) for i, s in fault_rows if s.get("tick")]
        mode_row = next(((i, s) for i, s in tick_rows
                         if any(t["want"] == "white" for t in s["tick"])), None)
        mode = None
        if live and mode_row is not None:
            _y, seen_mode = sample(mode_row[0])
            got_mode = lit.get(mode_row[0]) or (seen_mode if seen_mode in LIT else None)
            if got_mode == "white":
                mode = "tick"
            elif got_mode == "cyan":
                mode = "fault"

        if mode == "tick":
            print("\ntick reading -- this driver holds the timer interrupt, so the seven rows "
                  "below the clock are the program counter, not the fault:")
            print("%-11s %-7s %-12s %-9s %s" % ("offset", "colour", "state", "seen", "also"))
            bits = []
            arrived = None
            for i, s in tick_rows:
                _y, seen = sample(i)
                # The same second chance the fault rows get: a band this narrow can fall
                # between two detected runs, and "the tick never arrived" is exactly the
                # reading that must not come from a detection miss.
                got = lit.get(i) or (seen if seen in LIT else None)
                entries = s["tick"]
                entry = next((t for t in entries if t["want"] == got), entries[0])
                # The arrival row is the one band the table gives two colours to -- cyan for
                # a tick whose PC was inside the image, red for one outside -- so either of
                # them on it is the tick speaking, not a wrong paint.
                state = ("LIT" if got in [t["want"] for t in entries] else
                         ("dark" if not got else "WRONG(%s)" % got))
                if got:
                    if entry["want"] in ("cyan", "red"):
                        arrived = entry["want"]
                    elif entry["want"] == "yellow":
                        bits.append(i)
                print("%#011x %-7s %-12s %-9s %s / %s" %
                      (s["off"], entry["want"], state, seen, entry["name"], s["name"]))
            if arrived is None:
                print("\nthe slot is ours and no tick ever arrived: the loop is running with "
                      "interrupts masked, which is a driver stuck at high TPL rather than a "
                      "hardware bit that never sets")
            else:
                # Which bit of the page number a row carries comes from its place in the
                # driver's table, most significant first: row 9 is bit 4 and row 13 is bit 0.
                # The weight has to be counted over the five rows the table defines, not over
                # the rows that happen to be lit -- page 0b11001 lights rows 9, 10 and 13, and
                # compacting the three lit ones would decode it as 0b111.
                page_rows = sorted(i for i, s in tick_rows
                                   if any(t["want"] == "yellow" for t in s["tick"]))
                page = 0
                for j, i in enumerate(page_rows):
                    if i in bits:
                        page |= 1 << (len(page_rows) - 1 - j)
                if arrived == "red":
                    print("\nthe tick's PC was outside the image the index names, so the loop "
                          "is in something else -- a library the core linked, or the core")
                else:
                    print("\nthe tick found the PC in page %d of that image, offset %#x..%#x "
                          "of it (%d of the %d five-bit rows lit)" %
                          (page, page * 0x1000, page * 0x1000 + 0xFFF,
                           len(bits), len(page_rows)))
                    # A page number is only worth what the table behind it is worth:
                    # scripts/scan-clover-spins.py turns a blob's objdump listing into the
                    # dead-loop and bit-poll sites grouped by exactly this number.
                    if a.blob_map:
                        for line in blob_map(a.blob_map, page):
                            print(line)
        else:
            print("\n%s" % ("exception reading:" if live else
                            "exception reading is NOT LIVE -- the mark at 0x007c0000 is dark, "
                            "so either no CPU protocol appeared or something else already held "
                            "the exception slot, and dark rows below prove nothing:"))
            print("%-11s %-7s %-12s %-9s %s" % ("offset", "colour", "state", "seen", "also"))
            set_bits = []
            for i, s in fault_rows:
                _y, seen = sample(i)
                got = lit.get(i) or (seen if seen in LIT else None)
                want = s["fault_want"]
                state = "LIT" if got == want else ("dark" if not got else "WRONG(%s)" % got)
                if got == want:
                    set_bits.append(s["fault"])
                print("%#011x %-7s %-12s %-9s %s / %s" %
                      (s["off"], want, state, seen, s["fault"], s["name"]))
            if live and set_bits:
                print("\nthe fault says: %s" % "; ".join(set_bits))
            elif live:
                print("\nthe handler is registered and no fault row is lit: whatever the index "
                      "names did not abort, it is still inside a loop")
                if mode_row is not None:
                    print("the tick rows stayed dark too -- in a round-18 build that reads as "
                          "interrupts masked during the loop, but an older build has no tick "
                          "layer at all, so pass --driver <that round's CheckpointDxe.c> "
                          "before believing this")

    if a.debug:
        peak = max(blueness)
        dips = [(lo, hi) for _c, lo, hi in ranges(
            ["d" if blueness[y] < 0.72 * peak else "x" for y in range(h)], {"d"}) if hi - lo >= 1]
        print("\nblueness dips, candidates for empty slots (a vignette produces these too): %s" % dips)
        print("\nbands in this strip: %s" % "  ".join("%s%.0f" % (c, y) for y, c in bands))


if __name__ == "__main__":
    main()
