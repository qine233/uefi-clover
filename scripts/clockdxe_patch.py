"""ClockDxe.patched.efi: the six calls upstream Mu-Silicium disables in this blob.

On SDM660 the stock ClockDxe parks forever in MMCC's RCGR update handshake and in
a GDSC power-on wait when the DXE is a second UEFI run, entered after ABL has
released the resources the first XBL DXE used.  Project-Silicium's Device-Binaries
ships ClockDxe.patched.efi for every SDM660 board, and lavender's INF selects it;
the patch is six BL instructions in the clock-plan init replaced by NOP, so the
clock's descriptor is registered without the set-rate/parent steps that wait on
hardware that is no longer powered.

This module applies the same six edits to clover's own blob.  The offsets are
verified against the stock bytes before anything is written: a blob that does not
carry those instructions is refused rather than patched at a guessed address.
"""
import argparse
import hashlib
import pathlib
import sys

# file offset -> the BL word the stock blob carries there (little endian)
SITES = {
    0x7BD8: bytes.fromhex("95 eb ff 97"),
    0x7BF8: bytes.fromhex("49 ec ff 97"),
    0x7C04: bytes.fromhex("8a eb ff 97"),
    0x7C14: bytes.fromhex("86 eb ff 97"),
    0x7C38: bytes.fromhex("39 ec ff 97"),
    0x7C6C: bytes.fromhex("b5 ec ff 97"),
}
NOP = bytes.fromhex("1f 20 03 d5")


class PatchError(Exception):
    pass


def is_patched(data: bytes) -> bool:
    return all(data[offset:offset + 4] == NOP for offset in SITES)


def apply(data: bytes) -> bytes:
    wrong = [offset for offset, stock in SITES.items()
             if data[offset:offset + 4] != stock and data[offset:offset + 4] != NOP]
    if wrong:
        raise PatchError("the blob does not carry the stock instructions at "
                         + ", ".join(f"{offset:#x}" for offset in sorted(wrong)))
    patched = bytearray(data)
    for offset in SITES:
        patched[offset:offset + 4] = NOP
    changed = sum(1 for a, b in zip(data, patched) if a != b)
    if changed != 6 * 4:
        raise PatchError(f"the patch changed {changed} bytes, not 24")
    return bytes(patched)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("blob", type=pathlib.Path, help="a stock ClockDxe.efi")
    parser.add_argument("-o", "--output", type=pathlib.Path,
                        help="patched output (default: <blob>.patched.efi next to it)")
    parser.add_argument("--check", action="store_true",
                        help="only report whether the blob already carries the patch")
    args = parser.parse_args()
    data = args.blob.expanduser().read_bytes()
    if args.check:
        print(f"{args.blob}: {'patched' if is_patched(data) else 'stock'}")
        return 0 if is_patched(data) else 1
    out = args.output or args.blob.with_name(args.blob.stem + ".patched.efi")
    patched = apply(data)
    out.write_bytes(patched)
    print(f"{out}: {len(SITES)} calls -> NOP, {len(patched)} bytes, "
          f"sha256 {hashlib.sha256(patched).hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
