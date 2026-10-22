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

The boot image is v0, not the v1 lavender declares: `boot` and `recovery` on this
unit both have 0 in the header version slot, `page_size` 0x1000, and base-relative
load offsets (kernel `0x8000`, ramdisk `0x1000000`, tags `0x100`) with the
`0x80000000` left for the ABL to add.  Their kernel section is `Image.gz` with the
device trees appended after the gzip stream — 111 concatenated DTBs in `boot`, one
in `recovery`, selected by `qcom,msm-id`/`qcom,board-id` — which is the `append_dtb`
shape, and neither image carries an AVB footer.  `check-clover-uefi.py` pins those
numbers against `board.toml`.


## Setup

```sh
bash scripts/fetch-mu-silicium.sh ../Mu-Silicium     # see "Build host" below
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

That is the path this repository is actually tested through.  Two things about
it, both read out of upstream's `build_uefi.py` rather than assumed:

* `blocks` is not a config key.  `compile_uefi()` sets
  `fd_config["blocks"] = fd_config["size"] // 4096` before it shells out, so
  `[uefi_fd]` carries `base` and `size` only, exactly like every device config
  that builds today.  The checker warns if a `blocks` line sneaks in.
* `append_dtb = true` makes packing read `Resources/DTBs/clover.dtb`.  That file
  is the tablet's own downstream device tree, cut out of the boot image this
  unit dumped (`scripts/split-clover-dtbs.py` finds the 111-record table that
  follows the gzip stream; `scripts/scan-clover-dtbs.sh` names each record).
  Record `037` is the one the stock bootloader selects: `model` "SDM 660 PM660 +
  PM660L QRD", `qcom,msm-id = <0x13d>` (317), `qcom,board-id = <0x1000b>`, and
  it is the only sdm660 blob carrying this panel,
  `qcom,mdss_dsi_nt51021_boe_wuxga_video`.  Both `.dtb` and the `dtc`-generated
  `.dts` ship here, the same pair upstream keeps for all 163 other devices.

## Build host

macOS cannot build this (CLANGPDB cross-compiles to AArch64 PE/COFF with Linux
system headers), so the compile runs in a Linux guest and everything else stays
on this machine.  The route that works from this network, end to end:

```sh
bash    scripts/fetch-mu-silicium.sh ~/mu-clover      # pinned-SHA fetch, no --recursive
bash    scripts/build-clover-uefi.sh                  # colima guest, then build
```

`fetch-mu-silicium.sh` exists because `git clone --recursive` does not survive
here: direct GitHub transport stalls at 0-22 KB/s, while
`https://gh-proxy.com/https://github.com/…` answers `fetch` by arbitrary SHA at
~450 KB/s.  The script therefore takes every commit from the parent tree's own
`git submodule status` -- never a branch name -- and asserts each checkout with
`git rev-parse HEAD`.  It stops at `Mu-Silicium@42fe5637` and its submodules,
plus one level deeper: **mu_basecore vendors nine more repositories** (libfdt,
mipisyst, two brotli copies, oniguruma, libspdm, cmocka, googletest, subhook)
that a tarball fetch silently drops.  edk2 validates every `[Includes]` line of
each `.dec` it parses, so a missing submodule aborts with
`File/directory not found in workspace MdePkg.dec(33)` before a single file
compiles.  `Binaries` (Device-Binaries) is skipped on purpose, see below.

`build-clover-uefi.sh` provisions an Ubuntu 24.04 arm64 guest under colima's
`clover` profile (lima + docker binaries installed by hand, because Homebrew is
unusable while the Xcode license prompt is unanswered), installs upstream's own
dependency set (`setup_env.sh -p apt` plus `pip-requirements.txt`) against USTC
and Tencent mirrors, re-applies this overlay, rsyncs the tree into the guest,
runs `stuart_update` *after* the sync (it installs extdeps inside the tree), and
finishes with `build_uefi.py -d clover`.  It is idempotent; `OVERLAY`,
`CHECKOUT`, `VM_CPUS` and friends are environment overrides at the top.

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

## Trying it on the tablet

The test that means something is a **cold boot from the flashed partition**, because
that is the path where the stock loader draws the Mi splash first; anything taking
the panel over afterwards is unmissable.

```sh
adb -s 81ffcaaa reboot bootloader   # -s matters the moment an emulator is attached too
fastboot devices                   # must list 81ffcaaa
fastboot flash boot ~/clover-out/Mu-clover-v0.img
fastboot reboot
```

`fastboot boot <img>` is still worth running first as a zero-write smoke test, but on
this tablet its result is not readable: that path never draws the splash, so the
screen ends up backlight-on-and-black whether the firmware runs or not, and the device
returns to fastboot when the payload exits.

A hang recovers with Power+Volume-Down held for 10-20 seconds.  To put the tablet back
the way it came -- `boot` is `mmcblk0p12` and its stock contents are dumped in the board
repository at `facts/<serial>-<stamp>/img/unixnu-boot.img`, exactly the partition's
67108864 bytes:

```sh
fastboot flash boot ~/UniXNU-clover/facts/81ffcaaa-20261022-210928/img/unixnu-boot.img
```

## Status

| | |
| --- | --- |
| Package skeleton | done, every line traced to a real upstream file, to clover's own device tree, or to this unit's firmware |
| Memory map | 47 rows transcribed row-for-row from the device's `uefiplat.cfg` (14 `[MemoryMap]` + 33 `[RegisterMap]`), no undocumented collisions |
| Configuration map | 27 `[ConfigParameters]` keys, same file; `NumCpus = 4`/`NumActiveCores = 8` cross-checked against `/proc/cpuinfo` |
| Display | `USE_CUSTOM_DISPLAY_DRIVER = 1`: this unit's own `DisplayDxe` blob brings up MDSS, the nt51021 panel and the pm660l backlight, the route lavender uses on the same silicon. `= 0` (`SimpleFbDxe` over the splash handed over at `0x9D400000`, base taken from the memory map by name, stride assumed == width) was the starting point and is still one line away |
| Storage | eMMC through `SdccDxe`; UFS dropped (the driver is in the volume, the board is not UFS) |
| USB | DWC3 device stack only; no XHCI anywhere in this unit's firmware |
| Prebuilt blobs | extracted into `Binaries/clover` from the tablet's own xbl; gitignored, re-create with the extractor |
| Board-id / DRAM / userdata / GIC | dumped and applied — `scripts/dump-clover-facts.sh` in the board repo, results under `facts/` |
| Second DRAM bank | not described; `0x100000000 + 0x7E4C0000` needs a map row and a second `/chosen` window before XNU sees past 4 GiB |
| Boot image packing | header version 0, page 0x1000, kernel 0x8000 / ramdisk 0x1000000 / tags 0x100 — read off this unit's own `boot` and `recovery` headers, which agree, and pinned by the checker |
| Board DTB | `Resources/DTBs/clover.{dtb,dts}` cut from this unit's boot image, record `037` of 111; the checker is at 0 errors / 0 warnings |
| Real build | done: `build_uefi.py -d clover` on the colima guest compiles BootShim, resolves `Conf`, builds every module, and writes `FVMAIN_COMPACT` at exactly `0x300000` (29% full with `DisplayDxe`, 27% without), `SILICIUM_UEFI.fd` and `Mu-clover.img` — no warnings |
| Packing | `build_uefi.py` forwards a `[boot_image]` key only when it is truthy, so `base` cannot be set to 0 and mkbootimg's `0x10000000` default stands, and it never passes `--pagesize` at all. The packed `Mu-clover.img` therefore declares 0x10008000 / 0x11000000 / 0x10000100 with 2048-byte pages, where this unit's own boot header says 0x8000 / 0x1000000 / 0x100 with 4096 (`scripts/decode-boot-header.py` prints both side by side). Every Mu device shares that default, but all of them are header v1 or newer, and clover is v0 -- the one generation whose ABL may compute section offsets from its own page size instead of the header's. So `scripts/pack-clover-bootimg.py` re-packs the same payload against the tablet's own header page: page 4096, base 0, stock cmdline / board name / os_version, with only `kernel_size`, `ramdisk_size` and the image id changed. Its output `Mu-clover-v0.img` is the image to put on the device from here on, and `build-clover-uefi.sh` runs it as the last step. The UniXNU path is unaffected (it packs from `board.toml`'s `[bootimg.image]`, base 0, page 4096) |
| How to read an on-device test | `fastboot boot <img>` and a cold `flash boot` + reboot are **not comparable**. On this tablet the `fastboot boot` path never draws the ABL splash, so it ends at "backlight on, black" whether or not our code runs, and drops back to fastboot when the payload exits -- black after `fastboot boot` carries no information. Judge images by flash + cold reboot, where the Mi logo is drawn first and anything taking over is unmistakable. (`fastboot boot` is still the zero-write smoke test.) Note too that `system_profiler SPUSBDataType` returns nothing from the build host's shell here, so "no USB node" is not evidence of anything; use `ioreg -p IOUSB` |
| On-device rounds | (1) generic geometry, cold boot -> Mi logo frozen; (2) stock-geometry repack, `fastboot boot` -> black (uninformative); (3) the same image with `DisplayDxe`, `fastboot boot` -> black (uninformative); (4) the same image, cold boot -> **Mi logo frozen, exactly like round 1**. Two different display routes behaving identically means the framebuffer is not the variable: nothing ever draws. ABL was intact after every round (`fastboot getvar` answered `product: clover`, `unlocked: yes`) |
| Payload compression | the leading suspect, now removed. `kernel_compression = "gzip"` does not produce a self-decompressing image: `create_android_boot_img` swaps BootShim + FD for a **bare gzip stream**, so the first thing the loader enters is `1f 8b`, and BootShim never decompresses anything (it copies `FD_SIZE` bytes to `FD_BASE` and branches). Only an ABL that gunzips boot images can run that, and this unit's own kernels are arm64 Image.gz-with-stub -- they start with executable code and unpack themselves, so its 2018 header-v0 loader never needed gunzip. `= none` puts BootShim's head at the kernel entry (3 486 671-byte kernel, 3 497 984-byte image, against a 64 MiB partition and a 512 MiB download buffer) |
| Next suspect, if `= none` still freezes the logo | BootShim's deliberately abused arm64 header: `text_offset = FD_BASE = 0x9fc00000` and `image_size = 0x300000`, both far outside what the arm64 boot protocol allows (text_offset must be small and page-aligned), so a strict loader either rejects the image or loads it to the wrong place. Fixing that means the overlay owning `BootShim.S`, which is an upstream file today. The other candidate is the FD landing at `0x9FC00000` colliding with whatever the running loader still occupies there |

Flashing this does **not** touch `xbl`.  `clover.toml` declares `[boot_image]`,
the same output type lavender and the rest of the Xiaomi entries use: the
firm volume, fronted by `BootShim`, is packed as the *kernel* of an android boot
image, and stock ABL loads and jumps to it exactly as it would a Linux kernel.
So the partition is `boot` (mmcblk0p12, 67108864 bytes), which this repository's
board-side twin already holds a byte-complete dump of, and the bootloader on
this unit is unlocked (`androidboot.verifiedbootstate=orange`), so
`fastboot flash boot` is reversible in one command — and `fastboot boot
Mu-clover.img` tests it without writing anything at all.  `p-xbl.bin` is in the
dump as well, full partition size, which is the fall-back if that assumption is
ever wrong.  Nothing has been flashed.

## License

BSD-2-Clause-Patent, the same as Mu-Silicium, UniXNU and UniXNU-sheng.
