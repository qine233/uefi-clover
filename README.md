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
scripts/read-clover-photo.py                   turn a photograph of the panel into a reading
scripts/fv-order.py                             the FVMAIN file indexes the bit bands name
scripts/scan-clover-spins.py                   a blob's halt sites, grouped by the page a tick names
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

There is no ramdisk filesystem driver in this volume, and that is a fact about the
volume, not about the ramdisk. `Fat` and `PartitionDxe` are dispatched before BDS, but
the only `BlockIo` they can ever see comes from `SdccDxe`; nothing in the volume
interprets a memory buffer as a filesystem. So UniXNU's payload cannot be the boot
image's ramdisk, however small: the volume must be written to an eMMC partition and
mounted from there. On this board that is `cache` (`mmcblk0p49`, 256 MiB), and the
boot image carries no ramdisk at all. The board repository's `[payload]` comment and
its README record the same finding.

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

## Reading the panel from a photograph

The screen is the only output channel, so the ask every round is the same: one photo of
the ladder, held square to the panel if that is easy and however it comes out if it is
not.  `scripts/read-clover-photo.py` finds the reading strip itself, tries all four
orientations and keeps whichever explains the most bands, then reports the slot ladder,
decodes the seven index bits against `scripts/fv-order.py`'s listing, and -- from round 19
-- decodes twelve tick bits against a blob's own disassembly: five for the page and seven
for the 32-byte bucket inside it.  From round 20 those same twelve rows carry a second
reading, chosen by the arrival row's colour: when the sample lands in one of the two
counter-free acknowledgement polls they are bits 27..16 of the register the module is
waiting on, and `--register-map` names the device region that block falls in.  Round 21 adds
a third reading and two flags: when that block is the one round 20's photograph named -- MMCC
at `0x0c8c0000`, a node of this tablet's own device tree -- the twelve rows become bits 15..4
of the register, a 16-byte bucket that `--dt` compares against the power domains hanging off
that controller, and the `+0x300000` band says so.  Round 21's other flag, on `+0x340000`, is
gone: it answered its question (the block drives real data, so nothing is missing on the bus)
and round 22 needs that row for the protocol it was originally a slot for.

```sh
python3 scripts/fv-order.py            > ~/clover-out/fv-order.txt
python3 scripts/clover-register-map.py > ~/clover-out/register-map.txt
python3 scripts/read-clover-photo.py photo.jpg \
  --modules ~/clover-out/fv-order.txt \
  --blob-map ~/clover-out/clockdxe-pages.txt \
  --register-map ~/clover-out/register-map.txt
```

The `fv-order.py` line above is the *shape* of the command, not a working one: that script reads
the built firmware volumes out of `Build/cloverPkg/RELEASE_CLANGPDB/FV`, and that directory only
exists inside the colima guest, so running it on the host prints nothing -- into a redirect,
which then truncates the live listing it was decoding against.  Run it against the guest tree and
pipe it out, and check the line count before believing a photograph's index:

```sh
colima ssh --profile clover -- bash -c 'cd ~/mu-build && python3 - ' \
  < scripts/fv-order.py > ~/clover-out/fv-order.txt
```

Pass `--driver ~/clover-out/roundNN-CheckpointDxe.c` to read an archived frame: which band
carries which bit is read out of the driver the photograph was built from, and every round
keeps a copy of that driver next to its image.  Without it the reader uses the working tree,
which is right for the newest photo and wrong for an old one.

The `--blob-map` file is what `scripts/scan-clover-spins.py` builds from a GNU objdump
listing of the suspect blob (run the disassembly in the colima guest; the host `/usr/bin/objdump`
is LLVM's and rejects `-b`), and it turns "page 11" into the twenty-two `b .` halts sharing
that page, with the source file, line number and the expression each was about to report.
With a round-19 photograph the same table is filtered to the sampled bucket, so a reading
names one site rather than one page.
Two things came out of building it that no photograph can tell us.  Almost every `b .` in
`ClockDxe` has an ASSERT() report call in front of it -- 128 of its 130 sites resolve to a
`__FILE__`, and the scan marks the two that do not -- so the spins the ladder names are
assert halts whose text went to a serial port this tablet has no cable for, and the fix is
the condition, not a timeout.  And the module has exactly five counter-free hardware bit
polls, all on pages 9 and 10, so a tick landing anywhere else is a halt rather than a retry.
A page the table lists no sites for is its own answer, and the reader says so.

The `--register-map` file is `scripts/clover-register-map.py` dumping the `AddDev` regions
out of `MemoryMapLib.c` -- the map this firmware actually builds -- as
`0x<base> 0x<size> <name>` rows.  Twelve bits name a 64 KiB block rather than a register,
and which region that block overlaps is the finding: inside GCC the acknowledgement waits
only on a parent clock, while a block no region covers never reached hardware, which the
reader says in those terms and pairs with the nearest mapped neighbour.  Worth knowing
before reading one: this build maps no CAM_CC, VIDEO_CC, MDSS or Turing window, so an
address in any of those is a gap in the memory map as much as a clock bug.

Round 20's photograph did not need the map to be finer than 64 KiB: its twelve bits decoded to
`0x0c8c0000`, which is `clock-controller@c8c0000` in `Resources/DTBs/clover.dts`, `compatible =
"qcom,mmcc-sdm660"` -- the MMSS multimedia clock controller, with `mdss_mdp`, both DSI
controllers, the DP controller, venus, the camera front end and the MMSS SMMU as its listed
consumers.  The blob contains no literal anywhere near it, which is why the answer came from
the device rather than from the disk, and why `--dt` (that same file, by default) is what makes
round 21's 16-byte bucket useful: it names the eight GDSCs the tree hangs off that controller
(`+0x1024` venus, `+0x1040` venus_core0, `+0x2304` mdss, `+0x34a0` camss_top, `+0x3664` vfe0,
`+0x3674` vfe1, `+0x36d4` cpp, `+0xe020` bimc_smmu) and says whether the polled register falls
in one.  A bucket that is not a power domain is a branch clock's control triple, and the two
readings call for different fixes.

Round 21's photograph was read, and both of its new facts came back the same way: the twelve
rows decoded to `MMCC + 0x2040..0x204f`, and the liveness band was yellow, so the block answers
and only the acknowledgement bit fails to arrive.  `0x2040` is mainline's `mdp_clk_src`
`CMD_REG`/`CFG_REG` pair (`.cmd_rcgr = 0x2040` in `clk-rcg2` terms, `mmcc-sdm660.c`), the source
that feeds the blob's own `mmss_mdss_mdp_clk` record -- found by parsing the clock-record table
out of `ClockDxe.efi` and matching `0xc2040` against the device tree.  Upstream never polls that
bit; it writes `CMD_REG` and moves on, which is why the wait is this blob's own behaviour rather
than a hardware requirement.  Two candidates survived: the RCG's input clock is not running
(a glitch-free latch needs an edge, and the parents `mdp_clk_src` can select -- MMPLL5, MMPLL7,
GPLL0 -- are nothing our boot brings up, while a stock ABL had already drawn a splash from that
same MDSS), or MDSS power is simply off.  Round 22 stops measuring and tries to move: the tick
handler now counts consecutive milliseconds sampled inside either of the two counter-free polls
and, at 200 of them, points `Context->ELR` at that loop's own exit (`0xab1c` after the update
handshake, `0xa78c` after the status wait).  The vector table makes that a supported operation --
`ExceptionSupport.S` stores the saved link register into the frame it hands the handler and
reloads it from the same memory before `eret` -- and the cut only happens while the tested bit
still asks for another iteration, so a wait that was about to finish naturally is left alone and
`ClockDxe.efi` stays byte-identical.  What it does not do is fix the clock: `CMD_REG` bit 0 is
left set.  The reading that pays for that is `+0x340000`, which round 22 hands back to its own
protocol slot -- red there means `ClockDxe` reached the end of its entry point -- together with
the index meter, which can only leave 38 if the driver stopped being the last image loaded.

Round 22 came back with no ladder to read, and the way it came back is the finding: the bands
appeared, then the screen held only a backlight, then the tablet powered off.  A hang cannot do
that -- a hang leaves the picture up, which is what every round before this one did -- so
something past `ClockDxe` cleared or re-pointed the panel, and the ladder had no defence,
because each of its bars is painted once, at the moment its fact becomes true.  Round 23 is the
instrument that survives that: `CloverCheckpointBar` now records the colour it leaves behind,
indexed by the bar's position in the ladder's own 256 KiB pitch, and the tick handler spends one
bar of every millisecond comparing the panel against that record and putting the colour back
where it disagrees.  One bar per tick rather than a sweep, because restoring the whole ladder is
3.75 MiB of writes inside an interrupt handler, and thirty ticks is still far faster than a
photograph.  The two PEI anchors enter the record by a *claim* rather than a repaint -- the
record is per image, so `CheckpointDxe` restates green and yellow at its entry without touching
those pixels, because a stage that paints over another stage's slot destroys the reading the
first one carried, which is exactly what `check-clover-uefi.py` refuses a build over.  No
row changes meaning, so round 23 decodes exactly like round 22: red at `+0x340000` is still
`ClockDxe` finishing, and the index meter still names whatever the dispatch loop last started.
What the round decides is the next fork, and it is a real fork: if the ladder is readable in
this photograph, the wipe was a clear and the boot past the clock is now visible; if the screen
is still dark with the refresher running, the panel is no longer scanning `0x9D400000`, and the
target moves to wherever the display driver pointed it.

Round 23 came back with the same screen as round 22 -- bands, then a lit backlight over nothing,
then a power-off that only a ten-second hold answers -- and the reason turned out to be in the
tree rather than in the panel.  Round 22 did not get stuck again.  It got *to the end*: BDS found
no operating system, which on this port is the expected state of the world, and
`Silicon/Silicium/SiliciumPkg/Library/BootManagerLib/BootManager.c:202-224` answers that with
`DisplayBootGraphic (BG_NO_BOOT_OS)`, then `gBS->Stall (10000000)`, then
`gRT->ResetSystem (EfiResetShutdown, ...)`.  Three statements, and the device report has three
clauses in the same order.  The ladder is not being erased by something mysterious downstream:
the boot is drawing over it, waiting ten seconds, and switching the tablet off, and a refresher
that only defends memory cannot win an argument with a panel that has been told to show
something else.  So round 24 stops the argument at its source.  `CheckpointDxe` overwrites
`SystemTable->RuntimeServices->ResetSystem` at entry -- the same structure `gRT` points at, and
the one every caller dereferences, including `CoreResetSystem` on its way to the arch protocol --
and its replacement paints one new band and never returns.  The band is the ladder's only free
step, `+0x100000`, one pitch above the first protocol slot and two below the magenta anchor, and
its colour is the `EFI_RESET_TYPE` the caller asked for: yellow shutdown, red cold, cyan warm,
white platform-specific, so the row is four-valued where everything else on the panel is two, and
`read-clover-photo.py` says which.  Hanging there rather than continuing costs nothing the boot
still needed -- there is no OS to hand off to -- and it buys the one thing twenty-three rounds
have not had: a picture that stays.  Two answers come out of the same photograph.  If the ladder
is up and holding, the dark screen was one pass of a blit, the refresher out-painted it, and
everything above is the finished boot reading at leisure.  If the reset band is the only thing
lit, the panel really has stopped scanning `0x9D400000` and the instrument has to move to the
buffer the display driver chose.  And if the tablet still powers itself off with this build, then
the shutdown never came through runtime services at all, which points the next round at the
hardware watchdog instead.

Round 24 came back with that third branch, and it is not a finding about the tablet: it is a
finding about the instrument.  Bands, then a backlight over nothing, then a power-off that needs
a ten-second hold to answer -- round 22's screen, round 23's screen, and now a fourth time, from
a build that was supposed to stop the power-off.  The hook was installed.  It was not *kept*:
`CheckpointDxe` writes `gRT->ResetSystem` at `APRIORI.inc` line 23, and line 76 of the same list
is `ResetSystemRuntimeDxe`, whose entry point's first statement is
`gRT->ResetSystem = RuntimeServiceResetSystem;`
(`Mu_Basecore/MdeModulePkg/Universal/ResetSystemRuntimeDxe/ResetSystem.c:187`).  Fifty-three
lines later the pointer every caller dereferences was somebody else's again, BDS's
`EfiResetShutdown` went to the real service, and the tablet did what it has always done.  There
is also nothing to install *under*: the same entry point then publishes
`gEfiResetArchProtocolGuid` with a `NULL` interface (`ResetSystem.c:193-196`), so below the
runtime table there is a flag that a reset happened is allowed, not a service that one can be
intercepted in.  Round 25 therefore stops treating an install as permanent and treats it the way
round 23 treats a pixel.  The tick handler already runs every millisecond and already repairs one
bar of the ladder per visit; it now does one more comparison, `mRuntimeServices->ResetSystem ==
CloverResetCaught`, and when that is false it puts the hook back and paints the same
`+0x100000` band **green**, once.  Green is deliberately not one of the four reset colours,
because the two are different kinds of fact: green says this instrument was disarmed and had to
be re-armed, while yellow, red, cyan and white say somebody actually asked for an exit.  The tick
is the right place for it and the timing is not close -- line 76 is dispatch, and rounds 18
through 21 are nothing but samples taken from inside dispatch, so the restore lands a millisecond
after the theft and long before the BDS ever reaches for the pointer.  What the row can now say
about a boot that runs to the end: green means the theft was real and this round is the first
build where a shutdown call has anywhere to go; a reset colour on top of it, or instead of it,
means the call arrived and the boot is parked in the hook with the refresher sweeping; dark with
the tablet still powering itself off is the one reading that keeps the watchdog theory alive.
`read-clover-photo.py` names all three -- the row is five-valued now and reports `RE-ARMED` for
green rather than folding it into "lit".

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
| On-device rounds | (1) generic geometry, cold boot -> Mi logo frozen; (2) stock-geometry repack, `fastboot boot` -> black (uninformative); (3) the same image with `DisplayDxe`, `fastboot boot` -> black (uninformative); (4) the same image, cold boot -> **Mi logo frozen, exactly like round 1**; (5) the same geometry and driver with `kernel_compression = "none"`, cold boot -> **Mi logo frozen again**; (6) only bytes 8..63 changed (`requires_kernel_header = false`), cold boot -> Mi logo flashed, back in fastboot; (7) splash paint, still `"none"` -> no colour; (8) `b .` at `_Start`, still `"none"` -> Mi logo flashed, back in fastboot; **(9) `kernel_compression = "gzip"` restored + the same paint, cold boot -> the screen turned solid blue and the tablet never came back on USB** (no fastboot, no adb, minutes after the reboot). Round 9 is the first result that means something on its own: ABL gunzipped the kernel section, jumped into BootShim, and our store to `0x9D400000` reached the panel. It also retroactively disowns rounds 5-8: all four were `= none`, i.e. executable code fed to a loader that expects a gzip stream, so "header off changes the behaviour" (round 6) and "the paint shows nothing" (round 7) were readings of the encoding, not of the firmware or the header. USB was never a differential: the erase-`boot` control produced the same absent/fastboot/absent/fastboot timeline as the boots that ran; (10) the same image plus the four-bar ladder, cold boot -> the user read **a green band and a magenta band, no white** ("有绿带 / 这个紫色带是品红吗"), so round 9's blue stayed and the ladder worked first try. The reading is the user's eye on the panel -- this host has no output channel at UEFI stage; (11) the thirteen-bar ladder, cold boot -> **green, magenta, three evenly spaced cyan bands, no white** ("绿 品红 无 青色三条，间隔均匀"). Three cyan in consecutive slots is the shape the arch protocols make (CpuDxe, WatchdogTimer, TimerDxe are dispatched within one APRIORI step of each other), and no BDS/BlockIo/RTC band means the dispatch never got near the storage or variable drivers. Round 11's offsets were already the round-12 ones, so the bands did not move; (12) the twenty-one-bar ladder with eight red bands on the Qualcomm chain, cold boot -> **three cyan, five red, no white** ("青色三条 红色五条 白色没有"). The aggregate is the problem: which three and which five is not recoverable from a count, and the two shapes that fit say opposite things. Consecutive-from-the-top would mean the DXE core enumerated its firmware volumes, the arch protocols came up, SMEM appeared and the {AE37B942} fan-in was satisfied -- so ten vendor blobs became schedulable and the wall is inside one of them. The other shape, a lit set with holes, is what the dispatch order actually implies: `BdsDxe`, `VariableRuntimeDxe`, `DevicePathDxe` and `EmbeddedMonotonicCounter` are all `Depex TRUE` (verified in the Mu_Basecore INFs, not assumed), so they cannot be starved, and a dark BDS band with eight bands lit elsewhere means the dispatch loop *stopped* rather than ran out of schedulable drivers; (13) the positional ladder, cold boot -> the user sent a **photograph** of the panel instead of a count, which is worth several rounds of counting and reads band by band: `FV enumeration` **dark**, then `Cpu` / `Runtime` / `Security` / `watchdog` cyan, then `variable write`, `variable read`, `monotonic counter` and `RTC` **dark**, then `metronome` cyan, the {AE37B942} fan-in red, the GIC cyan, the timer cyan, `ChipInfo` red, `SMEM` red -- and every band from SMEM downward dark: Clock, BlockIo, DiskIo, partitions, FAT, collation, the display, PMIC, BDS. Three consequences. **(a) A dark band above a lit one is a real hole, not a paint that failed**: `VariableRuntimeDxe` (FV file 13) and `EmbeddedMonotonicCounter` (14) are `Depex TRUE` and the volume lists them ahead of `MetronomeDxe` (18), whose band lit, so they dispatched and *returned without installing their protocol* -- and an entry point that fails finishes the driver for the dispatcher, so its band stays dark forever. *(Withdrawn with round 15's finding: FV order is not dispatch order, and these three sit below the hang in `APRIORI.inc`, which the queue ignores depex for. Consequence (b) survives, and (c) is what the meter went on to confirm.)* **(b) The dark `FV enumeration` band is an artifact of the instrument, not of the firmware, and finding it cost the theory built on it**: `MdeModulePkg/Core/Dxe/Hand/Notify.c:99-159`, read at last, shows `CoreRegisterProtocolNotify` appends a notify record and returns -- it does *not* signal for handles that already exist, and only `LocateHandle (ByRegisterNotify)`, which starts at the head of the protocol's handle list, sees those. So a protocol installed before `CheckpointDxe` was dispatched paints dark whatever else is true, and FirmwareVolume2 is exactly that case: `CoreInitializeDispatcher` (`Dispatcher.c:1465`) hangs the whole FV scan off the FV2 notification, so the fact that twenty-odd drivers dispatched proves FV2 exists and was published before this driver ran. Every other round-13 band belongs to a driver dispatched after `CheckpointDxe` -- it is third in APRIORI and APRIORI entries are queued ahead of the volume scan -- so the rest of the reading stands, but the FV2 hole and the variable-store story built on it are withdrawn, and round 14 drains existing instances at entry so the ladder stops lying about early protocols. **(c) The wall itself**, from the FV file order measured off `FVMAIN.Fv.txt` joined to `FV/Guid.xref` (the numbering on that page, not remembered): the last module to reach an instrumented protocol is `SmemDxe` at file 30, and the first producer band dark below it is `ClockDxe` at 38, with `BdsDxe` (64, `Depex TRUE`) never appearing. So the hang is in 31..38: `ULogDxe` 31, `NpaDxe` 32, `DALSys` 37 -- `DiskIo` 33, `PartitionDxe` 34, `Fat` 35 and `EnglishDxe` 36 are in that range too but are bind-only, so their dark bands say nothing. `ClockDxe` is the one that matters downstream: DisplayDxe (45) and SdccDxe (43) both wait on its GUID, so the panel and the eMMC are still queued behind the hang; **(14) v0.2.21, cold `flash boot`, photographed:** green and magenta at the top, then three cyan bands (FV2, FVB, the CPU arch protocol -- the drain working, which round 13 could not show), then **three dark**, then red fan-in, cyan GIC, cyan timer, red ChipInfo, red SMEM, and everything from `ClockDxe` down dark, the seven index bands black. `scripts/read-clover-photo.py` read it, and needed two fixes first: a hand-held frame slants the bands by tens of rows edge to edge, so rows must be sampled from a narrow vertical strip, and colour agreement alone cannot pick the geometric fit (most of the ladder wants cyan), so the distance from a slot centre now comes off the score. The reading is round 13's shape with the volume bands acquitted, plus the hole at 13/14/17 and a meter that reported nothing; **(15) v0.2.22, cold `flash boot`, photographed: the meter named the module.** The last image the DXE core loaded is **FVMAIN file 38, `ClockDxe`**, and its own band is dark, so the loop stopped inside that driver's entry point -- `ULogDxe` 31, `NpaDxe` 32 and `DALSys` 37 are cleared, because 38 is only reached after they were loaded and started. The three marks report the reading is live rather than lucky: white lit (the driver found its own file in the volume list), cyan lit (images matched against it), red dark (nothing was loaded that is not in it). The hole round 14 found outlived the reading: `VariableRuntimeDxe` (13), `EmbeddedMonotonicCounter` (14) and `RealTimeClock` (17) were dark *because they are queued below the hang* -- apriori line 59, 60 and 62, past ClockDxe at 47 -- and the only reason they looked like a hole was that this ladder ordered its rows by dependency logic instead of by the queue that runs. The frame came back landscape, so the reader turns the picture itself now, and it lines the ladder up on the black bands as well as the coloured ones -- the entry-point black pass makes a dark slot a marked position rather than an absence, which is what pins the geometry to within a row at the bottom of the ladder, where a model-only fit was four to six rows off; **(16) v0.2.24, built and waiting for the tablet**: `ClockDxe` removed from `APRIORI.inc` *and* `Include/DXE.inc` so no depex round can resurrect it, the slot table re-ordered to `APRIORI.inc` line order, and the file numbers stripped out of the band labels because volume order and dispatch order are different axes and dropping a file shifts the first. The image is 1,220,608 bytes (24,576 smaller), sha256 `663d372fbb99d131…`, FVMAIN at 80 files with `HWIODxeDriver` now 38, `SdccDxe` 42, `DisplayDxe` 44 and `BdsDxe` 63. Two readings are being asked for: the free one first -- reboot on the saved round-15 image, wait ten minutes, photograph it again, which is the only way to tell a spin with no exit from a long timeout -- then this build; **(16) read, and it says `SdccDxe`**: the index meter painted for the first time -- three of its seven bit bands lit, decoding to 32+8+2 = **42 = SdccDxe** -- with the marks live (white and cyan lit, red dark), and every slot from the clock down still black. So the queue ran through the whole list ClockDxe used to sit in, loaded the eMMC host driver, and stopped there. That is round 16's answer, and it is a negative one: the four clock consumers do *not* survive without a clock producer, which is what their `.depex` said they would not, so `ClockDxe` goes back in and the removal is retired. Three things were ruled out on the host for free before drawing that conclusion. The `smc #0` retry loop visible in ClockDxe's disassembly is **not** the hang: all 29 blobs carry the same three sites (it is Qualcomm's `scm_call` "busy, try again" idiom), and ChipInfo, SMEM, DALSys and GLink all cleared them. `APRIORI.inc` is now **line-for-line lavender's** modulo our own CheckpointDxe, the removed ClockDxe and the absent UFSDxe, so the ordering theory is dead. And `MemoryMapLib.c`'s 46 MMIO rows and `ConfigurationMapLib.c`'s 27 keys are **identical to lavender's** in name, base, size and value -- the 95-line diff against that file is the RAM rows and the comments. What is left is the blob: ClockDxe is Xiaomi's HAL/DAL clock driver (`HAL_clk_GetNumberOfClocks`, `Clock_InitImage`, `DALSYS_SyncCreate`, `Clock %s BIST Failed!`), i.e. a driver whose normal failure mode is polling a PLL or a clock-domain handshake; and `v0.2.25` (`bc6996c`) is the reader fix this reading needed, because the camera renders the meter's `0xFFFF00` as rgb ~(138,253,25) and the old `r > 150` test called every lit bit "background" ; **(17) v0.2.27, built and waiting for the tablet** -- `ClockDxe` is back in `APRIORI.inc`, `DXE.inc` and `proprietary-files.txt`, so FVMAIN is 81 files again and the volume numbering is round 15's to the byte: `ClockDxe` 38, `SdccDxe` 43, `DisplayDxe` 45, `BdsDxe` 64. `scripts/fv-order.py` was re-exported against this build (`~/clover-out/fv-order.txt`), and round 16's 80-file list is kept as `~/clover-out/fv-order-round16.txt` -- built by dropping file 38 and shifting the rest down one, which reproduces that round's recorded `HWIODxeDriver` 38 / `SdccDxe` 42 / `DisplayDxe` 44 / `BdsDxe` 63 exactly -- because decoding a round-16 photograph against the round-17 list names file 42 as `SPIDxe` instead of `SdccDxe`. The image is `~/clover-out/Mu-clover-v0.img`, 1,245,184 bytes, sha256 `4190f0c5600429c3…`, header still v0 / page 4096 / kernel `0x8000`, and `CheckpointDxe` now registers a synchronous-exception callback on the CPU arch protocol and paints ESR/ELR/FAR into the seven protocol rows it borrows plus a fourth mark at `+0x7C0000`. **(17) read, and the answer is "neither":** the handler mark at `+0x7C0000` came back **lit**, the index meter again named **file 38, `ClockDxe`** (bits 32+4+2), and **not one of the seven fault rows is lit**. So `ClockDxe` does not abort -- no data abort, no translation fault, no NULL dereference -- it is sitting in a loop that never exits, which retires the "missing producer leaves a NULL protocol" shape for this hang and moves the question to *what it is polling*. Getting that reading needed a reader fix: the camera rendered this frame's white bars as rgb ~(150,250,250), which the old `hi - lo < 45` test called `background`, so both white marks read dark and the exception layer announced itself NOT LIVE. Round 15's white had measured (92,235,254) and only survived by falling through to the cyan rule and being rescued by the want-based `LIT(white)` label -- two frames, two different renderings of the same bar, and the calibration that worked for one silently failed for the other. `classify()` now takes white as "three channels high, none dead", which is what actually separates it from yellow (blue off), cyan (red off) and magenta (green off), and the cyan fallback stays for a dim frame. All three archived frames re-decode clean after the fix: round 17 → 38 with the handler lit and no fault, round 16 → 42 `SdccDxe`, round 15 → 38 `ClockDxe`, and both older frames still read their handler row dark, which is correct -- neither driver had one |
| Payload compression | **settled by round 9, and the opposite of what v0.2.10 claimed.** This unit's own `boot` and `recovery` kernels both begin `1f 8b` at the section start (`kernel/section-prefixes.txt`), so its header-v0 ABL does gunzip boot images, and `kernel_compression = "gzip"` -- a bare gzip stream of BootShim + FD + DTB -- is the encoding it wants. v0.2.10 flipped it to `"none"` on the sentence "this unit's own kernels are arm64 Image.gz-with-stub, so its loader never needed gunzip", which is false and was contradicted two blocks above itself in the same toml. Rounds 5, 6, 7 and 8 were all `"none"`: raw executable code handed to a decompressor, which is why they froze or bailed, and why none of those four rounds says anything about the header, the framebuffer or the FD address |
| Kernel header | `requires_kernel_header` is on, and the checker makes turning it off an error -- but that guard rests on round 6, which is now known to be a `"none"` build, so the measurement does not isolate the header. What is actually established: gzip + header on enters BootShim (round 9). Untested: gzip + header off. BootShim writes `text_offset = FD_BASE = 0x9fc00000` at offset 8 and `FD_SIZE + (_Payload - _Head)` at 16, neither legal under the arm64 boot protocol, so a loader that parses them is being lied to either way. The size field adds the shim on purpose (upstream writes `FD_SIZE` alone): the UniXNU boot-image step compares the header against the bytes it puts in the kernel field, and the boot-chain contract there says the header describes the shim plus the firmware volume. Expect the guard to be replaced by a measurement before the flag is trusted |
| Liveness probe | `BootShim/BootShim.S` (an upstream file, deliberately replaced -- see `apply-clover-overlay.py`) fills 8 MiB at `0x9D400000` with `0xFF0000FF` before it relocates the FD. **Round 9 read it: the screen went solid blue and the tablet never reappeared on USB.** That also fixes the pixel layout for the rest of the port -- words are read as ARGB8888, blue in the low byte, so green is `0xFF00FF00` and a red would be `0xFFFF0000`. The panel needs no driver to show a store: ABL is already scanning out that window. Remove by deleting the file and its `COPIED` entry |
| Checkpoint ladder | the paint proves the first instruction, nothing after it. `Platforms/Xiaomi/cloverPkg/Include/Checkpoint.h` therefore draws one bar per stage at its own offset inside the 8 MiB the paint filled, so a single boot reports the deepest stage reached: green from `GetMemoryMap` (first caller is `MemoryInitPeiLib`, so PEI), yellow from `GetConfigurationMap` (a bonus rather than a stage -- that library is linked into Sec as well, so its first caller is not necessarily PEI), magenta from `CheckpointDxe`'s entry (the DXE core dispatched a normal driver), white from its `GraphicsOutput` protocol notify (the vendor `DisplayDxe` came up), then nine cyan bands at +0x140000 to +0x340000, one per architecture or core protocol that appears: CPU, watchdog, timer, RTC, variable write, Block I/O, simple file system, BDS, USB I/O. Position is the message, so all nine share a colour, and `RegisterProtocolNotify` does *not* report instances that already exist (`Hand/Notify.c`), so a protocol published before this driver ran paints dark until round 14 drains them with `LocateHandle (ByRegisterNotify)` at entry. Round 11 read exactly three of those cyan and nothing below them, so eight **red** bands follow at +0x380000 to +0x540000 for the vendor side of the same gap (round 12 read three cyan, five red, no white -- and no amount of asking fixes what that means, because a count identifies neither band): the DXE core's firmware-volume enumeration, RuntimeArch, SecurityArch, SMEM, the private GUID ten blobs wait on, ChipInfo, Clock, VariableArch. Round 14 trims it to sixteen protocol slots and adds that drain; round 15 keeps the sixteen and adds ten more bands under them. What ships now is FV2, FVB, CPU, `VariableWriteArch`, the monotonic counter, RTC, then the Qualcomm chain -- the fan-in GUID, the GIC, the ARM timer, ChipInfo, SMEM, Clock -- then `BlockIo` off `SdccDxe`, `PartitionInfo`, `GraphicsOutput` in white and `BdsDxe`, at +0x140000 to +0x500000; below them +0x540000 to +0x6C0000 the seven bits of the last loaded image's FVMAIN file index, MSB topmost; and under those +0x700000, +0x740000, +0x780000 as white, cyan and red marks that report on the meter itself. The six slots round 14 dropped either lit in round 13 or can only ever follow one that did, and the duplicate variable band (the readable interface, which `VariableRuntimeDxe` always installs together with the write interface) became the monotonic counter in round 15 because round 14 proved the two variable bands carry the same fact and the counter watches a different driver. Round 13 made it positional: `CheckpointDxe` paints **all twenty-four protocol slots black at its own entry** and recolours a slot only when the module that owns it appears, so the panel always shows the whole ladder and the first black band below the magenta one is the first module that never dispatched -- no counting, and a hole in the middle is now visible as a hole. Round 13's slot table was in the order the DXE core reaches things rather than the order the volume lists them: firmware-volume enumeration from HOBs (`DxeMain.c` walks the `FIRMWARE_VOLUME_HOB`s before `CoreDispatcher`), then the architecture protocols, then `VariableRuntimeDxe` (write then readable), monotonic counter, RTC, metronome, then the Qualcomm chain -- the fan-in GUID, the GIC, the timer, ChipInfo, SMEM, Clock -- then storage as it actually happens (`BlockIo` off `SdccDxe`, then DiskIo, then partition handles, then FAT, then collation), then `GraphicsOutput` in white, `PmicDxe` and finally `BdsDxe`. That was twenty-seven bands from +0x40000 to +0x700000; it is now twenty-nine, from +0x40000 to +0x7A0000, each 128 KiB on a 256 KiB pitch, still inside the BootShim fill. Two band bindings were chosen from the tree rather than from memory: this Mu_Basecore has no `gEfiPartitionDiscoveryProtocolGuid` at all -- its `PartitionDxe` produces `gEfiPartitionInfoProtocolGuid`, so that is the partition band -- and `gHardwareInterruptProtocolGuid` lives in EmbeddedPkg.dec, so it is a literal in the C file like the four Qualcomm GUIDs, which keeps `CheckpointDxe` a one-package driver. Bars are 128 KiB: round 10's 1 MiB pitch was easy to read but could not fit thirteen stages inside the fill. The checker binds every offset it can find, including the ones stored in `CheckpointDxe`'s table rather than passed to a call, and fails on two bars closer than one bar length, because a merged band loses the reading. `CheckpointDxe` is ours, needs nothing and returns `EFI_SUCCESS`, and is third in `APRIORI DXE`. A screen with no bars at all but a real UEFI image is the best outcome. Round 13 was read from a **photograph** rather than a spoken count, and that is the standard ask from here on: twenty-seven bands cannot be named by a tally, and one picture gave the whole reading in a single boot (the rounds row). `scripts/read-clover-photo.py` turns the jpeg into band positions by resampling the frame and classifying each row, so the reading is reproducible instead of eyeballed: it first turns the picture into whichever of the four orientations puts the ladder running down the frame (round 15's photo came back landscape, with the bars across the long axis), then fits the geometry from the green and magenta anchors and refines it against the bands themselves. The refinement matters: a hand-held frame's pitch grows steadily down the ladder, a constant-pitch model is four to six rows off by the bottom, and at the bottom sit the marks, whose whole job is to tell a band painted black from a place nobody wrote -- so the sampling row has to be on the band. Bands are lined up on the table using the **dark** runs as well as the coloured ones, because the entry-point black pass makes an unlit slot a marked position rather than an absence; where two runs claim one position the coloured band wins and the closer claim beats the further. Colour agreement alone cannot pick the fit, because most of the ladder wants cyan, so how squarely a band lands on a slot comes off the score. Rows are read from a narrow vertical strip, not across the screen: a band is straight on the panel but slanted in a hand-held photo, and round 14's frame slants by tens of rows edge to edge, so a wide sample averages each band with the gap beside it and nothing wins a majority. Every band is then read twice, from its run and from the row the fit predicts, and both are printed, so a fit that had drifted shows up as the two columns disagreeing rather than as a confident wrong name. Remove by deleting `Checkpoint.h`, `Drivers/CheckpointDxe/`, the three `CloverCheckpointBar` calls and the two `INF` lines plus the `[Components]` line |
| Vendor dependency chain | read off the blobs rather than guessed: each `Binaries/clover/**/*.depex` is a small expression (opcode `0x02` pushes a 16-byte GUID, `0x03` AND, `0x06` TRUE, `0x08` end), and the 27 of them name a short list of Qualcomm protocols the platform waits on. `gEfiSMEMProtocolGuid` {F4E5C7D0-…} comes from SmemDxe, whose own depex is TRUE; DALSYSDxe waits on SMEM alone; and **ten** blobs -- ChipInfoDxe, ClockDxe, HWIODxe, I2CDxe, SPIDxe, PlatformInfoDxe, PmicDxeLa, AdcDxe, TsensDxe, TLMMDxe -- all wait on {AE37B942-457F-4C91-A196-D9669FD347A3}, a GUID no header or `.dec` in this tree declares, so it can only come from a blob. `gEfiClockProtocolGuid` {241AFAE6-…} then gates both `DisplayDxe` (twelve depex terms, among them `gEfiChipInfoProtocolGuid` {B0760469-…} and `gQcomPmicVersionProtocolGuid`) and `SdccDxe`, the eMMC host that has to hand UniXNU its `BLOCK_IO`. Nothing in the FV declares a producer for `gEfiFirmwareVolumeBlockProtocolGuid`, so whatever backs the variable store is a blob too. Round 13's dark `FV enumeration` band looked like proof that DxeCore never published FV2 and the variable store had nowhere to live; that was the instrument's blind spot (the registration is never drained for pre-existing interfaces), it was withdrawn in round 14, and the FVB band has lit in every photograph since. What the depexes *cannot* tell is whether a driver gets a turn at all: `APRIORI.inc` lists nearly everything, and the apriori queue starts its entries with no depex evaluation, so a blob whose dependency is unsatisfied is still loaded and started -- which is why round 16 removing the clock producer is a test of what `SdccDxe` and `DisplayDxe` do without it, not a prediction that they stay dark |
| Dispatch order, measured | Two different orders matter, and mixing them up is what produced round 14's false "hole". **Dispatch order is `Include/APRIORI.inc`, row for row**: that list contains nearly every DXE module in this volume, and the apriori pass in `MdeModulePkg/Core/Dxe/Dispatcher/Dispatcher.c` inserts each entry it finds at the tail of `mScheduledQueue` with `Dependent = FALSE` and **no depex evaluation** -- the drain loop then loads and starts in that order. So the queue is a prefix, `Depex TRUE` buys nothing here, and a dark band below the hang means "not started yet", not "starved". **Volume order is a build artifact** and a separate axis: `Build/cloverPkg/RELEASE_CLANGPDB/FV/FVMAIN.Fv.txt` lists offset and file GUID, `FV/Guid.xref` names the GUID, and `scripts/fv-order.py` joins them -- which is what the index meter's number refers to, so never read a number against the apriori list. Round 15's volume held 81 files: 1 `gAprioriGuid`, 2 DxeCore, 3 PcdDxe, 4 ArmCpuDxe, 5 RuntimeDxe, 6 SecurityStubDxe, **7 CheckpointDxe**, 8 TzDxe, 9 WatchdogTimer, 10 CapsuleRuntimeDxe, 11 ReportStatusCodeRouter, 12 StatusCodeHandler, 13 VariableRuntimeDxe, 14 EmbeddedMonotonicCounter, 15 SimpleTextInOutSerial, 16 ResetSystemRuntimeDxe, 17 RealTimeClock, 18 MetronomeDxe, 19 PrintDxe, 20 DevicePathDxe, 21 ConPlatformDxe, 22 ConSplitterDxe, 23 GraphicsConsoleDxe, 24 HiiDatabase, 25 EnvDxe, 26 ArmGicDxe, 27 ArmTimerDxe, 28 ChipInfo, 29 GlinkDxe, 30 SmemDxe, 31 ULogDxe, 32 NpaDxe, 33 DiskIoDxe, 34 PartitionDxe, 35 Fat, 36 EnglishDxe, 37 DALSys, **38 ClockDxe**, 39 HWIODxe, 40 I2C, 41 SPI, 42 SPMI, 43 SdccDxe, 44 DALTLMM, 45 DisplayDxe, 46 DisplayReEnablerDxe, 47 PlatformInfoDxe, 48 ButtonsDxe, 49 PmicDxe, 50 ChargerExDxe, 51 QcomChargerDxeLA, 52 AdcDxe, 53 TsensDxe, 54 LimitsDxe, 55 UsbfnDwc3Dxe, 56 UsbBusDxe, 57 UsbKbDxe, 58 UsbMassStorageDxe, 59 UsbMsdDxe, 60 UsbDeviceDxe, 61 UsbConfigDxe, 62 HashDxe, 63 RngDxe, **64 BdsDxe**, then raw files and the console/SMBIOS/BootManagement tail up to 81. Round 16 takes `ClockDxe` out of the volume, which leaves 80 and shifts everything from 38 up by one -- `HWIODxeDriver` becomes 38, `SdccDxe` 42, `DisplayDxe` 44, `BdsDxe` 63 -- so `scripts/fv-order.py` is re-exported for every build and a round-15 photograph must be decoded against `~/clover-out/fv-order-round15.txt` and `--driver ~/clover-out/round15-CheckpointDxe.c`, both kept aside for the ten-minute re-take. Reading a new photograph with the old mapping, or the old one with the new mapping, silently misnames the module -- which is the one way this instrument can produce a confident lie |
| Next suspects, in order | Round 14 read the ladder as designed: FV2, FVB and the CPU arch protocol lit; the fan-in GUID, `ArmGicDxe`, `ArmTimerDxe`, `ChipInfoDxe` and `SmemDxe` lit; `ClockDxe` (38), `BlockIo`, partitions, `GraphicsOutput` and `BdsDxe` dark. It also turned up a fact nobody had asked for -- three bands in the *middle* stayed dark while bands below them lit, namely `VariableRuntimeDxe` (13), `EmbeddedMonotonicCounter` (14) and `RealTimeClock` (17). Read at the time as a hole -- dispatched, returned, installed nothing -- and **retracted in round 15**: those three drivers sit at `APRIORI.inc` lines 59, 60 and 62, below the hang, and the apriori queue ignores depex, so they were simply never started. The hole was this ladder ordering its rows by depex logic instead of by the queue that actually runs, and the slot table now runs in `APRIORI.inc` line order so the panel reads as a prefix. The load meter, though, reported nothing: all seven index bands were dark, and dark is also what they stay at when the meter matched nothing, so the reading of "no driver ever loaded" was the instrument failing -- SMEM is file 30 and it plainly loaded. Two bugs caused it, and both are pinned in the driver's header comment. (a) `FvGetNextFile` treats `FileType` as IN OUT and stores the type of the file it returned (`MdeModulePkg/Core/Dxe/FwVol/FwVolRead.c:207`), so setting `EFI_FV_FILETYPE_ALL` once before the loop makes the second call and every call after it search for one file type: the list round 14 matched against held one or two GUIDs. (b) The list was every FV2 instance concatenated in handle order, so even a correct walk numbered FVMAIN files from however many files the boot firmware volume reported first -- an offset a photograph cannot see. Round 15 confines the walk to the volume holding `CheckpointDxe`'s own file, whose GUID the image handle reports at entry through `EFI_LOADED_IMAGE_PROTOCOL` and its `MEDIA_FW_VOL_FILEPATH_DEVICE_PATH` node, so the number is a row of `scripts/fv-order.py`; and it puts three bands under the index that report on the meter instead of on the boot -- **white** this drivers own file was found in the list, **cyan** an image was matched against it, **red** an image was loaded that is not in it. With those a dark index means nothing ambiguous any more: white and cyan lit with the bands dark is the dispatch loop dying inside `CoreLoadImage` itself, white dark is the enumeration failing, and cyan lit with a number on the screen is the answer. What the number named, in round 15, was `ClockDxe` (38): the index bands read 32+4+2, the marks said the meter was live -- white came back **photographed as cyan**, rgb `(92,235,254)`, which is what a white bar does under this light, and `read-clover-photo.py` reports it as `LIT(white)` -- and the driver's own band stayed dark, so it was loaded, entered, and never came out. Everything listed below line 47 of `APRIORI.inc` is therefore untested rather than guilty: `ULogDxe`, `NpaDxe`, `DiskIoDxe`, `PartitionDxe`, `Fat`, `EnglishDxe`, `DALSYSDxe` wait, no -- `DALSYSDxe`, `HWIODxe`, `PlatformInfoDxe`, `MetronomeDxe`, `GLinkDxe`, `ULogDxe` and `NpaDxe` are all *above* it and ran. Four blobs name the protocol `ClockDxe` produces ({241AFAE6-885F-4F6C-…}, `gClockProtocolGuid`): `SdccDxe` (the eMMC), `DisplayDxe`, `I2CDxe` and `SPIDxe`, and nothing in this tree declares that GUID, so a stub would mean inventing a vtable layout -- a guess the ladder cannot check, and it is not the move. Two moves remain, and round 16 is the build for both. First the free one: a driver spinning on a channel to an ADSP or RPM that never answers usually has a timeout, and every reading so far has been taken within a minute or two of the reboot, so a second photograph of the *same* screen ten minutes later tells a spin with no exit from one that eventually gives up -- `~/clover-out/round15-Mu-clover-v0.img` is kept aside for exactly that. Then the diagnostic one, now built: `ClockDxe` is out of `APRIORI.inc` **and** out of `Include/DXE.inc`, so the file is not in the volume and no depex round can resurrect it. Read the prediction against the queue, not against the depexes: since apriori entries are started without one, the four clock dependents still get their turn, so the question the panel answers is whether they survive without a clock -- if the ladder lights all the way to `BdsDxe`, this one blob was the wall; if it stops on a dependent, the index meter names which, one down from its round-15 number because the volume lost file 38 and `scripts/fv-order.py` has to be re-exported before a photograph is decoded. Third thread, untouched so far: the 5-byte `dummy` ramdisk against stock's 1.3 MiB gzip stream. **Round 16 came back and the meter named `SdccDxe` (42)**, so the removal is retired and `ClockDxe` goes back in; the three host-side rules-outs (the `scm_call` retry idiom is in all 29 blobs and the ones that cleared it prove the secure world answers, our `APRIORI.inc` is lavender's line for line, and the 46 MMIO rows plus 27 config keys are byte-identical to lavender's) leave the blob itself as the only variable, and its own strings say what kind of driver it is: `HAL_clk_GetNumberOfClocks`, `Clock_InitImage`, `DALSYS_SyncCreate`, `Clock %s BIST Failed!`. Round 17 therefore stops asking *where* the queue stops and starts asking *why*: `Mu_Basecore/UefiCpuPkg/Library/CpuExceptionHandlerLib/Aarch64/CpuExceptionHandlerLib.c:262` dispatches through an `mExceptionHandlers[ExceptionType]` table before it reaches `DumpCpuContext`, which writes ELR and the register file to a serial port this tablet has no cable for and then calls `CpuDeadLoop`, so a fault inside a blob is exactly the event the panel cannot see today. Round 17 is built, and it is *not* the hex-glyph panel this row promised, for one reason worth recording: a glyph renderer needs the framebuffer stride, and nothing on this tablet gives it -- no GOP at that moment, no splash resolution in any header we can read, and the photograph cannot disambiguate it either, because a band's thickness over its pitch is 1/2 for every candidate width (1200 px -> 4800 B/row, 1920 -> 7680, 720 -> 2880). So the report uses bands whose positions are already proven visible: **rows 9 to 15 of the protocol ladder, which a boot that hangs never reaches anyway**, plus a fourth mark at `+0x7C0000` saying the handler is in place. `CheckpointDxe` waits for the CPU arch protocol (APRIORI line 30, after its own line 24), registers one callback for `EXCEPT_AARCH64_SYNCHRONOUS_EXCEPTIONS` through `gCpu->RegisterInterruptHandler`, and its handler reads ESR, ELR and FAR out of the saved context -- `CommonCExceptionHandler` dispatches a registered handler *before* `DumpCpuContext`, which is the serial write this unit cannot reach -- then paints, in order: an exception happened at all; FAR zero / above `0xA0000000` / inside the RAM window (the bounds come from `MemoryMapLib`, which stops at `0xA0000000`); `ESR.EC` is a data abort; `DFSC` is a translation fault; and ELR lies inside the image the core last loaded. Four readings and each one is actionable: mark lit and no fault row lit is a spin, so look at polling; FAR zero is the NULL protocol a missing producer leaves behind; low non-zero FAR is an MMIO base the map does not carry; and a fault whose ELR row is dark happened outside the module the index names, which moves the search to a library or the core. Colours are only yellow, cyan, red and white on purpose -- green and magenta are what `read-clover-photo.py` anchors its geometry on, and a second band of either would move the fit. The reader prints the borrowed rows under both names and marks the layer NOT LIVE when `+0x7C0000` is dark, because Mu keeps one handler per type and does not chain, so a taken slot looks exactly like a clean boot. The 10-minute re-photograph is still worth doing on the current hung screen -- it separates a spin with no exit from one that eventually times out, and round 17 cannot tell those apart either. **Round 17 is read: the handler mark lit and no fault row lit, so `ClockDxe` spins rather than aborts**, which removes the whole "it dereferenced something a missing producer never installed" family from the list and leaves a poll. What to do next, cheapest first, is now a host-side question with no device round in it: disassemble the blob's entry path (`Binaries/clover/QcomPkg/Drivers/ClockDxe/ClockDxe.efi`, the same `objdump` route used to find the `scm_call` retry sites) and locate the loop the entry point falls into. The address it polls decides the story: a PLL status register in the GCC window (`0x001xxxxx`) or a subsystem clock window says the driver is waiting on silicon that a board-id/PMIC mismatch can leave unlocked -- and `Clock %s BIST Failed!` in its own strings is that failure shape; an address in the shared-memory / RPM / ADSP region says it is waiting on a remote processor whose images this build never loads, which would make the hang a consequence of the payload, not of the clock driver, and would point the fix at not dispatching the drivers that need a clock rather than at the clock. **The scan has now been re-run against the file, the first set of numbers was wrong, and the shape is far more useful.** `llvm-objdump` is not on this host and the guest's rejects `-b`, so the route is GNU `objdump -D -b binary -m aarch64 --adjust-vma=0` over the blob; the PE32+ header says `SizeOfImage` 0x1e000 with `.text` at VA 0x1000 for 0x14000 bytes and *file offset == RVA* throughout, which is what makes a photographed page number usable. What that scan finds is **130 copies of the word `0x14000000` -- `b .`, an unconditional branch to itself, all of them 4-byte aligned and all inside `.text` -- and every single one sits immediately after `bl 0x5f84`** whose arguments are `adrp/add x0` to a source-file string, `mov w1, #NNN` (a line number) and `adrp/add x2` to the asserted expression. So this blob is built with assertions live, an `ASSERT()` halts the machine, and `Clock %s BIST Failed!` is only one of many messages that go to a serial port nobody can read. What is left after them is **five** two-instruction bit polls with no counter anywhere in the body: `0x9074` and `0x90d0` (bit 25), `0x9240` (bit 0), `0xa784` (bit 31), `0xab14` (bit 0), each `ldr w?, [base]; tbz/tbnz w?, #bit, back`, and each base is a clock record's register pointer (`ldr x10, [x0, #8]` in the `0xa76c` family), so a static scan still cannot name the address it waits on. **That retires the free experiment this row has been asking for since round 15** -- none of these has a counter to run out -- and it turns round 18's page number into a file name, because the 4 KiB pages partition by source file: 5 `DebugLib.c`, 6 `SafeString`/`CopyMem`/`HobLib`/`ArmArchTimerLib`/`UefiLib`, 7 `DALModEnv.c`, 9 `npa_plugins.c` + `PrintShLib.c` and three of the five hardware polls, 10 `MemLibGuid`/`ReportStatusCodeLib` and the other two, and **11 through 15 are one PLL template family each -- 11 Huayra, 12 Prius, 13 Spark/SR/Veyron, 14 Agera/Brammo/BrammoBear, 15 Fabia** (the complete site table, with line numbers, is `~/clover-out/clockdxe-pages.txt`). A tick in page 11..15 therefore names a PLL template that asserted; page 9 or 10 means the driver is genuinely waiting on a hardware bit; page 5 or 6 means the assert machinery itself was entered with a bad pointer. **What a static scan cannot do is say which of them**: a call graph from the entry reaches a small fraction of the module, because this is a DAL/HAL driver whose work goes through device-object function pointers loaded from `.data`, so the callees are not `bl` immediates. Two things fall out. The cheap one: `Platforms/Xiaomi/lavenderPkg` and every other Qualcomm Xiaomi board in this checkout keeps `ClockDxe` in `APRIORI.inc` and boots, and `cloverPkg` is the only untracked platform here -- blob and silicon exonerated, same direction the `scm_call` and memory-map rules-outs pointed. The expensive one, and the only instrument that reaches the answer without a serial cable: **sample the interrupted program counter from the timer tick.** The first design for that was wrong, and the reason is the finding: `ArmGicDxe` is `APRIORI.inc` line 31, one line after `ArmCpuDxe` and one before `ArmTimerDxe`, and its entry ends in `GicCommonInstallAndRegisterInterruptService` (`Mu_Basecore/ArmPkg/Drivers/ArmGicDxe/ArmGicCommonDxe.c:165`), which registers its own dispatcher into the CPU arch protocol's `EXCEPT_AARCH64_IRQ` slot and **returns the error and installs nothing** if that fails -- so a driver that took the IRQ slot at line 30 would leave ten blobs waiting on a protocol that never appears and ArmTimerDxe asserting on it. That round would hang somewhere else and every band would describe *that* hang. The tick is therefore taken one level down, where the GIC's own rules help: `GicCommonRegisterInterruptSource` refuses to replace a handler it already has, so removing ArmTimerDxe's handler from the timer's INTID and registering this driver's in its place is two calls on `EFI_HARDWARE_INTERRUPT_PROTOCOL`, the GIC keeps its CPU slot and its acknowledge/EOI, and the notification that does it waits on the timer arch protocol -- which ArmTimerDxe installs as the last thing before it unmasks the counter, so by then the compare value is loaded and the tick is live. `USE_PHYSICAL_TIMER = 1` in `StarlordPkg.dsc.inc`, so the counter this build arms is the physical one and the INTIDs offered are ArmPkg.dec's 27, 26, 29 and 30, whichever of them actually has a handler. The handler reads `ELR` and paints `(ELR - mLastImageBase) >> 12`, a five-bit page index inside the module the meter already named, and reloads the compare value itself -- ArmTimerDxe's handler is what used to do that, and without it there would be exactly one sample. Three readings: a page number says which of those three functions the PC is parked in, and the disassembly above names the polls inside each; white lit with the arrival row dark says the tick never came, which can only mean the spin runs with **interrupts masked** -- a driver at `TPL_HIGH_LEVEL` rather than a bit that never sets; and white dark says the source was never taken, so the round reads exactly like round 17's. What it costs is event timeout processing for the drivers queued after line 32: `gBS->Stall` reads the counter and survives, `ArmTimerDxe`'s own band stays lit because its protocol really did install, and if losing the timeouts breaks something before the clock the index meter names it, which is a reading too; **(18) v0.2.30, built and waiting for the tablet**: the tick is taken from the GIC's timer source exactly as above -- `CheckpointDxe` now notifies on `gEfiTimerArchProtocolGuid`, locates `gHardwareInterruptProtocolGuid` (Mu's name for it, `EmbeddedPkg.dec:72`; the `gEfi…` spelling does not exist in this tree), offers INTID 27, 26, 29 and 30, and for each one *removes* the handler and re-registers its own, which is the only way in past `GicCommonRegisterInterruptSource`'s `EFI_ALREADY_STARTED` guard. The handler ends the interrupt, reloads the compare value from `ArmGenericTimerGetSystemCount ()` and re-enables the timer before it paints anything, so a sample is not a one-shot. The ladder is byte-for-byte comparable to round 17's -- `ClockDxe` is back in all three lists, FVMAIN is 81 files again, and a fresh `scripts/fv-order.py` export against this build diffs **empty** against `~/clover-out/fv-order-round17.txt` on the index/GUID/name columns, so `--modules ~/clover-out/fv-order.txt` still names `ClockDxe` as 38 and `ArmTimerDxe`'s own band (slot 5, `+0x280000`) stays lit because its protocol really did install. The image is 1,245,184 bytes -- the same size as round 17's -- sha256 `09f6393b3822cd9930ac885ec2189d18616dd3e1f6082969898939df7bd00159`, header still v0 / page 4096 / kernel `0x8000`. The reader grew the second reading of those seven rows (`--driver` this round's C file): the row at `+0x4C0000` picks the mode, white means the page bits below it are `(ELR - last image base) >> 12`, and the five-bit page is weighted by each row's **place in the table** rather than by the rows that happen to be lit -- page `0b11001` lights rows 9, 10 and 13 and compacting those three decoded it as 7 |

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
