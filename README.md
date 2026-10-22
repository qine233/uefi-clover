# uefi-clover

Mu-Silicium device package for the **Xiaomi Mi Pad 4 8" LTE** (`clover`,
`xiaomi,clover-lte`, Qualcomm **SDM660**), written for the sibling board
repository `UniXNU-clover`, which builds the XNU kernel and the boot image.
UniXNU boots iPadOS-era XNU on this tablet through UEFI, and this overlay is the
UEFI half of that work.

It is an **overlay, not a fork**: 13 files that land inside a plain
`Project-Silicium/Mu-Silicium` checkout.

```
Platforms/Xiaomi/cloverPkg/clover.dsc          the platform
Platforms/Xiaomi/cloverPkg/clover.fdf          the firmware volume layout
Platforms/Xiaomi/cloverPkg/clover.dec          placeholder, upstream ships these empty
Platforms/Xiaomi/cloverPkg/DeviceBuild.py      the stuart builder build_uefi.py expects
Platforms/Xiaomi/cloverPkg/Include/APRIORI.inc DXE apriori order for clover
Platforms/Xiaomi/cloverPkg/Include/DXE.inc     the module list
Platforms/Xiaomi/cloverPkg/Include/RAW.inc     SecParti.cfg and friends
Platforms/Xiaomi/cloverPkg/Library/MemoryMapLib          clover's own DDR map
Platforms/Xiaomi/cloverPkg/Library/ConfigurationMapLib   the SDM660 register table
Resources/Configs/clover.toml                  firmware volume geometry, boot image packing
proprietary-files.txt                          what must be extracted from the tablet
scripts/apply-clover-overlay.py                copy this overlay into a checkout
scripts/check-clover-uefi.py                   verify the result, and the two repos agree
```

## The tablet, as far as the firmware cares

| | |
| --- | --- |
| SoC | Qualcomm SDM660 |
| Silicon package | `Silicon/Qualcomm/StarlordPkg` |
| Board id | `qcom,msm-id = <317 0>`, `qcom,board-id = <0x0001000b 0>` — platform 11 (MTP) with subtype 1, read off the merged dtb on the device |
| Cores | 8 CPUs, `cpu@0-3` (`reg` 0x0-0x3) are CPU part `0x801` and `cpu@100-103` (`reg` 0x100-0x103) are `0x800` — Kryo 260 Silver/A53-based and Gold/A73-based, 1.8 and 2.2 GHz in the downstream tree; `enable-method = "psci"` |
| GIC | distributor `0x17A00000`/`0x10000`, redistributor `0x17B00000`/`0x100000`, stride `0x20000` |
| Timebase | 19.2 MHz |
| DRAM | `0x80000000` + `0x80000000` and `0x100000000` + `0x7E4C0000` (the 4 GiB unit; only the low bank is described) |
| Panel | 1200×1920, 32 bpp, splash handed over at `0x9D400000` + `0x2400000` |
| Storage | eMMC (`sdhc_1` at `0x0c0c4000`) — **no UFS** |
| Console | `blsp1_uart2` at `0x0C170000`, 115200 |
| Firmware volume | `0x9FC00000` + `0x300000` |

The two things here that a device tree cannot settle were settled by the tablet
itself.  `sdm660-common.dtsi` puts the splash at `0x9d400000` and
`clover-overlay.dtsi` overrides it to `0x9d500000`, but the `uefiplat.cfg`
inside *this unit's* xbl partition reserves `0x9D400000` + `0x2400000` as
"Display Reserved", and stock xbl has already drawn into it before any UEFI code
runs — so the framebuffer SimpleFbDxe can hand over is at `0x9D400000`, which is
what `MemoryMapLib.c`, `clover.toml`, and the ADT's `display`/`framebuffer0` all
say.  The same file's `[MemoryMap]` (14 rows) and `[RegisterMap]` (33 rows) are
transcribed row for row into `Library/MemoryMapLib`, and its `[ConfigParameters]`
(27 of 33 keys) into `Library/ConfigurationMapLib`; the map stops at
`0xA0000000`, so nothing above the low 2 GiB bank is described to XNU yet.

One consequence of that adjacency: `ramoops`/pstore wants `0x9FE00000` + `0x100000`
on this SoC, which is inside the firmware volume, so there is no usable panic
region under UniXNU and a panic goes to the UART instead.


## Setup

```sh
git clone --recurse-submodules https://github.com/Project-Silicium/Mu-Silicium
cd uefi-clover
python3 scripts/apply-clover-overlay.py --uefi ../Mu-Silicium
```

The apply step is idempotent, reports files in the checkout that this overlay
does not own instead of deleting them, and finishes by running the checker.

Then either path:

**Through UniXNU** (this is the supported one).  From the board repository:

```sh
cd UniXNU
./unixnu defconfig clover_defconfig -D ../UniXNU-clover
./unixnu build firmware --uefi ../Mu-Silicium
```

`scripts/unixnu/firmware.py` reads `board.toml`, opens
`Resources/Configs/clover.toml` for the `[uefi_fd]` geometry, passes every
`[firmware.defines]` key as `-D`, and calls EDK II's `build` directly with
`-p Platforms/Xiaomi/cloverPkg/clover.dsc`.

**Standalone**, for a firmware image to flash without the UniXNU kernel:

```sh
cd ../Mu-Silicium && python3 build_uefi.py -d clover
```

Two caveats, both verified against upstream's own source: `compile_uefi()` reads
`fd_config["blocks"]` with no default and `[uefi_fd] blocks` is not in a device
config that works today (gta4l's has the same shape as this one), so add
`blocks = 0x300` locally if you go this way; and `append_dtb = true` makes
packing read `Resources/DTBs/clover.dtb`, which this repository does not ship —
build it from the board kernel with `dtc`, the command is in the checker's
warning.

## What UniXNU adds to a stock device package

gta4l's README says to hand-edit `gta4l.dsc` and `Include/DXE.inc` after each
checkout update.  That works and it is fragile, so clover carries the same three
modules behind a define instead:

```
!ifdef $(UNIXNU_BUILD)
  INF UniXNUPkg/Application/UniXNU/UniXNU.inf
  INF UniXNUPkg/Driver/UniXNUDxe/UniXNUDxe.inf
  INF DarwinBootPkg/Driver/DarwinBoot.inf
!endif
```

in `Include/DXE.inc`, mirrored in `clover.dsc` (the `UniXNULib` library mapping
plus the same three components).  `UniXNU-clover/board.toml` sets
`UNIXNU_BUILD = "1"` in `[firmware.defines]`, and `firmware.py` turns that table
into `-D` arguments, so the symbols are visible to `!ifdef` exactly like a
`[Defines]` entry.  A checkout with this overlay applied therefore builds two
different things from one DSC: plain Android firmware with
`build_uefi.py -d clover`, and firmware with a DarwinBoot loader and the UniXNU
application under UniXNU.  Nothing to re-apply after a `git pull`.

The two package roots are the board repository's: `{tree}/package` supplies
`UniXNUPkg`, `{tree}/drivers/DarwinBoot` supplies `DarwinBootPkg`, and
`[firmware] packages` in board.toml puts both on the EDK II package path.
`UniXNUDxe` has a Depex on the variable arch plus write protocols, which Mu's
variable stack (`VariableRuntimeDxe`, in `APRIORI.inc`) provides.

## Binaries/clover: extracted from this tablet, not from Device-Binaries

`Project-Silicium/Device-Binaries` has 75 device directories and clover is not
among them; the nearest is lavender, another SDM660 board.  So the blob set is
produced locally, from the unit's own firmware:

```sh
python3 scripts/extract-clover-blobs.py --xbl <dump>/fw/p-xbl.bin --list   # inventory
python3 scripts/extract-clover-blobs.py --xbl <dump>/fw/p-xbl.bin          # write it
```

clover has no `uefi`/`uefi_a` partition.  The SEC in `xbl` (mmcblk0p1) gunzips a
firmware volume that lives *inside that same partition* — a gzip stream at
offset `0xa89b0` on this unit, inflating to a `_FVH` volume with `FvLength`
`0x459040`, 83 FFS records of which 68 are AArch64 PE32 images.  The extractor
walks those records and writes only what `APRIORI.inc`, `DXE.inc` and `RAW.inc`
ask for, regenerating each stub INF with the `FILE_GUID` read from the volume
rather than one borrowed from lavender; every module this board carries matched
a GUID upstream already publishes.  That lands 91 files under `Binaries/clover`
(30 INF, 30 EFI, 27 DEPEX, 4 RAW config blobs), and the checker resolves all
33 blob paths the firmware volume requests against them.

`Binaries/` is gitignored — the set comes from a device nobody else owns, and
`proprietary-files.txt` is the reviewable contract for it.  `apply-clover-overlay.py`
never touches it, so a checkout has to be populated the same way.  The checker
compares each stub INF's `[Binaries.AARCH64]` table with the files next to it,
which is the error class that otherwise surfaces as an indecipherable AutoGen
failure.

## Checking

```sh
python3 scripts/check-clover-uefi.py                      # offline
python3 scripts/check-clover-uefi.py --checkout ../Mu-Silicium
```

Four groups.  `fv` expands `clover.fdf` the way EDK II's preprocessor would —
`!include` along the package roots, `!if`/`!ifdef` against `clover.dsc` merged
with board.toml's defines — and cross-checks every `INF` and `SECTION RAW`
against `proprietary-files.txt`, in both directions.  `blobs` looks at a real
checkout.  `map` parses `MemoryMapLib.c` and fails on any overlap that is not
the documented IMEM nesting.  `board` pins the geometry across the two
repositories: `[uefi_fd]` in clover.toml, the `UEFI FD` row, the ADT's
`uefi_fd`, the splash window in `[[bootimg.dtb_node]]` versus `Display Reserved`,
every ADT reserved region against the memory map (contained, or an announced
collision on the device's own carve-outs), `header_version` in both configs, and
whether board.toml still carries `UNIXNU_BUILD`.

Point `--checkout` at this repository to check the overlay alone; upstream's two
`!include`s are then reported as unresolved rather than as errors, because the
Mu packages only exist in a real checkout.  The TOML groups use `tomllib`,
`tomli`, or the built-in subset reader, so the whole check runs on the stock
macOS Python 3.9.

## Status

| | |
| --- | --- |
| Package skeleton | done, every line traced to a real upstream file, to clover's own device tree, or to this unit's firmware |
| Memory map | 47 rows transcribed row-for-row from the device's `uefiplat.cfg` (14 `[MemoryMap]` + 33 `[RegisterMap]`), no undocumented collisions |
| Configuration map | 27 `[ConfigParameters]` keys, same file; `NumCpus = 4`/`NumActiveCores = 8` cross-checked against `/proc/cpuinfo` |
| Display | `USE_CUSTOM_DISPLAY_DRIVER = 0`, `SimpleFbDxe` on the splash handed over at `0x9D400000` |
| Storage | eMMC through `SdccDxe`; UFS dropped (the driver is in the volume, the board is not UFS) |
| USB | DWC3 device stack only; no XHCI anywhere in this unit's firmware |
| Prebuilt blobs | extracted into `Binaries/clover` from the tablet's own xbl; gitignored, re-create with the extractor |
| Board-id / DRAM / userdata / GIC | dumped and applied — `scripts/dump-clover-facts.sh` in the board repo, results under `facts/` |
| Second DRAM bank | not described; `0x100000000 + 0x7E4C0000` needs a map row and a second `/chosen` window before XNU sees past 4 GiB |
| Boot image packing | `header_version = 1` is unconfirmed: this stock boot header's address fields do not line up with the documented layout, so `[bootimg.image]` still carries placeholder offsets |
| Real build | unverified — the overlay is complete and self-consistent, but no Mu-Silicium checkout has been assembled on this host yet |

Flashing this firmware means writing a new `xbl` partition, the one the signed
boot chain starts from: a bad image there is the recoverable kind of bad only as
long as PBL still accepts the EDL path.  Nothing here has been flashed.

## License

BSD-2-Clause-Patent, the same as Mu-Silicium, UniXNU and UniXNU-sheng.
