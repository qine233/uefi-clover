#!/usr/bin/env python3
"""Split the appended DTB table out of the clover boot image.

The stock kernel is an Image.gz with the board's downstream DTBs appended after
the gzip stream, so they have to be cut out before anything can read them.  The
records are self-describing (big-endian totalsize), so no device tree compiler
is needed here -- `dtc` is only used afterwards, to name each blob.
"""
import struct
import sys
from pathlib import Path

FDT_MAGIC = b"\xd0\x0d\xfe\xed"


def header_fields (raw: bytes) -> dict:
    return {
        "kernel_size":    struct.unpack_from ("<I", raw, 8)[0],
        "ramdisk_size":   struct.unpack_from ("<I", raw, 12)[0],
        "second_size":    struct.unpack_from ("<I", raw, 16)[0],
        "page_size":      struct.unpack_from ("<I", raw, 20)[0],
        "header_version": struct.unpack_from ("<I", raw, 24)[0],
    }


def is_fdt (blob: bytes, off: int) -> bool:
    if off + 40 > len (blob) or blob[off:off + 4] != FDT_MAGIC:
        return False
    _, total, off_struct, _, _, version = struct.unpack_from (">6I", blob, off)
    return (16 <= total <= len (blob) - off
            and 40 <= off_struct < total
            and version >= 16)


def find_table (blob: bytes) -> int:
    off = blob.find (FDT_MAGIC)
    while off != -1:
        if is_fdt (blob, off):
            return off
        off = blob.find (FDT_MAGIC, off + 4)
    return -1


def main () -> int:
    boot   = Path (sys.argv[1]).expanduser ().resolve ()
    outdir = Path (sys.argv[2]).expanduser ().resolve ()
    raw    = boot.read_bytes ()
    if raw[:8] != b"ANDROID!":
        sys.exit (f"{boot} is not an android boot image")
    print ("boot header:", header_fields (raw))

    off = find_table (raw)
    if off == -1:
        sys.exit ("no appended DTB table found")

    dtbs, pos = [], off
    while is_fdt (raw, pos):
        total = struct.unpack_from (">I", raw, pos + 4)[0]
        dtbs.append (raw[pos:pos + total])
        pos += total

    outdir.mkdir (parents = True, exist_ok = True)
    for i, dtb in enumerate (dtbs):
        (outdir / f"{i:03d}.dtb").write_bytes (dtb)
    print (f"{len (dtbs)} DTBs, table at image offset {hex (off)}, "
           f"{sum (len (d) for d in dtbs)} bytes -> {outdir}")
    return 0


if __name__ == "__main__":
    sys.exit (main ())
