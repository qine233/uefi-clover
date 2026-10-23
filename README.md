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

The rsync with `--delete` wipes those in-tree extdeps every run, and two of them
(`Mu-Basetools`, `onecrypto-bin`) are GitHub release assets, so a build used to die
where the network does: `github.com` resets the TLS handshake here, `stuart_update`
answers "unable to successfully update 2 dependencies", and the compile refuses to
start with "External Dependencies in the environment are out of date".  That is not a
build error and it was read as one.  `scripts/seed-clover-extdeps.py` now fills the
cache edk2toolext already supports -- `STUART_EXTDEP_CACHE_PATH`, entries keyed by
`sha1(version || source)`, which is why the bytes may come from the mirror while the
path stays the GitHub one -- by fetching every github web ext_dep through
`gh-proxy.com`, checking the sha256 the descriptor itself advertises, and unpacking it
in the guest exactly as `WebDependency.fetch()` would.  The build script sets the
variable, seeds first, and runs `stuart_update` under `pipefail` (piped through `tail`,
the ssh session used to exit 0 on a failed update, so the retry loop never retried).
A warm cache makes the whole step a local copy; `--list` says what is missing.

The cache path has to be resolved *inside* the guest, and the first version of this
wrote `EXTDEP_CACHE=${EXTDEP_CACHE:-~/.mu_extdeps}` in a double-quoted string, so the
host shell expanded the tilde and stuart was pointed at `/Users/zhouzhou/.mu_extdeps`
-- a path the VM has never had, and a cache miss that looked like the mirror being
broken.  The script now asks the guest for `$HOME`.  Proof that the cache is what does
the work: delete both in-tree extdep directories, run the update with `HTTP(S)_PROXY`
aimed at a closed port, and it completes in a second with both payloads reinstalled.

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

Five groups.  `fv` expands `clover.fdf` the way EDK II's preprocessor would —
`!include` along the package roots, `!if`/`!ifdef` against `clover.dsc` merged
with board.toml's defines — and cross-checks every `INF` and `SECTION RAW`
against `proprietary-files.txt`, in both directions.  `blobs` looks at a real
checkout.  `map` parses `MemoryMapLib.c` and fails on any overlap that is not
the documented IMEM nesting.  `board` pins the geometry across the two
repositories: `[uefi_fd]` in clover.toml, the `UEFI FD` row, the ADT's
`uefi_fd`, the splash window in `[[bootimg.dtb_node]]` versus `Display Reserved`,
every ADT reserved region against the memory map (contained, or an announced
collision on the device's own carve-outs), `header_version` in both configs, and
whether board.toml still carries `UNIXNU_BUILD`.  `inf`, with `--checkout`,
resolves every `[Protocols]` GUID this overlay's own INFs name against the `.dec`
files that same INF lists in `[Packages]` — EDK II answers a mismatch with build
error 4000, which costs a compile round, and the `.dec` files are already on disk.

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
| On-device rounds | (1) generic geometry, cold boot -> Mi logo frozen; (2) stock-geometry repack, `fastboot boot` -> black (uninformative); (3) the same image with `DisplayDxe`, `fastboot boot` -> black (uninformative); (4) the same image, cold boot -> **Mi logo frozen, exactly like round 1**; (5) the same geometry and driver with `kernel_compression = "none"`, cold boot -> **Mi logo frozen again**; (6) only bytes 8..63 changed (`requires_kernel_header = false`), cold boot -> Mi logo flashed, back in fastboot; (7) splash paint, still `"none"` -> no colour; (8) `b .` at `_Start`, still `"none"` -> Mi logo flashed, back in fastboot; **(9) `kernel_compression = "gzip"` restored + the same paint, cold boot -> the screen turned solid blue and the tablet never came back on USB** (no fastboot, no adb, minutes after the reboot). Round 9 is the first result that means something on its own: ABL gunzipped the kernel section, jumped into BootShim, and our store to `0x9D400000` reached the panel. It also retroactively disowns rounds 5-8: all four were `= none`, i.e. executable code fed to a loader that expects a gzip stream, so "header off changes the behaviour" (round 6) and "the paint shows nothing" (round 7) were readings of the encoding, not of the firmware or the header. USB was never a differential: the erase-`boot` control produced the same absent/fastboot/absent/fastboot timeline as the boots that ran; (10) the same image plus the four-bar ladder, cold boot -> the user read **a green band and a magenta band, no white** ("有绿带 / 这个紫色带是品红吗"), so round 9's blue stayed and the ladder worked first try. The reading is the user's eye on the panel -- this host has no output channel at UEFI stage; (11) the thirteen-bar ladder, cold boot -> **green, magenta, three evenly spaced cyan bands, no white** ("绿 品红 无 青色三条，间隔均匀"). Three cyan in consecutive slots is the shape the arch protocols make (CpuDxe, WatchdogTimer, TimerDxe are dispatched within one APRIORI step of each other), and no BDS/BlockIo/RTC band means the dispatch never got near the storage or variable drivers. Round 11's offsets were already the round-12 ones, so the bands did not move; (12) the twenty-one-bar ladder with eight red bands on the Qualcomm chain, cold boot -> **three cyan, five red, no white** ("青色三条 红色五条 白色没有"). The aggregate is the problem: which three and which five is not recoverable from a count, and the two shapes that fit say opposite things. Consecutive-from-the-top would mean the DXE core enumerated its firmware volumes, the arch protocols came up, SMEM appeared and the {AE37B942} fan-in was satisfied -- so ten vendor blobs became schedulable and the wall is inside one of them. The other shape, a lit set with holes, is what the dispatch order actually implies: `BdsDxe`, `VariableRuntimeDxe`, `DevicePathDxe` and `EmbeddedMonotonicCounter` are all `Depex TRUE` (verified in the Mu_Basecore INFs, not assumed), so they cannot be starved, and a dark BDS band with eight bands lit elsewhere means the dispatch loop *stopped* rather than ran out of schedulable drivers; (13) the positional ladder, cold boot -> the user sent a **photograph** of the panel instead of a count, which is worth several rounds of counting and reads band by band: `FV enumeration` **dark**, then `Cpu` / `Runtime` / `Security` / `watchdog` cyan, then `variable write`, `variable read`, `monotonic counter` and `RTC` **dark**, then `metronome` cyan, the {AE37B942} fan-in red, the GIC cyan, the timer cyan, `ChipInfo` red, `SMEM` red -- and every band from SMEM downward dark: Clock, BlockIo, DiskIo, partitions, FAT, collation, the display, PMIC, BDS. Three consequences. **(a) A dark band above a lit one is a real hole, not a paint that failed**: `VariableRuntimeDxe` (FV file 13) and `EmbeddedMonotonicCounter` (14) are `Depex TRUE` and the volume lists them ahead of `MetronomeDxe` (18), whose band lit, so they dispatched and *returned without installing their protocol* -- and an entry point that fails finishes the driver for the dispatcher, so its band stays dark forever. *(Withdrawn with round 15's finding: FV order is not dispatch order, and these three sit below the hang in `APRIORI.inc`, which the queue ignores depex for. Consequence (b) survives, and (c) is what the meter went on to confirm.)* **(b) The dark `FV enumeration` band is an artifact of the instrument, not of the firmware, and finding it cost the theory built on it**: `MdeModulePkg/Core/Dxe/Hand/Notify.c:99-159`, read at last, shows `CoreRegisterProtocolNotify` appends a notify record and returns -- it does *not* signal for handles that already exist, and only `LocateHandle (ByRegisterNotify)`, which starts at the head of the protocol's handle list, sees those. So a protocol installed before `CheckpointDxe` was dispatched paints dark whatever else is true, and FirmwareVolume2 is exactly that case: `CoreInitializeDispatcher` (`Dispatcher.c:1465`) hangs the whole FV scan off the FV2 notification, so the fact that twenty-odd drivers dispatched proves FV2 exists and was published before this driver ran. Every other round-13 band belongs to a driver dispatched after `CheckpointDxe` -- it is third in APRIORI and APRIORI entries are queued ahead of the volume scan -- so the rest of the reading stands, but the FV2 hole and the variable-store story built on it are withdrawn, and round 14 drains existing instances at entry so the ladder stops lying about early protocols. **(c) The wall itself**, from the FV file order measured off `FVMAIN.Fv.txt` joined to `FV/Guid.xref` (the numbering on that page, not remembered): the last module to reach an instrumented protocol is `SmemDxe` at file 30, and the first producer band dark below it is `ClockDxe` at 38, with `BdsDxe` (64, `Depex TRUE`) never appearing. So the hang is in 31..38: `ULogDxe` 31, `NpaDxe` 32, `DALSys` 37 -- `DiskIo` 33, `PartitionDxe` 34, `Fat` 35 and `EnglishDxe` 36 are in that range too but are bind-only, so their dark bands say nothing. `ClockDxe` is the one that matters downstream: DisplayDxe (45) and SdccDxe (43) both wait on its GUID, so the panel and the eMMC are still queued behind the hang; **(14) v0.2.21, cold `flash boot`, photographed:** green and magenta at the top, then three cyan bands (FV2, FVB, the CPU arch protocol -- the drain working, which round 13 could not show), then **three dark**, then red fan-in, cyan GIC, cyan timer, red ChipInfo, red SMEM, and everything from `ClockDxe` down dark, the seven index bands black. `scripts/read-clover-photo.py` read it, and needed two fixes first: a hand-held frame slants the bands by tens of rows edge to edge, so rows must be sampled from a narrow vertical strip, and colour agreement alone cannot pick the geometric fit (most of the ladder wants cyan), so the distance from a slot centre now comes off the score. The reading is round 13's shape with the volume bands acquitted, plus the hole at 13/14/17 and a meter that reported nothing; **(15) v0.2.22, cold `flash boot`, photographed: the meter named the module.** The last image the DXE core loaded is **FVMAIN file 38, `ClockDxe`**, and its own band is dark, so the loop stopped inside that driver's entry point -- `ULogDxe` 31, `NpaDxe` 32 and `DALSys` 37 are cleared, because 38 is only reached after they were loaded and started. The three marks report the reading is live rather than lucky: white lit (the driver found its own file in the volume list), cyan lit (images matched against it), red dark (nothing was loaded that is not in it). The hole round 14 found outlived the reading: `VariableRuntimeDxe` (13), `EmbeddedMonotonicCounter` (14) and `RealTimeClock` (17) were dark *because they are queued below the hang* -- apriori line 59, 60 and 62, past ClockDxe at 47 -- and the only reason they looked like a hole was that this ladder ordered its rows by dependency logic instead of by the queue that runs. The frame came back landscape, so the reader turns the picture itself now, and it lines the ladder up on the black bands as well as the coloured ones -- the entry-point black pass makes a dark slot a marked position rather than an absence, which is what pins the geometry to within a row at the bottom of the ladder, where a model-only fit was four to six rows off; **(16) v0.2.24, built and waiting for the tablet**: `ClockDxe` removed from `APRIORI.inc` *and* `Include/DXE.inc` so no depex round can resurrect it, the slot table re-ordered to `APRIORI.inc` line order, and the file numbers stripped out of the band labels because volume order and dispatch order are different axes and dropping a file shifts the first. The image is 1,220,608 bytes (24,576 smaller), sha256 `663d372fbb99d131…`, FVMAIN at 80 files with `HWIODxeDriver` now 38, `SdccDxe` 42, `DisplayDxe` 44 and `BdsDxe` 63. Two readings are being asked for: the free one first -- reboot on the saved round-15 image, wait ten minutes, photograph it again, which is the only way to tell a spin with no exit from a long timeout -- then this build |
| Payload compression | **settled by round 9, and the opposite of what v0.2.10 claimed.** This unit's own `boot` and `recovery` kernels both begin `1f 8b` at the section start (`kernel/section-prefixes.txt`), so its header-v0 ABL does gunzip boot images, and `kernel_compression = "gzip"` -- a bare gzip stream of BootShim + FD + DTB -- is the encoding it wants. v0.2.10 flipped it to `"none"` on the sentence "this unit's own kernels are arm64 Image.gz-with-stub, so its loader never needed gunzip", which is false and was contradicted two blocks above itself in the same toml. Rounds 5, 6, 7 and 8 were all `"none"`: raw executable code handed to a decompressor, which is why they froze or bailed, and why none of those four rounds says anything about the header, the framebuffer or the FD address |
| Kernel header | `requires_kernel_header` is on, and the checker makes turning it off an error -- but that guard rests on round 6, which is now known to be a `"none"` build, so the measurement does not isolate the header. What is actually established: gzip + header on enters BootShim (round 9). Untested: gzip + header off. BootShim writes `text_offset = FD_BASE = 0x9fc00000` at offset 8 and `FD_SIZE` at 16, neither legal under the arm64 boot protocol, so a loader that parses them is being lied to either way. Expect the guard to be replaced by a measurement before the flag is trusted |
| Liveness probe | `BootShim/BootShim.S` (an upstream file, deliberately replaced -- see `apply-clover-overlay.py`) fills 8 MiB at `0x9D400000` with `0xFF0000FF` before it relocates the FD. **Round 9 read it: the screen went solid blue and the tablet never reappeared on USB.** That also fixes the pixel layout for the rest of the port -- words are read as ARGB8888, blue in the low byte, so green is `0xFF00FF00` and a red would be `0xFFFF0000`. The panel needs no driver to show a store: ABL is already scanning out that window. Remove by deleting the file and its `COPIED` entry |
| Checkpoint ladder | the paint proves the first instruction, nothing after it. `Platforms/Xiaomi/cloverPkg/Include/Checkpoint.h` therefore draws one bar per stage at its own offset inside the 8 MiB the paint filled, so a single boot reports the deepest stage reached: green from `GetMemoryMap` (first caller is `MemoryInitPeiLib`, so PEI), yellow from `GetConfigurationMap` (a bonus rather than a stage -- that library is linked into Sec as well, so its first caller is not necessarily PEI), magenta from `CheckpointDxe`'s entry (the DXE core dispatched a normal driver), white from its `GraphicsOutput` protocol notify (the vendor `DisplayDxe` came up), then nine cyan bands at +0x140000 to +0x340000, one per architecture or core protocol that appears: CPU, watchdog, timer, RTC, variable write, Block I/O, simple file system, BDS, USB I/O. Position is the message, so all nine share a colour, and `RegisterProtocolNotify` does *not* report instances that already exist (`Hand/Notify.c`), so a protocol published before this driver ran paints dark until round 14 drains them with `LocateHandle (ByRegisterNotify)` at entry. Round 11 read exactly three of those cyan and nothing below them, so eight **red** bands follow at +0x380000 to +0x540000 for the vendor side of the same gap (round 12 read three cyan, five red, no white -- and no amount of asking fixes what that means, because a count identifies neither band): the DXE core's firmware-volume enumeration, RuntimeArch, SecurityArch, SMEM, the private GUID ten blobs wait on, ChipInfo, Clock, VariableArch. Round 14 trims it to sixteen protocol slots and adds that drain; round 15 keeps the sixteen and adds ten more bands under them. What ships now is FV2, FVB, CPU, `VariableWriteArch`, the monotonic counter, RTC, then the Qualcomm chain -- the fan-in GUID, the GIC, the ARM timer, ChipInfo, SMEM, Clock -- then `BlockIo` off `SdccDxe`, `PartitionInfo`, `GraphicsOutput` in white and `BdsDxe`, at +0x140000 to +0x500000; below them +0x540000 to +0x6C0000 the seven bits of the last loaded image's FVMAIN file index, MSB topmost; and under those +0x700000, +0x740000, +0x780000 as white, cyan and red marks that report on the meter itself. The six slots round 14 dropped either lit in round 13 or can only ever follow one that did, and the duplicate variable band (the readable interface, which `VariableRuntimeDxe` always installs together with the write interface) became the monotonic counter in round 15 because round 14 proved the two variable bands carry the same fact and the counter watches a different driver. Round 13 made it positional: `CheckpointDxe` paints **all twenty-four protocol slots black at its own entry** and recolours a slot only when the module that owns it appears, so the panel always shows the whole ladder and the first black band below the magenta one is the first module that never dispatched -- no counting, and a hole in the middle is now visible as a hole. Round 13's slot table was in the order the DXE core reaches things rather than the order the volume lists them: firmware-volume enumeration from HOBs (`DxeMain.c` walks the `FIRMWARE_VOLUME_HOB`s before `CoreDispatcher`), then the architecture protocols, then `VariableRuntimeDxe` (write then readable), monotonic counter, RTC, metronome, then the Qualcomm chain -- the fan-in GUID, the GIC, the timer, ChipInfo, SMEM, Clock -- then storage as it actually happens (`BlockIo` off `SdccDxe`, then DiskIo, then partition handles, then FAT, then collation), then `GraphicsOutput` in white, `PmicDxe` and finally `BdsDxe`. That was twenty-seven bands from +0x40000 to +0x700000; it is now twenty-nine, from +0x40000 to +0x7A0000, each 128 KiB on a 256 KiB pitch, still inside the BootShim fill. Two band bindings were chosen from the tree rather than from memory: this Mu_Basecore has no `gEfiPartitionDiscoveryProtocolGuid` at all -- its `PartitionDxe` produces `gEfiPartitionInfoProtocolGuid`, so that is the partition band -- and `gHardwareInterruptProtocolGuid` lives in EmbeddedPkg.dec, so it is a literal in the C file like the four Qualcomm GUIDs, which keeps `CheckpointDxe` a one-package driver. Bars are 128 KiB: round 10's 1 MiB pitch was easy to read but could not fit thirteen stages inside the fill. The checker binds every offset it can find, including the ones stored in `CheckpointDxe`'s table rather than passed to a call, and fails on two bars closer than one bar length, because a merged band loses the reading. `CheckpointDxe` is ours, needs nothing and returns `EFI_SUCCESS`, and is third in `APRIORI DXE`. A screen with no bars at all but a real UEFI image is the best outcome. Round 13 was read from a **photograph** rather than a spoken count, and that is the standard ask from here on: twenty-seven bands cannot be named by a tally, and one picture gave the whole reading in a single boot (the rounds row). `scripts/read-clover-photo.py` turns the jpeg into band positions by resampling the frame and classifying each row, so the reading is reproducible instead of eyeballed: it first turns the picture into whichever of the four orientations puts the ladder running down the frame (round 15's photo came back landscape, with the bars across the long axis), then fits the geometry from the green and magenta anchors and refines it against the bands themselves. The refinement matters: a hand-held frame's pitch grows steadily down the ladder, a constant-pitch model is four to six rows off by the bottom, and at the bottom sit the marks, whose whole job is to tell a band painted black from a place nobody wrote -- so the sampling row has to be on the band. Bands are lined up on the table using the **dark** runs as well as the coloured ones, because the entry-point black pass makes an unlit slot a marked position rather than an absence; where two runs claim one position the coloured band wins and the closer claim beats the further. Colour agreement alone cannot pick the fit, because most of the ladder wants cyan, so how squarely a band lands on a slot comes off the score. Rows are read from a narrow vertical strip, not across the screen: a band is straight on the panel but slanted in a hand-held photo, and round 14's frame slants by tens of rows edge to edge, so a wide sample averages each band with the gap beside it and nothing wins a majority. Every band is then read twice, from its run and from the row the fit predicts, and both are printed, so a fit that had drifted shows up as the two columns disagreeing rather than as a confident wrong name. Remove by deleting `Checkpoint.h`, `Drivers/CheckpointDxe/`, the three `CloverCheckpointBar` calls and the two `INF` lines plus the `[Components]` line |
| Vendor dependency chain | read off the blobs rather than guessed: each `Binaries/clover/**/*.depex` is a small expression (opcode `0x02` pushes a 16-byte GUID, `0x03` AND, `0x06` TRUE, `0x08` end), and the 27 of them name a short list of Qualcomm protocols the platform waits on. `gEfiSMEMProtocolGuid` {F4E5C7D0-…} comes from SmemDxe, whose own depex is TRUE; DALSYSDxe waits on SMEM alone; and **ten** blobs -- ChipInfoDxe, ClockDxe, HWIODxe, I2CDxe, SPIDxe, PlatformInfoDxe, PmicDxeLa, AdcDxe, TsensDxe, TLMMDxe -- all wait on {AE37B942-457F-4C91-A196-D9669FD347A3}, a GUID no header or `.dec` in this tree declares, so it can only come from a blob. `gEfiClockProtocolGuid` {241AFAE6-…} then gates both `DisplayDxe` (twelve depex terms, among them `gEfiChipInfoProtocolGuid` {B0760469-…} and `gQcomPmicVersionProtocolGuid`) and `SdccDxe`, the eMMC host that has to hand UniXNU its `BLOCK_IO`. Nothing in the FV declares a producer for `gEfiFirmwareVolumeBlockProtocolGuid`, so whatever backs the variable store is a blob too. Round 13's dark `FV enumeration` band looked like proof that DxeCore never published FV2 and the variable store had nowhere to live; that was the instrument's blind spot (the registration is never drained for pre-existing interfaces), it was withdrawn in round 14, and the FVB band has lit in every photograph since. What the depexes *cannot* tell is whether a driver gets a turn at all: `APRIORI.inc` lists nearly everything, and the apriori queue starts its entries with no depex evaluation, so a blob whose dependency is unsatisfied is still loaded and started -- which is why round 16 removing the clock producer is a test of what `SdccDxe` and `DisplayDxe` do without it, not a prediction that they stay dark |
| Dispatch order, measured | Two different orders matter, and mixing them up is what produced round 14's false "hole". **Dispatch order is `Include/APRIORI.inc`, row for row**: that list contains nearly every DXE module in this volume, and the apriori pass in `MdeModulePkg/Core/Dxe/Dispatcher/Dispatcher.c` inserts each entry it finds at the tail of `mScheduledQueue` with `Dependent = FALSE` and **no depex evaluation** -- the drain loop then loads and starts in that order. So the queue is a prefix, `Depex TRUE` buys nothing here, and a dark band below the hang means "not started yet", not "starved". **Volume order is a build artifact** and a separate axis: `Build/cloverPkg/RELEASE_CLANGPDB/FV/FVMAIN.Fv.txt` lists offset and file GUID, `FV/Guid.xref` names the GUID, and `scripts/fv-order.py` joins them -- which is what the index meter's number refers to, so never read a number against the apriori list. Round 15's volume held 81 files: 1 `gAprioriGuid`, 2 DxeCore, 3 PcdDxe, 4 ArmCpuDxe, 5 RuntimeDxe, 6 SecurityStubDxe, **7 CheckpointDxe**, 8 TzDxe, 9 WatchdogTimer, 10 CapsuleRuntimeDxe, 11 ReportStatusCodeRouter, 12 StatusCodeHandler, 13 VariableRuntimeDxe, 14 EmbeddedMonotonicCounter, 15 SimpleTextInOutSerial, 16 ResetSystemRuntimeDxe, 17 RealTimeClock, 18 MetronomeDxe, 19 PrintDxe, 20 DevicePathDxe, 21 ConPlatformDxe, 22 ConSplitterDxe, 23 GraphicsConsoleDxe, 24 HiiDatabase, 25 EnvDxe, 26 ArmGicDxe, 27 ArmTimerDxe, 28 ChipInfo, 29 GlinkDxe, 30 SmemDxe, 31 ULogDxe, 32 NpaDxe, 33 DiskIoDxe, 34 PartitionDxe, 35 Fat, 36 EnglishDxe, 37 DALSys, **38 ClockDxe**, 39 HWIODxe, 40 I2C, 41 SPI, 42 SPMI, 43 SdccDxe, 44 DALTLMM, 45 DisplayDxe, 46 DisplayReEnablerDxe, 47 PlatformInfoDxe, 48 ButtonsDxe, 49 PmicDxe, 50 ChargerExDxe, 51 QcomChargerDxeLA, 52 AdcDxe, 53 TsensDxe, 54 LimitsDxe, 55 UsbfnDwc3Dxe, 56 UsbBusDxe, 57 UsbKbDxe, 58 UsbMassStorageDxe, 59 UsbMsdDxe, 60 UsbDeviceDxe, 61 UsbConfigDxe, 62 HashDxe, 63 RngDxe, **64 BdsDxe**, then raw files and the console/SMBIOS/BootManagement tail up to 81. Round 16 takes `ClockDxe` out of the volume, which leaves 80 and shifts everything from 38 up by one -- `HWIODxeDriver` becomes 38, `SdccDxe` 42, `DisplayDxe` 44, `BdsDxe` 63 -- so `scripts/fv-order.py` is re-exported for every build and a round-15 photograph must be decoded against `~/clover-out/fv-order-round15.txt` and `--driver ~/clover-out/round15-CheckpointDxe.c`, both kept aside for the ten-minute re-take. Reading a new photograph with the old mapping, or the old one with the new mapping, silently misnames the module -- which is the one way this instrument can produce a confident lie |
| Next suspects, in order | Round 14 read the ladder as designed: FV2, FVB and the CPU arch protocol lit; the fan-in GUID, `ArmGicDxe`, `ArmTimerDxe`, `ChipInfoDxe` and `SmemDxe` lit; `ClockDxe` (38), `BlockIo`, partitions, `GraphicsOutput` and `BdsDxe` dark. It also turned up a fact nobody had asked for -- three bands in the *middle* stayed dark while bands below them lit, namely `VariableRuntimeDxe` (13), `EmbeddedMonotonicCounter` (14) and `RealTimeClock` (17). Read at the time as a hole -- dispatched, returned, installed nothing -- and **retracted in round 15**: those three drivers sit at `APRIORI.inc` lines 59, 60 and 62, below the hang, and the apriori queue ignores depex, so they were simply never started. The hole was this ladder ordering its rows by depex logic instead of by the queue that actually runs, and the slot table now runs in `APRIORI.inc` line order so the panel reads as a prefix. The load meter, though, reported nothing: all seven index bands were dark, and dark is also what they stay at when the meter matched nothing, so the reading of "no driver ever loaded" was the instrument failing -- SMEM is file 30 and it plainly loaded. Two bugs caused it, and both are pinned in the driver's header comment. (a) `FvGetNextFile` treats `FileType` as IN OUT and stores the type of the file it returned (`MdeModulePkg/Core/Dxe/FwVol/FwVolRead.c:207`), so setting `EFI_FV_FILETYPE_ALL` once before the loop makes the second call and every call after it search for one file type: the list round 14 matched against held one or two GUIDs. (b) The list was every FV2 instance concatenated in handle order, so even a correct walk numbered FVMAIN files from however many files the boot firmware volume reported first -- an offset a photograph cannot see. Round 15 confines the walk to the volume holding `CheckpointDxe`'s own file, whose GUID the image handle reports at entry through `EFI_LOADED_IMAGE_PROTOCOL` and its `MEDIA_FW_VOL_FILEPATH_DEVICE_PATH` node, so the number is a row of `scripts/fv-order.py`; and it puts three bands under the index that report on the meter instead of on the boot -- **white** this drivers own file was found in the list, **cyan** an image was matched against it, **red** an image was loaded that is not in it. With those a dark index means nothing ambiguous any more: white and cyan lit with the bands dark is the dispatch loop dying inside `CoreLoadImage` itself, white dark is the enumeration failing, and cyan lit with a number on the screen is the answer. What the number named, in round 15, was `ClockDxe` (38): the index bands read 32+4+2, the marks said the meter was live -- white came back **photographed as cyan**, rgb `(92,235,254)`, which is what a white bar does under this light, and `read-clover-photo.py` reports it as `LIT(white)` -- and the driver's own band stayed dark, so it was loaded, entered, and never came out. Everything listed below line 47 of `APRIORI.inc` is therefore untested rather than guilty: `ULogDxe`, `NpaDxe`, `DiskIoDxe`, `PartitionDxe`, `Fat`, `EnglishDxe`, `DALSYSDxe` wait, no -- `DALSYSDxe`, `HWIODxe`, `PlatformInfoDxe`, `MetronomeDxe`, `GLinkDxe`, `ULogDxe` and `NpaDxe` are all *above* it and ran. Four blobs name the protocol `ClockDxe` produces ({241AFAE6-885F-4F6C-…}, `gClockProtocolGuid`): `SdccDxe` (the eMMC), `DisplayDxe`, `I2CDxe` and `SPIDxe`, and nothing in this tree declares that GUID, so a stub would mean inventing a vtable layout -- a guess the ladder cannot check, and it is not the move. Two moves remain, and round 16 is the build for both. First the free one: a driver spinning on a channel to an ADSP or RPM that never answers usually has a timeout, and every reading so far has been taken within a minute or two of the reboot, so a second photograph of the *same* screen ten minutes later tells a spin with no exit from one that eventually gives up -- `~/clover-out/round15-Mu-clover-v0.img` is kept aside for exactly that. Then the diagnostic one, now built: `ClockDxe` is out of `APRIORI.inc` **and** out of `Include/DXE.inc`, so the file is not in the volume and no depex round can resurrect it. Read the prediction against the queue, not against the depexes: since apriori entries are started without one, the four clock dependents still get their turn, so the question the panel answers is whether they survive without a clock -- if the ladder lights all the way to `BdsDxe`, this one blob was the wall; if it stops on a dependent, the index meter names which, one down from its round-15 number because the volume lost file 38 and `scripts/fv-order.py` has to be re-exported before a photograph is decoded. Third thread, untouched so far: the 5-byte `dummy` ramdisk against stock's 1.3 MiB gzip stream |

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
