#!/usr/bin/env python3
"""Decode an android boot image header (v0/v1/v2) and compare two of them.

Field order is the one Resources/Scripts/mkbootimg.py writes in `write_header`:
each section's size is immediately followed by its load address, which is why a
generic AOSP layout table reads these fields shifted by one slot.

Run it on a built Mu image and on the tablet's own dump to see whether a stock
Qualcomm loader would find the kernel where it expects it.
"""
import struct
import sys

FIELDS = [
    ("kernel_size",    "<I", 8),
    ("kernel_addr",    "<I", 12),
    ("ramdisk_size",   "<I", 16),
    ("ramdisk_addr",   "<I", 20),
    ("second_size",    "<I", 24),
    ("second_addr",    "<I", 28),
    ("tags_addr",      "<I", 32),
    ("page_size",      "<I", 36),
    ("header_version", "<I", 40),
    ("os_version",     "<I", 44),
]


def decode (path: str) -> dict:
    with open (path, "rb") as handle:
        head  = handle.read (4096)
        total = handle.seek (0, 2)
    if head[:8] != b"ANDROID!":
        sys.exit (f"{path}: no ANDROID! magic")
    out = {name: struct.unpack_from (fmt, head, off)[0] for name, fmt, off in FIELDS}
    page = out["page_size"] or 2048
    out["name"]        = head[48:64].split (b"\0")[0].decode (errors = "replace")
    out["cmdline"]      = head[64:576].split (b"\0")[0].decode (errors = "replace")
    out["kernel_at"]    = hex (page)
    out["sections_end"] = hex (page + (out["kernel_size"] + page - 1) // page * page)
    out["file_size"]    = hex (total)
    return out


tables = [(path, decode (path)) for path in sys.argv[1:]]
names  = list (tables[0][1])
print ("                " + "".join (f"{path.split('/')[-1][:24]:>26}" for path, _ in tables))
for key in names:
    values = []
    for _, table in tables:
        value = table[key]
        values.append (f"{value:#x}" if isinstance (value, int) and key.endswith ("_addr")
                       else str (value))
    same = len (set (values)) == 1
    print (f"{key:14}" + "".join (f"{v:>26}" for v in values) + ("" if same else "   <-- differs"))
