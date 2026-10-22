/**
  Screen checkpoints for the Xiaomi Mi Pad 4 8" LTE (clover, Qualcomm SDM660).

  This unit has no serial console we can reach, and the only thing that has ever
  visibly changed on it is the ABL splash.  Round 9 proved that a store into the
  splash region survives to the panel: BootShim filled 8 MiB at 0x9D400000 and the
  screen came up blue.  These bars are the same trick, used as a ladder, so one
  boot answers "how far did it get" instead of only "did the first instruction run".

  Each stage paints its own bar at its own offset and never touches another's, so
  the deepest bar visible is the furthest stage reached.  All of it sits inside the
  8 MiB BootShim filled, which is itself inside the map's "Display Reserved"
  0x9D400000 + 0x02400000.

    stage  colour  offset from the splash base   painted from
    -----  ------  ----------------------------  ------------------------------
     0      blue   whole framebuffer             BootShim (before the FD)
     1      green  +0x00040000                   MemoryMapLib, first call (PEI)
     2      yellow +0x00080000                   ConfigurationMapLib, first call (Sec)
     3      magenta +0x000C0000                  CheckpointDxe entry (DXE dispatch)
     4      white  +0x00100000                   CheckpointDxe, GOP notification
     5..13  cyan   +0x00140000 .. +0x00340000    one band per protocol that appears,
                                                 256 KiB apart and all the same colour
                                                 because the position is the message:
                                                 CPU, watchdog, timer, RTC, variable
                                                 write, block I/O, file system, BDS,
                                                 USB

  Round 10 read stages 0, 1 and 3 -- green and magenta, no white -- so SEC
  decompressed FVMAIN, PEI built the HOBs, DxeMain started and dispatched an
  ordinary driver, and the stop is somewhere in the DXE dispatch after that.
  Stages 5..13 exist to say where.

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

// 128 KiB: about 27 rows at a 1200-pixel stride, about 17 at 1920. Round 10's
// 256 KiB bars were unmistakable, but at a 256 KiB pitch they would touch, and
// thirteen bands have to share the 8 MiB BootShim filled.
#define CLOVER_BAR_SIZE  0x00020000

#define CLOVER_COLOR_GREEN    0xFF00FF00
#define CLOVER_COLOR_YELLOW   0xFFFFFF00
#define CLOVER_COLOR_MAGENTA  0xFFFF00FF
#define CLOVER_COLOR_WHITE    0xFFFFFFFF
#define CLOVER_COLOR_CYAN     0xFF00FFFF

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
