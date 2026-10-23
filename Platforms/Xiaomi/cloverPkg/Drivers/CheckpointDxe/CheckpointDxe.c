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
  have run and returned without installing.  A FirmwareVolumeBlock band is added
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

  Cyan is EDK II, red is Qualcomm, white is the display, black is a stage this boot
  did not reach, and yellow is data rather than progress.  Order in the slot table is
  the order the DXE core reaches things, which for the storage drivers is their
  dependency order rather than their order in the volume: PartitionDxe is file 34
  and SdccDxe is 43, and the partitions cannot exist before the eMMC does.

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

// EmbeddedPkg.dec: gHardwareInterruptProtocolGuid, which the timer waits on.
STATIC EFI_GUID  mHardwareInterruptProtocolGuid = {
  0x2890B3EA, 0x053D, 0x1643, { 0xAD, 0x0C, 0xD6, 0x48, 0x08, 0xDA, 0x3F, 0xF1 }
};

//
// Sixteen protocol slots, +0x140000 to +0x500000, each CLOVER_BAR_SIZE long, on the
// 256 KiB pitch inside the 8 MiB BootShim filled.  Round 13 spent twenty-four bands,
// six of which told nothing this time (Runtime, Security, Watchdog and Metronome all
// lit, DiskIo, the file system and collation could only ever follow BlockIo), and the
// index needs seven more.  scripts/check-clover-uefi.py fails the build if any offset
// leaves the filled window or a band overlaps its neighbour.
//
STATIC CONST struct {
  EFI_GUID   *Guid;
  UINT64     Offset;
  UINT32     Argb;
  CHAR8      *Name;
} mSlots[] = {
  // DxeCore publishes both of these before APRIORI runs, so a dark band here is now
  // a real reading rather than the round-13 artifact.
  { &gEfiFirmwareVolume2ProtocolGuid,          0x00140000, CLOVER_COLOR_CYAN,  "FV2: volumes enumerated from HOBs"       },
  { &gEfiFirmwareVolumeBlockProtocolGuid,      0x00180000, CLOVER_COLOR_CYAN,  "FVB: the store a variable driver needs"  },

  { &gEfiCpuArchProtocolGuid,                  0x001C0000, CLOVER_COLOR_CYAN,  "ArmCpuDxe"                               },

  // Both of these belong to VariableRuntimeDxe, file 13, Depex TRUE and listed ahead
  // of MetronomeDxe, which lit in round 13.  If they stay dark while FVB above them
  // lights, that driver ran and returned without installing them.  Round 14 says it
  // did: the write interface and the read interface go together, so one band is enough
  // and the second one now watches a different Depex TRUE driver instead -- the
  // monotonic counter at file 14, which sits in the gap that came out dark.
  { &gEfiVariableWriteArchProtocolGuid,        0x00200000, CLOVER_COLOR_CYAN,  "VariableRuntimeDxe (Depex TRUE)"         },
  { &gEfiMonotonicCounterArchProtocolGuid,     0x00240000, CLOVER_COLOR_CYAN,  "EmbeddedMonotonicCounter, file 14"       },
  { &gEfiRealTimeClockArchProtocolGuid,        0x00280000, CLOVER_COLOR_CYAN,  "RealTimeClock, file 17"                  },

  // The Qualcomm chain, in the order its depex sections can be satisfied.  The
  // fan-in GUID is named by ten blobs and declared by nothing in this tree, so it
  // has to come from one of them.
  { &mVendorFanInGuid,                         0x002C0000, CLOVER_COLOR_RED,   "the GUID ten blobs wait on"              },
  { &mHardwareInterruptProtocolGuid,           0x00300000, CLOVER_COLOR_CYAN,  "ArmGicDxe, file 26"                      },
  { &gEfiTimerArchProtocolGuid,                0x00340000, CLOVER_COLOR_CYAN,  "ArmTimerDxe, file 27"                    },
  { &mChipInfoProtocolGuid,                    0x00380000, CLOVER_COLOR_RED,   "ChipInfoDxe, file 28"                    },
  { &mSmemProtocolGuid,                        0x003C0000, CLOVER_COLOR_RED,   "SmemDxe, file 30: last thing that lit"   },

  // Round 13's first dark producer below the last lit one, and the one that matters
  // downstream: DisplayDxe and SdccDxe both wait on this GUID.
  { &mClockProtocolGuid,                       0x00400000, CLOVER_COLOR_RED,   "ClockDxe, file 38"                       },

  { &gEfiBlockIoProtocolGuid,                  0x00440000, CLOVER_COLOR_CYAN,  "BlockIo: SdccDxe, the eMMC, file 43"     },
  { &gEfiPartitionInfoProtocolGuid,            0x00480000, CLOVER_COLOR_CYAN,  "PartitionDxe: partitions parsed"          },
  { &gEfiGraphicsOutputProtocolGuid,           0x004C0000, CLOVER_COLOR_WHITE, "the display: DisplayDxe or SimpleFbDxe"  },

  // Depex TRUE, so this stays the cleanest single bit of information the ladder
  // holds: lit means the loop finished with something to do, dark with everything
  // above it lit means it stopped on the way.
  { &gEfiBdsArchProtocolGuid,                  0x00500000, CLOVER_COLOR_CYAN,  "BdsDxe, file 64 (Depex TRUE)"            }
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

STATIC CONST struct {
  UINT64   Offset;
  UINT32   Argb;
  CHAR8    *Name;
} mMarks[] = {
  { 0x00700000, CLOVER_COLOR_WHITE, "this drivers own file is in the list"   },
  { 0x00740000, CLOVER_COLOR_CYAN,  "an image was matched against the list"  },
  { 0x00780000, CLOVER_COLOR_RED,   "an image was not in the list"           }
};

STATIC EFI_EVENT    mEvents[ARRAY_SIZE (mSlots)];
STATIC VOID         *mRegistrations[ARRAY_SIZE (mSlots)];
STATIC EFI_EVENT    mImageEvent;
STATIC VOID         *mImageRegistration;

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
  CloverCheckpointBar (mSlots[Index].Offset, mSlots[Index].Argb);
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

    // The round-13 fix: ask the registration what it can already see.
    if (DrainAndReport (mSlots[Index].Guid, mRegistrations[Index])) {
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

  return EFI_SUCCESS;
}
