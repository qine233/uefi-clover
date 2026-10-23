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
        [--center 0.50] [--span 0.12] [--modules fv-order.txt] [--register-map map.txt]
        [--dt Resources/DTBs/clover.dts] [--driver path/to/that/round/CheckpointDxe.c]
        [--debug]
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
# Round 24's reset band answers with its colour rather than with being lit: the hook that
# paints it takes the colour from the EFI_RESET_TYPE the caller passed, so a red band is
# not a yellow band read wrong -- it is a cold reset, which names a different caller
# entirely.  Everything else on the ladder is one bit; this row is four.
RESET_TYPE_BY_COLOR = {
    "yellow": "EfiResetShutdown",
    "red":    "EfiResetCold",
    "cyan":   "EfiResetWarm",
    "white":  "EfiResetPlatformSpecific",
}
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


def register_window(path, addr, span=1 << 16):
    """Which mapped device region a polled register address lands in.

    The address is the whole point of round 20.  The module is waiting for an
    acknowledgement bit in some clock controller, and the controller's name is what says
    which prerequisite is missing: a PLL inside GCC waits on nothing but its parent, one in
    the video, display or Turing controller waits on that subsystem being reachable at all,
    and an address no region covers means the read never touched hardware.

    `span` is how wide the sampled region is, and it is a parameter because round 21 made the
    same twelve rows finer: 64 KiB for the wide reading, 16 bytes for the narrow one.  The
    sampled block is what is being matched, so a region that merely overlaps it counts, and
    more than one is reported as the ambiguity it is rather than resolved by picking the
    first.
    """
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except (IOError, OSError) as exc:
        return ["  cannot read %s: %s" % (path, exc)]

    rows = []
    for l in lines:
        m = re.match(r"\s*(0x[0-9a-f]+)\s+(0x[0-9a-f]+)\s+(.+)", l, re.I)
        if m:
            rows.append((int(m.group(1), 16), int(m.group(2), 16), m.group(3).strip()))
    if not rows:
        return ["  no `0x<base> 0x<size> <name>` rows in %s -- regenerate it with "
                "scripts/clover-register-map.py" % path]

    hits = [(b, s, n) for b, s, n in rows if b < addr + span and addr < b + s]
    if not hits:
        near = min(rows, key=lambda r: abs(r[0] - addr))
        return ["  no mapped region covers %#x..%#x; the nearest is %r at %#x + %#x, which is "
                "%#x away.  A clock register nobody maps cannot answer a poll, so if the "
                "ladder still says this loop is spinning, the read is coming back from "
                "somewhere else -- all ones, or a default slave." %
                (addr, addr + span - 1, near[2], near[0], near[1],
                 addr - near[0] if addr > near[0] else near[0] - addr)]
    out = ["  %d mapped region%s overlapping that block:" %
           (len(hits), "s" if len(hits) > 1 else "")]
    for b, s, n in hits:
        out.append("    %-22s %#010x + %#010x" % (n, b, s))
    if len(hits) == 1:
        b, s, n = hits[0]
        # The twelve rows name a block, not a register, so the honest statement is which part
        # of the region the block covers and which part of the block the region sits in --
        # both, because the register is in the overlap and either half of the overlap can hang
        # off the other side.
        lo, hi = max(addr, b), min(addr + span, b + s)
        out.append("  so the polled register is %s: the block's %#x..%#x, which is that "
                   "region's %#x..%#x of its %#x mapped bytes -- whose power domain and "
                   "parent clock the acknowledgement waits on" %
                   (n, lo - addr, hi - 1 - addr, lo - b, hi - 1 - b, s))
    else:
        out.append("  more than one region shares this %#x-wide block, so the twelve rows are "
                   "not fine enough to name one of them%s" %
                   (span, "" if span > 16 else "; a 16-byte bucket that straddles two regions "
                    "means the offset is at the boundary"))
    return out


def blob_map(path, page, delta=None):
    """The halt sites scripts/scan-clover-spins.py found on one page of a loaded blob.

    A page number is only worth the listing behind it: page 11 of `ClockDxe` is not a
    count, it is `HALclkHuayraPLLTemplate.c:622` and the twenty-one other self-branches
    sharing that page.  Given round 19's twelve-bit sample the answer narrows to one row of
    that listing, which is the difference between "somewhere in the clock enable path" and
    "the poll that waits for bit 31 of a register the clock record points at".

    Absence is an answer too, and a different one in each direction -- a tick that lands on
    a page the scan lists no sites for is inside a loop that has an exit rather than inside
    a halt, and a tick on a page that has sites but in another bucket is doing ordinary
    work.  Say both rather than complaining about the file.
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
    body = []
    for l in lines[start + 1:]:
        if not l.startswith("    0x"):
            break
        body.append(l)
    out.extend(body)
    # The polls live in their own section at the foot of the file, keyed by the same
    # page marker, and they are the sites a tick can be caught in mid-loop rather than
    # at a halt, so they belong under the same answer.
    polls = [l for l in lines if l.startswith("    0x") and want in l]
    if polls:
        out.append("    counter-free hardware bit polls on this page:")
        out.extend(polls)

    if delta is None:
        if any("[no signature]" in l for l in out):
            out.append("    one row above has no ASSERT() signature, which is what "
                       "CpuDeadLoop() compiles to -- so this page is also consistent with an "
                       "assert having parked the CPU, and a five-bit sample cannot separate "
                       "that halt from the page's other sites")
        return out

    # Twelve bits of the address is a 32-byte bucket, and every site on the page is a row
    # of the listing, so the question is simply which rows fall inside it.
    addr = re.compile(r"^    0x([0-9a-f]{5,7})\b")
    bucket = delta & ~0x1f
    here = [l for l in body + polls
            if (m := addr.match(l)) and (int(m.group(1), 16) & ~0x1f) == bucket]
    if not here:
        return out + ["\nnone of this page's %d sites is in the sampled bucket %#x..%#x, so the "
                      "PC is in code the scan files as neither halt nor poll -- a loop with an "
                      "exit, or ordinary work. The module is busy, not parked."
                      % (len(body) + len(polls), bucket, bucket + 31)]
    head = ["\nthe sampled bucket %#x..%#x is these rows:" % (bucket, bucket + 31)]
    head.extend(here)
    if any("PAGE" in l for l in here):
        head.append("    a poll with no counter and no timeout: the hardware bit it waits for "
                    "never arrives, so this is the register, not the code, and the loop never "
                    "leaves it")
    elif any("[no signature]" in l for l in here):
        head.append("    a bare `b .` with no ASSERT() report in front of it, so this is not an "
                    "assert halt and not a poll -- a self-branch the compiler emitted for a "
                    "loop that cannot end")
    else:
        head.append("    an ASSERT() halt: the report call ran, printed to the serial port this "
                    "tablet has no cable for, and the CPU has been parked here since")
    return out + head


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
    # An entry is { row, CLOVER_COLOR_X, [shift], "name" }.  The shift appeared in round 19,
    # when the tick layer grew from five page bits to twelve address bits: a row then
    # carries the bit it says it carries, so neither the driver nor this reader has to
    # weight rows by the order they happen to sit in.
    for m in re.finditer(
        r"\{\s*(\d+)\s*,\s*(CLOVER_COLOR_\w+)\s*(?:,\s*(\d+))?\s*,\s*\"([^\"]+)\"", body
    ):
        row = int(m.group(1))
        if row >= len(rows):
            raise SystemExit("a %s row names slot %d and the table has %d" % (table, row, len(rows)))
        out.append({"off": rows[row]["off"], "row": row,
                    "want": NAME_BY_COLOR[m.group(2)], "name": m.group(4),
                    "shift": int(m.group(3)) if m.group(3) else None})
    return out


def tick_addr_bits(path, table="mTickAddrBits"):
    """Round 20's second reading of the same twelve bands: { row, shift, "name" }, with no
    colour because every one of them is yellow and the colour is what says which of the two
    readings a photograph is in.

    The driver keeps this as its own table rather than as a second column on `mTickBits`
    because a row then holds two bit positions and the reader would have to pick one by
    hand; two tables that list the same rows in the same order keep the pairing explicit,
    and `SlotIsLent()` on the device side reads the first one's rows for exactly that
    reason.  A driver from before round 20 simply has no such table and the reader stays in
    program-counter mode, which is what an old photograph means.

    Round 21 adds a third table of the same shape -- the same twelve rows again as bits
    15..4 of the polled register, the reading taken when the wide one says MMCC -- so this
    reads whichever one is asked for.
    """
    try:
        src = path.read_text(encoding="utf-8")
    except (IOError, OSError):
        return []
    head = src.find(table + "[] = {")
    if head < 0:
        return []
    body = src[head:src.find("\n};", head)]
    rows = slots(path)
    out = []
    for m in re.finditer(r"\{\s*(\d+)\s*,\s*(\d+)\s*,\s*\"([^\"]+)\"", body):
        row = int(m.group(1))
        if row >= len(rows):
            raise SystemExit("a %s row names slot %d and the table has %d"
                             % (table, row, len(rows)))
        out.append({"off": rows[row]["off"], "row": row, "shift": int(m.group(2)),
                    "name": m.group(3)})
    return out


def _hexsize(size):
    """The device tree's own window size for a block, phrased so a missing one reads as a
    question rather than as zero."""
    return "%#x bytes" % size if size else "an unstated span"


def tick_block(path):
    """The base of the block round 21's narrow reading is an offset inside, from the driver's
    own #define and nowhere else: 0xC8C is `0x0C8C0000 >> 16`, the value round 20's photograph
    produced, and if the driver is ever pointed at another block the reader has to follow it
    rather than keep repeating the old answer.
    """
    try:
        src = path.read_text(encoding="utf-8")
    except (IOError, OSError):
        return None
    m = re.search(r"#define\s+CLOVER_TICK_BLOCK_MMCC\s+\(?\s*(0x[0-9A-Fa-f]+)", src)
    if not m:
        return None
    return int(m.group(1), 16) << 16


def block_regions(path, base):
    """What the tablet's own device tree says lives at one clock controller: its size and the
    power domains inside it, as (size, [(offset, name)]).

    Read from Resources/DTBs/clover.dts rather than typed out here because that file is the
    thing round 20's reading was corroborated against, because Xiaomi's tree names domains
    mainline does not, and because a 16-byte bucket that contains a GDSC register is a
    different finding from one that contains a branch clock's RCGR triple.  Missing or
    unreadable is not an error -- an older photograph simply has no offset to place.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (IOError, OSError):
        return None, []
    m = re.search(r"clock-controller@%x\s*\{([^{}]*)\}" % base, text)
    if not m:
        return None, []
    size = None
    reg = re.search(r"\breg\s*=\s*<0x[0-9a-fA-F]+\s+0x([0-9a-fA-F]+)>", m.group(1))
    if reg:
        size = int(reg.group(1), 16)
    domains = []
    for node in re.finditer(r"qcom,gdsc@[0-9a-fA-F]+\s*\{([^{}]*)\}", text):
        body = node.group(1)
        name = re.search(r'regulator-name\s*=\s*"([^"]+)"', body)
        addr = re.search(r"\breg\s*=\s*<0x([0-9a-fA-F]+)\s+0x[0-9a-fA-F]+>", body)
        if not (name and addr):
            continue
        offset = int(addr.group(1), 16) - base
        if size is None or 0 <= offset < size:
            domains.append((offset, name.group(1)))
    return size, sorted(domains)


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
            if kind == "mark" and entry["name"].startswith("a reset was requested"):
                ladder[index]["reset"] = RESET_TYPE_BY_COLOR
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
    for key, table in (("tick_addr", "mTickAddrBits"), ("tick_reg", "mTickRegBits")):
        for entry in tick_addr_bits(Path(driver), table):
            index = (entry["off"] - base) // pitch
            band = ladder.get(index)
            if band is None or band["kind"] != "slot":
                raise SystemExit("an address row points at %#x, which is not a slot band"
                                 % entry["off"])
            if not band.get("tick"):
                raise SystemExit("%s row %d has no mTickBits row to be a second "
                                 "reading of" % (table, entry["row"]))
            band[key] = entry["shift"]
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
    ap.add_argument("--register-map", help="text file of scripts/clover-register-map.py output, "
                                           "so a polled register address prints the device "
                                           "region it sits in")
    ap.add_argument("--dt", default=str(HERE.parent / "Resources/DTBs/clover.dts"),
                    help="the tablet's own device tree source, so a narrow register reading "
                         "names the clock controller it falls in and any power domain inside "
                         "it (default: Resources/DTBs/clover.dts)")
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
        if s.get("reset"):
            return "LIT: %s" % s["reset"].get(got, "a type no caller passes")
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
            # A slot row that a report layer borrowed is no longer the slot's own colour:
            # the driver suppresses that paint on purpose (SlotIsLent) so the report can be
            # read there.  Calling the yellow of a tick bit "WRONG", or a dark borrowed row
            # "the protocol never appeared", would both be inventions -- the sections below
            # say what the band is actually holding.
            if kind == "slot" and (s.get("fault") or s.get("tick")):
                print("%#011x %-7s %-12s %-9s %s" % (s["off"], s["want"], "LENT", seen, s["name"]))
                continue
            state = state_of(s, got)
            if kind == "slot" and not got:
                dark.append((i, s["off"], s["name"]))
            print("%#011x %-7s %-12s %-9s %s" % (s["off"], s["want"], state, seen, s["name"]))
        return dark

    dark = report_kind("slot", "protocol slots:")
    if dark:
        print("\nfirst dark slot: index %d at %#011x  %s" % dark[0])
        lit_slots = [i for i in lit if i in ladder and ladder[i]["kind"] == "slot"
                     and not (ladder[i].get("fault") or ladder[i].get("tick"))]
        if lit_slots:
            print("deepest lit slot: index %d" % max(lit_slots))
    else:
        print("\nevery un-borrowed slot lit")

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

    # Round 24's fork, said in one place rather than left to be inferred from a row of the
    # table above, because it decides the next build instead of describing this one.  The
    # hook that paints this band never returns, so a lit row does not just mean "BDS gave
    # up":  it means the tablet is sitting in that loop right now, with the refresher still
    # sweeping, and whatever is on the panel is what the panel is going to keep showing.
    reset_row = next((i for i in sorted(ladder) if ladder[i].get("reset")), None)
    if reset_row is not None:
        _y, seen = sample(reset_row)
        got = lit.get(reset_row) or (seen if seen in LIT else None)
        held = sum(1 for i in ladder
                   if ladder[i]["kind"] == "slot" and not
                   (ladder[i].get("fault") or ladder[i].get("tick")) and lit.get(i))
        if got:
            print("\nRESET REQUESTED: %s.  This build holds the boot at that call instead "
                  "of letting it cut the power, so the picture is stable and there is no "
                  "rush to photograph it." % ladder[reset_row]["reset"].get(got, got))
            if held:
                print("%d protocol slot(s) are lit under it, which means the panel still "
                      "scans the window the ladder is drawn in and the whole reading above "
                      "is the boot as far as it went -- read it, do not re-run it." % held)
            else:
                print("...and nothing else on the panel came back while the refresher kept "
                      "sweeping.  That is the second branch: the display is no longer "
                      "scanning %s, so the next round has to draw where the display driver "
                      "pointed the scan-out rather than where BootShim filled." % "0x9D400000")
        else:
            print("\nthe reset band is dark, so no caller went through gRT->ResetSystem "
                  "before this frame was taken.  If the tablet still powered itself off, "
                  "the shutdown came from somewhere this hook cannot see -- a hardware "
                  "watchdog barking, or a driver that reaches the PMIC without asking the "
                  "runtime services -- and that is what the next round goes after.")

    report_rows = [(i, ladder[i]) for i in sorted(ladder)
                   if ladder[i].get("fault") or ladder[i].get("tick")]
    fault_rows = [(i, ladder[i]) for i in sorted(ladder) if ladder[i].get("fault")]
    if report_rows:
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
        tick_rows = [(i, s) for i, s in report_rows if s.get("tick")]
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

        # Round 18's table declared no bit positions at all and let the rows' order carry the
        # weight; round 19 gave every row its shift explicitly.  Which convention a frame is
        # written in is a property of the driver, not of the photograph, so decide it once here.
        positional = not any(t.get("shift") is not None
                             for _i, s in tick_rows for t in s["tick"])

        def tick_role(s):
            """Which kind of tick row a borrowed band is: a bit, one of the two marks that say
            the layer is live and in which mode, or one of round 21's two flags.

            Read off the entry colours rather than a row index, because the arrival row grew a
            third colour in round 20 (cyan for a PC inside the image, red for one outside it,
            yellow for a register address) and round 21 put red on a second row as well.  Only
            the arrival row has ever had cyan, only a bit row has ever had a declared shift,
            and of the two remaining marks the one that can also read red is the one that says
            whether the block answered.

            The last test only means anything from round 19, which is when the table started
            declaring shifts; round 18 weighted its five rows by their order and declared none,
            so for that driver every row that is not a mark is a bit.
            """
            entries = s["tick"]
            if any(t["want"] == "white" for t in entries):
                return "ours"
            if any(t["want"] == "cyan" for t in entries):
                return "arrival"
            if positional or any(t.get("shift") for t in entries):
                return "bit"
            if any(t["want"] == "red" for t in entries):
                return "liveness"
            return "width"

        if mode == "tick":
            print("\ntick reading -- this driver holds the timer interrupt, so the borrowed rows "
                  "are the program counter, not the fault:")
            print("%-11s %-7s %-12s %-9s %s" % ("offset", "colour", "state", "seen", "also"))
            bits = []
            arrived = None
            width = None
            answered = None
            roles = {}
            for i, s in tick_rows:
                _y, seen = sample(i)
                # The same second chance the fault rows get: a band this narrow can fall
                # between two detected runs, and "the tick never arrived" is exactly the
                # reading that must not come from a detection miss.
                got = lit.get(i) or (seen if seen in LIT else None)
                entries = s["tick"]
                entry = next((t for t in entries if t["want"] == got), entries[0])
                role = tick_role(s)
                roles[i] = role
                state = ("LIT" if got in [t["want"] for t in entries] else
                         ("dark" if not got else "WRONG(%s)" % got))
                if got:
                    if role == "arrival":
                        if state == "LIT":
                            arrived = got
                    elif role == "bit":
                        if entry["want"] == "yellow":
                            bits.append((i, entry))
                    elif state == "LIT":
                        # Either colour on the liveness row is the driver answering the
                        # question it was built to ask -- red for the dead pattern, yellow for
                        # a real value -- and the width row has exactly one colour to give.
                        if role == "width":
                            width = got
                        elif role == "liveness":
                            answered = got
                print("%#011x %-7s %-12s %-9s %s / %s" %
                      (s["off"], entry["want"], state, seen, entry["name"], s["name"]))
            addr_mode = (arrived == "yellow")
            # Narrow only when the driver ships a third table to read the rows with; a
            # photograph cannot invent bits 15..4 out of a round-20 build, and silently
            # decoding a wide address as an offset would be worse than saying so.
            narrow = (addr_mode and width == "yellow" and
                      any(ladder[i].get("tick_reg") is not None for i, _s in tick_rows))
            if arrived is None:
                print("\nthe slot is ours and no tick ever arrived: the loop is running with "
                      "interrupts masked, which is a driver stuck at high TPL rather than a "
                      "hardware bit that never sets")
            else:
                # Round 19 gives every row the bit its own label names, so the value is the OR
                # of the lit rows' shifts and nothing depends on how many rows happen to be
                # lit.  Round 18 weighted by table position instead -- five rows, most
                # significant first -- and a photograph from that round still has to read the
                # way that driver painted it, so the positional rule survives as the fallback
                # for a table that declares no shifts.
                order = [i for i, s in tick_rows if roles.get(i, tick_role(s)) == "bit"]

                def shift_of(i, entry):
                    """The bit this row carries in the reading this photograph is holding: the
                    program counter's, the polled register's wide bits, or round 21's offset
                    bits inside the block."""
                    if narrow:
                        return ladder[i].get("tick_reg")
                    if addr_mode:
                        return ladder[i].get("tick_addr")
                    return entry["shift"]

                shifted = any(shift_of(i, entry) for i, entry in bits)
                if shifted:
                    value = 0
                    for i, entry in bits:
                        shift = shift_of(i, entry)
                        if shift:
                            value |= 1 << shift
                    page = value >> 12
                else:
                    weight = {i: 1 << (len(order) - 1 - k) for k, i in enumerate(order)}
                    page = 0
                    for i, _entry in bits:
                        page |= weight.get(i, 0)
                    value = page << 12
                if arrived == "red":
                    print("\nthe tick's PC was outside the image the index names, so the loop "
                          "is in something else -- a library the core linked, or the core")
                elif not bits:
                    print("\nthe tick arrived inside that image but no address row is lit, and "
                          "the marks above are lit, so the sample was taken while the rows were "
                          "being erased rather than after one was painted -- photograph a boot "
                          "that has been sitting for a few seconds and this resolves")
                    if addr_mode or narrow:
                        print("  the other reading, which the flags cannot rule out: every bit "
                              "the sample carries is zero, and that is a value a polled register "
                              "can have -- the first 16 bytes of MMCC in the narrow reading, the "
                              "block at address 0 in the wide one, which no region covers.  Take "
                              "a second photograph: a real reading repeats and a race moves")
                elif narrow:
                    base = tick_block(Path(a.driver))
                    bucket = value & ~0xF
                    size, domains = block_regions(a.dt, base) if base else (None, [])
                    print("\nthe arrival row is yellow and the width row is lit, so these twelve "
                          "rows are bits 15..4 of the polled register: %s%#x..%#x, a 16-byte "
                          "bucket" %
                          (("MMCC + ") if base else "offset ", bucket, bucket | 0xF))
                    if base:
                        print("  in full that is %#x..%#x%s" %
                              (base + bucket, base + bucket | 0xF,
                               ", inside the %s the device tree declares for "
                               "clock-controller@%x" % (_hexsize(size), base)
                               if size else ""))
                        if a.register_map:
                            for line in register_window(a.register_map, base + bucket, 16):
                                print(line)
                    hits = [name for off, name in domains if bucket <= off <= bucket | 0xF]
                    if hits:
                        print("  that bucket holds %s -- one of the power domains this tablet's "
                              "own tree hangs off the multimedia clock controller, so the wait "
                              "is on a domain coming up, not on a branch clock's acknowledge bit"
                              % ", ".join(hits))
                    elif domains:
                        print("  no power-domain register falls in that bucket; the tree names "
                              "them at %s" %
                              ", ".join("%#x %s" % (off, name) for off, name in domains))
                elif addr_mode:
                    print("\nthe tick is parked in one of the two acknowledgement polls this "
                          "module can stop in, so the twelve rows are the address of the "
                          "register it is waiting on: %#x..%#x" %
                          (value, value + (1 << 16) - 1))
                    if a.register_map:
                        for line in register_window(a.register_map, value):
                            print(line)
                    else:
                        print("  (pass --register-map to have that address named as a "
                              "device region; scripts/clover-register-map.py builds it)")
                    if any(roles.get(i) == "width" for i in roles):
                        if width != "yellow":
                            print("  the width row is dark, so the high bits name a block other "
                                  "than the one round 21 narrows; these rows stay a 64 KiB "
                                  "reading and the offset inside it is not known")
                    else:
                        print("  this driver has no narrow reading at all, so the register is "
                              "known only to the 64 KiB block that contains it")
                else:
                    print("\nthe tick found the PC at %#x..%#x of that image: page %d, %d of "
                          "the %d address rows lit%s" %
                          (value, value + (1 << (5 if shifted else 12)) - 1,
                           page, len(bits), len(order),
                           "" if shifted else "   (positional table: this driver samples the "
                           "page only, so the bucket is not known)"))
                    # A page number is only worth what the table behind it is worth, and an
                    # offset is worth a line of source: scripts/scan-clover-spins.py turns a
                    # blob's objdump listing into the dead-loop and bit-poll sites grouped by
                    # exactly these numbers.
                    if a.blob_map:
                        for line in blob_map(a.blob_map, page, value if shifted else None):
                            print(line)
                # The liveness flag is the one thing an address cannot give: a register whose
                # bit never arrives and a bus that answers nothing are different bugs, and only
                # the word the loop itself tested tells them apart.  It is printed after the
                # address because an offset means nothing for a block nobody is home in.
                if addr_mode or narrow:
                    if answered == "red":
                        print("\nthe liveness row is red: the word this poll is testing reads "
                              "the dead pattern for it -- all ones in the update handshake at "
                              "0xab14, all zeros in the status wait at 0xa784.  The transaction "
                              "completed and nothing drove the data, which points at the block "
                              "being unpowered or clocked from a parent that never came up, not "
                              "at a bit that is slow to clear")
                    elif answered == "yellow":
                        print("\nthe liveness row is yellow: the polled word is a real value, so "
                              "the block answers and this is a bit hardware is not setting -- "
                              "look for the parent clock or the power domain whose own enable "
                              "was never confirmed")
                    elif any(roles.get(i) == "liveness" for i in roles):
                        print("\nthe liveness row is dark while the address rows are painted, "
                              "which the driver does not do -- this frame caught the rows "
                              "between the flag paint and the bit paint, and a second "
                              "photograph resolves it")
                # Round 22 onward is the build set that has a width row and no liveness row: it
                # gave the clock band back to its own slot, because from that round on the
                # interesting question is not whether the polled word is real but whether the
                # driver ever reached the end of its entry point.  Round 23 changes no row
                # meaning at all -- it only keeps every row painted -- so it reads through
                # exactly this branch.  Say so, or the band above reads as a protocol row the
                # tick layer forgot to borrow.
                if (any(roles.get(i) == "width" for i in roles) and
                        not any(roles.get(i) == "liveness" for i in roles)):
                    clock_row = next((j for j, s in ladder.items()
                                      if s["kind"] == "slot" and s["off"] == 0x340000), None)
                    if clock_row is not None:
                        _y, clock_seen = sample(clock_row)
                        clock_got = (lit.get(clock_row) or
                                     (clock_seen if clock_seen in LIT else None))
                        print("\nthis build does not borrow the clock row, so +0x340000 reads "
                              "as its own protocol band (seen: %s): %s.  Red means `ClockDxe` "
                              "finished and installed the clock protocol, which is this "
                              "round's success signal -- the wait was cut short by the tick "
                              "handler and not by hardware, so a driver that gets there "
                              "leaves its RCGR update bit set" %
                              (clock_got or "dark", ladder[clock_row]["name"]))
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
