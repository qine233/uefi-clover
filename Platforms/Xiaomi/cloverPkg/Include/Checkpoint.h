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
  every slot black at its own entry, recolours a slot when the protocol it names
  exists, and leaves black what the boot never produced.  The screen therefore always
  shows the whole ladder, and a band identifies itself by where it sits.  Below the
  slots the seven yellow bands are not stages at all but a number: the FVMAIN file
  index of the last driver the DXE core loaded, bit 6 topmost, so the module that
  hangs names itself.  The three bands under that are the meter telling the truth
  about itself, because in round 14 a dark index meant either nothing had loaded or
  the meter was broken, and the two looked identical.

    stage  colour  offset from the splash base   painted from
    -----  ------  ----------------------------  ------------------------------
     0      blue   whole framebuffer             BootShim (before the FD)
     1      green  +0x00040000                   MemoryMapLib, first call (PEI)
     2      yellow +0x00080000                   ConfigurationMapLib, first call (Sec)
     3      magenta +0x000C0000                  CheckpointDxe entry (DXE dispatch)
     4..19  black  +0x00140000 .. +0x00500000    every protocol slot, at that entry,
            ->     256 KiB apart                 and then recoloured below
     4..19  mixed  +0x00140000 .. +0x00500000    sixteen slots in the order the DXE
            (cyan  core reaches them: FV2 and FVB, which it publishes itself; the
             with   CPU arch protocol; VariableRuntimeDxe; the monotonic counter at
             red    file 14; RTC; the vendor fan-in GUID; the GIC and the ARM timer
             ones)  inside the Qualcomm chain; then red ChipInfo, SMEM and Clock;
                   then BlockIo off the eMMC host, partitions, and at the end
                   GraphicsOutput and BdsDxe
    20..26  yellow +0x00540000 .. +0x006C0000    the seven bits of the last loaded
            ->black                             image's file index, high bit first
    27      white  +0x00700000                   this drivers own file was found in the
                                                 list the index is matched against, so
                                                 the number above is a row of fv-order.py
    28      cyan   +0x00740000                   an image was loaded whose file was in
                                                 that list, so the meter is live
    29      red    +0x00780000                   an image was loaded whose file was
                                                 not in it, so the number above is
                                                 whatever was matched last, not the
                                                 newest load
    30      white  +0x007C0000                   the CPU arch protocol appeared and this
                                                 driver holds its synchronous-exception
                                                 slot, so the seven rows below mean
                                                 what they say

  Round 17 gives rows 9 to 15 of the protocol ladder a second meaning, and the mark at
  +0x7C0000 is what decides which meaning a photograph is showing.  Those seven rows are
  PartitionDxe, BlockIo, the variable write interface, the monotonic counter, the RTC,
  BDS and the display -- every protocol band below the clock -- and a boot that stops
  inside a driver never reaches any of them, so they are dark on exactly the screens that
  need somewhere to put an exception report.  When the mark is lit they read:

    +0x380000 red      a synchronous exception was taken at all
    +0x3C0000 yellow   FAR is zero, which is a NULL pointer, and the shape a protocol
                       nobody produced takes
    +0x400000 yellow   FAR is above 0xA0000000, past the last row of the memory map
    +0x440000 yellow   FAR is inside the RAM and firmware window, 0x80000000..0x9FFFFFFF
    +0x480000 red      ESR calls it a data abort (EC 0x24 or 0x25), so FAR can be trusted
    +0x4C0000 cyan     the fault is a translation fault, DFSC 0x04..0x07, so no page
                       table entry exists for the address at all
    +0x500000 yellow   ELR is inside the image the core last loaded, so the abort is in
                       the module the index names and not in something it called

  None of the seven lit, with the mark lit, is the answer a spin gives: the driver is
  looping with no exit and no pointer is being dereferenced.  The mark dark is not an
  answer at all, because Mu keeps one handler per exception type and does not chain, so a
  slot that was already taken leaves the fault rows exactly as dark as a boot that never
  faulted.

  Colour is not the information in that table and green and magenta are kept out of it on
  purpose: those two are what a photograph is aligned on, at stages 1 and 3, and a second
  band of either in the middle of the ladder would move the fit and misplace every band
  below it.

  Round 17 was read, and it returned the spin case: the mark lit, none of the seven.  That
  made "where inside the module" the next question, and the module's own disassembly says
  the loops it is stuck in have no counters -- so the same seven rows are borrowed a third
  time, this round for a sample of the program counter taken from a timer interrupt.  The
  row at +0x4C0000 decides which of the two readings a photograph is in: **white** means
  this driver holds the timer's tick and the rows below are the tick's, **cyan** means a
  translation fault overwrote it and the whole table above is live.  When it is white:

    +0x140000 yellow   tick PC, bit 11 (the page's upper half)  \
    +0x180000 yellow   tick PC, bit 10                          |
    +0x1C0000 yellow   tick PC, bit 9                           |  seven bits of the address
    +0x200000 yellow   tick PC, bit 8                           |  from bit 11 down to bit 5,
    +0x240000 yellow   tick PC, bit 7                           |  i.e. which 32 bytes of the
    +0x280000 yellow   tick PC, bit 6                           |  page the core was sitting
    +0x2C0000 yellow   tick PC, bit 5                          /   on
    +0x380000 yellow   tick PC page, bit 4 (the 64 KiB half)   \
    +0x3C0000 yellow   tick PC page, bit 3                      | five bits of
    +0x400000 yellow   tick PC page, bit 2                      | (ELR - last image base)>>12
    +0x440000 yellow   tick PC page, bit 1                      |
    +0x480000 yellow   tick PC page, bit 0                     /
    +0x4C0000 white    the timer's GIC source is ours, taken from ArmTimerDxe by removing
                       its handler and registering this driver's in its place
    +0x500000 cyan     a tick arrived with its PC inside that image
    +0x500000 red      a tick arrived with its PC outside it, which says the loop is in a
                       library the core linked rather than in the module the index names

  Round 18 was read, and its five page bits were the whole answer they could give: page 10
  of ClockDxe, which is the clock enable-and-acknowledge region and holds twelve candidate
  sites -- two counter-free hardware polls waiting on bit 31 and on bit 0 clearing, three
  ASSERT(0)s in the Huayra PLL template, six library asserts and one bare `b .`.  "An ack
  bit that never arrives" and "an assert that parked the CPU in CpuDeadLoop" are different
  bugs with different fixes, and one page could not tell them apart, so the seven rows at
  the top of the ladder came from the protocol slots to make the sample twelve bits wide.
  They are slots 0..6 (FV2, FVB, the CPU, the vendor fan-in GUID, ArmGicDxe, ArmTimerDxe,
  SmemDxe), the seven that have lit on every photograph since round 14 and that the index
  bands make redundant -- the module is named by its file number, not by its protocols.
  SlotIsLent() is what keeps their notifications from colouring a band the tick owns, and
  the two rows left in the middle (ChipInfo at +0x300000, the clock at +0x340000) are the
  anchor that says the ladder has not moved.

  A bit is therefore painted or erased by its own position in the driver's table, not by
  where its row happens to sit among the lit ones: round 18's decode counted yellow rows
  and would have re-weighted every bit if a row were inserted, which is exactly what
  happened here.

  White lit and +0x500000 dark is the other answer, and it is not a failure of the
  instrument: the only way a tick can be registered and never arrive is for the loop to run
  with interrupts masked, which is a driver stuck at high TPL rather than a hardware bit
  that never sets.  Dark at +0x4C0000 with the exception mark lit is the third case, and it
  says the timer's source was never taken, so the rows below belong to nothing and the
  round reads like round 17.

  The tick is taken from the interrupt controller rather than from the CPU's exception
  slots, and that is not a style choice.  ArmGicDxe registers its own dispatcher into
  EXCEPT_AARCH64_IRQ on the CPU arch protocol as the last step before it installs
  EFI_HARDWARE_INTERRUPT_PROTOCOL, and if the registration fails it returns the error and
  installs nothing -- so a driver that took the IRQ slot first would take it from ten blobs
  that wait on that protocol and from ArmTimerDxe, which asserts on it.  That round would
  hang somewhere else and every band would be describing that other hang.  Taking the
  timer's INTID instead leaves the GIC's dispatcher in place: the tick still arrives at the
  IRQ vector, the dispatcher still acknowledges it, and only the handler at the end of the
  table has changed.

  What it costs is still real, and it is one thing: ArmTimerDxe's handler is what reloads
  the compare value and calls the DXE core's timeout notify.  This handler reloads the
  compare, so the ticks keep coming, and does not call the notify, so event timeouts stop
  being processed for everything APRIORI-queued after line 32.  The sample is last-writer-
  wins for the same reason it is coarse-grained-but-not-too-coarse: the tick also fires
  during ordinary dispatch, so the value that stops changing is the one the loop is parked
  at, and the erase-before-paint keeps the bands from becoming the union of every address
  the loop walked through on the way there.

  Rounds 9 through 13 are the reason the table is this shape, and each of the three
  parts answers a reading that came back ambiguous.

  Round 10 read stages 0, 1 and 3 -- green and magenta, no white -- so SEC
  decompressed FVMAIN, PEI built the HOBs, DxeMain started and dispatched an
  ordinary driver, and the stop is somewhere in the DXE dispatch after that.

  Round 11 read three evenly spaced cyan bands and round 12 read three cyan and five
  red, both with no white.  A count identifies no band, and the two shapes that fit
  said opposite things, so round 13 added the black pass.  Checking the INFs under
  Mu_Basecore settles what those two readings could not: BdsDxe, VariableRuntimeDxe,
  DevicePathDxe and EmbeddedMonotonicCounter all have Depex TRUE, so they cannot be
  starved, and a dark band on one of them means the dispatch loop stopped rather than
  ran out of things to run.  Round 13's photograph said exactly that -- the last
  producer band lit was SMEM (file 30 of FVMAIN) and Clock (38) was the first dark one
  under it, with BdsDxe (64) dark too -- and it exposed two flaws in the instrument
  itself, which are what stages 4..19 and 20..26 now exist to fix.

  Round 14 confirmed the drained reading -- FV2, FVB and the CPU arch protocol lit; the
  fan-in GUID, the GIC, the timer, ChipInfo and SMEM lit -- and added a fact nobody had
  asked for: the three bands between them, VariableRuntimeDxe, the monotonic counter and
  RTC, stayed dark.  A hole in the middle of a ladder whose bands below it light is not
  a stopped loop, it is drivers that ran and returned without producing what they are
  supposed to produce.  The two variable bands went together, so one of them now watches
  the monotonic counter instead, and the meter is the reason for asking again.

  The meter itself reported nothing: all seven index bands came back dark, which is also
  exactly what they look like when the meter never matched anything.  Two bugs in
  CheckpointDxe caused it, and stages 27..29 exist so that a dark index can never again
  be read as either of two opposite things.  FvGetNextFile treats FileType as IN OUT and
  writes back the type of the file it returned (MdeModulePkg/Core/Dxe/FwVol/FwVolRead.c:
  207), so setting it to EFI_FV_FILETYPE_ALL once before the loop makes the second call
  and every call after it search for one file type only.  And the list was built from
  every volume with an FV2 instance concatenated in handle order, so even a correct walk
  would have numbered FVMAIN files from however many files the boot firmware volume
  reported first -- an offset a photograph cannot see.  The walk is now confined to the
  volume holding this drivers own file, taken from its loaded image protocol at entry.

  The first is that CoreRegisterProtocolNotify does not report interfaces that already
  exist; it only appends a notification record (MdeModulePkg/Core/Dxe/Hand/Notify.c:
  139), and a protocol installed before this driver ran keeps its band dark.  DxeCore
  publishes FirmwareVolume2 and FirmwareVolumeBlock from the HOBs long before APRIORI,
  so round 13's dark volume band meant nothing, and the driver now drains every
  registration by hand at entry.  An FVB slot was added because that is the protocol a
  variable store needs and DxeCore derives FV2 from it (FwVol.c:622), so the two bands
  together say whether any volume was readable.

  The second is that a set of dark bands still names no module.  The DXE core calls
  CoreLoadImage for a driver the moment it reaches the head of the scheduled queue and
  CoreStartImage only afterwards (Dispatcher.c:456 and :520), so the last image loaded
  is the module the loop was working on -- and a notification event at TPL_NOTIFY runs
  while that load is still in progress, because an event fires on the first TPL
  lowering below its own level (Event/Tpl.c:120-133) and the install queues it
  (Hand/Notify.c:32).  Hence seven bands rather than a taller ladder.

  Round 10's offsets were 1 MiB apart (green +0x100000, magenta +0x300000). The
  ladder was then dense enough to read but too coarse to fit the slots into the
  BootShim fill, so the whole table moved to a 256 KiB stride; the ordering
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
