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
| SoC | SDM660, `qcom,msm-id = <317 0x0>` (`0x13D`) |
| Silicon package | `Silicon/Qualcomm/StarlordPkg` |
| Cores | 4 Cortex-A53 `0x0-0x3` @1804800 kHz, 4 Kryo gold `0x100-0x103` @2208000 kHz |
| GIC | distributor `0x17A00000`/`0x10000`, redistributor `0x17B00000`/`0x100000`, stride `0x20000` |
| Timebase | 19.2 MHz |
| DRAM | low bank at `0x80000000`; the 4 GiB unit adds `0x1800000000` (not described yet) |
| Panel | 1200×1920, 32 bpp, splash handed over at `0x9D500000` + `0x2400000` |
| Storage | eMMC (`sdhc_1` at `0x0c0c4000`) — **no UFS** |
| Console | `blsp1_uart2` at `0x0C170000`, 115200 |
| Firmware volume | `0x9FC00000` + `0x300000` |

Both device trees disagree in one place that matters: `sdm660-common.dtsi` puts
the splash at `0x9d400000`, and `clover-overlay.dtsi` overrides it to
`0x9d500000` with `0x2400000` bytes.  The overlay follows the override, because
that is what this board's ABL actually reserves, and that shift is what squeezes
`FV Region` down to 1 MiB and moves `pstore` out of a usable address (it lands
inside the firmware volume, so a panic goes to the UART).

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

## Binaries/clover does not exist yet

`Project-Silicium/Device-Binaries` has 75 device directories and clover is not
among them; the nearest is lavender, another SDM660 board.  So the firmware
cannot link until the tablet's own DXE drivers are extracted — that is the whole
of `proprietary-files.txt`, and `check-clover-uefi.py` will not stop reporting
the 33 outstanding paths until they are on disk.

`apply-clover-overlay.py` never touches `Binaries/`; populate
`<checkout>/Binaries/clover/` from the dump and the checker confirms each stub
INF's `[Binaries.AARCH64]` table against the files next to it, which is the
error class that otherwise surfaces as an indecipherable AutoGen failure.

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
`header_version` in both configs, and whether board.toml still carries
`UNIXNU_BUILD`.

The TOML-backed groups need Python 3.11 or the `tomli` module; the rest runs on
3.9.

## Status

| | |
| --- | --- |
| Package skeleton | done, every line traced to a real upstream file or to clover's own device tree |
| Memory map | rebuilt from `clover-overlay.dtsi`, 50 rows, no undocumented collisions |
| Display | `USE_CUSTOM_DISPLAY_DRIVER = 0`, `SimpleFbDxe` on the splash handed over at `0x9D500000` |
| Storage | eMMC through `SdccDxe`; UFS dropped |
| Prebuilt blobs | **not available** — extraction from the tablet is the blocker |
| Board-id / ABL parameters | `TODO-DEVICE`, from `scripts/dump-clover-facts.sh` in the board repo |
| Second DRAM bank | not described; the 4 GiB unit's `0x1800000000` bank needs a map row and an ADT `/chosen` entry |
| Real build | unverified — no Mu-Silicium checkout with clover blobs exists |

`NumCpus` in `ConfigurationMapLib.c` and the userdata GPT window are marked
`TODO-DEVICE` in the source; they are the two numbers a dump settles and the
checker cannot.

## License

BSD-2-Clause-Patent, the same as Mu-Silicium, UniXNU and UniXNU-sheng.
