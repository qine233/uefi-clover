#!/usr/bin/env python3
"""Print FVMAIN's DXE dispatch order: the volume's files in physical order, named.

The DXE core scans a firmware volume in file order, so this list *is* the order the
dispatcher considers drivers, and it is a build artifact rather than something to
remember.  `FVMAIN.Fv.txt` gives offset and file GUID for every FFS file, `Guid.xref`
maps a GUID to the module that produced it, and joining them names the scan.

Run it against a build tree, in the build guest or anywhere the Build/ directory is:

    python3 scripts/fv-order.py ~/mu-build/Build/cloverPkg/RELEASE_CLANGPDB/FV
    python3 scripts/fv-order.py <fvdir> --grep clock
"""

import argparse
import os
import re


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("fvdir", nargs="?", default="Build/cloverPkg/RELEASE_CLANGPDB/FV")
    ap.add_argument("--grep", default=None, help="case-insensitive filter on the module name")
    a = ap.parse_args()

    xref = {}
    for line in open(os.path.join(a.fvdir, "Guid.xref"), encoding="utf-8", errors="ignore"):
        parts = line.split()
        if len(parts) == 2:
            xref[parts[0].upper()] = parts[1]

    order = []
    for line in open(os.path.join(a.fvdir, "FVMAIN.Fv.txt"), encoding="utf-8", errors="ignore"):
        m = re.match(r"^(0x[0-9a-fA-F]+) ([0-9a-fA-F-]{36})$", line.strip())
        if m:
            order.append((int(m.group(1), 16), m.group(2).upper()))
    if not order:
        raise SystemExit("no FFS files parsed out of %s -- is the FV built?" % a.fvdir)
    order.sort()

    total = int(re.search(r"EFI_FV_TOTAL_SIZE\s*=\s*(0x[0-9a-fA-F]+)", open(os.path.join(a.fvdir, "FVMAIN.Fv.txt")).read()).group(1), 16)

    for i, (off, guid) in enumerate(order, 1):
        name = xref.get(guid, "??? (a raw file, or a GUID Guid.xref does not list)")
        if a.grep and a.grep.lower() not in name.lower():
            continue
        end = order[i][0] if i < len(order) else total
        print("%3d  %#010x  %6d KiB  %s  %s" % (i, off, (end - off) // 1024, guid, name))
    print("\n%d files, %s named" % (len(order), sum(1 for _o, g in order if g in xref)))


if __name__ == "__main__":
    main()
