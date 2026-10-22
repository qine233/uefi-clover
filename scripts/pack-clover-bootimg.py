#!/usr/bin/env python3
"""Repack a Mu boot image using the tablet's own stock boot header geometry.

Why this exists: upstream's create_android_boot_img() calls mkbootimg.py with
only --header_version from the device config, so every other field falls back to
mkbootimg's *generic* defaults -- --pagesize 2048 and --base 0x10000000.  That is
fine for the shipping Xiaomi targets, which are all header v1/v2/v4, and those
ABLs honour page_size as read from the header.  clover's stock boot is header
**v0** with page_size 4096, base 0, kernel at +0x8000, ramdisk at +0x1000000 and
tags at +0x100.  A legacy v0 ABL is the one generation that may compute the
section offsets from its own hardcoded 4096 page instead of trusting the header;
if it does, it reads the kernel from 0x1000 while our image put it at 0x800 and
jumps into padding.

So instead of arguing about it, this script copies the stock header page
field-for-field (page size, all four load addresses, os_version, board name, the
whole cmdline, extra cmdline and any padding ABL expects) and replaces only the
three things that must differ: kernel_size, ramdisk_size and the image id.  The
sections are then laid out with stock's page size.

The payload does not have to be rebuilt: it is read back out of an existing
Mu-<device>.img, so this runs on the host against Build artifacts copied out of
the build guest.

  pack-clover-bootimg.py --mu Mu-clover.img --stock unixnu-boot.img \
                         --out Mu-clover-v0.img

Then check the result with decode-boot-header.py; every header row except
kernel_size, ramdisk_size and the section offsets should now match stock.
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import struct
import sys

MAGIC = b"ANDROID!"

# Header v0 field offsets (little-endian uint32 unless noted).
KERNEL_SIZE, KERNEL_ADDR = 8, 12
RAMDISK_SIZE, RAMDISK_ADDR = 16, 20
SECOND_SIZE, SECOND_ADDR = 24, 28
TAGS_ADDR, PAGE_SIZE_FIELD = 32, 36
HEADER_VERSION, OS_VERSION = 40, 44
NAME, CMDLINE, ID, EXTRA = 48, 64, 576, 608


def get_u32(buf: bytes, offset: int) -> int:
    return struct.unpack_from("<I", buf, offset)[0]


def put_u32(buf: bytearray, offset: int, value: int) -> None:
    struct.pack_into("<I", buf, offset, value)


def pages(size: int, page: int) -> int:
    return -(-size // page)


def read_header(path: pathlib.Path) -> bytes:
    with path.open("rb") as handle:
        first = handle.read(PAGE_SIZE_FIELD + 4)
        if not first.startswith(MAGIC):
            sys.exit(f"{path} does not start with ANDROID!")
        page = get_u32(first, PAGE_SIZE_FIELD)
        handle.seek(0)
        head = handle.read(page)
        if len(head) != page:
            sys.exit(f"{path} is shorter than its own header page ({page} bytes)")
        return head


def load_section(image: bytes, offset: int, size: int, name: str) -> bytes:
    blob = image[offset:offset + size]
    if len(blob) != size:
        sys.exit(f"{name} runs past the end of the image")
    return blob


def describe(label: str, header: bytes) -> None:
    page = get_u32(header, PAGE_SIZE_FIELD)
    fields = (
        ("kernel_size", get_u32(header, KERNEL_SIZE)),
        ("kernel_addr", f"0x{get_u32(header, KERNEL_ADDR):08x}"),
        ("ramdisk_size", get_u32(header, RAMDISK_SIZE)),
        ("ramdisk_addr", f"0x{get_u32(header, RAMDISK_ADDR):08x}"),
        ("tags_addr", f"0x{get_u32(header, TAGS_ADDR):08x}"),
        ("page_size", page),
        ("header_version", get_u32(header, HEADER_VERSION)),
        ("os_version", f"0x{get_u32(header, OS_VERSION):08x}"),
        ("name", header[NAME:NAME + 16].split(b"\0")[0].decode("ascii", "replace")),
        ("cmdline", header[CMDLINE:CMDLINE + 512].split(b"\0")[0].decode("ascii", "replace")[:48]),
    )
    print(f"  {label}:")
    for key, value in fields:
        print(f"    {key:<16} {value}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mu", type=pathlib.Path, required=True,
                        help="the Mu-<device>.img produced by build_uefi.py")
    parser.add_argument("--stock", type=pathlib.Path, required=True,
                        help="this tablet's own stock boot dump (the geometry donor)")
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--dry-run", action="store_true", help="report, write nothing")
    args = parser.parse_args()

    mu_header = read_header(args.mu)
    stock_header = bytearray(read_header(args.stock))

    # Pull the payload back out of the Mu image using *its* page size.
    mu_image = args.mu.read_bytes()
    mu_page = get_u32(mu_header, PAGE_SIZE_FIELD)
    kernel = load_section(mu_image, mu_page, get_u32(mu_header, KERNEL_SIZE), "kernel")
    ramdisk_page = pages(get_u32(mu_header, KERNEL_SIZE), mu_page)
    ramdisk = load_section(mu_image, mu_page + ramdisk_page * mu_page,
                           get_u32(mu_header, RAMDISK_SIZE), "ramdisk")

    if get_u32(stock_header, HEADER_VERSION) != 0:
        print(f"note: {args.stock} is header v{get_u32(stock_header, HEADER_VERSION)}, "
              "not v0 -- the geometry being cloned is still the donor's")
    put_u32(stock_header, KERNEL_SIZE, len(kernel))
    put_u32(stock_header, RAMDISK_SIZE, len(ramdisk))

    # Image id: sha1 over kernel, ramdisk and second, in that order, as
    # mkbootimg.py computes it.  second is absent here.
    digest = hashlib.sha1()
    for blob in (kernel, ramdisk, b""):
        digest.update(blob)
    stock_header[ID:ID + 20] = digest.digest()

    page = get_u32(stock_header, PAGE_SIZE_FIELD)
    out = bytearray(stock_header[:page])
    for blob in (kernel, ramdisk, b""):
        out += blob
        out += b"\0" * (pages(len(blob), page) * page - len(blob))

    describe("stock donor", bytes(stock_header[:page]))
    describe("output", bytes(out[:page]))
    print(f"\n  sections_end   0x{len(out):x} bytes written to {args.out}")
    if args.dry_run:
        print("  (dry run, nothing written)")
        return 0
    args.out.write_bytes(bytes(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
