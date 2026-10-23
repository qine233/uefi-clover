/**
  DXE-dispatch checkpoint for the Xiaomi Mi Pad 4 8" LTE (clover).

  Round 13 painted every protocol slot black at this driver's entry and recoloured
  one when the module owning it appeared, and the photograph was readable: CPU,
  Runtime, Security and Watchdog lit; the fan-in GUID, the GIC, the timer, ChipInfo
  and SMEM lit; Clock and everything under it stayed dark, BdsDxe included.  BdsDxe
  is Depex TRUE, so a dark band on it means the dispatch loop stopped rather than
  ran out of schedulable drivers, and the stop is bracketed by the last lit producer
  (SmemDxe, file 30 of FVMAIN) and the first dark one below it (ClockDxe, file 38).
  Two questions survived that reading, and this driver is built to answer them.

  The first is a lie this instrument told.  The firmware-volume band stayed dark,
  which read as though the DXE core had never enumerated its volumes.  It had.
  CoreRegisterProtocolNotify (MdeModulePkg/Core/Dxe/Hand/Notify.c:139) allocates a
  PROTOCOL_NOTIFY, points its Position at the head of the protocol's interface list
  and returns; nothing signals an event for an interface that is already there.  The
  only way to see a protocol installed before this driver ran is to drain the
  registration by hand with LocateHandle (ByRegisterNotify), which is what every
  EDK II notify callback does but which cannot happen if the callback is never
  called.  So every slot below is drained at entry as well as registered, and the
  band now means the protocol exists rather than the protocol appeared after us.
  That acquits the volume enumeration and puts the honest question somewhere else:
  VariableRuntimeDxe (file 13) is listed ahead of MetronomeDxe (18), which lit, yet
  both of its bands stayed dark, and a Depex TRUE driver cannot be starved.  It must
  have run and returned without installing.  (Round 15 withdrew this:  both drivers are
  in the apriori list, and it, not depex, is what sets the order -- VariableRuntimeDxe
  sits below the hang like everything else in the dark.  The sentence is kept because
  it is why an FVB band was added, and the FVB band is worth having.)  A FirmwareVolumeBlock band is added
  because that is what it would have needed to do so, and DxeCore derives FV2 from
  FVB (FwVol.c:622), so the two bands together say whether any volume was readable
  at all.

  The second question is which module the loop stopped inside.  Sixteen dark bands
  identify no file, and this unit has no serial console, so the answer has to be
  encoded in the same 8 MiB of framebuffer.  The seven yellow bands carry the FVMAIN
  file index of the last image the DXE core loaded, most significant bit first, and
  the index is looked up against the volume enumerated at entry.  Dispatcher.c:456
  calls CoreLoadImage the moment a driver reaches the head of mScheduledQueue and
  CoreStartImage only afterwards, so the load names the module the loop was working
  on, and the module that hangs announces itself first.  For that the notification
  has to run while the load is still in progress.  An event's notification function
  fires on the first CoreRestoreTpl to a level strictly below its NotifyTpl
  (Event/Tpl.c:120-133), and the notification is queued by the interface install
  itself (Hand/Notify.c:32), whose lock is already dropped when the level is restored
  (Library.c:80).  TPL_NOTIFY is the highest level an event may use, so it runs on the
  very first lowering; a TPL_CALLBACK event has to wait for a lowering below
  CALLBACK, which need not happen between two drivers, and the number would name
  whichever load came after the hang.

  Round 14 shipped that meter and it reported nothing: every one of the seven bands
  came back dark, and dark is what the black pass leaves them at, so the reading said
  no image had loaded since entry -- while SMEM, which is file 30, had plainly loaded.
  The meter was therefore broken, not the boot, and there were two ways for it to
  break while still leaving the bands black.

    The list it matched against was wrong.  FvGetNextFile takes FileType as IN OUT and
  on success stores the type of the file it just returned (FwVolRead.c:207).  Set to
  EFI_FV_FILETYPE_ALL once before the loop, the first call hands back the type of the
  volume first file, and every later call filters on it: the walk silently becomes
  all files of that one type instead of all files.  Round 14 therefore stored one or
  two GUIDs, no driver matched, and the index stayed zero.  FileType is now reset
  before every call.

    The list was not even one volume.  Every FV with an FV2 instance was walked in
  handle order and concatenated, so FVMAIN files were numbered from however many files
  the boot firmware volume reported before them -- a constant offset that no
  photograph can reveal.  The walk is now confined to the volume that holds this
  drivers own file, which the image handle reports at entry through its loaded image
  protocol and its device path.  That makes the number the position in FVMAIN, which
  is what scripts/fv-order.py prints.

  Three marks at the very bottom say which of these the meter is doing, so a dark
  index stops being ambiguous: white when this drivers own file was found in the list
  (the enumeration worked and picked the right volume), cyan when an image was loaded
  whose file was in the list (the meter is live and the number below it means
  something), red when an image was loaded whose file was not (a volume or numbering
  problem, whatever the bands say).

  Round 15 read this instrument and it answered: all three marks lit what they should,
  the seven bits decoded to FVMAIN file 38, ClockDxe, and its own band stayed dark.
  Both surviving guesses from round 14 died there.  The variable, monotonic and RTC
  bands were never a hole -- see the order rule by the slot table, they are queued below
  the hang -- and the file numbers those rows carried described the volume, not the
  dispatch, which is the axis that actually matters here.

  Cyan is EDK II, red is Qualcomm, white is the display, black is a stage this boot
  did not reach, and yellow is data rather than progress.  Order in the slot table is
  order in Include/APRIORI.inc, which for this build is the dispatch order itself: the
  apriori entries are queued by list position with no depex evaluation, so the panel is
  a prefix and the last lit row is the last driver the queue reached.

  Round 16 asked the question the meter cannot answer, and it answered a different one.
  Taking ClockDxe out of the volume did not starve the four blobs that wait on its
  protocol -- they are apriori entries themselves, so they were still started -- and the
  queue then ran four rows further and stopped inside SdccDxe, the eMMC host driver.  No
  clock producer, no eMMC: the removal had told the truth about the dependency and
  nothing about the hang, so the driver is back in for round 17 and the ladder's rows are
  worth re-explaining.

  What the panel has never said is *why* a driver that was loaded never came back.  Two
  shapes fit and they need opposite fixes: a poll loop that never exits, which is a
  hardware or ordering problem inside the blob, and a CPU exception, which is a NULL
  pointer or an unmapped register and is a bug this tree can patch.  The second one used
  to be invisible because the default handler writes its report to a serial port this
  tablet has no cable for and then dead-loops.  ArmCpuDxe installs the CPU arch protocol
  at APRIORI line 30, and its exception dispatch (UefiCpuPkg/Library/CpuExceptionHandlerLib/
  Aarch64/CpuExceptionHandlerLib.c, CommonCExceptionHandler) calls a registered handler
  for the type before it ever reaches DumpCpuContext, so a callback registered on
  EXCEPT_AARCH64_SYNCHRONOUS_EXCEPTIONS sees the context of every data abort in the boot.
  It brings ESR, ELR and FAR, and seven of this drivers rows are free to carry what they
  say, because in a boot that hangs inside a driver, every slot below that driver is dark
  anyway.

  That is the trade this round makes, and it is worth stating plainly: rows 9 to 15 of the
  slot table now have a second meaning, and they only have it when the red row-9 band is
  lit.  A boot that reaches those drivers paints their protocol band and never paints a
  fault bit, because nothing raised an exception, so the rows mean what the table says.
  A boot that faults overwrites seven bands with the story of the fault, in a boot that
  was never going to use them.  Green and magenta are deliberately absent from the fault
  colours: those two are what the photograph is aligned on, at stages 1 and 3, and a
  second one of either would move the fit.

  Four readings come out of it.  No fault band and the red mark lit means the driver spun
  -- a loop with no exit, which no patch to a pointer will fix.  FAR zero means a NULL
  protocol pointer, which is the shape a missing producer takes.  FAR in the low physical
  range means a register the map does not carry, which is the shape a wrong base takes.
  And a fault with its ELR band dark means the abort happened outside the driver the
  index meter names, in a library copy or in the core, which changes who has to be fixed.

  Drawing nothing through the UEFI display stack and returning EFI_SUCCESS is the
  point: a bar here cannot be the reason a boot stops.

  @copyright  SPDX-License-Identifier: BSD-2-Clause-Patent
**/

#include <Uefi.h>
#include <Library/UefiDriverEntryPoint.h>
#include <Library/UefiBootServicesTableLib.h>
#include <Library/BaseMemoryLib.h>

// Protocol/FirmwareVolume2.h uses the Pi firmware-format types without including
// them, the way every EDK II header does: whoever wants it brings the Pi headers,
// and has to bring them first.
#include <Pi/PiFirmwareFile.h>
#include <Pi/PiFirmwareVolume.h>
#include <Protocol/FirmwareVolume2.h>
#include <Protocol/FirmwareVolumeBlock.h>
#include <Protocol/DevicePath.h>
#include <Protocol/LoadedImage.h>
#include <Protocol/Cpu.h>
#include <Protocol/VariableWrite.h>
#include <Protocol/MonotonicCounter.h>
#include <Protocol/RealTimeClock.h>
#include <Protocol/Timer.h>
#include <Protocol/BlockIo.h>
#include <Protocol/PartitionInfo.h>
#include <Protocol/GraphicsOutput.h>
#include <Protocol/Bds.h>
#include <Protocol/Cpu.h>

// Round 18's sampler hangs off the interrupt controller rather than the CPU.  The timer's
// tick is a GIC INTID whose handler sits in a table ArmGicDxe owns, and taking that source
// over is the only way to get a tick without dispossessing the GIC driver of the one CPU
// exception slot it must have to install its protocol at all.
#include <Protocol/HardwareInterrupt.h>
#include <Library/ArmLib.h>
#include <Library/ArmGenericTimerCounterLib.h>
#include <Library/PcdLib.h>

#include "../../Include/Checkpoint.h"

//
// The four Qualcomm-side protocols below are named by symbol in the vendor tree's
// .dec files, but no header this package can include declares them, and one of
// them is declared nowhere at all -- it only exists inside the blobs.  Copying the
// values out is the honest form: these are the bytes the dispatch actually waits
// on, and a dependency on QcomPkg/Include would make a bring-up instrument fail to
// build for a packaging reason.  gHardwareInterruptProtocolGuid is the same story
// in reverse: it exists, in EmbeddedPkg.dec, but naming it here would add a
// package to a driver that is supposed to need nothing.
//
STATIC EFI_GUID  mSmemProtocolGuid = {
  0xF4E5C7D0, 0xD239, 0x47CB, { 0xAA, 0xCD, 0x7F, 0x66, 0xEF, 0x76, 0x32, 0x38 }
};

STATIC EFI_GUID  mVendorFanInGuid = {
  0xAE37B942, 0x457F, 0x4C91, { 0xA1, 0x96, 0xD9, 0x66, 0x9F, 0xD3, 0x47, 0xA3 }
};

STATIC EFI_GUID  mChipInfoProtocolGuid = {
  0xB0760469, 0x970C, 0x487A, { 0xA4, 0xB5, 0x28, 0xDB, 0x7B, 0x45, 0xCE, 0xF1 }
};

STATIC EFI_GUID  mClockProtocolGuid = {
  0x241AFAE6, 0x885F, 0x4F6C, { 0xA7, 0xEA, 0xC2, 0x8E, 0xAB, 0x79, 0xC3, 0xE5 }
};

// The interrupt controller's protocol is the one EmbeddedPkg GUID this driver used to copy
// out of the vendor tree by hand: round 18 consumes it, so the copy is gone and the band
// below points at the declaration in EmbeddedPkg.dec instead.
//

//
// Sixteen protocol slots, +0x140000 to +0x500000, each CLOVER_BAR_SIZE long, on the
// 256 KiB pitch inside the 8 MiB BootShim filled.  Round 13 spent twenty-four bands,
// six of which told nothing this time (Runtime, Security, Watchdog and Metronome all
// lit, DiskIo, the file system and collation could only ever follow BlockIo), and the
// index needs seven more.  scripts/check-clover-uefi.py fails the build if any offset
// leaves the filled window or a band overlaps its neighbour.
//
// ORDER RULE, and it is the one round 14 did not know:  this table runs in
// Include/APRIORI.inc line order, because that file lists every DXE module this volume
// has, and CoreDispatchAllAprioriFiles (MdeModulePkg/Core/Dxe/Dispatcher/Dispatcher.c,
// the loop over AprioriEntryCount) inserts a match at the tail of mScheduledQueue with
// no depex evaluation at all -- the drain loop in CoreDispatcher then loads and starts
// in that order, straight through.  So the panel is a prefix:  the last lit row is the
// last driver the queue reached, and everything below it is simply not started yet.
//
// That retraction is why the rows moved.  Round 14 read "the write interface, the
// monotonic counter and the RTC are dark while bands around them are lit -- a hole, so
// those drivers ran and returned without installing their arch protocols".  They are
// listed at APRIORI.inc lines 59, 60 and 62, which is *below* ClockDxe at 47, the
// driver the index meter names.  They never ran; the hole was this table putting them
// near the top.  Depex TRUE only means a driver cannot be starved in the ordinary loop,
// and this build barely has an ordinary loop.
//
// The file numbers the older rows carried are gone on purpose:  FV file order is the
// FDF's packing order, which is a different axis from the dispatch order, and dropping
// a module shifts every later index.  scripts/fv-order.py is the only honest source for
// those, and the reader already resolves the meter's number through it.
//
STATIC CONST struct {
  EFI_GUID   *Guid;
  UINT64     Offset;
  UINT32     Argb;
  CHAR8      *Name;
} mSlots[] = {
  // DxeCore publishes both of these while it walks the FV HOBs, before any APRIORI
  // driver runs, so a dark band here is a real reading rather than the round-13 artifact.
  { &gEfiFirmwareVolume2ProtocolGuid,          0x00140000, CLOVER_COLOR_CYAN,  "FV2: volumes enumerated from HOBs"       },
  { &gEfiFirmwareVolumeBlockProtocolGuid,      0x00180000, CLOVER_COLOR_CYAN,  "FVB: the store a variable driver needs"  },

  // APRIORI DXE line 30.
  { &gEfiCpuArchProtocolGuid,                  0x001C0000, CLOVER_COLOR_CYAN,  "ArmCpuDxe (apriori 30)"                  },

  // Named by ten vendor blobs and declared by nothing in this tree, so it has to come
  // from one of them.  Where in the queue it appears is not known; it is placed after
  // the CPU because it has lit this far up every round it was watched.
  { &mVendorFanInGuid,                         0x00200000, CLOVER_COLOR_RED,   "the GUID ten blobs wait on"              },

  // Lines 31, 32, 36 and 39:  the Qualcomm chain around the hang.  mHardwareInterrupt
  // is EmbeddedPkg.dec's gHardwareInterruptProtocolGuid, which the timer waits on.
  { &gHardwareInterruptProtocolGuid,           0x00240000, CLOVER_COLOR_CYAN,  "ArmGicDxe (apriori 31)"                  },
  { &gEfiTimerArchProtocolGuid,                0x00280000, CLOVER_COLOR_CYAN,  "ArmTimerDxe (apriori 32)"                },
  { &mSmemProtocolGuid,                        0x002C0000, CLOVER_COLOR_RED,   "SmemDxe (apriori 36)"                    },
  { &mChipInfoProtocolGuid,                    0x00300000, CLOVER_COLOR_RED,   "ChipInfoDxe (apriori 39)"                },

  // Line 47, and round 15's reading:  this is where the queue stopped.  Nothing in this
  // tree declares the GUID, so no module of ours can answer for it -- the four blobs
  // that wait on it are SdccDxe, DisplayDxe, I2CDxe and SPIDxe.  Round 16 took it out to
  // see whether those four could run without it; they could not, and the first of them
  // to stop was SdccDxe, so it is back and this row means the clock protocol again.
  { &mClockProtocolGuid,                       0x00340000, CLOVER_COLOR_RED,   "the clock protocol (ClockDxe)"            },

  // Lines 50, 53, 59, 60, 62, 67 and 89:  these seven rows are what round 17 reads the
  // exception context into, and they are rows 9 to 15 of this table.  See mFaultBits:
  // the borrowing is why none of these offsets is repeated there, and why a fault band is
  // only ever painted by the handler, never here.
  { &gEfiPartitionInfoProtocolGuid,            0x00380000, CLOVER_COLOR_CYAN,  "PartitionDxe (apriori 50)"               },
  { &gEfiBlockIoProtocolGuid,                  0x003C0000, CLOVER_COLOR_CYAN,  "BlockIo, from SdccDxe (apriori 53)"      },
  { &gEfiVariableWriteArchProtocolGuid,        0x00400000, CLOVER_COLOR_CYAN,  "VariableRuntimeDxe (apriori 59)"         },
  { &gEfiMonotonicCounterArchProtocolGuid,     0x00440000, CLOVER_COLOR_CYAN,  "EmbeddedMonotonicCounter (apriori 60)"   },
  { &gEfiRealTimeClockArchProtocolGuid,        0x00480000, CLOVER_COLOR_CYAN,  "RealTimeClock (apriori 62)"              },

  // Line 67.  Still the cleanest single bit of information on the panel:  lit means the
  // queue drained all the way to the boot services, dark with everything above it lit
  // means it stopped on the way.
  { &gEfiBdsArchProtocolGuid,                  0x004C0000, CLOVER_COLOR_CYAN,  "BdsDxe (apriori 67)"                     },

  // Line 89, below BDS in the vendor's own ordering, so the display is last by
  // construction rather than by starvation.
  { &gEfiGraphicsOutputProtocolGuid,           0x00500000, CLOVER_COLOR_WHITE, "the display (apriori 89, below BDS)"     }
};


//
// The last loaded image's FVMAIN file index, most significant bit first, at the
// bottom of the ladder.  Index 1 is the first file in the volume, which is how
// scripts/fv-order.py numbers them, and 0 means no image has been loaded since this
// driver ran -- or the file was not in the list built at entry.
//
#define CLOVER_FV_FILES     128
#define CLOVER_INDEX_BITS   7
#define CLOVER_INDEX_MAX    (CLOVER_FV_FILES - 1)

STATIC CONST struct {
  UINT64   Offset;
  UINTN    Bit;
} mBits[] = {
  { 0x00540000, 6 },
  { 0x00580000, 5 },
  { 0x005C0000, 4 },
  { 0x00600000, 3 },
  { 0x00640000, 2 },
  { 0x00680000, 1 },
  { 0x006C0000, 0 }
};

//
// Three marks below the index, painted by this driver itself rather than by a
// protocol appearing.  Round 14 proved the meter needs them: its seven bands came
// back dark and dark is also what they stay at when the meter is broken, so a
// failure of the instrument and a boot that loaded nothing were the same screen.
// These three separate them.  White says the file list was built and holds this
// drivers own file, which means the enumeration ran on the right volume and the
// numbering matches scripts/fv-order.py.  Cyan says at least one image was matched
// against it, so the number above is live.  Red says an image was loaded whose file
// is not in the list, which makes that number stale rather than meaningless.
//
#define CLOVER_MARK_OWN_FILE   0
#define CLOVER_MARK_MATCHED    1
#define CLOVER_MARK_UNMATCHED  2
#define CLOVER_MARK_HANDLER    3

STATIC CONST struct {
  UINT64   Offset;
  UINT32   Argb;
  CHAR8    *Name;
} mMarks[] = {
  { 0x00700000, CLOVER_COLOR_WHITE, "this drivers own file is in the list"   },
  { 0x00740000, CLOVER_COLOR_CYAN,  "an image was matched against the list"  },
  { 0x00780000, CLOVER_COLOR_RED,   "an image was not in the list"           },

  // Round 17, and the fourth mark is of the same kind as the other three: it says
  // whether an instrument works, not where a boot got to.  White here means the CPU arch
  // protocol was found and this driver owns the synchronous-exception slot in it, so the
  // seven fault rows below are live.  Dark means they are not: either no CPU protocol
  // appeared, or ArmCpuDxe already had a handler registered for the type and Mu returns
  // EFI_ALREADY_STARTED rather than chaining, in which case a fault would have gone to
  // the default handler, out to a serial port nobody can read, and a screen with the
  // fault rows dark says nothing about whether one happened.
  { 0x007C0000, CLOVER_COLOR_WHITE, "the exception handler is registered"    }
};


STATIC EFI_EVENT    mEvents[ARRAY_SIZE (mSlots)];
STATIC VOID         *mRegistrations[ARRAY_SIZE (mSlots)];
STATIC EFI_EVENT    mImageEvent;
STATIC VOID         *mImageRegistration;

// The image the DXE core was last seen loading, so a faulting address can be said to be
// inside it or not.  Bases and sizes are taken in ImageLoaded, at the same moment the
// index bands are painted, which is inside CoreLoadImage.
STATIC UINT64   mLastImageBase;
STATIC UINT64   mLastImageSize;
STATIC BOOLEAN  mHaveLastImage;

//
// The volume as this driver chose it: the file GUIDs of the one firmware volume that
// holds this drivers own file, in the order GetNextFile walks it, which is physical
// order and therefore the order fv-order.py prints.
//
STATIC EFI_GUID     mFvFiles[CLOVER_FV_FILES];
STATIC UINTN        mFvFileCount;

// Where this driver itself sits in the image, read off its own loaded image protocol.
STATIC EFI_GUID     mSelfFile;
STATIC BOOLEAN      mHaveSelfFile;
STATIC BOOLEAN      mSelfIsListed;

// What is on the screen right now, so a band is only rewritten when it changes.
STATIC UINT8        mBitsShown[CLOVER_INDEX_BITS];
STATIC UINT8        mMarksShown[ARRAY_SIZE (mMarks)];

/**
  Drain everything a protocol registration can still see and report whether that was
  anything.  A notify registration starts at the head of the interface list, so this
  returns the instances that were installed before RegisterProtocolNotify ran as well
  as any that arrive later; without it a protocol the platform already produced reads
  as a dark band.
**/
STATIC
BOOLEAN
DrainAndReport (
  IN EFI_GUID  *Protocol,
  IN VOID      *Registration
  )
{
  BOOLEAN     Found;
  EFI_HANDLE  Handle;
  UINTN       Size;

  Found = FALSE;

  for ( ; ;) {
    Size   = sizeof (Handle);
    Handle = NULL;
    if (EFI_ERROR (gBS->LocateHandle (ByRegisterNotify, Protocol, Registration, &Size, &Handle))) {
      break;
    }


    if (Handle == NULL) {
      break;
    }

    Found = TRUE;
  }

  return Found;
}

STATIC
BOOLEAN
SlotIsLent (
  IN UINTN  Index
  );

STATIC
VOID
EFIAPI
SlotAppeared (
  IN EFI_EVENT  Event,
  IN VOID       *Context
  )
{
  UINTN  Index = (UINTN)Context;

  // Drain the registration so it cannot queue up behind this instance and repaint a
  // band that is already lit; painting is idempotent anyway.
  DrainAndReport (mSlots[Index].Guid, mRegistrations[Index]);

  // The row may belong to a report layer (SlotIsLent), in which case the protocol still
  // has to be drained -- that is what keeps later notifications flowing -- but the band
  // is not ours to colour.
  if (!SlotIsLent (Index)) {
    CloverCheckpointBar (mSlots[Index].Offset, mSlots[Index].Argb);
  }
}

/**
  The 1-based position of a firmware volume file in the list built at entry, or 0 when
  the volume did not contain it.  A linear scan: the list is at most 128 entries and
  this runs once per driver load.
**/
STATIC
UINTN
FileIndex (
  IN EFI_GUID  *Name
  )
{
  UINTN  Index;

  for (Index = 0; Index < mFvFileCount; Index++) {
    if (CompareGuid (&mFvFiles[Index], Name)) {
      return Index + 1;
    }
  }

  return 0;
}

/**
  The file GUID a loaded image came from.  The DXE core builds every driver's device
  path from one firmware-file node (Dispatcher.c:827 and :1325 both go through
  EfiInitializeFwVolDevicepathNode), so this is the same GUID that names the file in
  the volume.  Walked by hand rather than with DevicePathLib: the nodes needed are two
  header bytes and a length, and a bring-up instrument should not grow a library
  dependency to read them.
**/
STATIC
EFI_GUID *
FirmwareFileOf (
  IN EFI_DEVICE_PATH_PROTOCOL  *DevicePath
  )
{
  EFI_DEVICE_PATH_PROTOCOL  *Node;
  UINTN                     Count;
  UINTN                     Length;

  Node = DevicePath;
  for (Count = 0; Count < 16; Count++) {
    if ((Node == NULL) ||
        ((Node->Type == END_DEVICE_PATH_TYPE) && (Node->SubType == END_ENTIRE_DEVICE_PATH_SUBTYPE)))
    {
      break;
    }

    if ((Node->Type == MEDIA_DEVICE_PATH) && (Node->SubType == MEDIA_PIWG_FW_FILE_DP)) {
      return &((MEDIA_FW_VOL_FILEPATH_DEVICE_PATH *)Node)->FvFileName;
    }

    Length = (UINTN)(Node->Length[0] | (((UINT16)Node->Length[1]) << 8));
    if (Length <= sizeof (EFI_DEVICE_PATH_PROTOCOL)) {
      break;
    }

    Node = (EFI_DEVICE_PATH_PROTOCOL *)((UINT8 *)Node + Length);
  }

  return NULL;
}

/**
  Paint the index across the seven bands, writing only the ones whose bit changed.
  A band is a store into a 2 MiB window ABL is already scanning out, so it costs
  nothing on a screen that is already showing it, and a driver that hangs after the
  paint still leaves its number up.
**/
STATIC
VOID
PaintIndex (
  IN UINTN  Index
  )
{
  UINTN   Slot;
  BOOLEAN Set;

  if (Index > CLOVER_INDEX_MAX) {
    Index = CLOVER_INDEX_MAX;
  }

  for (Slot = 0; Slot < ARRAY_SIZE (mBits); Slot++) {
    Set = (BOOLEAN)((Index & ((UINTN)1 << mBits[Slot].Bit)) != 0);
    if (Set == (BOOLEAN)(mBitsShown[Slot] != 0)) {
      continue;
    }

    mBitsShown[Slot] = (UINT8)(Set ? 1 : 0);
    CloverCheckpointBar (mBits[Slot].Offset, Set ? CLOVER_COLOR_YELLOW : CLOVER_COLOR_BLACK);
  }
}

/**
  Put one mark up.  Idempotent: the marks say whether the meter works, and once that
  is known there is nothing to gain from writing the same band again on every load.
**/
STATIC
VOID
PaintMark (
  IN UINTN  Index
  )
{
  if (mMarksShown[Index] != 0) {
    return;
  }

  mMarksShown[Index] = 1;
  CloverCheckpointBar (mMarks[Index].Offset, mMarks[Index].Argb);
}

/**
  Runs while CoreLoadImage still has the driver being loaded on its hands, so the
  number reaches the screen before that driver's entry point does.  Everything here
  is a read of the protocol database plus a store: no allocation, no event, nothing
  that would make a hang in a vendor driver this instrument's fault.
**/
STATIC
VOID
EFIAPI
ImageLoaded (
  IN EFI_EVENT  Event,
  IN VOID       *Context
  )
{
  EFI_HANDLE                 Handle;
  UINTN                      Size;
  EFI_LOADED_IMAGE_PROTOCOL  *LoadedImage;
  EFI_GUID                   *File;
  UINTN                      Index;

  for ( ; ;) {
    Size   = sizeof (Handle);
    Handle = NULL;
    if (EFI_ERROR (gBS->LocateHandle (ByRegisterNotify, &gEfiLoadedImageProtocolGuid, mImageRegistration, &Size, &Handle))) {
      break;
    }

    if (Handle == NULL) {
      break;
    }

    LoadedImage = NULL;
    if (EFI_ERROR (gBS->HandleProtocol (Handle, &gEfiLoadedImageProtocolGuid, (VOID **)&LoadedImage))) {
      continue;
    }

    File = FirmwareFileOf (LoadedImage->FilePath);
    if (File == NULL) {
      continue;
    }

    // An image that is not one of the files in the chosen volume -- a driver read off
    // the eMMC, a section loaded twice -- must not be reported as the last thing the
    // core worked on, but the fact that one arrived is worth a band: it means the
    // number still on the screen is one the meter found, not one it never updated.
    Index = FileIndex (File);
    if (Index == 0) {
      PaintMark (CLOVER_MARK_UNMATCHED);
      continue;
    }

    PaintMark (CLOVER_MARK_MATCHED);
    PaintIndex (Index);

    // The bounds of the code the core has this moment on its hands, kept for the fault
    // handler: ELR inside this range says the abort is in the module the index names, and
    // outside it says the module called something else that died.  ImageSize is the size
    // the core loaded, which covers the image and its fixups, and the entry point of an
    // in-place loaded driver is inside it.
    mLastImageBase  = (UINT64)(UINTN)LoadedImage->ImageBase;
    mLastImageSize  = (UINT64)LoadedImage->ImageSize;
    mHaveLastImage  = (BOOLEAN)(mLastImageSize != 0);
  }
}

/**
  The file GUID this driver was loaded from.  CoreLoadImage installs the loaded image
  protocol before the entry point runs, so at entry the image handle already carries a
  device path that names this file, and that GUID is what picks the volume to number.
**/
STATIC
VOID
FindOwnFile (
  IN EFI_HANDLE  ImageHandle
  )
{
  EFI_STATUS                 Status;
  EFI_LOADED_IMAGE_PROTOCOL  *LoadedImage;
  EFI_GUID                   *File;

  LoadedImage = NULL;
  Status      = gBS->HandleProtocol (ImageHandle, &gEfiLoadedImageProtocolGuid, (VOID **)&LoadedImage);
  if (EFI_ERROR (Status) || (LoadedImage == NULL)) {
    return;
  }

  File = FirmwareFileOf (LoadedImage->FilePath);
  if (File == NULL) {
    return;
  }

  CopyGuid (&mSelfFile, File);
  mHaveSelfFile = TRUE;
}

/**
  Walk one volume once.  Count is how many files it reports; when Files is given the
  GUIDs are copied there up to Max; when Self is given, ContainsSelf says whether one
  of the files carried that GUID.

  FileType is set back to EFI_FV_FILETYPE_ALL before every call, which is the whole
  point of writing this twice.  FvGetNextFile is IN OUT on that argument and stores the
  type of the file it returned (FwVolRead.c:207), so a value set once outside the loop
  turns the second call and everything after it into a search for files of the first
  files type.  Round 14 did exactly that: the list held one or two GUIDs, no driver
  matched it, and the index never left zero.
**/
STATIC
VOID
WalkVolume (
  IN  EFI_FIRMWARE_VOLUME2_PROTOCOL  *Fv,
  OUT EFI_GUID                       *Files,       OPTIONAL
  IN  UINTN                          Max,
  IN  EFI_GUID                       *Self,        OPTIONAL
  OUT UINTN                          *Count,
  OUT BOOLEAN                        *ContainsSelf
  )
{
  UINTN                   Key[2];
  EFI_FV_FILETYPE         FileType;
  EFI_FV_FILE_ATTRIBUTES  Attributes;
  EFI_GUID                Name;
  UINTN                   Size;
  UINTN                   Number;

  Number        = 0;
  *Count        = 0;
  *ContainsSelf = FALSE;

  ZeroMem (Key, sizeof (Key));

  for ( ; ;) {
    FileType = EFI_FV_FILETYPE_ALL;
    if (EFI_ERROR (Fv->GetNextFile (Fv, Key, &FileType, &Name, &Attributes, &Size))) {
      break;
    }

    if ((Self != NULL) && CompareGuid (&Name, Self)) {
      *ContainsSelf = TRUE;
    }

    if ((Files != NULL) && (Number < Max)) {
      CopyGuid (&Files[Number], &Name);
    }

    Number++;
  }

  *Count = Number;
}

/**
  Build the list a loaded image GUID is matched against, from the one firmware volume
  that holds this driver, so the number the index bands carry is the position of a file
  in that volume -- the same numbering scripts/fv-order.py prints.
**/
STATIC
VOID
EnumerateVolumeFiles (
  VOID
  )
{
  EFI_HANDLE                         *Handles;
  EFI_STATUS                         Status;
  UINTN                              HandleCount;
  UINTN                              HandleIndex;
  EFI_FIRMWARE_VOLUME2_PROTOCOL      *Fv;
  EFI_FIRMWARE_VOLUME2_PROTOCOL      *Chosen;
  UINTN                              Count;
  UINTN                              BestCount;
  BOOLEAN                            Contains;

  Handles   = NULL;
  Fv        = NULL;
  Chosen    = NULL;
  Count     = 0;
  BestCount = 0;
  Contains  = FALSE;

  Status = gBS->LocateHandleBuffer (
                  ByProtocol,
                  &gEfiFirmwareVolume2ProtocolGuid,
                  NULL,
                  &HandleCount,
                  &Handles
                  );
  if (EFI_ERROR (Status) || (Handles == NULL)) {
    return;
  }

  // Find the volume to number.  The one holding this driver is the right answer; if
  // the file was not recognized, the biggest volume is, because FVMAIN carries the
  // whole driver set and the boot firmware volume carries a handful of core files.
  for (HandleIndex = 0; HandleIndex < HandleCount; HandleIndex++) {
    Fv = NULL;
    if (EFI_ERROR (gBS->HandleProtocol (Handles[HandleIndex], &gEfiFirmwareVolume2ProtocolGuid, (VOID **)&Fv))) {
      continue;
    }

    // A key bigger than the two words WalkVolume hands back would be read out of
    // bounds, and DxeCore owns the only instances here: FwVol.c:31 declares
    // sizeof (UINTN).
    if ((Fv->KeySize == 0) || (Fv->KeySize > sizeof (UINTN))) {
      continue;
    }

    WalkVolume (Fv, NULL, 0, mHaveSelfFile ? &mSelfFile : NULL, &Count, &Contains);
    if (Contains) {
      Chosen = Fv;
      break;
    }

    if (Count > BestCount) {
      BestCount = Count;
      Chosen    = Fv;
    }
  }

  if (Chosen != NULL) {
    WalkVolume (Chosen, mFvFiles, CLOVER_FV_FILES, mHaveSelfFile ? &mSelfFile : NULL, &mFvFileCount, &Contains);
    if (mHaveSelfFile && Contains) {
      mSelfIsListed = TRUE;
    }
  }

  gBS->FreePool (Handles);
}

//
// Round 17: the exception context, in seven borrowed rows.
//
// These are indices into mSlots, not offsets, and that is not laziness.  The rows are
// slot 9 through 15, the seven below the clock -- PartitionDxe, BlockIo, the variable
// write interface, the monotonic counter, the RTC, BDS and the display -- and a boot
// that stops inside a driver never reaches any of them, so they are dark on every screen
// this round can produce.  Naming them by row also keeps the checker honest: two tables
// of literal offsets onto the same bands would be the one thing that can silently merge
// two stages, and scripts/check-clover-uefi.py is right to fail on it.
//
// Colours are not the information; position is.  Only the four LIT colours the photograph
// is calibrated for are used, and green and magenta are left out on purpose -- the reader
// anchors its geometry on the stage-1 and stage-3 bands, and a second band of either
// colour in the middle of the ladder would move the fit and misplace everything.
//
#define CLOVER_FAULT_TAKEN      0
#define CLOVER_FAULT_FAR_NULL   1
#define CLOVER_FAULT_FAR_HIGH   2
#define CLOVER_FAULT_FAR_RAM    3
#define CLOVER_FAULT_DATA_ABORT 4
#define CLOVER_FAULT_TRANSLATE  5
#define CLOVER_FAULT_PC_IN_FV   6

STATIC CONST struct {
  UINTN    Row;
  UINT32   Argb;
  CHAR8    *Name;
} mFaultBits[] = {
  {  9, CLOVER_COLOR_RED,    "a synchronous exception was taken"                  },
  { 10, CLOVER_COLOR_YELLOW, "FAR is zero -- a NULL pointer"                       },
  { 11, CLOVER_COLOR_YELLOW, "FAR is above every row of the memory map"            },
  { 12, CLOVER_COLOR_YELLOW, "FAR is inside the RAM and firmware window"           },
  { 13, CLOVER_COLOR_RED,    "ESR calls it a data abort (EC 0x24 or 0x25)"         },
  { 14, CLOVER_COLOR_CYAN,   "and a translation fault -- no mapping at all"        },
  { 15, CLOVER_COLOR_YELLOW, "ELR is inside the last image the core loaded"        }
};

//
// The two bounds are the memory map, not a guess.  Platforms/Xiaomi/cloverPkg/Library/
// MemoryMapLib/MemoryMapLib.c starts the RAM rows at 0x80000000 and the last one ends at
// 0xA0000000 -- Kernel, SMEM, the DXE heap, the display reservation, the FV region, the
// ABOOT FV, the UEFI FD and the handful of buffers above it, and as its header says,
// nothing above that appears at all.  So FAR lands in one of three named places: below
// the RAM window, which is where every Qualcomm register this board has sits, from the GCC
// clock controller at 0x00100000 to the SoC peripherals at 0x0C000000 and up; inside it,
// which is a pointer into real memory; or above it, which no device of this SoC answers.
//
#define CLOVER_RAM_BASE   0x080000000ULL
#define CLOVER_RAM_TOP    0x0A0000000ULL

// AArch64 exception syndrome fields, from the ARMv8 pseudocode that DebugSupport.h
// describes: EC is bits 31:26 and DFSC the low six.  Data abort taken from a lower
// exception level is 0x24, from the same level 0x25; an instruction abort is 0x20 or 0x21;
// translation faults are DFSC 0x04 through 0x07, one per level of the walk.
//
#define CLOVER_EC(ESR)        ((UINTN)((ESR) >> 26))
#define CLOVER_DFSC(ESR)      ((UINTN)((ESR) & 0x3F))
#define CLOVER_EC_DATA_LOWER  0x24
#define CLOVER_EC_DATA_SAME   0x25
#define CLOVER_EC_INST_LOWER  0x20
#define CLOVER_EC_INST_SAME   0x21


STATIC EFI_EVENT   mCpuEvent;
STATIC VOID        *mCpuRegistration;
STATIC BOOLEAN     mHandlerInstalled;
STATIC BOOLEAN     mFaultPainted;
STATIC volatile UINTN  mFaultSpin;

/**
  Paint one fault row.  Idempotent in the direction that matters: once the handler has
  run, the rows describe that fault, and a second call -- from the same fault arriving
  again because this handler never returns to the faulting instruction -- changes nothing.
**/
STATIC
VOID
PaintFault (
  IN UINTN  Bit
  )
{
  CloverCheckpointBar (mSlots[mFaultBits[Bit].Row].Offset, mFaultBits[Bit].Argb);
}

/**
  The synchronous-exception callback.

  Registered on the CPU arch protocol, which ArmCpuDxe installs at APRIORI line 30 --
  after this driver, so the registration happens from CpuAppeared rather than here.
  CommonCExceptionHandler calls a handler for the type and returns without touching
  DumpCpuContext, which means this is the only report a fault on this unit can produce:
  everything else about it goes to a serial port that has no cable in it.

  The context is the register file as the vector table left it, so ESR, ELR and FAR are
  read from memory rather than reconstructed.  No allocation, no protocol call, no
  print: a fault report has to be writable from the moment the abort happened, and the
  heap may well be what set the abort off.

  This never returns.  Returning would ERET back to the instruction that faulted, which
  faults again, and the recursion guard that would normally stop that lives in the
  default handler this callback replaced.  The loop is the same CpuDeadLoop does, written
  out because BaseLib is not linked into a driver that is supposed to need nothing, and
  the counter is volatile so the store cannot be optimised away and the loop cannot
  become an empty branch the compiler is entitled to treat as unreachable.
**/
STATIC
VOID
EFIAPI
FaultSeen (
  IN CONST EFI_EXCEPTION_TYPE  ExceptionType,
  IN CONST EFI_SYSTEM_CONTEXT  SystemContext
  )
{
  EFI_SYSTEM_CONTEXT_AARCH64  *Context;
  UINT64                      Esr;
  UINT64                      Far;
  UINT64                      Elr;
  UINTN                       Ec;
  UINTN                       Dfsc;
  UINTN                       Index;

  if (mFaultPainted) {
    for ( ; ;) {
      mFaultSpin++;
    }
  }

  mFaultPainted = TRUE;

  // Round 18 paints the same seven bands with a tick's page bits and a white "the slot is
  // ours", and a tick can arrive before the fault that follows it.  A reader then has to
  // work out which layer a yellow band belongs to from the colour of one other band, which
  // is a reading that can be wrong.  So the fault layer takes the whole band back the
  // moment an exception is taken: black first, and after it only what this exception
  // actually says.  Every tick row is a fault row, so this pass erases the tick layer
  // completely, and in a build that never installed a tick it repaints seven bands that
  // the entry point already made black.
  for (Index = 0; Index < ARRAY_SIZE (mFaultBits); Index++) {
    CloverCheckpointBar (mSlots[mFaultBits[Index].Row].Offset, CLOVER_COLOR_BLACK);
  }

  PaintFault (CLOVER_FAULT_TAKEN);

  Context = SystemContext.SystemContextAArch64;
  if (Context == NULL) {
    for ( ; ;) {
      mFaultSpin++;
    }
  }

  Esr  = Context->ESR;
  Far  = Context->FAR;
  Elr  = Context->ELR;
  Ec   = CLOVER_EC (Esr);
  Dfsc = CLOVER_DFSC (Esr);

  // Where the address was.  Three named ranges and one left over: a FAR that is neither
  // zero, nor in the RAM window, nor above it is below the RAM window, which is the
  // register space, and that is the shape a poll of a clock controller with the wrong
  // base takes.  Note the caveat the reader has to carry: FAR is only meaningful for
  // translation and permission faults, so an alignment fault reads as FAR zero, and it
  // is the data-abort row that says whether the address can be believed at all.
  if (Far == 0) {
    PaintFault (CLOVER_FAULT_FAR_NULL);
  } else if (Far >= CLOVER_RAM_TOP) {
    PaintFault (CLOVER_FAULT_FAR_HIGH);
  } else if (Far >= CLOVER_RAM_BASE) {
    PaintFault (CLOVER_FAULT_FAR_RAM);
  }

  if ((Ec == CLOVER_EC_DATA_LOWER) || (Ec == CLOVER_EC_DATA_SAME)) {
    PaintFault (CLOVER_FAULT_DATA_ABORT);
  }

  if (((Ec == CLOVER_EC_DATA_LOWER) || (Ec == CLOVER_EC_DATA_SAME) ||
       (Ec == CLOVER_EC_INST_LOWER) || (Ec == CLOVER_EC_INST_SAME)) &&
      (Dfsc >= 0x04) && (Dfsc <= 0x07))
  {
    PaintFault (CLOVER_FAULT_TRANSLATE);
  }

  // Whose code it was.  Without this the index meter names the driver the core was
  // loading, which is not the same claim as the fault happening inside it: a blob can
  // fault inside a copy of a library the core linked, or inside the core itself on its
  // behalf.  Dark here with a fault otherwise fully reported is the reading that says
  // look somewhere other than the module the number names.
  if (mHaveLastImage && (Elr >= mLastImageBase) && (Elr < (mLastImageBase + mLastImageSize))) {
    PaintFault (CLOVER_FAULT_PC_IN_FV);
  }

  for ( ; ;) {
    mFaultSpin++;
  }
}

/**
  Round 18: the same seven rows, read a second way -- where the PC actually is.

  Round 17 answered "did it fault", and the answer was no: the handler mark lit and every
  fault row stayed dark, so the queue is stuck in a loop rather than in an abort.  The
  disassembly of the blob that names (ClockDxe, FVMAIN file 38) shows why waiting cannot
  help -- seventeen of its backward branches contain a load and no add or sub, i.e. no
  counter, and they are all of the shape `ldr w?, [x?]; tbz/tbnz w?, #bit, back` -- but it
  cannot say *which* of the three polling functions the core is parked in, because this is
  a DAL/HAL driver whose work goes through device-object function pointers loaded from
  .data, so a static call graph from the entry reaches nineteen of its six hundred and
  sixty-five functions.

  What can say it is an interrupt, and the first design for getting one was wrong in a way
  worth writing down, because it is the reason this layer looks the way it does.  The CPU
  arch protocol's EXCEPT_AARCH64_IRQ slot is not free at APRIORI line 30: ArmGicDxe is line
  31 and its entry ends in `GicCommonInstallAndRegisterInterruptService`, which registers
  its own dispatcher into that slot and, if the registration fails, returns the error and
  never installs EFI_HARDWARE_INTERRUPT_PROTOCOL at all.  Ten blobs wait on that protocol
  and ArmTimerDxe asserts on it, so taking the slot first would not sample the round-17
  boot -- it would be a different boot, hanging somewhere else, and every band on the
  screen would be describing that one instead.

  So the tick is taken one level down instead, where the GIC's own rules work in favour of
  the instrument.  ArmGicDxe keeps a handler per INTID in `GicCommonRegisterInterruptSource`
  and refuses to replace one it already has, so the way in is to remove ArmTimerDxe's
  handler from the timer's source and put this one there.  The notification that does that
  is registered on the timer arch protocol, which ArmTimerDxe installs as the last thing it
  does before unmasking the counter: by the time this callback runs, the timer is armed, the
  GIC keeps its CPU slot and its dispatcher, and the only thing that has changed is who the
  tick is handed to.

  The cost is the one a tick always has.  ArmTimerDxe's handler is what reloads the compare
  and calls the DXE core's timeout notify, so from line 32 on, event timeouts are not
  processed -- which is why this handler re-arms the compare itself, and why the reading is
  only meaningful for the drivers queued behind it.  The clock that hangs is line 38, six
  lines later, and `gBS->Stall` survives because it reads the counter rather than the tick.
  ArmTimerDxe's own band, slot 5, stays lit: the protocol really did appear, and the ladder
  therefore reads like round 17's at a glance, with the difference confined to the borrowed
  rows.

  The handler reads ELR out of the context the vector table left, which is the address the
  spin was sitting at, and paints `(ELR - last image base) >> 12`: a five-bit page index
  inside the module the meter already named, enough to place the PC anywhere in a 128 KiB
  image to 4 KiB.  Two readings, and they are different findings.  A page number says which
  function the loop is in, and the disassembly above already names the polls inside each.
  The white row lit and the arrival row dark says the tick never came, which can only mean
  the spin runs with interrupts masked -- a driver stuck at TPL_HIGH_LEVEL rather than a
  bit that never sets, and a different bug class with a different fix.

  Rows are shared with the fault layer, and the mode is readable rather than assumed: the
  fault layer's first row is red and this one's page bits are yellow, and the fault layer's
  row 14 is cyan where this one's is white.  A fault also wins the rows outright: FaultSeen
  blacks the whole borrowed band before it reports, so a tick that arrived first cannot be
  mistaken for a FAR range, and TickSeen checks mFaultPainted and stays out of the way.
**/
#define CLOVER_TICK_FIRST_BIT  0
#define CLOVER_TICK_BIT_ROWS   12           // entries 0..11 carry a Shift; the rest are marks
#define CLOVER_TICK_OURS       12
#define CLOVER_TICK_ARRIVED    13
#define CLOVER_TICK_OUTSIDE    14
#define CLOVER_TICK_ADDR_MODE  15
#define CLOVER_TICK_WIDTH_FLAG 16            // row 7: twelve rows are a block offset

// The four INTIDs ArmTimerDxe registers, in the order it registers them.  Copied rather
// than read from its header because that header is private to its driver, and because the
// values come from the same PCDs either way: 27 virtual, 26 hyp, 29 secure, 30 non-secure
// physical at ArmPkg.dec's defaults, which no clover .dsc overrides.  Under a GICv5 the
// same four come from the system-register encoding instead, which is what the branch in
// TimerInitialize does; this board is GICv2, so the branch is here only so that a wrong
// reading of it shows up as a dark row rather than as a silent nothing.
#define CLOVER_GICV5_TIMER_HYP_INTID    0x2000001a
#define CLOVER_GICV5_TIMER_VIRT_INTID   0x2000001b
#define CLOVER_GICV5_TIMER_SEC_INTID    0x2000001d
#define CLOVER_GICV5_TIMER_INTID        0x2000001e

//
// The tick's program counter, painted as the bit positions it actually has rather than as
// a row order, because round 18's decode had to count yellow rows from their place in this
// table and a row inserted in the middle would have silently re-weighted every other one.
// `Shift` is the bit of (ELR - last image base) the row carries; 0 means the row is a mark
// and not a bit.
//
// Round 19 adds the seven rows at the top.  Round 18 answered "which 4 KiB page", and the
// answer was page 10 -- a page that holds two counter-free hardware ack polls, three
// HALclkHuayraPLLTemplate ASSERT(0)s, six library asserts and one bare `b .`, so the page
// could not separate an acknowledgement bit that never arrives from an assert that parked
// the CPU in CpuDeadLoop.  Five more bits of the same address can: every site on that page
// is at least 0x1C apart except `0xa348`/`0xa364`, and 32-byte buckets split those too.
//
// The rows come from slots 0..6 (FV2, FVB, the CPU, the vendor fan-in GUID, ArmGicDxe,
// ArmTimerDxe, SmemDxe), which have lit on every photograph since round 14 and are the
// cheapest thing on the panel to give up: the module the hang is in is named by the index
// bands, not by them.  SlotIsLent() is what stops their notifications from painting a cyan
// band over a bit.
//
#define CLOVER_TICK_SHIFT_MIN  5            // the finest bit any row carries

// The two loops `ClockDxe` can park in, by the 32-byte bucket round 19's sample named them
// in, and the register each one polls.  Both come out of the blob's own disassembly rather
// than out of a guess, and both are stable because the blob is extracted from this unit and
// never rebuilt:
//
//   0xab14  `orr w9,w9,#0x1; str w9,[x8]` then `ldr w9,[x8]; tbnz w9,#0,0xab14` -- the
//           Huayra PLL's update handshake: the driver asks for the latch by setting bit 0
//           and waits for hardware to clear it.  The address is in x8, at [record, #0].
//   0xa784  `and w11,w8,#0xfffffffe; str w11,[x10]` then `ldr w9,[x10]; tbz w9,#31,0xa784`
//           -- a disable followed by a wait for the status bit.  The address is in x10, at
//           [record, #8].
//
// Round 19's photograph landed in the first of these, which is why round 20 samples the
// register rather than the PC: the PC is now known to the byte, and the one thing that
// still has no answer is *which* PLL block is refusing to acknowledge.
#define CLOVER_TICK_POLL_UPDATE  (0xab14 >> CLOVER_TICK_SHIFT_MIN)
#define CLOVER_TICK_POLL_STATUS  (0xa784 >> CLOVER_TICK_SHIFT_MIN)

//
// Round 22: the way out of each of those two loops, taken from the same disassembly.
//
// Neither loop has a counter and neither has a deadline, and the one instruction word each
// spends on the branch is all that is left in it, so a bounded retry cannot be written into
// the blob -- it would need a counter to initialise, a decrement, and two branches, and there
// is no executable range in `ClockDxe.efi` this file has been able to prove safe to write
// into (its PE section table does not parse into a trustworthy code cave).  So the bound
// lives here instead, in the tick handler that already knows how to find these two loops:
// count the ticks that come while the program counter is parked in one of them, and once
// that count passes the limit, aim the return from the interrupt at the instruction the
// loop would have fallen through to had hardware ever answered.
//
// That is only legal because of how the vector table leaves.  `ExceptionSupport.S` builds an
// `EFI_SYSTEM_CONTEXT_AARCH64` on the stack, points the handler at it, and *after* the
// handler returns reloads the pair it stored first (`ldp x29, x30, [x28]`) and writes it
// back with `msr elr_el1, x29` before the `eret`.  The saved link register is therefore read
// from memory that the handler is allowed to change, which makes `Context->ELR` a supported
// way to retarget an interrupted instruction -- not a hack against the ABI.  Everything else
// about the resumed context is untouched: the same x8, x9, x10 and x30 the loop was holding,
// so falling through looks exactly like a latch that finally completed.
//
// The four addresses below the loop entry are matched to the byte, not to the bucket,
// because a 32-byte bucket also contains the loop's own exit: 0xa784's bucket runs through
// 0xa79f, which is where the code that was waited for lives.
//
#define CLOVER_TICK_UPDATE_LDR   0xab14  // `ldr w9, [x8]`  -- the update handshake's read
#define CLOVER_TICK_UPDATE_TBNZ  0xab18  // `tbnz w9,#0,0xab14`
#define CLOVER_TICK_UPDATE_EXIT  0xab1c  // `ret`, reached when bit 0 clears
#define CLOVER_TICK_STATUS_LDR   0xa784  // `ldr w9, [x10]` -- the status wait's read
#define CLOVER_TICK_STATUS_TBZ   0xa788  // `tbz w9,#31,0xa784`
#define CLOVER_TICK_STATUS_EXIT  0xa78c  // the first instruction after the wait

// One millisecond per tick, so two hundred of them is a fifth of a second spent in a loop
// whose hardware answer, if it were coming, would have come within tens of microseconds --
// round 18 measured this latch as never arriving at all.  Twenty times slower than any real
// latch keeps the instrument from cutting a legitimate wait short; two hundred ms per bad
// clock keeps the whole screen from taking minutes if every one of this driver's records
// fails the same way.
#define CLOVER_TICK_PARK_LIMIT   200

// In address mode the same twelve rows carry bits 16..27 of the polled register: 64 KiB
// granularity, which is exactly the resolution that separates this SoC's clock controllers
// (GCC 0x0010_0000, CAM 0x00AA_C000, VIDEO 0x00AB_0000, MDSS 0x00AE_0000, Turing 0x01C4_0000
// -- 0x10, 0xaa, 0xab, 0xae, 0x1c4), and 256 MiB of reach, which covers every register row
// in MemoryMapLib.c but the GICr window nobody polls a clock bit in.  An address that does
// not fit is not sampled at all: the rows stay a PC sample and the arrival row stays cyan,
// so a saturated reading is indistinguishable from round 19's rather than silently wrong.
#define CLOVER_TICK_ADDR_SHIFT_MIN  16

// Round 20 was read, and its twelve bits decoded to 0x0C8C0000 -- not a guess and not a
// range this file invented, but a node in this tablet's own device tree:
// `clock-controller@c8c0000 { compatible = "qcom,mmcc-sdm660"; reg = <0xc8c0000 0x40000>; }`
// in Resources/DTBs/clover.dts, the MMSS Multimedia Clock Controller, whose consumers are
// mdss_mdp, the DSI and DP controllers, venus, the camera front end and the MMSS SMMU.
// The blob carries no such literal (its DALSYS device table stops at MMSS base
// 0x0C800000 + 0x4000), which is why only the device could answer this.
//
// So round 21 keeps the same twelve bands and reads them 64 KiB narrower: bits 15..4, a
// 16-byte bucket inside the block, which is where MMCC's RCGR triples live (a branch's
// CLK_SRC, CLK_CFG and CLK_ENABLE sit 4 bytes apart, and the GDSCs the DT names at
// 0xc8ce020 sit further up).  The narrow reading is taken only while the high bits still
// say MMCC; if a future hang polls another block the rows fall back to round 20's wide
// reading and the width flag below says which one a photograph is holding.
#define CLOVER_TICK_BLOCK_MMCC     0xC8C      // 0x0C8C0000 >> 16, from the device tree
#define CLOVER_TICK_REG_SHIFT_MIN  4          // the narrow reading's finest bit

//
// Which of the two polls the sample came from, because the bit each one waits on is the
// other one's opposite: the update poll at 0xab14 spins while bit 0 stays set, and the
// status poll at 0xa784 spins while bit 31 stays clear.  Round 21 used that to ask whether
// the block answers at all -- both loops load into w9, so the value sampled is already in
// the interrupted context and no second MMIO read, which would have to be justified all
// over again, was needed.  Round 22 keeps the same register for a different reason: the
// watchdog only cuts a loop short while the tested bit still says "keep waiting", so an
// interrupt that lands on the iteration about to fall through naturally is left alone.
//
#define CLOVER_TICK_KIND_NONE    0
#define CLOVER_TICK_KIND_UPDATE  1
#define CLOVER_TICK_KIND_STATUS  2

STATIC CONST struct {
  UINTN    Row;
  UINT32   Argb;
  UINTN    Shift;
  CHAR8    *Name;
} mTickBits[] = {
  {  0, CLOVER_COLOR_YELLOW, 11, "tick PC, bit 11 (the page's upper half)"          },
  {  1, CLOVER_COLOR_YELLOW, 10, "tick PC, bit 10"                                  },
  {  2, CLOVER_COLOR_YELLOW,  9, "tick PC, bit 9"                                   },
  {  3, CLOVER_COLOR_YELLOW,  8, "tick PC, bit 8"                                   },
  {  4, CLOVER_COLOR_YELLOW,  7, "tick PC, bit 7"                                   },
  {  5, CLOVER_COLOR_YELLOW,  6, "tick PC, bit 6"                                   },
  {  6, CLOVER_COLOR_YELLOW,  5, "tick PC, bit 5 (a 32-byte bucket)"                },
  {  9, CLOVER_COLOR_YELLOW, 16, "tick PC page, bit 4 (the 64 KiB half of the image)" },
  { 10, CLOVER_COLOR_YELLOW, 15, "tick PC page, bit 3"                              },
  { 11, CLOVER_COLOR_YELLOW, 14, "tick PC page, bit 2"                              },
  { 12, CLOVER_COLOR_YELLOW, 13, "tick PC page, bit 1"                              },
  { 13, CLOVER_COLOR_YELLOW, 12, "tick PC page, bit 0"                              },
  { 14, CLOVER_COLOR_WHITE,   0, "the timer's GIC source is ours"                   },
  { 15, CLOVER_COLOR_CYAN,    0, "a tick arrived, with its PC inside that image"    },
  { 15, CLOVER_COLOR_RED,     0, "a tick arrived, with its PC outside that image"   },
  { 15, CLOVER_COLOR_YELLOW,  0, "the twelve rows are the polled register, not the PC" },
  //
  // Round 21's width flag, kept after the twelve bit rows rather than in their ladder order
  // because the paint loop addresses bit rows by index -- entries 0..11 are the twelve bits
  // in all three tables, and anything inserted among them would misalign the address tables
  // that share that indexing.  Its row is ChipInfo (+0x300000), one of the slots the index
  // meter makes redundant.
  //
  // Round 21's other flag, on the clock protocol's row (+0x340000), is gone, and that is a
  // reading rather than a loss: round 21's photograph answered its question (yellow -- the
  // block drives real data, so nothing is missing on the bus side), and round 22 asks a
  // question only that row can answer.  The slot is being handed back so that when
  // `ClockDxe` finally reaches the end of its entry point, the protocol it installs paints
  // the band itself.  `SlotIsLent` is a scan of this table, so deleting the two entries is
  // what un-borrows the row; no flag in the notify path is needed.
  //
  {  7, CLOVER_COLOR_YELLOW,  0, "the twelve rows are a 16-byte offset inside MMCC" }
};

//
// The same twelve bands read as an address.  Row 9 is the sampled bit's least significant
// end here, where in the table above it was the page's most significant one, because the
// rows are painted from these constants and never from their order.
//
STATIC CONST struct {
  UINTN    Row;
  UINTN    Shift;
  CHAR8    *Name;
} mTickAddrBits[] = {
  {  0, 27, "polled register, bit 27 (the 64 MiB quarter of the address space)"      },
  {  1, 26, "polled register, bit 26"                                                },
  {  2, 25, "polled register, bit 25"                                                },
  {  3, 24, "polled register, bit 24"                                                },
  {  4, 23, "polled register, bit 23"                                                },
  {  5, 22, "polled register, bit 22"                                                },
  {  6, 21, "polled register, bit 21"                                                },
  {  9, 16, "polled register, bit 16 (the block's low 64 KiB)"                       },
  { 10, 17, "polled register, bit 17"                                                },
  { 11, 18, "polled register, bit 18"                                                },
  { 12, 19, "polled register, bit 19"                                                },
  { 13, 20, "polled register, bit 20"                                                }
};

//
// The same twelve bands again, this time as the offset inside the block -- bits 15..4, most
// significant at the top of the ladder, which is the order the reader's own bit table
// prints and the reason rows 9..13 run downwards here where the wide table above runs up.
//
STATIC CONST struct {
  UINTN    Row;
  UINTN    Shift;
  CHAR8    *Name;
} mTickRegBits[] = {
  {  0, 15, "register offset, bit 15"                                                },
  {  1, 14, "register offset, bit 14"                                                },
  {  2, 13, "register offset, bit 13"                                                },
  {  3, 12, "register offset, bit 12"                                                },
  {  4, 11, "register offset, bit 11"                                                },
  {  5, 10, "register offset, bit 10"                                                },
  {  6,  9, "register offset, bit 9"                                                 },
  {  9,  8, "register offset, bit 8"                                                 },
  { 10,  7, "register offset, bit 7"                                                 },
  { 11,  6, "register offset, bit 6"                                                 },
  { 12,  5, "register offset, bit 5"                                                 },
  { 13,  4, "register offset, bit 4 (a 16-byte bucket)"                              }
};

STATIC BOOLEAN                             mTickInstalled;
STATIC BOOLEAN                             mTickArrived;
STATIC BOOLEAN                             mTickOutsideShown;
STATIC UINTN                               mTickBucketShown;
STATIC UINTN                               mTickRegShown;
STATIC BOOLEAN                             mTickAddressShown;
STATIC UINT32                              mTickArrivedShown;
STATIC UINT32                              mTickShownMask;
STATIC UINTN                               mTickWidthShown;   // row 7, as an offset or not
STATIC EFI_HARDWARE_INTERRUPT_PROTOCOL     *mInterrupt;
STATIC UINT64                              mTickTicks;
STATIC UINTN                               mTickParkKind;     // which loop mTickParkCount is
STATIC UINTN                               mTickParkCount;    // ticks taken inside it
STATIC EFI_EVENT                           mTickEvent;
STATIC VOID                                *mTickRegistration;

/**
  Whether a slot row has been lent to one of the report layers.

  Rows 0..6 are tick bits from round 19 and rows 9..15 are the fault and tick rows, so a
  protocol appearing in one of them would otherwise recolour a band a report owns.  The
  notification itself is never skipped -- the registration has to be drained or later
  instances of that protocol go unseen -- only its paint is.

  A scan of the two tables rather than a flag in mSlots, because the tables are the things
  that borrow and they have to stay the single source of truth for who owns a row.
**/
STATIC
BOOLEAN
SlotIsLent (
  IN UINTN  Index
  )
{
  UINTN  Entry;

  for (Entry = 0; Entry < ARRAY_SIZE (mFaultBits); Entry++) {
    if (mFaultBits[Entry].Row == Index) {
      return TRUE;
    }
  }

  for (Entry = 0; Entry < ARRAY_SIZE (mTickBits); Entry++) {
    if (mTickBits[Entry].Row == Index) {
      return TRUE;
    }
  }

  return FALSE;
}

/**
  Paint one tick row in a given colour.

  Black is as important as the report colours: the sampled value is repainted whenever the
  PC's 32-byte bucket changes, and a bit that an earlier sample set and this one clears has
  to be erased.  Without the erase the bands end up the union of every address the loop
  passed through, which on a page holding twelve candidates is not a reading at all.
**/
STATIC
VOID
PaintTickAs (
  IN UINTN   Index,
  IN UINT32  Argb
  )
{
  CloverCheckpointBar (mSlots[mTickBits[Index].Row].Offset, Argb);
}

/**
  Paint one tick row in the colour its table entry names.
**/
STATIC
VOID
PaintTick (
  IN UINTN  Index
  )
{
  PaintTickAs (Index, mTickBits[Index].Argb);
}

/**
  The timer-interrupt callback: one sample of where the core is stuck, and, from round 22,
  the only clock in this firmware that can say a vendor loop has waited long enough.

  Returns, unlike FaultSeen.  It has to: the instruction the tick interrupted is not
  broken, it is just not done, and ERET is the only way to keep the loop running long
  enough to sample it again.  Nothing is allocated, no boot service is called and no
  protocol is looked up, because this runs at whatever level the vector table raised, in
  the middle of a dispatch loop that is not expecting anything -- and the compare write is
  what keeps the instrument alive: this handler has replaced the one that used to reload
  the timer, so without it there is exactly one sample and then silence.

  It writes one thing: `Context->ELR`, and only when the same unbounded poll has been
  sampled CLOVER_TICK_PARK_LIMIT times in a row.  That is not a side effect of the
  instrument -- the frame this handler is handed is the frame the vector table returns
  from, which is what makes an interrupt able to retarget the interrupted thread at all.
**/
STATIC
VOID
EFIAPI
TickSeen (
  IN HARDWARE_INTERRUPT_SOURCE  Source,
  IN EFI_SYSTEM_CONTEXT         SystemContext
  )
{
  EFI_SYSTEM_CONTEXT_AARCH64  *Context;
  UINT64                      Elr;
  UINTN                       Delta;
  UINTN                       Bucket;
  UINTN                       Entry;
  UINTN                       Reg;
  UINTN                       Value;
  UINTN                       Shift;
  UINTN                       Kind;
  UINTN                       BailTo;
  UINT32                      Word;
  UINT32                      Argb;
  BOOLEAN                     AddressMode;
  BOOLEAN                     Narrow;
  BOOLEAN                     Waiting;

  // End of interrupt first, the way ArmTimerDxe does it, so a repaint of a 128 KiB band
  // cannot make the next tick be missed, and the timer is re-armed whether or not this
  // sample is worth painting: leaving it disarmed on the fault path would turn one tick
  // into the last interrupt this machine ever took.
  if (mInterrupt != NULL) {
    mInterrupt->EndOfInterrupt (mInterrupt, Source);
  }

  ArmGenericTimerSetCompareVal (ArmGenericTimerGetSystemCount () + mTickTicks);
  ArmGenericTimerReenableTimer ();

  if (mFaultPainted) {
    return;
  }

  Context = SystemContext.SystemContextAArch64;
  if ((Context == NULL) || !mHaveLastImage) {
    return;
  }

  Elr = Context->ELR;
  if ((Elr < mLastImageBase) || (Elr >= (mLastImageBase + mLastImageSize))) {
    // The loop is not in the module the index names.  That is a finding, not a failure:
    // a blob can spin inside a library the core linked into it, and the index meter has
    // no way to tell those apart on its own.  Latched for the same reason the arrival row
    // is: this band says the same thing every time it is written.
    if (!mTickOutsideShown) {
      mTickOutsideShown = TRUE;
      mTickArrivedShown = CLOVER_COLOR_RED;
      PaintTick (CLOVER_TICK_OUTSIDE);
    }

    return;
  }

  // The arrival row is painted whenever its meaning changes, which round 20 made more often
  // than once: a tick that came is a fact that does not change, but the same band now also
  // says *which* twelve bits the rows above are holding.
  mTickArrived      = TRUE;
  Delta             = (UINTN)(Elr - mLastImageBase);
  Bucket            = Delta >> CLOVER_TICK_SHIFT_MIN;

  /*
    Rounds 20 and 21.  Round 19's photograph put the PC at 0xab14, the Huayra PLL's update
    handshake -- set bit 0 of a register, wait for hardware to clear it, no counter and no
    timeout -- so the only thing left was the register itself, which is x8 there and x10 in
    the other parkable poll at 0xa784, both live across a two-instruction loop and both
    loaded from the clock record at run time.  Round 20's photograph answered that: bits
    27..16 decoded to 0x0C8C0000, which is this tablet's own `clock-controller@c8c0000`,
    compatible "qcom,mmcc-sdm660" -- the MMSS Multimedia Clock Controller, and no literal
    anywhere near it exists in the blob.  Round 21 narrows the same twelve bands to bits
    15..4 of that register, a 16-byte bucket, which is the scale MMCC's RCGR triples and
    its GDSCs are laid out on, and adds the one fact an offset cannot give by itself:
    whether the word the loop is testing is a value at all.  Both polls load into w9, so
    the interrupted context already holds it and no second MMIO read is needed to ask.
    Round 22 reads that same word for a different purpose -- to be sure it is not cutting
    a wait short on the iteration where hardware had finally answered.
  */
  Reg  = 0;
  Word = 0;
  Kind = CLOVER_TICK_KIND_NONE;
  if (Bucket == CLOVER_TICK_POLL_UPDATE) {
    Reg  = (UINTN)Context->X8;
    Word = (UINT32)Context->X9;
    Kind = CLOVER_TICK_KIND_UPDATE;
  } else if (Bucket == CLOVER_TICK_POLL_STATUS) {
    Reg  = (UINTN)Context->X10;
    Word = (UINT32)Context->X9;
    Kind = CLOVER_TICK_KIND_STATUS;
  }

  /*
    Round 22: the bound the blob does not have.

    The two loops above wait on a hardware acknowledgement that this unit has never, in
    nineteen photographs, been seen to give.  A third of the panel is therefore spent
    deciding whether the boot can get past `ClockDxe` at all, and the only way to find out
    without rewriting a vendor binary is to stop the wait from the outside.  The tick
    handler is already inside this machine's interrupt path and already recognises these
    two loops to the byte, so it counts how many milliseconds it has been sitting in one of
    them and, past the limit, aims the interrupt return at that loop's own exit.

    Two things make this safe rather than merely creative.  The exit path re-reads the saved
    link register from the frame this handler is handed, so `Context->ELR` is the supported
    way to change where an interrupt returns to; and the cut happens only while the tested
    bit still asks for another iteration, so a sample that lands on the pass that was about
    to fall through on its own leaves it alone.

    What it does *not* do is fix the clock.  The RCGR's CMD_REG bit 0 is left set, the latch
    never completes, and whatever the caller configures next is configured against a
    generator that is still in the state the blob found it in.  That is the price of this
    round, and it is paid on purpose: the question is whether the dispatch loop is starved
    by this one handshake or by something behind it, and no reading of the panel will answer
    that while the CPU is parked here.
  */
  BailTo  = 0;
  Waiting = FALSE;
  if (Kind == CLOVER_TICK_KIND_UPDATE) {
    if ((Delta == CLOVER_TICK_UPDATE_LDR) || (Delta == CLOVER_TICK_UPDATE_TBNZ)) {
      BailTo  = CLOVER_TICK_UPDATE_EXIT;
      Waiting = (Word & 0x00000001u) != 0;
    }
  } else if (Kind == CLOVER_TICK_KIND_STATUS) {
    if ((Delta == CLOVER_TICK_STATUS_LDR) || (Delta == CLOVER_TICK_STATUS_TBZ)) {
      BailTo  = CLOVER_TICK_STATUS_EXIT;
      Waiting = (Word & 0x80000000u) == 0;
    }
  }

  if (Waiting && (Kind == mTickParkKind)) {
    mTickParkCount++;
  } else {
    mTickParkKind  = Kind;
    mTickParkCount = Waiting ? 1 : 0;
  }

  if (Waiting && (mTickParkCount >= CLOVER_TICK_PARK_LIMIT)) {
    Context->ELR   = mLastImageBase + BailTo;
    mTickParkCount = 0;
  }

  // Only a sample that knows which register a poll is waiting on can claim address mode.
  // Round 20 did not check this, and its reading was fine only by luck of where the PC
  // happened to sit: a tick anywhere else on the page left Reg at 0, and 0 >> 16 is well
  // inside the twelve rows' reach, so the panel would have painted all twelve bands dark
  // under a yellow "this is an address" label and the reader would have decoded a polled
  // register of 0x00000000 -- an address that means nothing, reported as if it did.
  AddressMode = (Kind != CLOVER_TICK_KIND_NONE) &&
                ((Reg >> CLOVER_TICK_ADDR_SHIFT_MIN) < ((UINTN)1 << CLOVER_TICK_BIT_ROWS));

  // Narrow only while the block is still the one round 20 named.  An offset means nothing
  // for a register that has moved, so a photograph must never be read as MMCC + offset
  // when the high bits say otherwise; it falls back to the wide reading instead, and the
  // width flag below tells the two apart.
  Narrow = AddressMode &&
           ((Reg >> CLOVER_TICK_ADDR_SHIFT_MIN) == CLOVER_TICK_BLOCK_MMCC);

  Argb = AddressMode ? CLOVER_COLOR_YELLOW : CLOVER_COLOR_CYAN;
  if (mTickArrivedShown != Argb) {
    mTickArrivedShown = Argb;
    PaintTick (AddressMode ? CLOVER_TICK_ADDR_MODE : CLOVER_TICK_ARRIVED);
  }

  // The width flag is the last thing this handler paints on a borrowed row, and only that
  // one row: round 21's second flag, which sat on the clock protocol's band, has been given
  // back so that a driver that gets as far as installing its protocol says so itself.
  if (Narrow != (mTickWidthShown != 0)) {
    mTickWidthShown = Narrow ? 1u : 0u;
    PaintTickAs (CLOVER_TICK_WIDTH_FLAG, Narrow ? CLOVER_COLOR_YELLOW : CLOVER_COLOR_BLACK);
  }

  if (AddressMode) {
    if (mTickAddressShown && (Reg == mTickRegShown)) {
      return;
    }

    mTickRegShown = Reg;
  } else {
    if (!mTickAddressShown && (Bucket == mTickBucketShown)) {
      return;
    }

    mTickBucketShown = Bucket;
  }

  mTickAddressShown = AddressMode;

  // Erase the bits the previous sample set before painting this one, so the bands are the
  // newest address and not the union of everything the loop has walked through.  This is
  // load-bearing in a way round 19 did not need: the three modes put different weights on
  // the same twelve bands, so a mode switch with no erase paints one reading under
  // another's label.
  for (Entry = CLOVER_TICK_FIRST_BIT; Entry < CLOVER_TICK_BIT_ROWS; Entry++) {
    if (((mTickShownMask >> Entry) & 1) != 0) {
      PaintTickAs (Entry, CLOVER_COLOR_BLACK);
    }
  }

  mTickShownMask = 0;

  Value = AddressMode ? Reg : Delta;

  for (Entry = CLOVER_TICK_FIRST_BIT; Entry < CLOVER_TICK_BIT_ROWS; Entry++) {
    // The three tables list the same rows in the same order, so one index addresses all of
    // them; the colour always comes from mTickBits, which is the only one that has any.
    if (Narrow) {
      Shift = mTickRegBits[Entry].Shift;
    } else if (AddressMode) {
      Shift = mTickAddrBits[Entry].Shift;
    } else {
      Shift = mTickBits[Entry].Shift;
    }

    if (((Value >> Shift) & 1) != 0) {
      PaintTick (Entry);
      mTickShownMask |= (UINT32)(1u << Entry);
    }
  }
}

/**
  ArmCpuDxe has appeared, so the exception slot can be taken.

  This runs at TPL_CALLBACK from a protocol notification, which is the first moment the
  CPU protocol exists: this driver is APRIORI line 24 and the CPU driver is line 30, so
  the protocol is not there at entry and the drain at entry cannot find it either.  The
  registration is done once and the white mark is painted only on success, because the
  difference between "no fault happened" and "nobody could have reported one" is the
  whole value of the seven rows above.
**/
STATIC
VOID
EFIAPI
CpuAppeared (
  IN EFI_EVENT  Event,
  IN VOID       *Context
  )
{
  EFI_STATUS              Status;
  EFI_CPU_ARCH_PROTOCOL   *Cpu;

  if (mHandlerInstalled) {
    return;
  }

  // Consume the registration either way, so a callback that keeps being queued cannot
  // paint the ladder again behind this one.
  DrainAndReport (&gEfiCpuArchProtocolGuid, mCpuRegistration);

  Cpu    = NULL;
  Status = gBS->LocateProtocol (&gEfiCpuArchProtocolGuid, NULL, (VOID **)&Cpu);
  if (EFI_ERROR (Status) || (Cpu == NULL) || (Cpu->RegisterInterruptHandler == NULL)) {
    return;
  }

  Status = Cpu->RegisterInterruptHandler (Cpu, EXCEPT_AARCH64_SYNCHRONOUS_EXCEPTIONS, FaultSeen);
  if (EFI_ERROR (Status)) {
    // EFI_ALREADY_STARTED is the likely one: Mu installs one handler per type and will
    // not say who owns the slot.  A dark mark with everything else lit is that case, and
    // it is a fact about this build worth having.
    return;
  }

  mHandlerInstalled = TRUE;
  PaintMark (CLOVER_MARK_HANDLER);
}

/**
  ArmTimerDxe has appeared, so its tick can be re-pointed at this driver.

  The registration this fires from is the timer arch protocol, which ArmTimerDxe installs
  near the end of its entry and unmasking the counter after -- so by the time this runs,
  the four timer INTIDs are registered in the GIC's table, the compare value is loaded and
  the counter is counting.  That ordering is the whole design: it is why the instrument
  takes a source rather than the CPU exception slot, and why nothing earlier than line 32
  has to be re-explained in the photograph.

  Stealing a source is two calls, because ArmGicDxe will not overwrite a handler it already
  has: `RegisterInterruptSource (Interrupt, Id, NULL)` removes ArmTimerDxe's and disables
  the line, and the same call with TickSeen installs ours and re-enables it.  An INTID that
  returns EFI_INVALID_PARAMETER to the first call had no handler, which means it was not
  the timer's on this board, and it is left exactly as it was rather than enabled by
  accident.
**/
STATIC
VOID
EFIAPI
TimerAppeared (
  IN EFI_EVENT  Event,
  IN VOID       *Context
  )
{
  EFI_STATUS                        Status;
  EFI_HARDWARE_INTERRUPT_PROTOCOL   *Interrupt;
  UINT32                            Ids[4];
  UINT64                            Freq;
  UINTN                             Index;

  if (mTickInstalled) {
    return;
  }

  // Consume the registration either way, so a callback that keeps being queued cannot
  // take the source back a second time behind this one.
  DrainAndReport (&gEfiTimerArchProtocolGuid, mTickRegistration);

  Interrupt = NULL;
  Status    = gBS->LocateProtocol (&gHardwareInterruptProtocolGuid, NULL, (VOID **)&Interrupt);
  if (EFI_ERROR (Status) || (Interrupt == NULL) || (Interrupt->RegisterInterruptSource == NULL)) {
    // Without the GIC's protocol there is nobody to take the source from, and the white
    // row staying dark is the honest record of that.  It is also a reading: ArmGicDxe is
    // APRIORI line 31 and the timer is 32, so a timer that appeared with no interrupt
    // controller behind it means the queue got here by a route the ladder does not show.
    return;
  }

  if (ArmHasGicV5SystemRegisters ()) {
    Ids[0] = CLOVER_GICV5_TIMER_VIRT_INTID;
    Ids[1] = CLOVER_GICV5_TIMER_HYP_INTID;
    Ids[2] = CLOVER_GICV5_TIMER_SEC_INTID;
    Ids[3] = CLOVER_GICV5_TIMER_INTID;
  } else {
    Ids[0] = PcdGet32 (PcdArmArchTimerVirtIntrNum);
    Ids[1] = PcdGet32 (PcdArmArchTimerHypIntrNum);
    Ids[2] = PcdGet32 (PcdArmArchTimerSecIntrNum);
    Ids[3] = PcdGet32 (PcdArmArchTimerIntrNum);
  }

  for (Index = 0; Index < ARRAY_SIZE (Ids); Index++) {
    if (Ids[Index] == 0) {
      continue;
    }

    if (EFI_ERROR (Interrupt->RegisterInterruptSource (Interrupt, Ids[Index], NULL))) {
      continue;
    }

    if (!EFI_ERROR (Interrupt->RegisterInterruptSource (Interrupt, Ids[Index], TickSeen))) {
      mTickInstalled = TRUE;
    }
  }

  if (!mTickInstalled) {
    return;
  }

  // One millisecond of counter, which is a sample every thousand ticks of a megahertz clock
  // and fast enough that a bounded loop is caught in the same page over and over.  The
  // frequency comes from the same library instance ArmTimerDxe uses, so the compare values
  // written here and the counter it reads cannot disagree.
  mInterrupt  = Interrupt;
  Freq        = ArmGenericTimerGetTimerFreq ();
  mTickTicks  = (Freq != 0) ? (Freq / 1000) : 20000;
  PaintTick (CLOVER_TICK_OURS);
}

EFI_STATUS
EFIAPI
CheckpointDxeEntry (
  IN EFI_HANDLE        ImageHandle,
  IN EFI_SYSTEM_TABLE  *SystemTable
  )
{
  UINTN  Index;

  CloverCheckpointBar (0x000C0000, CLOVER_COLOR_MAGENTA);

  // Every slot, every bit band and every mark starts dark.  This pass has to precede
  // the registrations below, and it does: no notification can run until this entry
  // point returns, because the level being restored has to drop below the event's
  // first.
  for (Index = 0; Index < ARRAY_SIZE (mSlots); Index++) {
    CloverCheckpointBar (mSlots[Index].Offset, CLOVER_COLOR_BLACK);
  }

  for (Index = 0; Index < ARRAY_SIZE (mBits); Index++) {
    CloverCheckpointBar (mBits[Index].Offset, CLOVER_COLOR_BLACK);
    mBitsShown[Index] = 0;
  }

  for (Index = 0; Index < ARRAY_SIZE (mMarks); Index++) {
    CloverCheckpointBar (mMarks[Index].Offset, CLOVER_COLOR_BLACK);
    mMarksShown[Index] = 0;
  }

  for (Index = 0; Index < ARRAY_SIZE (mSlots); Index++) {
    if (EFI_ERROR (gBS->CreateEvent (
                         EVT_NOTIFY_SIGNAL,
                         TPL_CALLBACK,
                         SlotAppeared,
                         (VOID *)Index,
                         &mEvents[Index]
                         ))) {
      continue;
    }

    if (EFI_ERROR (gBS->RegisterProtocolNotify (
                         mSlots[Index].Guid,
                         mEvents[Index],
                         &mRegistrations[Index]
                         ))) {
      continue;
    }

    // The round-13 fix: ask the registration what it can already see.  A row that a report
    // layer borrowed is still drained -- the drain is what makes later instances visible --
    // but the band belongs to the report, not to the protocol.
    if (DrainAndReport (mSlots[Index].Guid, mRegistrations[Index]) && !SlotIsLent (Index)) {
      CloverCheckpointBar (mSlots[Index].Offset, mSlots[Index].Argb);
    }
  }

  FindOwnFile (ImageHandle);
  EnumerateVolumeFiles ();

  // The first of the three marks, and the one the other two are read against: white
  // here means the list under the index bands is the volume this driver lives in, so
  // a number taken from it is a row of fv-order.py.
  if (mSelfIsListed) {
    PaintMark (CLOVER_MARK_OWN_FILE);
  }

  // Then the load meter.  With no files enumerated there is nothing to match an image
  // against, so the bands would sit at zero no matter what loaded, and registering the
  // callback would buy nothing.  The drain throws away every image loaded up to this
  // point: the first number on the screen is the first driver dispatched after
  // CheckpointDxe, which is the one the ladder needs.
  if (mFvFileCount > 0) {
    if (!EFI_ERROR (gBS->CreateEvent (
                          EVT_NOTIFY_SIGNAL,
                          TPL_NOTIFY,
                          ImageLoaded,
                          NULL,
                          &mImageEvent
                          ))) {
      if (!EFI_ERROR (gBS->RegisterProtocolNotify (
                           &gEfiLoadedImageProtocolGuid,
                           mImageEvent,
                           &mImageRegistration
                           ))) {
        DrainAndReport (&gEfiLoadedImageProtocolGuid, mImageRegistration);
      }
    }
  }

  // Then the exception layer, which is a registration rather than an instrument: the CPU
  // arch protocol does not exist yet at APRIORI line 24, and ArmCpuDxe is line 30, so
  // there is nothing to register with until it appears.  Asking at entry would be the
  // round-13 mistake in a new place -- a LocateProtocol that fails reads as a boot with
  // no faults, when it is a boot whose fault nobody could report.  The notify is drained
  // at once as well, in case this driver is ever dispatched after the CPU.
  if (!EFI_ERROR (gBS->CreateEvent (
                        EVT_NOTIFY_SIGNAL,
                        TPL_CALLBACK,
                        CpuAppeared,
                        NULL,
                        &mCpuEvent
                        ))) {
    if (!EFI_ERROR (gBS->RegisterProtocolNotify (
                          &gEfiCpuArchProtocolGuid,
                          mCpuEvent,
                          &mCpuRegistration
                          ))) {
      CpuAppeared (mCpuEvent, NULL);
    }
  }

  // And the sampler, which waits on the timer rather than on the CPU: the tick has to be
  // taken from a driver that has already finished arming the counter, and ArmTimerDxe is
  // APRIORI line 32.  Drained at entry too, in case the queue ever reaches the timer before
  // this driver -- on a build where the timer protocol is already installed, the notify
  // would otherwise never run and the white row would lie about a slot nobody took.
  if (!EFI_ERROR (gBS->CreateEvent (
                        EVT_NOTIFY_SIGNAL,
                        TPL_CALLBACK,
                        TimerAppeared,
                        NULL,
                        &mTickEvent
                        ))) {
    if (!EFI_ERROR (gBS->RegisterProtocolNotify (
                          &gEfiTimerArchProtocolGuid,
                          mTickEvent,
                          &mTickRegistration
                          ))) {
      TimerAppeared (mTickEvent, NULL);
    }
  }

  return EFI_SUCCESS;
}
