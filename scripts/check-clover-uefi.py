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

# Facts about the tablet.  DRAM_BASE, the splash window, the firmware volume
# and the stack are all rows of the uefiplat.cfg in the device's own xbl
# partition (UniXNU-clover/facts/<serial>-<stamp>/fw/xbl-uefiplat.txt); the
# panel comes from the nt51021_boe downstream device tree.
DRAM_BASE = 0x80000000
SPLASH_BASE = 0x9D400000
SPLASH_SIZE = 0x02400000
FD_BASE = 0x9FC00000
FD_SIZE = 0x300000
STACK_BASE = 0x9FF90000
PANEL = (1200, 1920, 32)

# The stock boot image's own header, read out of this unit's `boot` and `recovery`
# partitions (facts/<serial>-<stamp>/img/unixnu-boot.img, unixnu-recovery.img --
# the prefix is the dump script's naming, the bytes are the partitions).  Both
# images agree on every value below, which is what makes them safe to treat as
# what this ABL accepts rather than as one vendor's quirk:
#
#   header_version 0        the slot at 0x28 is zero in both, and a v0 header is
#                           the shape the appended-DTB layout needs (no dtb slot)
#   page_size 0x1000        proven independently by the section arithmetic: the
#                           gzip kernel starts at 0x1000 and the ramdisk starts at
#                           0x1000 + align(kernel_size, 0x1000)
#   0x00008000 / 0x01000000 / 0x00000100 in the kernel_addr, ramdisk_addr and
#                           tags_addr slots -- base-relative offsets, with the
#                           0x80000000 base left out, which is why they look too
#                           small to be physical addresses
#
# The kernel section is Image.gz with the device trees appended after the gzip
# stream: 111 concatenated DTBs in `boot`, one in `recovery`.  That is the
# append_dtb shape this board packs, and the ABL selects among them by
# qcom,msm-id and qcom,board-id.  Neither image has an AVB footer or a non-zero
# `id` field, so nothing in the boot image itself is signed on this variant.
BOOT_HEADER_VERSION = 0
BOOT_PAGE_SIZE = 0x1000
BOOT_ADDRESSES = {"kernel_offset": 0x00008000,
                  "ramdisk_offset": 0x01000000,
                  "tags_offset": 0x00000100}

# Mainline pins the video codec PIL region at 0x9cc00000 (sdm660-xiaomi-clover-
# common.dtsi) while the downstream tree only takes it from a reusable CMA pool
# in the low 512 MiB, so the UEFI map lets the DXE heap cover it and the ADT
# lists it for reference.  framebuffer0 is the usable part of the splash window
# and ramoops is the pstore collision described in make-clover-adt.py.  The zap
# shader page at 0xf0b00000 (mainline's gpu@f0b00000, deleted again by
# /delete-node/) only becomes live when a Qualcomm KGSL build loads
# a512_zap.mdt from userspace, which no UniXNU boot does, so it needs no
# reservation either.  pil_adsp_mem is a collision the device's own map creates:
# the adsp window runs 0x92a00000..0x94900000, and uefiplat.cfg lists nothing
# between SMEM and "DXE Heap", so its top 9 MiB sit in memory the stock firmware
# treats as its own heap.  These four are the only sanctioned collisions;
# anything else is a real bug.
# framebuffer0 is NOT exempt: it is 1200*1920*4 bytes at the splash base and must
# sit inside the Display Reserved row, which is exactly what this group proves.
OVERLAP_EXEMPT = ("pil_venus_mem", "ramoops", "gpu_zap_mem", "pil_adsp_mem")

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
    """proprietary-files.txt as {path: marker}; marker is R or O."""
    entries = {}
    for lineno, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        m = re.fullmatch(r"([RO])\s+(\S+)", line)
        if not m:
            problems.append(f"proprietary-files.txt:{lineno}: '{raw.strip()}' is not "
                            "'R|O <path>'")
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


def board_firmware_defines(unixnu_arg=None, problems: list = None) -> dict:
    """[firmware.defines] of the UniXNU board repo, {} when it is not visible.

    The fv group needs these to evaluate the !ifdef guards in DXE.inc, so a board
    repository it cannot read is a problem, not a silent empty dict."""
    unixnu = find_unixnu(unixnu_arg, problems)
    if unixnu is None:
        return {}
    try:
        board = load_toml(unixnu / "board.toml") or {}
    except Exception as error:
        if problems is not None:
            problems.append(f"{unixnu}/board.toml did not parse: {error}")
        return {}
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
    for name, value in board_firmware_defines(args_unixnu, problems).items():
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


def mu_checkout(path: pathlib.Path) -> bool:
    """Whether this directory is a Mu-based tree rather than the overlay alone."""
    return any((path / probe).is_dir() for probe in
               ("Silicon", "Common", "MdeModulePkg", "ArmPkg"))


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
        # board.toml lists rather than walking the whole checkout.  Pointing
        # --checkout at this overlay instead is how it gets used before a Mu-Silicium
        # tree exists on the host, and the upstream packages are not in it by design.
        if not mu_checkout(checkout):
            continue
        roots = ["", "Silicon/Qualcomm", "Silicon/Silicium", "Common/Mu",
                 "Common/Mu_OEM_Sample", "Silicium-ACPI", "Platforms/Xiaomi"]
        if not any((checkout / root / target).is_file() for root in roots):
            problems.append(f"{where}: !include {target} resolves nowhere on the "
                            f"package path of {checkout.name}")
    if checkout != REPO and not mu_checkout(checkout):
        warnings.append(f"{checkout} has no Mu-Silicium packages, so the "
                        f"{len(externals)} upstream !include(s) were not resolved")
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
            # macOS still ships 3.9, and this file has to be checkable on the same
            # host that runs the dump scripts.  The subset below covers the two
            # board files: tables, arrays, inline tables, hex, strings, booleans.
            return toml_subset(path.read_text())
    return tomllib.loads(path.read_text())


def toml_split(text: str, at: str = ",") -> list:
    """Split on `at` outside quotes and brackets."""
    parts, depth, quote, start = [], 0, None, 0
    for i, char in enumerate(text):
        if quote:
            if char == quote and text[i - 1:i] != "\\":
                quote = None
            continue
        if char in "\"'":
            quote = char
        elif char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
        elif char == at and depth == 0:
            parts.append(text[start:i])
            start = i + 1
    parts.append(text[start:])
    return [p.strip() for p in parts if p.strip()]


def toml_unquote(text: str) -> str:
    text = text.strip()
    inner = text[1:-1]
    return inner.replace('\\"', '"').replace("\\\\", "\\") if text[0] == '"' else inner


def toml_value(text: str):
    text = text.strip()
    if text.startswith("[") and text.endswith("]"):
        return [toml_value(item) for item in toml_split(text[1:-1])]
    if text.startswith("{") and text.endswith("}"):
        return toml_table(text[1:-1])
    if text[:1] in "\"'" and text[-1:] == text[:1] and len(text) > 1:
        return toml_unquote(text)
    if text in ("true", "false"):
        return text == "true"
    try:
        return int(text, 16) if text[:2].lower() == "0x" else int(text, 10)
    except ValueError:
        return text


def toml_table(text: str) -> dict:
    table = {}
    for item in toml_split(text):
        key, _, value = item.partition("=")
        table[toml_value(key.strip())] = toml_value(value)
    return table


def toml_subset(text: str) -> dict:
    root: dict = {}
    stack: list = []                                   # the tables [a.b] descends into
    for line in _toml_logical_lines(text):
        line = line.strip()
        if line.startswith("[[") and line.endswith("]]"):
            keys = [toml_value(k) for k in line[2:-2].split(".")]
            parent = _toml_descend(root, keys[:-1])
            entry: dict = {}
            parent.setdefault(keys[-1], [])
            if not isinstance(parent[keys[-1]], list):
                raise ValueError(f"{line} redeclares {keys[-1]} as an array")
            parent[keys[-1]].append(entry)
            stack = [entry]
            continue
        if line.startswith("[") and line.endswith("]"):
            keys = [toml_value(k) for k in line[1:-1].split(".")]
            stack = [root]
            for key in keys:
                child = stack[-1].setdefault(key, {})
                if not isinstance(child, dict):
                    raise ValueError(f"{line} redeclares {key} as a value")
                stack.append(child)
            continue
        key, _, value = line.partition("=")
        stack[-1][toml_value(key.strip())] = toml_value(value)
    return root


def _toml_descend(root: dict, keys: list) -> dict:
    table = root
    for key in keys:
        table = table.setdefault(key, {})
    return table


def _toml_logical_lines(text: str):
    """One entry per key or header, comments dropped and arrays joined."""
    buffer = ""
    for raw in text.splitlines():
        line = raw.rstrip()
        cut = _toml_comment_at(line)
        if not buffer and cut == 0:
            continue
        line = line[:cut].rstrip() if cut >= 0 else line
        if not buffer and not line.strip():
            continue
        buffer = f"{buffer} {line.strip()}".strip() if buffer else line.strip()
        if _toml_balanced(buffer):
            yield buffer
            buffer = ""
    if buffer:
        yield buffer


def _toml_comment_at(line: str) -> int:
    quote = None
    for i, char in enumerate(line):
        if quote:
            if char == quote and line[i - 1:i] != "\\":
                quote = None
        elif char in "\"'":
            quote = char
        elif char == "#":
            return i
    return -1


def _toml_balanced(text: str) -> bool:
    quote = None
    depth = 0
    for i, char in enumerate(text):
        if quote:
            if char == quote and text[i - 1:i] != "\\":
                quote = None
        elif char in "\"'":
            quote = char
        elif char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
    return depth <= 0


def find_unixnu(explicit: pathlib.Path, problems: list = None):
    """The board repository.  Two layouts are supported: beside this checkout, or
    assembled as a UniXNU build tree that carries the overlay as its own board dir.

    An explicit --unixnu that does not look like the board repository is refused
    rather than replaced by the automatic search; silently falling back made a
    pointed-at-the-wrong-place run report the real repository as cross-checked."""
    if explicit:
        if (explicit / "board.toml").is_file() and (explicit / "scripts" /
                "make-clover-adt.py").is_file():
            return explicit
        if problems is not None:
            message = (f"{explicit} was named as the board repository but has no board.toml "
                       "and scripts/make-clover-adt.py, so nothing was cross-checked "
                       "against it")
            if message not in problems:          # two groups ask, one complaint
                problems.append(message)
        return None
    for candidate in [REPO.parent / "UniXNU-clover", REPO, pathlib.Path.cwd()]:
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
    hardware = getattr(module, "CLOVER_HARDWARE_SPEC", None)
    if not isinstance(hardware, dict) or "framebuffer" not in hardware:
        # An empty or restructured ADT tool imports cleanly and then has nothing to
        # say, which would otherwise surface as a formatting crash below.
        problems.append(f"{script} imported but carries no CLOVER_HARDWARE_SPEC framebuffer "
                        "spec, so the UEFI map has nothing to be compared against")
        return
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
        if holder is not None:
            note("*", f"ADT {name} sits inside UEFI {holder!r}")
            continue
        # The device's own map describes part of DRAM and leaves the rest out; a
        # carve-out with no row around it is only a problem where it cuts into a
        # row, because that is memory the stock firmware does claim.
        cut = [row for row, (b, s) in map_rows.items() if b < base + size and base < b + s]
        if cut:
            problems.append(f"ADT region {name} 0x{base:x}+0x{size:x} cuts into "
                            + " and ".join(repr(row) for row in cut)
                            + "; XNU would be handed firmware memory")
        else:
            note("*", f"ADT {name} lies in memory the device map does not list at all")


def check_group_board(map_rows, defines, problems, warnings, unixnu_arg):
    config = REPO / "Resources" / "Configs" / "clover.toml"
    if not config.is_file():
        problems.append("Resources/Configs/clover.toml is missing; build_uefi.py and "
                        "UniXNU's firmware.py both find the board through it")
        return
    try:
        toml = load_toml(config)
    except Exception as error:
        problems.append(f"clover.toml did not parse: {error}")
        return
    fd = toml.get("uefi_fd", {})
    for key, want in (("base", FD_BASE), ("size", FD_SIZE)):
        if fd.get(key) != want:
            problems.append(f"clover.toml [uefi_fd] {key} = {fd.get(key)}, "
                            f"MemoryMapLib and the device tree say {hex(want)}")
    if fd.get("blocks") is not None:
        # Verified against the checkout (build_uefi.py, before compile_uefi()):
        #   fd_config["blocks"] = fd_config["size"] // 4096
        # so the key is computed, never read -- upstream's own device configs do
        # not carry it.  UniXNU's firmware.py derives it the same way.
        warnings.append("clover.toml [uefi_fd] sets blocks=, but build_uefi.py overwrites "
                        "it with size // 4096; drop the key like every other device config")
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
    if str(image.get("header_version")) != str(BOOT_HEADER_VERSION):
        problems.append(f"clover.toml [boot_image] header_version is {image.get('header_version')}; "
                        f"both boot and recovery on this unit carry header version "
                        f"{BOOT_HEADER_VERSION}")
    # BootShim.S emits an arm64 Linux image header between its _Head branch and
    # _Start: text_offset = FD_BASE at 8, image_size = FD_SIZE at 16, "ARM\x64" at 56.
    # mkbootimg never writes those -- its boot header is the image's first page, outside
    # the kernel blob -- so this flag is Mu's way of showing the loader those fields,
    # and text_offset = 0x9fc00000 lies about the entry offset either way.
    # Round 6 turned it off and the tablet fell back to fastboot, which read like the
    # header being what makes ABL load us.  Round 6 was also kernel_compression = "none",
    # and rounds 5 and 8 -- "none", header on -- did the same, so the difference measured
    # the encoding.  Upstream's value is kept, and the claim about it stays a warning
    # until gzip-plus-no-header is actually put on the device.
    if not shim.get("requires_kernel_header"):
        warnings.append("clover.toml [boot_shim] requires_kernel_header is off: that is "
                        "the one combination never tested with kernel_compression = "
                        "\"gzip\" (round 6 was a \"none\" build), so its behaviour on this "
                        "unit is a guess")
    # This overlay now ships its own copy of upstream BootShim/BootShim.S with a
    # liveness probe: it paints ABL's already-live splash framebuffer before it
    # relocates the firmware volume, because a logo cannot distinguish "our code ran
    # and drew nothing" from "the loader never jumped to us".  A probe aimed at the
    # wrong window is worse than no probe -- it either never shows or scribbles over
    # memory the running loader still uses -- so bind it to the same map row every
    # other board number in this file is checked against.
    probe = REPO / "BootShim" / "BootShim.S"
    if probe.is_file():
        text = probe.read_text()
        mode = re.search(r"#define\s+PROBE_MODE\s+PROBE_(OFF|HANG|PAINT)", text)
        if mode is None:
            problems.append("BootShim/BootShim.S has no '#define PROBE_MODE PROBE_*' line, so "
                            "the checker cannot say what the probe in the shipped image does")
        elif mode.group(1) == "PAINT":
            got = re.search(r"\.equ\s+SPLASH_BASE,\s*(0x[0-9a-fA-F]+)", text)
            fill = re.search(r"\.equ\s+SPLASH_FILL,\s*(0x[0-9a-fA-F]+)", text)
            row = map_rows.get("Display Reserved") if map_rows else None
            if got is None or fill is None:
                problems.append("BootShim probe is PROBE_PAINT but no .equ SPLASH_BASE/"
                                "SPLASH_FILL is in scope for the checker to bind")
            elif row is None:
                warnings.append("BootShim probe is PROBE_PAINT but MemoryMapLib has no "
                                "'Display Reserved' row to validate it against")
            else:
                base, span = int(got.group(1), 0), int(fill.group(1), 0)
                if base != row[0]:
                    problems.append(f"BootShim/BootShim.S paints {base:#x}, but MemoryMapLib "
                                    f"starts 'Display Reserved' at {row[0]:#x}")
                elif base + span > row[0] + row[1]:
                    problems.append(f"BootShim/BootShim.S paints {span:#x} bytes from "
                                    f"{base:#x}, past the end of 'Display Reserved' at "
                                    f"{row[0] + row[1]:#x}")
                else:
                    note("*", f"BootShim splash probe covers {base:#x}+{span:#x}, inside "
                              f"'Display Reserved' {row[0]:#x}+{row[1]:#x}")
        elif mode.group(1) == "HANG":
            note("*", "BootShim probe is PROBE_HANG: the payload branches to itself at entry, "
                      "so the round is read from how long fastboot stays away, not from the "
                      "screen (seconds = ABL never entered; never = it did)")
        else:
            warnings.append("BootShim/BootShim.S is copied into the checkout with "
                            "PROBE_MODE = PROBE_OFF, i.e. it only reverts upstream's file; "
                            "delete it and its COPIED entry unless that is intended")

    # The second probe layer: bars inside the firmware itself, so one boot reports
    # how far it got instead of only that it started.  Include/Checkpoint.h holds the
    # splash base and the bar size; the stage files pass an offset and a colour.  Two
    # things are worth failing on: a base that is not the row the map reserves (the
    # bars would land on the DXE heap, or on nothing), and a bar outside the window
    # BootShim filled, which would make the reading depend on where ABL's logo happened
    # to be rather than on the code that ran.
    ladder = REPO / "Platforms" / "Xiaomi" / "cloverPkg" / "Include" / "Checkpoint.h"
    if ladder.is_file():
        head = ladder.read_text()
        cbase = re.search(r"#define\s+CLOVER_SPLASH_BASE\s+(0x[0-9a-fA-F]+)", head)
        csize = re.search(r"#define\s+CLOVER_BAR_SIZE\s+(0x[0-9a-fA-F]+)", head)
        stages = {}
        for path in sorted((REPO / "Platforms" / "Xiaomi" / "cloverPkg").rglob("*")):
            if path.suffix not in {".c", ".h"} or path == ladder:
                continue
            for offset in re.findall(r"CloverCheckpointBar\s*\(\s*(0x[0-9a-fA-F]+)",
                                     path.read_text(errors="ignore")):
                stages.setdefault(int(offset, 0), path.name)
        row = map_rows.get("Display Reserved") if map_rows else None
        if cbase is None or csize is None:
            problems.append("Include/Checkpoint.h must keep its #define CLOVER_SPLASH_BASE "
                            "and CLOVER_BAR_SIZE on one line each; the checker reads them "
                            "to prove the bars are inside the panel window")
        elif row is None:
            warnings.append("checkpoint bars are in the tree but MemoryMapLib has no "
                            "'Display Reserved' row to validate them against")
        else:
            base, size = int(cbase.group(1), 0), int(csize.group(1), 0)
            if base != row[0]:
                problems.append(f"Include/Checkpoint.h paints at {base:#x}, but MemoryMapLib "
                                f"starts 'Display Reserved' at {row[0]:#x}")
            elif not stages:
                problems.append("Include/Checkpoint.h is in the tree but no "
                                "CloverCheckpointBar call site exists, so the shipped image "
                                "has no checkpoint bars to read")
            else:
                filled = 0x00800000
                if probe.is_file():
                    match = re.search(r"\.equ\s+SPLASH_FILL,\s*(0x[0-9a-fA-F]+)",
                                      probe.read_text())
                    if match:
                        filled = int(match.group(1), 0)
                outside = [f"{offset:#x} in {name}" for offset, name in sorted(stages.items())
                           if offset + size > row[1]]
                unfilled = [f"{offset:#x} in {name}" for offset, name in sorted(stages.items())
                            if offset + size > filled]
                if outside:
                    problems.append("checkpoint bar runs past 'Display Reserved': "
                                    + ", ".join(outside))
                elif unfilled:
                    problems.append(f"checkpoint bar sits outside the {filled:#x} BootShim "
                                    "filled, so its visibility depends on ABL's logo and not "
                                    "on the code: " + ", ".join(unfilled))
                else:
                    note("*", f"checkpoint ladder has {len(stages)} bars at "
                              + ", ".join(f"{offset:#x}" for offset in sorted(stages))
                              + f", each {size:#x} bytes, all inside the BootShim fill")
        apriori = REPO / "Platforms" / "Xiaomi" / "cloverPkg" / "Include" / "APRIORI.inc"
        dxe = REPO / "Platforms" / "Xiaomi" / "cloverPkg" / "Include" / "DXE.inc"
        if stages and apriori.is_file() and dxe.is_file():
            for name, text in (("APRIORI.inc", apriori.read_text()),
                               ("DXE.inc", dxe.read_text())):
                if "CheckpointDxe.inf" not in text:
                    problems.append(f"{name} does not list CheckpointDxe.inf, so the "
                                    "checkpoint driver is not in the firmware volume and "
                                    "its bars can never appear")
        # Measured, the hard way: an INF that only the FDF lists is not built at all,
        # and the build stops with "Module ... NOT found in DSC file; Is it really a
        # binary module?".  The vendor blobs escape this because QcomPkg.dsc.inc
        # declares them; a module of our own has to appear in clover.dsc too.
        dsc = REPO / "Platforms" / "Xiaomi" / "cloverPkg" / "clover.dsc"
        if dsc.is_file():
            listed = set()
            for text in (apriori, dxe):
                if text.is_file():
                    listed |= set(re.findall(r"INF\s+(cloverPkg/\S+\.inf)", text.read_text()))
            absent = sorted(p for p in listed if p not in dsc.read_text())
            if absent:
                problems.append("clover.dsc [Components] does not declare "
                                + ", ".join(absent)
                                + "; the FDF alone does not build a module")
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

    unixnu = find_unixnu(unixnu_arg, problems)
    if unixnu is None:
        if unixnu_arg is None:
            note("-", "UniXNU-clover not found; use --unixnu to cross-check board.toml")
        return
    try:
        board = load_toml(unixnu / "board.toml")
    except Exception as error:
        problems.append(f"{unixnu}/board.toml did not parse: {error}")
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
    def number(value):
        return int(value, 0) if isinstance(value, str) else int(value)

    if number(image_board.get("pagesize", 0)) != BOOT_PAGE_SIZE:
        problems.append(f"board.toml [bootimg.image] pagesize is {image_board.get('pagesize')}; "
                        f"the stock images set page_size to {BOOT_PAGE_SIZE:#x}")
    for key, want in BOOT_ADDRESSES.items():
        got = image_board.get(key)
        if got is None:
            problems.append(f"board.toml [bootimg.image] has no {key}")
        elif number(got) != want:
            problems.append(f"board.toml [bootimg.image] {key} is {number(got):#x}, but the header "
                            f"of this unit's own boot and recovery images says {want:#x}")
    if number(image_board.get("base", 0)) != 0:
        problems.append("board.toml [bootimg.image] base must stay 0: the stock headers keep the "
                        "0x80000000 DRAM base out of the kernel_addr, ramdisk_addr and tags_addr "
                        "slots, and adding it here would double it against what the ABL applies")
    dtb_nodes = board.get("bootimg", {}).get("dtb_node", [])
    splash_row = map_rows.get("Display Reserved") if map_rows else None
    quoted = re.findall(r"0x[0-9a-fA-F]+", str(dtb_nodes))
    if splash_row and f"0x{SPLASH_BASE:x}" not in [v.lower() for v in quoted]:
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




