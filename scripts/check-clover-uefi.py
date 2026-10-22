#!/usr/bin/env python3
"""Consistency check for the clover Mu-Silicium overlay.

Run it from anywhere inside this repository.  Four groups, each independent:

  fv       expands Platforms/Xiaomi/cloverPkg/clover.fdf the way EDK II's FDF
           preprocessor would (!include, !if, !ifdef against the [Defines] of
           clover.dsc), collects every INF and RAW reference, and cross-checks
           the result against proprietary-files.txt.  This is the group that
           catches an include pointing at a module nobody wrote down.
  blobs    with --checkout <Mu-Silicium dir>, verifies the binary set is really
           on disk: each stub INF plus every file its [Binaries.AARCH64] table
           names.  Without the flag the group only reports the outstanding
           extraction work.
  map      parses cloverPkg/Library/MemoryMapLib/MemoryMapLib.c, checks the
           regions do not overlap, and pins the addresses the whole port rests
           on (DRAM base, the splash window, the firmware volume).
  board    cross-checks this overlay against UniXNU-clover: the firmware volume
           geometry in Resources/Configs/clover.toml, the boot image header
           version, and the !ifdef $(UNIXNU_BUILD) contract in board.toml
           [firmware.defines].

Exit status is 1 if any group reports an error; warnings do not fail the run.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve()
REPO = HERE.parents[1]
PKG = REPO / "Platforms" / "Xiaomi" / "cloverPkg"

# Facts about the tablet, each proven by a device-tree line quoted in
# UniXNU-clover/notes/clover-device-tree-sources.md.
DRAM_BASE = 0x80000000
SPLASH_BASE = 0x9D500000
SPLASH_SIZE = 0x02400000
FD_BASE = 0x9FC00000
FD_SIZE = 0x300000
STACK_BASE = 0x9FF90000
PANEL = (1200, 1920, 32)

# Mainline pins the video codec PIL region at 0x9cc00000 (sdm660-xiaomi-clover-
# common.dtsi) while the downstream tree only takes it from a reusable CMA pool
# in the low 512 MiB, so the UEFI map lets the DXE heap cover it and the ADT
# lists it for reference.  framebuffer0 is the usable part of the splash window
# and ramoops is the pstore collision described in make-clover-adt.py.  The zap
# shader page at 0xf0b00000 (mainline's gpu@f0b00000, deleted again by
# /delete-node/) only becomes live when a Qualcomm KGSL build loads
# a512_zap.mdt from userspace, which no UniXNU boot does, so it needs no
# reservation either.  These four are the only sanctioned collisions; anything
# else is a real bug.
# framebuffer0 is NOT exempt: it is 1200*1920*4 bytes at the splash base and must
# sit inside the Display Reserved row, which is exactly what this group proves.
OVERLAP_EXEMPT = ("pil_venus_mem", "ramoops", "gpu_zap_mem")

# Upstream describes the IMEM window twice: "IMEM Base" spans the whole 256 KiB
# at 0x14680000 and "IMEM Cookie Base" names the download cookie page inside it.
# A row nested in another one of these is intentional, not an overlap bug.
CONTAINED_OK = {("IMEM Base", "IMEM Cookie Base")}

# Packages that live in the Mu-Silicium checkout rather than in this overlay; an
# !include of one of them is only resolvable once the overlay has been applied.
EXTERNAL_PACKAGES = ("ArmPkg", "EmbeddedPkg", "FatPkg", "MdeModulePkg", "MdePkg",
                     "NetworkPkg", "OvmfPkg", "QcomPkg", "SiliciumPkg", "StarlordPkg")


def note(mark: str, message: str) -> None:
    print(f"  {mark}  {message}")


def strip_comment(line: str) -> str:
    """EDK II treats '#' as a comment start anywhere outside a quoted string."""
    out, quote = [], None
    for ch in line:
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
        elif ch in ('"', "'"):
            quote = ch
            out.append(ch)
        elif ch == "#":
            break
        else:
            out.append(ch)
    return "".join(out).strip()


def parse_defines(dsc: pathlib.Path) -> dict:
    """The [Defines] block of a DSC as {NAME: value}, quotes removed."""
    defines, section = {}, None
    for raw in dsc.read_text().splitlines():
        line = strip_comment(raw)
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].split(",")[0].strip()
            continue
        if section == "Defines" and "=" in line:
            key, value = (part.strip() for part in line.split("=", 1))
            defines[key] = value.strip('"')
    return defines


def evaluate(expr: str, defines: dict, where: str, problems: list) -> bool:
    """Decide the !if / !ifdef / !ifndef spellings this overlay actually uses."""
    expr = expr.strip()
    for keyword, present in (("ifdef", True), ("ifndef", False)):
        m = re.fullmatch(rf"!{keyword}\s+\$[\{{(](\w+)[\}})]", expr)
        if m:
            return (m.group(1) in defines) == present
    m = re.fullmatch(r"!if\s+\$[\{{(](\w+)[\}})]\s*(==|!=)\s*(\S+)", expr)
    if m:
        name, op, literal = m.group(1), m.group(2), m.group(3).strip('"')
        if name not in defines:
            problems.append(f"{where}: $(name) {name} is not defined in clover.dsc "
                            "[Defines] nor on the build command line")
            return False
        value = defines[name]
        same = (int(value) == int(literal)
                if value.isdigit() and literal.isdigit() else value == literal)
        return same if op == "==" else not same
    problems.append(f"{where}: check-clover-uefi.py cannot evaluate '{expr}'")
    return True


def resolve_include(current: pathlib.Path, target: str):
    """EDK II resolves !include along PACKAGES_PATH; here that is the package root."""
    for candidate in (PKG / target, current.parent / target):
        if candidate.is_file():
            return candidate
    return None


def is_external_include(target: str) -> bool:
    return target.split("/", 1)[0] in EXTERNAL_PACKAGES


def expand_fv(fdf: pathlib.Path, defines: dict, problems: list, externals=None):
    """Flatten clover.fdf into (included, guarded_out) lists of (path, kind, where)."""
    included, guarded_out = [], []
    externals = externals if externals is not None else []
    stack = [True]                      # one truth value per open conditional

    def walk(path: pathlib.Path, chain):
        for lineno, raw in enumerate(path.read_text().splitlines(), 1):
            line = strip_comment(raw)
            if not line:
                continue
            where = f"{path.relative_to(REPO)}:{lineno}"
            if line.startswith("!include"):
                if not all(stack):
                    continue
                target = line.split(None, 1)[1].strip()
                resolved = resolve_include(path, target)
                if resolved is None:
                    if is_external_include(target):
                        # Provided by the Mu-Silicium checkout: QcomPkg/Extra.fdf.inc
                        # pulls MassStorage and SiliciumPkg's rules.  Checked only when
                        # a checkout is on the command line.
                        externals.append((target, where))
                    else:
                        problems.append(f"{where}: !include {target} is not in this overlay")
                    continue
                if resolved in chain:
                    problems.append(f"{where}: !include loop at {resolved.name}")
                    continue
                walk(resolved, chain + [resolved])
                continue
            if line.startswith("!if"):        # !if, !ifdef, !ifndef
                stack.append(evaluate(line, defines, where, problems))
                continue
            if line == "!else":
                if len(stack) == 1:
                    problems.append(f"{where}: !else without an open !if")
                else:
                    stack[-1] = not stack[-1]
                continue
            if line == "!endif":
                if len(stack) == 1:
                    problems.append(f"{where}: !endif without an open !if")
                else:
                    stack.pop()
                continue
            if line.startswith("!"):
                continue                 # !define and friends: not used by this package
            m = re.match(r"INF\s+(\S+)$", line) or re.match(r"SECTION\s+RAW\s*=\s*(\S+)", line)
            if not m:
                continue
            entry = (m.group(1), "raw" if line.startswith("SECTION") else "inf", where)
            (included if all(stack) else guarded_out).append(entry)

    walk(fdf, [fdf])
    return included, guarded_out


def load_manifest(path: pathlib.Path, problems: list):
    """proprietary-files.txt as {path: marker}; marker is R, O or P."""
    entries = {}
    for lineno, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        m = re.fullmatch(r"([ROP])\s+(\S+)", line)
        if not m:
            problems.append(f"proprietary-files.txt:{lineno}: '{raw.strip()}' is not "
                            "'R|O|P <path>'")
            continue
        if m.group(2) in entries:
            problems.append(f"proprietary-files.txt:{lineno}: {m.group(2)} listed twice")
        entries[m.group(2)] = m.group(1)
    return entries


ROW = re.compile(r'\{\s*"([^"]+)"\s*,\s*(0x[0-9a-fA-F]+)\s*,\s*(0x[0-9a-fA-F]+)\s*,')


def parse_memory_map(source: pathlib.Path):
    """MemoryMapLib.c rows as [(name, base, size)]."""
    return [(m.group(1), int(m.group(2), 16), int(m.group(3), 16))
            for m in ROW.finditer(source.read_text())]


def board_firmware_defines(unixnu_arg=None) -> dict:
    """[firmware.defines] of the UniXNU board repo, {} when it is not visible."""
    unixnu = find_unixnu(unixnu_arg)
    if unixnu is None:
        return {}
    board = load_toml(unixnu / "board.toml") or {}
    return board.get("firmware", {}).get("defines", {}) or {}


def check_group_fv(problems: list, warnings: list, args_unixnu=None):
    dsc = PKG / "clover.dsc"
    fdf = PKG / "clover.fdf"
    if not dsc.is_file() or not fdf.is_file():
        problems.append("Platforms/Xiaomi/cloverPkg/clover.dsc or clover.fdf is missing")
        return {}, [], []
    defines = parse_defines(dsc)
    # firmware.py passes board.toml [firmware.defines] as -D on the EDK II command
    # line, and those are visible to !ifdef exactly like a [Defines] entry.  Merge
    # them here so the guards in DXE.inc can be evaluated offline.
    for name, value in board_firmware_defines(args_unixnu).items():
        defines.setdefault(name, str(value))
    externals = []
    included, guarded_out = expand_fv(fdf, defines, problems, externals)
    manifest = load_manifest(REPO / "proprietary-files.txt", problems)

    binaries = [e for e in included if e[0].startswith("Binaries/")]
    for path, kind, where in binaries:
        marker = manifest.get(path)
        if marker is None:
            problems.append(f"{where}: {path} is in the firmware volume but not in "
                            "proprietary-files.txt")
        elif kind == "raw" and marker == "P":
            problems.append(f"{where}: {path} is a clover blob, marked P (provided) "
                            "in the manifest")
        elif kind == "inf" and marker == "O" and "USE_CUSTOM_DISPLAY_DRIVER" not in defines:
            warnings.append(f"{path} is optional in the manifest but unconditional here")

    # A blob behind a guard that is off must be optional: requiring it would make
    # the checker fail a build that never reads the file.
    for path, kind, where in guarded_out:
        if not path.startswith("Binaries/clover/"):
            continue
        marker = manifest.get(path)
        if marker == "R":
            problems.append(f"{where}: {path} is compiled out by a guard yet marked "
                            "required; mark it O or enable the guard")
        elif marker is None:
            warnings.append(f"{path} is guarded out and not listed in the manifest "
                            "(fine, but nobody documented why)")

    referenced = {e[0] for e in included} | {e[0] for e in guarded_out}
    for entry in list(referenced):
        if entry.endswith(".inf"):
            stem = entry[:-4]
            referenced |= {stem + ".efi", stem + ".depex"}
    for path, marker in sorted(manifest.items()):
        if path.startswith("Binaries/clover/") and path not in referenced and marker == "R":
            problems.append(f"proprietary-files.txt: {path} is required but no include "
                            "references it")
    note("*", f"{len(included)} firmware volume entries, "
              f"{len(guarded_out)} behind a guard, {len(manifest)} manifest lines")
    for target, where in externals:
        note("*", f"{where} pulls in {target} from the Mu-Silicium checkout")
    return defines, included, externals


def check_group_blobs(included, externals, checkout, problems: list, warnings: list):
    """Presence of the prebuilt blobs, as far as the host can see them."""
    binaries = [e[0] for e in included if e[0].startswith("Binaries/")]
    # APRIORI.inc and DXE.inc both list the apriori modules, so report each path once.
    seen, unique = set(), []
    for path in binaries:
        if path not in seen:
            seen.add(path)
            unique.append(path)
    binaries = unique
    if checkout is None:
        mine = sorted(p for p in binaries if p.startswith("Binaries/clover/"))
        note("-", f"{len(mine)} files under Binaries/clover still have to be extracted "
                  "(no --checkout given); see proprietary-files.txt")
        return
    for target, where in externals:
        # A !include of an upstream package is only real once the overlay is applied;
        # EDK II finds these along PACKAGES_PATH, so look in the package roots the
        # board.toml lists rather than walking the whole checkout.
        roots = ["", "Silicon/Qualcomm", "Silicon/Silicium", "Common/Mu",
                 "Common/Mu_OEM_Sample", "Silicium-ACPI", "Platforms/Xiaomi"]
        if not any((checkout / root / target).is_file() for root in roots):
            problems.append(f"{where}: !include {target} resolves nowhere on the "
                            f"package path of {checkout.name}")
    for path in binaries:
        full = checkout / path
        if not full.is_file():
            problems.append(f"{checkout.name}/{path} is missing from the checkout")
            continue
        if path.endswith(".inf"):
            # A stub INF names its own payload files; if the two disagree the build
            # fails inside AutoGen with a message nobody connects to this manifest.
            text = full.read_text(errors="replace")
            table = re.search(r"\[Binaries\.AARCH64\](.*?)(?:\n\[|\Z)", text, re.S)
            if not table:
                warnings.append(f"{path} has no [Binaries.AARCH64] table")
            for m in re.finditer(r"^\s*(?:PE32|DXE_DEPEX|RAW|TE)\s*\|\s*([^|\s]+)",
                                 table.group(1) if table else "", re.M):
                if not (full.parent / m.group(1)).is_file():
                    problems.append(f"{path} names {m.group(1)} which is not next to it")
    note("*", f"checked {len(binaries)} blob paths against {checkout}")


def check_group_map(problems: list, warnings: list):
    source = PKG / "Library" / "MemoryMapLib" / "MemoryMapLib.c"
    if not source.is_file():
        problems.append("Library/MemoryMapLib/MemoryMapLib.c is missing")
        return {}
    rows = parse_memory_map(source)
    if len(rows) < 10:
        problems.append(f"MemoryMapLib.c parsed as only {len(rows)} rows, "
                        "expected the full SDM660 map")
        return {}
    by_name = {name: (base, size) for name, base, size in rows}
    for name, want in (("Display Reserved", (SPLASH_BASE, SPLASH_SIZE)),
                       ("UEFI FD", (FD_BASE, FD_SIZE)),
                       ("Kernel", (DRAM_BASE, None)),
                       ("UEFI Stack", (STACK_BASE, None))):
        got = by_name.get(name)
        if got is None:
            problems.append(f"MemoryMapLib.c has no {name!r} row")
        elif got[0] != want[0] or (want[1] is not None and got[1] != want[1]):
            problems.append(f"MemoryMapLib.c {name!r} is "
                            f"0x{got[0]:x}+0x{got[1]:x}, hardware says "
                            f"0x{want[0]:x}" + (f"+0x{want[1]:x}" if want[1] else ""))
    ordered = sorted(rows, key=lambda r: r[1])
    for left, right in zip(ordered, ordered[1:]):
        if right[1] >= left[1] + left[2]:
            continue
        if left[1] + left[2] >= right[1] + right[2] and (left[0], right[0]) in CONTAINED_OK:
            note("*", f"{left[0]!r} spans {right[0]!r} inside itself, the way upstream "
                      "describes the IMEM cookie")
            continue
        problems.append(f"MemoryMapLib.c {left[0]!r} 0x{left[1]:x}+0x{left[2]:x} runs "
                        f"into {right[0]!r} at 0x{right[1]:x}")
    top = max(base + size for _, base, size in rows)
    if top > 0x100000000:
        problems.append(f"MemoryMapLib.c reaches 0x{top:x}, past the low 4 GiB DRAM bank")
    note("*", f"{len(rows)} memory map rows, {len(ordered)} checked for overlap, "
              f"top of map 0x{top:x}")
    return by_name


def load_toml(path: pathlib.Path):
    try:
        import tomllib                                  # Python 3.11 and newer
    except ModuleNotFoundError:
        try:
            import tomli as tomllib                     # its pure-Python predecessor
        except ModuleNotFoundError:
            return None
    return tomllib.loads(path.read_text())


def find_unixnu(explicit: pathlib.Path):
    """The board repository.  Two layouts are supported: beside this checkout, or
    assembled as a UniXNU build tree that carries the overlay as its own board dir."""
    candidates = [explicit] if explicit else []
    candidates += [REPO.parent / "UniXNU-clover", REPO, pathlib.Path.cwd()]
    for candidate in candidates:
        if (candidate / "board.toml").is_file() and (candidate / "scripts" /
                "make-clover-adt.py").is_file():
            return candidate
    return None


def check_adt(unixnu, map_rows, problems, warnings):
    """The board spec inside make-clover-adt.py must agree with the UEFI map."""
    script = unixnu / "scripts" / "make-clover-adt.py"
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("make_clover_adt", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as error:                        # a broken ADT tool is a hard stop
        problems.append(f"{script} could not be imported: {error}")
        return
    hardware = getattr(module, "CLOVER_HARDWARE_SPEC", {})
    frame = hardware.get("framebuffer", {})
    if (frame.get("base"), frame.get("window_size")) != (SPLASH_BASE, SPLASH_SIZE):
        problems.append(f"ADT framebuffer is {frame.get('base'):x}+{frame.get('window_size'):x}, "
                        f"UEFI reserves Display Reserved at {SPLASH_BASE:x}+{SPLASH_SIZE:x}")
    if (frame.get("width"), frame.get("height")) != (PANEL[0], PANEL[1]):
        problems.append(f"ADT panel is {frame.get('width')}x{frame.get('height')}, "
                        f"clover.dsc sets PcdFrameBuffer* to {PANEL[0]}x{PANEL[1]}")
    fd_row = hardware.get("uefi_fd", {})
    if (fd_row.get("base"), fd_row.get("size")) != (FD_BASE, FD_SIZE):
        problems.append(f"ADT uefi_fd is {fd_row.get('base'):x}+{fd_row.get('size'):x}, "
                        f"clover.toml and the memory map say {FD_BASE:x}+{FD_SIZE:x}")
    if getattr(module, "DRAM_BASE", DRAM_BASE) != DRAM_BASE:
        problems.append("make-clover-adt.py DRAM_BASE moved away from 0x80000000")
    for region in hardware.get("reserved_memory", []):
        name = region["name"]
        base, size = region["base"], region["size"]
        if name in OVERLAP_EXEMPT:
            continue
        holder = next((row for row, (b, s) in map_rows.items() if b <= base and base + size <= b + s),
                      None)
        if holder is None:
            problems.append(f"ADT region {name} 0x{base:x}+0x{size:x} is not covered by any "
                            "MemoryMapLib reservation; XNU would be handed firmware memory")
        else:
            note("*", f"ADT {name} sits inside UEFI {holder!r}")


def check_group_board(map_rows, defines, problems, warnings, unixnu_arg):
    config = REPO / "Resources" / "Configs" / "clover.toml"
    if not config.is_file():
        problems.append("Resources/Configs/clover.toml is missing; build_uefi.py and "
                        "UniXNU's firmware.py both find the board through it")
        return
    toml = load_toml(config)
    if toml is None:
        note("-", "clover.toml not parsed (needs Python 3.11 or the tomli module)")
        return
    fd = toml.get("uefi_fd", {})
    for key, want in (("base", FD_BASE), ("size", FD_SIZE)):
        if fd.get(key) != want:
            problems.append(f"clover.toml [uefi_fd] {key} = {fd.get(key)}, "
                            f"MemoryMapLib and the device tree say {hex(want)}")
    if fd.get("blocks") is None:
        # build_uefi.py's compile_uefi() does hex(fd_config.get("blocks")) with no
        # default, so the standalone path needs the key; gta4l's config omits it
        # the same way this one does, and UniXNU's firmware.py never reads it
        # (it computes size // 0x1000 itself).  Warn rather than diverge from the
        # board that is known to work.
        warnings.append("clover.toml [uefi_fd] has no blocks= ; `build_uefi.py -d clover` "
                        "would raise in compile_uefi(). Add `blocks = 0x300` there if the "
                        "standalone path is wanted; the UniXNU firmware step does not read it")
    # firmware.py asserts the produced FD is exactly [uefi_fd] size bytes, and it
    # passes base/size/blocks as -D FD_BASE/-D FD_SIZE/-D FD_BLOCKS to EDK II, so
    # clover.fdf must use the macros rather than a hardcoded number.
    fdf_text = (PKG / "clover.fdf").read_text()
    for macro in ("$(FD_BASE)", "$(FD_SIZE)", "$(FD_BLOCKS)"):
        if macro not in fdf_text:
            problems.append(f"clover.fdf never uses {macro}; the firmware size would be "
                            "set independently of clover.toml")
    image = toml.get("boot_image", {})
    shim = toml.get("boot_shim", {})
    kernel = toml.get("boot_image_kernel", {})
    if str(image.get("header_version")) != "1":
        problems.append("clover.toml [boot_image] header_version must be 1 for this "
                        "board's fastboot")
    if not shim.get("requires_kernel_header"):
        problems.append("clover.toml [boot_shim] requires_kernel_header must be true: "
                        "mkbootimg writes a v1 header, so BootShim.S has to skip it")
    if kernel.get("append_dtb") and not (REPO / "Resources" / "DTBs" / "clover.dtb").is_file():
        # Only the standalone `build_uefi.py -d clover` path reads this; the UniXNU
        # path never calls build_uefi.py and packs its own Apple device tree.  A
        # derived DTB does not belong in this repository, so it is a warning with
        # the recipe rather than a committed blob.
        warnings.append(
            "clover.toml sets append_dtb but Resources/DTBs/clover.dtb is absent: a "
            "standalone boot.img cannot be packed until one is built from the board "
            "kernel, e.g. `dtc -O dtb -o Resources/DTBs/clover.dtb -b 0 -i "
            "arch/arm64/boot/dts/qcom -d /tmp/clover.dts <(cpp -nostdinc "
            "-I include -undef -D__DTS__ -x assembler-with-cpp "
            "arch/arm64/boot/dts/qcom/sdm660-xiaomi-clover.dts)`")

    unixnu = find_unixnu(unixnu_arg)
    if unixnu is None:
        note("-", "UniXNU-clover not found; use --unixnu to cross-check board.toml")
        return
    board = load_toml(unixnu / "board.toml")
    if board is None:
        note("-", f"{unixnu}/board.toml not parsed (needs tomllib or tomli)")
        return
    fw = board.get("firmware", {})
    if fw.get("config") != "clover":
        problems.append(f"{unixnu}/board.toml [firmware] config = {fw.get('config')!r}, "
                        "this overlay is clover")
    if fw.get("dsc") != "Platforms/Xiaomi/cloverPkg/clover.dsc":
        problems.append(f"{unixnu}/board.toml [firmware] dsc = {fw.get('dsc')!r} does not "
                        "point into Platforms/Xiaomi/cloverPkg")
    if "{uefi}/Platforms/Xiaomi" not in fw.get("packages", []):
        problems.append("board.toml [firmware] packages lacks {uefi}/Platforms/Xiaomi, so "
                        "EDK II cannot resolve cloverPkg")
    if "cloverPkg/clover.fdf" not in (PKG / "clover.dsc").read_text():
        problems.append("clover.dsc [Defines] FLASH_DEFINITION does not name "
                        "cloverPkg/clover.fdf")
    dsc_defines = fw.get("defines", {})
    if "UNIXNU_BUILD" not in dsc_defines:
        problems.append("board.toml [firmware.defines] has no UNIXNU_BUILD. firmware.py "
                        "turns that table into -D arguments, and clover.dsc/DXE.inc guard "
                        "UniXNU, UniXNUDxe and DarwinBoot with !ifdef $(UNIXNU_BUILD); "
                        "without the define the firmware volume has no loader in it")
    image_board = board.get("bootimg", {}).get("image", {})
    if image_board.get("header_version") != image.get("header_version"):
        problems.append(f"header version disagrees: board.toml {image_board.get('header_version')} "
                        f"vs clover.toml {image.get('header_version')}")
    dtb_nodes = board.get("bootimg", {}).get("dtb_node", [])
    splash_row = map_rows.get("Display Reserved") if map_rows else None
    quoted = re.findall(r"0x[0-9a-fA-F]+", str(dtb_nodes))
    if splash_row and "0x9d500000" not in [v.lower() for v in quoted]:
        problems.append("board.toml's [[bootimg.dtb_node]] splash reg does not name "
                        f"0x{SPLASH_BASE:x}, the address MemoryMapLib reserves for the panel")
    if map_rows:
        check_adt(unixnu, map_rows, problems, warnings)
    note("*", f"cross-checked against {unixnu}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--checkout", type=pathlib.Path, default=None,
                        help="a Mu-Silicium checkout with this overlay applied and "
                             "Binaries/clover populated")
    parser.add_argument("--unixnu", type=pathlib.Path, default=None,
                        help="path of the UniXNU-clover board repository")
    parser.add_argument("--quiet", action="store_true", help="only print problems")
    args = parser.parse_args()

    problems, warnings = [], []
    checkout = None
    if args.checkout:
        checkout = args.checkout.expanduser().resolve()
        if not checkout.is_dir():
            print(f"--checkout {checkout} is not a directory", file=sys.stderr)
            return 2

    print("fv: firmware volume contents against proprietary-files.txt")
    defines, included, externals = check_group_fv(problems, warnings, args.unixnu)
    print("blobs: prebuilt binaries")
    check_group_blobs(included, externals, checkout, problems, warnings)
    print("map: MemoryMapLib.c")
    map_rows = check_group_map(problems, warnings)
    print("board: this overlay against UniXNU-clover")
    check_group_board(map_rows, defines, problems, warnings, args.unixnu)

    if not args.quiet:
        for message in warnings:
            note("!", message)
    for message in problems:
        note("X", message)
    if not problems:
        note("ok", "no errors")
    print(f"\n{len(problems)} error(s), {len(warnings)} warning(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())




