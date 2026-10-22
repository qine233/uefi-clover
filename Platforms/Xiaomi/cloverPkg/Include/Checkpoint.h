/**
  Screen checkpoints for the Xiaomi Mi Pad 4 8" LTE (clover, Qualcomm SDM660).

  This unit has no serial console we can reach, and the only thing that has ever
  visibly changed on it is the ABL splash.  Round 9 proved that a store into the
  splash region survives to the panel: BootShim filled 8 MiB at 0x9D400000 and the
  screen came up blue.  These bars are the same trick, used as a ladder, so one
  boot answers "how far did it get" instead of only "did the first instruction run".

  Every stage paints its own bar at its own offset and never touches another's, so
  the deepest bar visible is the furthest stage reached.  All of it sits inside the
  8 MiB BootShim filled, which is itself inside the map's "Display Reserved"
  0x9D400000 + 0x02400000.

  From stage 4 the ladder is positional rather than counted: CheckpointDxe paints
  every slot black at its own entry and recolours a slot only when the module that
  owns it appears.  The screen therefore always shows the whole ladder, and the
  first black band below the magenta one is the first module that never dispatched.
  Reading it is "the first N bands are coloured, the rest are black" or, if a hole
  opens in the middle, which band it is.

    stage  colour  offset from the splash base   painted from
    -----  ------  ----------------------------  ------------------------------
     0      blue   whole framebuffer             BootShim (before the FD)
     1      green  +0x00040000                   MemoryMapLib, first call (PEI)
     2      yellow +0x00080000                   ConfigurationMapLib, first call (Sec)
     3      magenta +0x000C0000                  CheckpointDxe entry (DXE dispatch)
     4..27  black  +0x00140000 .. +0x00700000    every slot, at that entry, and then
            ->     256 KiB apart                 recoloured below
     4..13  cyan   +0x00140000 .. +0x00380000    EDK II: the DXE core enumerating
                                                 its firmware volumes, then Cpu,
                                                 Runtime, Security, watchdog,
                                                 variable write, variable read,
                                                 monotonic counter, RTC, metronome
     14..19  mixed +0x003C0000 .. +0x00500000    the Qualcomm chain in the order its
            (red    red fan-in, then the cyan GIC
     with         and timer, then red ChipInfo, SMEM and Clock -- the two ARM
     two          drivers sit inside the vendor chain because the chain runs
     cyan)      through them
     20..24 cyan   +0x00540000 .. +0x00640000    BlockIo off SdccDxe, then DiskIo,
                                                 partitions, file systems, collation
     25     white   +0x00680000                  GraphicsOutput, the display
     26     red     +0x006C0000                  PmicDxe, which is late in the volume
     27     cyan    +0x00700000                  BdsDxe: the loop finished

  Round 10 read stages 0, 1 and 3 -- green and magenta, no white -- so SEC
  decompressed FVMAIN, PEI built the HOBs, DxeMain started and dispatched an
  ordinary driver, and the stop is somewhere in the DXE dispatch after that.
  Stages 5..13 exist to say where.

  Round 11 read green, magenta and three evenly spaced cyan bands and no white,
  which puts the stop in the same gap. The red stages exist because that gap is
  not one step: parsing the depex sections under Binaries/clover (opcode 0x02
  pushes a GUID, 0x03 ANDs, 0x06 TRUE, 0x08 ends the expression) shows the vendor
  blobs are chained, not parallel.  EnvDxe and SmemDxe wait on nothing; DALSYSDxe
  waits on SMEM; and ChipInfoDxe, ClockDxe, HWIODxe, I2CDxe, SPIDxe,
  PlatformInfoDxe, PmicDxe, AdcDxe, TsensDxe and TLMMDxe all wait on
  {0xAE37B942,0x457F,0x4C91,{0xA1,0x96,0xD9,0x66,0x9F,0xD3,0x47,0xA3}}, a GUID no
  header in this tree declares -- so it is produced by a blob, and if that blob
  does not run, ten of the thirty-five never even become schedulable.  DisplayDxe
  then waits on SMEM, ChipInfo, Clock and eleven more, and SdccDxe (the eMMC that
  has to give UniXNU its BLOCK_IO) waits on Clock and the timer.  The red bands
  walk that chain in order.

  Round 12 read three cyan, five red and no white, which is the reason for the
  black pass: a count cannot say which bands, and the two readings that fit are
  opposite.  Checking the INFs under Mu_Basecore removes half the ambiguity --
  BdsDxe, VariableRuntimeDxe, DevicePathDxe and EmbeddedMonotonicCounter all have
  Depex TRUE, so they cannot starve, and a dark band on any of them means the
  dispatch loop stopped rather than ran out of things to run.

  Round 10's offsets were 1 MiB apart (green +0x100000, magenta +0x300000). The
  ladder was then dense enough to read but too coarse to fit nine protocols into
  the BootShim fill, so the whole table moved to a 256 KiB stride; the ordering
  top-to-bottom is unchanged, only the spacing.

  A screen with no bars at all but a real UEFI image is the best result: it means
  the vendor display path took the panel over.

  Words are stored as 0xAARRGGBB, which is what round 9 measured: the blue that
  appeared came from 0xFF0000FF, so the panel reads little-endian words as ARGB8888
  (blue in the low byte).

  @copyright  SPDX-License-Identifier: BSD-2-Clause-Patent
**/

#ifndef CLOVER_CHECKPOINT_H_
#define CLOVER_CHECKPOINT_H_

#include <Base.h>

// 0x9D400000: the "Display Reserved" row of Platforms/Xiaomi/cloverPkg/Library/
// MemoryMapLib/MemoryMapLib.c, which is where this unit's own xbl put the splash.
// scripts/check-clover-uefi.py fails the build if this and that row diverge.
#define CLOVER_SPLASH_BASE  0x9D400000

// EDK II builds these with -Werror, and two things in a comment can stop the
// compile: a `/*` pair inside the block (a repo path spelled with a glob is the
// way to do it by accident), and an apostrophe or quote, which clang reports as a
// missing terminating character.  Write globs as "the .depex files under ..." and
// leave the apostrophes out.
//
// 128 KiB: about 27 rows at a 1200-pixel stride, about 17 at 1920. Round 10's
// 256 KiB bars were unmistakable, but at a 256 KiB pitch they would touch, and
// thirteen bands have to share the 8 MiB BootShim filled.
#define CLOVER_BAR_SIZE  0x00020000

#define CLOVER_COLOR_GREEN    0xFF00FF00
#define CLOVER_COLOR_YELLOW   0xFFFFFF00
#define CLOVER_COLOR_MAGENTA  0xFFFF00FF
#define CLOVER_COLOR_WHITE    0xFFFFFFFF
#define CLOVER_COLOR_CYAN     0xFF00FFFF
#define CLOVER_COLOR_RED      0xFFFF0000

// The not-reached colour.  Black on the blue the BootShim filled is unmistakable,
// and it is what lets a band be identified by where it sits instead of by what it
// looks like: every slot is this colour until its module appears.
#define CLOVER_COLOR_BLACK  0xFF000000

//
// Plain stores, because this runs from PEI (before the DXE memory services exist)
// as well as from DXE, and the splash window is normal DRAM either way.  Write
// through volatile so nothing reorders a bar past the stage it reports.
//
STATIC
VOID
CloverCheckpointBar (
  IN UINT64  OffsetFromSplashBase,
  IN UINT32  Argb
  )
{
  // EDK2's Base.h defines STATIC and CONST but not VOLATILE.
  volatile UINT64  *Slot;
  UINTN            Index;
  UINT64           Pair;

  Slot = (volatile UINT64 *)(UINTN)(CLOVER_SPLASH_BASE + OffsetFromSplashBase);
  Pair = ((UINT64)Argb << 32) | (UINT64)Argb;   // no LShiftU64: BASE modules skip BaseLib

  for (Index = 0; Index < CLOVER_BAR_SIZE / sizeof (UINT64); Index++) {
    Slot[Index] = Pair;
  }
}

#endif // CLOVER_CHECKPOINT_H_
