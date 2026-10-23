# uefi-clover

Mu-Silicium device package for the **Xiaomi Mi Pad 4 8" LTE** (`clover`,
`xiaomi,clover-lte`, Qualcomm **SDM660**). Together with the sibling board
repository `UniXNU-clover`, which builds XNU and the boot image, it is the UEFI
half of a UniXNU port.

It is an **overlay, not a fork**: files that land inside a plain
`Project-Silicium/Mu-Silicium` checkout.

```
Platforms/Xiaomi/cloverPkg/clover.dsc            the platform
Platforms/Xiaomi/cloverPkg/clover.fdf            the firmware volume layout
Platforms/Xiaomi/cloverPkg/clover.dec            placeholder, upstream ships these empty
Platforms/Xiaomi/cloverPkg/DeviceBuild.py        the stuart builder build_uefi.py expects
Platforms/Xiaomi/cloverPkg/Include/APRIORI.inc   DXE apriori order for clover
Platforms/Xiaomi/cloverPkg/Include/DXE.inc       the module list
Platforms/Xiaomi/cloverPkg/Include/RAW.inc       SecParti.cfg and friends
Platforms/Xiaomi/cloverPkg/Drivers/CloverGopDxe  a GraphicsOutput over the splash window
Platforms/Xiaomi/cloverPkg/Library/MemoryMapLib          clover's own DDR map
Platforms/Xiaomi/cloverPkg/Library/ConfigurationMapLib   the SDM660 register table
Resources/Configs/clover.toml                    firmware volume geometry, boot image packing
Resources/DTBs/clover.{dtb,dts}                  this unit's own board tree, cut from its boot image
BootShim/BootShim.S                              upstream's shim with an Image Size fix
proprietary-files.txt                            what must be extracted from the tablet
scripts/apply-clover-overlay.py                  copy this overlay into a checkout
scripts/check-clover-uefi.py                     verify the result, and the two repos agree
scripts/extract-clover-blobs.py                  build Binaries/clover from the unit's own xbl
scripts/fetch-mu-silicium.sh                     pinned-SHA checkout, through the mirror
scripts/build-clover-uefi.sh                     colima guest, then the EDK II build
scripts/seed-clover-extdeps.py                   fill the stuart extdep cache
scripts/fv-order.py                              FVMAIN file indexes, for the standalone path
scripts/decode-boot-header.py                    print a boot image header, both geometries
scripts/split-clover-dtbs.py                     cut the DTB table out of a stock boot image
scripts/scan-clover-dtbs.sh                      name each DTB record
```

The vendor blob set lives under `Binaries/clover`, is gitignored, and comes from
this unit's own firmware rather than from Device-Binaries (which has no clover
directory). `proprietary-files.txt` is its reviewable contract.

## The tablet, as far as the firmware cares

| | |
| --- | --- |
| SoC | Qualcomm SDM660 |
| Silicon package | `Silicon/Qualcomm/StarlordPkg` |
| Board id | `qcom,msm-id = <317 0>`, `qcom,board-id = <0x0001000b 0>` — platform 11 (MTP) with subtype 1, read off the merged dtb on the device |
| Cores | 8 CPUs at `reg` 0x0-0x3 (part `0x801`) and 0x100-0x103 (part `0x800`), `enable-method = "psci"` |
| GIC | distributor `0x17A00000` + `0x10000`, redistributor `0x17B00000` + `0x100000`, stride `0x20000` |
| Timebase | 19.2 MHz |
| DRAM | `0x80000000` + `0x80000000`; the second bank at `0x100000000` + `0x7E4C0000` is not described yet |
| Panel | 1200×1920, 32 bpp, splash handed over at `0x9D400000` + `0x2400000` |
| Storage | eMMC (`sdhc_1` at `0x0c0c4000`) — no UFS |
| Console | `blsp1_uart2` at `0x0C170000`, 115200 |
| Firmware volume | `0x9FC00000` + `0x300000` |
| Boot image | header v0, page 4096, base 0, kernel `0x8000`, ramdisk `0x1000000`, tags `0x100` |

The splash window is a device measurement, not a device-tree reading:
`sdm660-common.dtsi` and `clover-overlay.dtsi` disagree about it, while
`uefiplat.cfg` in *this unit's* xbl reserves `0x9D400000` + `0x2400000` as
"Display Reserved" and stock xbl has already drawn into it before any UEFI code
runs. `MemoryMapLib.c`, `clover.toml` and the ADT all use that address.

There is no ramdisk filesystem driver in this volume. `Fat` and `PartitionDxe`
are dispatched, but the only `BlockIo` they can see comes from `SdccDxe`, so the
UniXNU payload cannot ride in the boot image's ramdisk: it is a FAT volume on an
eMMC partition (`cache`, `mmcblk0p49`) and the boot image carries no ramdisk.
`ramoops`/pstore wants `0x9FE00000`, which is inside the firmware volume, so a
panic goes to the UART.

`uefiplat.cfg`'s `[MemoryMap]` and `[RegisterMap]` are transcribed row for row
into `MemoryMapLib`, and 27 `[ConfigParameters]` keys into `ConfigurationMapLib`.
The map stops at `0xA0000000`.

The boot image is v0: `boot` and `recovery` on this unit both have 0 in the
header version slot, `page_size` 0x1000, and base-relative load offsets with the
`0x80000000` left for the ABL to add. Their kernel section is `Image.gz` with the
device trees appended after the gzip stream, selected by `qcom,msm-id` /
`qcom,board-id`. The DTB this overlay ships is record `037` of that 111-record
table — the only sdm660 blob carrying `qcom,mdss_dsi_nt51021_boe_wuxga_video`.

## Display

`clover.toml` sets `USE_CUSTOM_DISPLAY_DRIVER = 1`, which compiles out
`SimpleFbDxe` and brings in the unit's own `DisplayDxe` blob. That blob contains
the GOP GUID but never publishes a usable interface in this build, and
`GraphicsConsoleDxe` consequently has an unsatisfiable depex — the only console
left is `SimpleTextInOutSerial`. `Drivers/CloverGopDxe` closes that gap with a
single-mode GOP at `0x9D400000` (1200×1920, `PixelBlueGreenRedReserved8BitPerColor`)
implemented over the window ABL is already scanning out. It sits in `APRIORI.inc`
immediately before `GraphicsConsoleDxe`, and APRIORI entries are started without
a depex evaluation, so it does not depend on the vendor blob.

## What UniXNU adds to a stock device package

gta4l's README says to hand-edit the DSC and `Include/DXE.inc` after each
checkout update. clover carries the same three modules behind a define instead:

```
!ifdef $(UNIXNU_BUILD)
  INF UniXNUPkg/Application/UniXNU/UniXNU.inf
  INF UniXNUPkg/Driver/UniXNUDxe/UniXNUDxe.inf
  INF DarwinBootPkg/Driver/DarwinBoot.inf
!endif
```

`UniXNU-clover/board.toml` sets `UNIXNU_BUILD = "1"` in `[firmware.defines]`,
and `firmware.py` turns that table into `-D` arguments. One checkout with this
overlay therefore builds two things from one DSC: plain Android firmware with
`build_uefi.py -d clover`, and the UniXNU volume with `./unixnu build firmware`.
The two package roots come from the board repository (`{tree}/package` and
`{tree}/drivers/DarwinBoot`) through `[firmware] packages`.

## Build

macOS cannot build this (CLANGPDB cross-compiles AArch64 PE/COFF against Linux
headers), so the compile runs in a Linux guest under colima.

```sh
bash scripts/fetch-mu-silicium.sh ~/mu-clover   # pinned-SHA fetch, no --recursive
python3 scripts/apply-clover-overlay.py --uefi ~/mu-clover
bash scripts/build-clover-uefi.sh               # guest provision, overlay, build
```

`fetch-mu-silicium.sh` takes every commit from the parent tree's `git submodule
status` — never a branch name — and asserts each checkout with `git rev-parse
HEAD`, because direct GitHub transport stalls on this network while
`gh-proxy.com` answers by SHA. It goes one level below the direct submodules,
since mu_basecore vendors nine more repositories.

`build-clover-uefi.sh` provisions an Ubuntu 24.04 arm64 guest under colima's
`clover` profile, installs upstream's dependency set, re-applies this overlay,
rsyncs the tree into the guest, seeds the extdep cache, runs `stuart_update`,
and finishes with `build_uefi.py -d clover`. `seed-clover-extdeps.py` fills
`STUART_EXTDEP_CACHE_PATH` by fetching each GitHub `ext_dep` through the mirror
and checking the sha256 the descriptor advertises — without it a network failure
surfaces as "External Dependencies in the environment are out of date".

The supported path is the board repository's driver:

```sh
cd ~/UniXNU
./unixnu build firmware --uefi ~/mu-clover --edk2 ~/mu-clover/Mu_Basecore --target RELEASE
./unixnu bootimg --ramdisk none -o ~/clover-out/clover-boot.img
```

`scripts/unixnu/firmware.py` reads `board.toml`, opens
`Resources/Configs/clover.toml` for the `[uefi_fd]` geometry, passes every
`[firmware.defines]` key as `-D`, and calls EDK II's `build` with
`-p Platforms/Xiaomi/cloverPkg/clover.dsc`. `bootimg` compiles
`BootShim/BootShim.S` from the checkout, prepends it to the volume, gzips the
pair and appends the board DTB — the shape the stock ABL expects. It checks the
shim's Image Size against the bytes it puts in the kernel field, which is why
this overlay's `BootShim.S` writes `FD_SIZE + shim` instead of `FD_SIZE`.

`[boot_image]` in `clover.toml` covers the standalone path. `build_uefi.py` only
forwards a `[boot_image]` key when it is truthy, so `base` cannot be set to 0 and
mkbootimg's defaults (2048-byte pages, `0x10000000` base) stand there; every Mu
device shares that default, and all of them are header v1 or newer. clover is v0,
so the image that goes on the tablet is the one `./unixnu bootimg` packs: page
4096, base 0, stock offsets.

## Checking

```sh
python3 scripts/check-clover-uefi.py                      # offline
python3 scripts/check-clover-uefi.py --checkout ~/mu-clover
```

Five groups. `fv` expands `clover.fdf` the way EDK II's preprocessor would and
cross-checks every `INF` and `SECTION RAW` against `proprietary-files.txt` in
both directions. `blobs` looks at a real checkout. `map` parses `MemoryMapLib.c`
and fails on any overlap that is not the documented IMEM nesting. `board` pins
the geometry across the two repositories: the `[uefi_fd]` size, the `UEFI FD`
row, the ADT's `uefi_fd`, the splash window against the `Display Reserved` row,
every ADT reserved region against the memory map, `header_version`, whether
`board.toml` still carries `UNIXNU_BUILD`, and that every `INF` in
`APRIORI.inc`/`DXE.inc` is also declared in `clover.dsc`. `inf` resolves every
`[Protocols]` GUID this overlay's INFs name against the `.dec` files the same
INF lists in `[Packages]`.

It runs on the stock macOS Python 3.9 (`tomllib`, `tomli`, or a built-in subset
reader).

## On the tablet

The meaningful test is a cold boot from the flashed partition, because that is
the path where the stock loader draws the Mi splash first — anything taking the
panel over afterwards is unmissable. `fastboot boot` never draws the splash on
this tablet, so its black screen carries no information.

```sh
adb -s 81ffcaaa reboot bootloader
fastboot devices
fastboot flash boot  ~/clover-out/clover-boot.img
fastboot flash cache ~/UniXNU/out/clover/payload/payload.img
fastboot reboot
```

The payload on `cache` is what the UniXNU menu reads. `boot` is `mmcblk0p12`;
the stock contents are dumped byte-complete in the board repository at
`facts/81ffcaaa-20261022-210928/img/unixnu-boot.img`, and the bootloader is
unlocked, so restoring is one command:

```sh
fastboot flash boot ~/UniXNU-clover/facts/81ffcaaa-20261022-210928/img/unixnu-boot.img
```

A hang recovers with Power+Volume-Down held for 10-20 seconds.

## Porting status

Against the guide's bring-up order (`unixnu.com/porting/bring-up`):

| Stage | State |
| --- | --- |
| UEFI reaches BDS with the services the port needs | GOP published by `CloverGopDxe`; simple text in/out, serial, `BlockIo`/`SimpleFileSystem` from `SdccDxe`, FV2 and the variable stack from APRIORI. A boot that reaches the menu on the panel is the open confirmation |
| UniXNU menu reads the payload volume | payload written to `cache`; menu over serial works, the graphics menu awaits the GOP test |
| Payload handoff to DarwinBoot | not started on this unit |
| DarwinBoot to XNU entry | not started |
| Storage and root device | not started |
| Userland | not started |

Firmware below `v0.3.0` carried a debug instrument — a checkpoint bar ladder, an
exception reporter and a timer-sampled PC meter — used to find where the DXE
dispatch stopped on this board. That work is preserved at tag `v0.2.42` and its
findings are in the board repository's notes; it is not part of this build.

## License

BSD-2-Clause-Patent, the same as Mu-Silicium, UniXNU and UniXNU-sheng.
