#!/usr/bin/env python3
"""Print the firmware's own device regions, one `0x<base> 0x<size> <name>` line each.

Round 20's photograph can name a 64 KiB block of address space that a clock driver is
waiting inside, and a number is only useful once it has a name attached.  The list is not
assembled from a datasheet: it is the `MemoryMapLib.c` table this build actually hands to
the DXE core, which was transcribed row for row from the device's own `uefiplat.cfg`, so a
region that does not appear here is a region the firmware never mapped and a register in it
cannot be read.

Only the device rows are printed.  System RAM, the DXE heap and the framebuffer are not
places a clock control register lives, and listing them would let a stray poll address
"match" something meaningless.

    python3 scripts/clover-register-map.py > ~/clover-out/register-map.txt
    python3 scripts/read-clover-photo.py photo.jpg --register-map ~/clover-out/register-map.txt
"""

import os
import re
import sys

SRC = os.path.join("Platforms", "Xiaomi", "cloverPkg", "Library",
                   "MemoryMapLib", "MemoryMapLib.c")

# {"GCC CLK CTL", 0x00100000, 0x000B0000, AddDev, MMAP_IO, UNCACHEABLE, MmIO, NS_DEVICE},
ROW = re.compile(r'\{\s*"([^"]+)"\s*,\s*0x([0-9a-fA-F]+)\s*,\s*0x([0-9a-fA-F]+)\s*,\s*(\w+)')


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else SRC
    rows = []
    for line in open(path, encoding="utf-8", errors="ignore"):
        m = ROW.search(line)
        if m and m.group(4) in ("AddDev", "NoHob"):
            rows.append((int(m.group(2), 16), int(m.group(3), 16), m.group(1)))
    if not rows:
        sys.exit("no device rows found in %s -- is that the right path?" % path)
    print("# device regions from %s, sorted by base" % path)
    for base, size, name in sorted(rows):
        print("0x%08x 0x%08x %s" % (base, size, name))
    sys.stderr.write("%d device regions, %#x..%#x\n" %
                     (len(rows), min(r[0] for r in rows),
                      max(r[0] + r[1] for r in rows)))


if __name__ == "__main__":
    main()
