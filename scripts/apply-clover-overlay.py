#!/usr/bin/env python3
"""Apply this overlay onto a Mu-Silicium checkout and say what is still missing.

The overlay is not a fork: it is a device package that upstream's build already
knows how to find.  build_uefi.py looks for Platforms/*/*Pkg, and UniXNU's
scripts/unixnu/firmware.py opens Resources/Configs/<config>.toml from the
--uefi checkout, so copying these two trees into a plain Mu-Silicium clone is
all the integration there is.

Mapping applied:

    Platforms/Xiaomi/cloverPkg/**  ->  Platforms/Xiaomi/cloverPkg/**
    Resources/Configs/clover.toml  ->  Resources/Configs/clover.toml
    proprietary-files.txt          ->  Platforms/Xiaomi/cloverPkg/proprietary-files.txt

Everything else in this repository (scripts/, README.md, LICENSE) is overlay
tooling and stays here.

Re-running is safe: files are copied over, and anything in the checkout's
cloverPkg that this overlay does not provide is reported instead of deleted, so
local edits are never silently lost.  Pass --force to proceed with those edits
in place, --dry-run to see the plan only.
"""
from __future__ import annotations

import argparse
import pathlib
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve()
REPO = HERE.parents[1]
PKG_REL = pathlib.Path("Platforms/Xiaomi/cloverPkg")

# Files the overlay owns, relative to its own root, and where they land.
COPIED = [PKG_REL, pathlib.Path("Resources/Configs/clover.toml")]
DOC = pathlib.Path("proprietary-files.txt")

SUBMODULES = ["Common/Mu", "Common/Mu_OEM_Sample", "Silicium-ACPI",
              "Silicon/Silicium/OpensslPkg/Library/OpensslLib/openssl", "Binaries"]


def note(mark: str, message: str) -> None:
    print(f"  {mark}  {message}")


def source_files() -> list[pathlib.Path]:
    """Every file the overlay would copy, relative to the checkout root."""
    out = []
    for entry in COPIED:
        base = REPO / entry
        if base.is_dir():
            out += sorted(p.relative_to(REPO) for p in base.rglob("*")
                          if p.is_file() and p.name not in {".DS_Store"}
                          and "__pycache__" not in p.parts)
        elif base.is_file():
            out.append(entry)
        else:
            sys.exit(f"{base} is missing from the overlay")
    return out


def check_checkout(uefi: pathlib.Path) -> list[str]:
    problems = []
    for marker in ("build_uefi.py", "Platforms", "Resources/Configs", "Silicon/Qualcomm"):
        if not (uefi / marker).exists():
            problems.append(f"{uefi} has no {marker}; it is not a Mu-Silicium checkout")
    if not (uefi / "Silicon" / "Qualcomm" / "StarlordPkg").is_dir():
        problems.append("Silicon/Qualcomm/StarlordPkg is missing. clover is an SDM660 "
                        "board and clover.dsc !includes StarlordPkg/StarlordPkg.dsc.inc; "
                        "check the checkout is on a branch that has the SDM660 silicon "
                        "package (main)")
    return problems


def check_submodules(uefi: pathlib.Path) -> list[str]:
    """The firmware build needs these filled; Mu_Basecore only matters for the
    standalone build_uefi.py path, which patches it, so it is reported, not required."""
    missing = [name for name in SUBMODULES if not (uefi / name).is_dir()
               or not any((uefi / name).iterdir())]
    if missing:
        command = ["git", "-C", str(uefi), "submodule", "update", "--init", "--depth", "1",
                   "--", *[str(m) for m in missing]]
        note("!", "empty submodules: " + ", ".join(missing))
        note(">", " ".join(command))
    basecore = uefi / "Mu_Basecore"
    if not basecore.is_dir() or not any(basecore.iterdir()):
        note("-", "Mu_Basecore is not filled; only build_uefi.py needs it, UniXNU's "
                  "firmware step does not touch it")
    return missing


def copy_plan(uefi: pathlib.Path, sources: list[pathlib.Path]):
    create, update, foreign = [], [], []
    pkg_target = uefi / PKG_REL
    owned = set()
    for relative in sources:
        owned.add(relative)
        target = uefi / relative
        (update if target.is_file() else create).append(relative)
    if DOC.is_file():
        # Carried next to the package so a checkout documents its own blob needs.
        landing = PKG_REL / DOC.name
        target = uefi / landing
        (update if target.is_file() else create).append(DOC)
        owned.add(landing)
    if pkg_target.is_dir():
        for existing in sorted(pkg_target.rglob("*")):
            if existing.is_file() and existing.relative_to(uefi) not in owned:
                foreign.append(existing.relative_to(uefi))
    return create, update, foreign


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--uefi", type=pathlib.Path, default=REPO.parent / "Mu-Silicium",
                        help="the Mu-Silicium checkout to overlay (default: ../Mu-Silicium)")
    parser.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")
    parser.add_argument("--force", action="store_true",
                        help="apply even when the checkout's cloverPkg has files this "
                             "overlay does not provide")
    parser.add_argument("--no-check", action="store_true",
                        help="skip running check-clover-uefi.py afterwards")
    args = parser.parse_args()

    uefi = args.uefi.expanduser().resolve()
    if not uefi.is_dir():
        print(f"{uefi} is not a directory; clone Mu-Silicium first, see README.md",
              file=sys.stderr)
        return 2
    problems = check_checkout(uefi)
    for message in problems:
        note("X", message)
    if problems:
        return 2

    sources = source_files()
    create, update, foreign = copy_plan(uefi, sources)
    note("*", f"{len(create)} new, {len(update)} replaced")
    for relative in foreign:
        note("!", f"{relative} is in the checkout but not in this overlay")
    if foreign and not args.force:
        print("\nRefusing to leave those files unexplained. Remove them, or pass "
              "--force to keep them and apply anyway.", file=sys.stderr)
        return 2

    if args.dry_run:
        for relative in sorted(create + update):
            note(">", f"would copy {REPO / relative}")
        return 0

    for relative in sorted(create + update):
        source = REPO / relative if relative != DOC else REPO / DOC
        target = uefi / relative if relative != DOC else uefi / PKG_REL / DOC.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    note("ok", f"clover overlay applied to {uefi}")

    check_submodules(uefi)
    checker = HERE.parent / "check-clover-uefi.py"
    if not args.no_check:
        # Reported, not propagated: applying the overlay and populating Binaries/
        # are separate steps, and a nonzero status here normally just means the
        # tablet's own firmware has not been extracted yet.
        result = subprocess.run([sys.executable, str(checker), "--checkout", str(uefi)])
        if result.returncode:
            note("!", "check-clover-uefi.py reported the items above; the overlay is "
                      "applied, the build is not ready")
        else:
            note("ok", "check-clover-uefi.py is clean, the checkout can build")
    return 0


if __name__ == "__main__":
    sys.exit(main())
