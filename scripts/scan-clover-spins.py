#!/usr/bin/env python3
"""
  clover: turn one DXE blob into the table round 18's tick page is read against.

  Round 17 said the DXE loop stops inside ClockDxe and that it *spins* rather than
  aborts, and round 18 put a five-bit page number of the program counter on the
  screen (Include/Checkpoint.h).  A page number is only worth what the table behind
  it is worth, and this builds that table: it finds every `b .` in the module, every
  two-instruction bit poll with no counter, and for each one the source file, the
  line number and the expression the code was about to report -- because almost every
  `b .` in this blob has an ASSERT() report call in front of it, which is what an
  assert compiles to once the print has gone to a serial port this tablet has no cable
  for.  The few that have no such signature are marked, since a bare `b .` is a
  different bug and wants a different fix.

  Grouping is by 4 KiB page of the *loaded image*, which is the number the panel
  paints, so the reading is one lookup: a photograph decodes to page N, and
  read-clover-photo.py --blob-map this output prints every site in page N.

  Where the addresses come from is the part worth writing down.  These blobs are
  PE32+ images that the DXE core relocates, and for ClockDxe every section's RVA
  equals its file offset (.text at 0x1000 for 0x14000, .data at 0x15000), so the
  offset a host scan prints and the offset the firmware's ELR implies are the same
  number -- the script checks that and says so if a blob breaks the habit.

  objdump is the only disassembler here, and the two that exist do not agree: this
  Mac's /usr/bin/objdump is LLVM's and rejects `-b`, while the guest's GNU objdump
  takes `-b binary -m aarch64` happily.  So run it there and point this at the
  listing, or run the whole thing in the guest:

    colima ssh --profile clover -- bash -c \\
      'objdump -D -b binary -m aarch64 --adjust-vma=0 ClockDxe.efi > /tmp/clock.txt'
    python3 scripts/scan-clover-spins.py ClockDxe.efi --lines /tmp/clock.txt

  The instruction text it parses is GNU objdump's, with the separators normalised;
  anything it cannot classify it ignores, which is safe here because the two shapes
  it looks for are unambiguous -- an unconditional branch to its own address, and a
  load immediately followed by a test-and-branch back to that load.

  SPDX-License-Identifier: BSD-2-Clause-Patent
"""

import argparse
import re
import struct
import subprocess
import sys
from collections import defaultdict

DEAD_LOOP = 0x14000000          # b .  -- imm26 == 0


def sections(path):
    """RVA ranges of the image's sections, so the scan can stay inside code."""
    data = open(path, "rb").read()
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\0\0":
        sys.exit("%s is not a PE image" % path)
    nsec = struct.unpack_from("<H", data, pe + 6)[0]
    optsize = struct.unpack_from("<H", data, pe + 20)[0]
    opt = pe + 24
    if struct.unpack_from("<H", data, opt)[0] != 0x20B:
        sys.exit("%s is not PE32+" % path)
    out = []
    off = opt + optsize
    for _ in range(nsec):
        name = data[off:off + 8].rstrip(b"\0").decode("latin-1")
        vsize, rva, rawsize, raw = struct.unpack_from("<IIII", data, off + 8)
        out.append((name, rva, vsize, rawsize, raw))
        off += 40
    return data, struct.unpack_from("<I", data, opt + 16)[0], \
        struct.unpack_from("<I", data, opt + 56)[0], out


def listing(path, command):
    text = None
    if path:
        text = open(path).read()
    elif command:
        text = subprocess.run(command, shell=True, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL).stdout.decode("latin-1")
    if not text or ":\t" not in text and "://" not in text and not re.search(r"^\s+[0-9a-f]+:", text, re.M):
        sys.exit("no disassembly to read -- on this Mac objdump is LLVM's and rejects "
                 "`-b binary`; run the listing in the colima guest and pass it with --lines")
    ins = []
    for line in text.splitlines():
        m = re.match(r"^\s+([0-9a-f]+):\s+([0-9a-f]{8})\s+(.*)$", line)
        if not m:
            continue
        ins.append((int(m.group(1), 16), int(m.group(2), 16),
                    m.group(3).split("//")[0].strip().replace("\t", " ")))
    return ins


def cstring(data, rva):
    if rva is None or rva >= len(data):
        return None
    blob = data[rva:rva + 160].split(b"\0")[0]
    blob = re.sub(rb"[^ -~]", b"", blob)
    return blob.decode("latin-1") or None


def branch_target(text):
    m = re.match(r"^b(?:\.?\w*) 0x([0-9a-f]+)", text)
    return int(m.group(1), 16) if m else None


def bit_poll_target(text):
    m = re.match(r"^(?:tbz|tbnz) w\d+, #(\d+), 0x([0-9a-f]+)$", text)
    if m:
        return int(m.group(1)), int(m.group(2), 16)
    return None


def resolve_args(window):
    """The three ASSERT() arguments, out of the adrp/add and mov pairs before a call."""
    pages, line, afile, expr = {}, None, None, None
    for text in window:
        m = re.match(r"mov w1, #0x([0-9a-f]+)", text)
        if m:
            line = int(m.group(1), 16)
        m = re.match(r"adrp (x\d+), 0x([0-9a-f]+)", text)
        if m:
            pages[m.group(1)] = int(m.group(2), 16)
        m = re.match(r"add (x\d+), (x\d+), #0x([0-9a-f]+)", text)
        if m and m.group(2) in pages:
            rva = pages[m.group(2)] + int(m.group(3), 16)
            if m.group(1) == "x0":
                afile = rva
            elif m.group(1) == "x2":
                expr = rva
    return line, afile, expr


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[2])
    ap.add_argument("blob", help="the DXE .efi to scan, e.g. ClockDxe.efi")
    ap.add_argument("--lines", help="a GNU objdump listing of it, with --adjust-vma=0")
    ap.add_argument("--objdump", help="a shell command that produces that listing")
    ap.add_argument("--text", help="section name to scan (default: the biggest code one)")
    args = ap.parse_args()

    data, entry, imagesize, secs = sections(args.blob)
    want = args.text or max(secs, key=lambda s: s[2])[0]
    lo = min(s[1] for s in secs if s[0] == want)
    hi = lo + max(s[2] for s in secs if s[0] == want)
    aligned = [(n, rva, vs, raw) for n, rva, vs, rs, raw in secs if rva == raw]
    print("%s: PE32+, entry %#x, SizeOfImage %#x, sections %s" %
          (args.blob, entry, imagesize,
           ", ".join("%s %#x+%#x" % (n, rva, vs) for n, rva, vs, _rs, _raw in secs)))
    print("RVA == file offset for %s, so a page of the loaded image is a page of this file%s"
          % (", ".join(n for n, _r, _v, _x in aligned) or "no section",
           "" if aligned else " -- READ THE ADDRESSES WITH CARE"))

    ins = listing(args.lines, args.objdump)
    ins = [i for i in ins if lo <= i[0] < hi]
    index = {a: k for k, (a, _w, _t) in enumerate(ins)}
    print("%d instructions in %s %#x..%#x" % (len(ins), want, lo, hi))

    dead = [(a, w) for a, w, t in ins if w == DEAD_LOOP and
            branch_target(t) == a]
    polls = []
    for k, (a, _w, t) in enumerate(ins):
        bp = bit_poll_target(t)
        if not bp or bp[1] != a - 4:
            continue
        prev = ins[k - 1][2] if k else ""
        if re.match(r"ldr (w|x)\d+, \[", prev):
            polls.append((ins[k - 1][0], a, bp[0], prev))

    by = defaultdict(list)
    for a, _w in dead:
        k = index[a]
        window = [t for _x, _w2, t in ins[max(0, k - 8):k]]
        line, f, e = resolve_args(window)
        name = cstring(data, f)
        # What makes a `b .` legible is the ASSERT() argument triple ahead of it: __FILE__
        # is the first, so a site whose window holds a call and a readable `.c` name is
        # DebugLib's report, and its text went to a serial port this tablet has no cable
        # for.  A site without that signature is a bare dead loop, and the two need
        # different fixes, so they are counted separately below rather than rounded up.
        by[a >> 12].append((a, line, name, cstring(data, e),
                            any(t.startswith("bl ") for t in window)
                            and (name or "").endswith(".c")))
    signed = sum(1 for sites in by.values() for s in sites if s[4])

    print("\n%d sites of `b .`, and %d two-instruction bit polls with no counter"
          % (len(dead), len(polls)))
    print("%d of these sites have the ASSERT() report signature in the eight instructions "
          "before the branch -- a call plus a readable __FILE__ -- so they read as halts "
          "whose text went to the absent serial port; the other %d have no such signature, "
          "and a tick on one of those is a real dead loop.  Page numbers are of the loaded "
          "image, which is what the panel paints, and an unsigned site is marked "
          "[no signature]\n" % (signed, len(dead) - signed))
    for page in sorted(by):
        files = sorted({x[2] for x in by[page] if x[2]})
        print("PAGE %2d  %2d sites   files: %s" % (page, len(by[page]), ", ".join(files)))
        for a, line, f, e, is_assert in by[page]:
            print("    %#07x  line %-5s %-34s %s%s" %
                  (a, line, f, e, "" if is_assert else "   [no signature]"))
    print("\ncounter-free hardware bit polls:")
    for s, e, bit, load in polls:
        print("    %#07x..%#07x PAGE %2d  bit %-2s  %s" % (s, e, e >> 12, bit, load))
    outside = sorted({a >> 12 for a, _w in dead} | {e >> 12 for _s, e, _b, _l in polls})
    print("\npages this module can paint: %s" % ", ".join(str(p) for p in outside))


if __name__ == "__main__":
    main()
