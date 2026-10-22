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
  encoded in the same 8 MiB of framebuffer.  The seven yellow bands at the bottom
  carry the FVMAIN file index of the last image the DXE core loaded, seven bits wide
  with bit 6 topmost, and the index is looked up against the volume enumerated at
  entry.  Dispatcher.c:456 calls CoreLoadImage the moment a driver reaches the head
  of mScheduledQueue and CoreStartImage only afterwards, so the load names the
  module the loop was working on, and the module that hangs announces itself first.
  For that the notification has to run while the load is still in progress.  An
  event's notification function fires on the first CoreRestoreTpl to a level
  strictly below its NotifyTpl (Event/Tpl.c:120-133), and the notification is
  queued by the interface install itself (Hand/Notify.c:32), whose lock is already
  dropped when the level is restored (Library.c:80).  TPL_NOTIFY is the highest
  level an event may use, so it runs on the very first lowering; a TPL_CALLBACK
  event has to wait for a lowering below CALLBACK, which need not happen between two
  drivers, and the number would name whichever load came after the hang.

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
#include <Protocol/Variable.h>
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
  // lights, that driver ran and returned without installing them.
  { &gEfiVariableWriteArchProtocolGuid,        0x00200000, CLOVER_COLOR_CYAN,  "VariableRuntimeDxe (Depex TRUE)"         },
  { &gEfiVariableArchProtocolGuid,             0x00240000, CLOVER_COLOR_CYAN,  "variable store readable"                 },
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

STATIC EFI_EVENT    mEvents[ARRAY_SIZE (mSlots)];
STATIC VOID         *mRegistrations[ARRAY_SIZE (mSlots)];
STATIC EFI_EVENT    mImageEvent;
STATIC VOID         *mImageRegistration;

//
// The volume as this driver found it: every file GUID of every firmware volume with
// an FV2 instance, in the order GetNextFile walks them, which is physical order and
// therefore the order fv-order.py prints.
//
STATIC EFI_GUID     mFvFiles[CLOVER_FV_FILES];
STATIC UINTN        mFvFileCount;

// What is on the screen right now, so a band is only rewritten when its bit flips.
STATIC UINT8        mBitsShown[CLOVER_INDEX_BITS];

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
  EFI_HANDLE                  Handle;
  UINTN                       Size;
  EFI_LOADED_IMAGE_PROTOCOL   *LoadedImage;
  EFI_GUID                    *File;

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

    PaintIndex (FileIndex (File));
  }
}

/**
  Copy the file GUIDs of every firmware volume into mFvFiles, in volume order, so a
  loaded image's GUID can be turned into a number the photograph can carry.  GetNextFile
  is documented as callable at TPL_NOTIFY and below, and this entry point is not above
  it.  Files the volume does not report -- deleted ones, or ones past the 127 the bit
  field can hold -- simply are not in the list, and the band then reads 0.
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
  UINTN                              Key[4];
  EFI_FV_FILETYPE                    FileType;
  EFI_FV_FILE_ATTRIBUTES             Attributes;
  EFI_GUID                           Name;
  UINTN                              Size;

  Handles     = NULL;
  HandleCount = 0;

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

  for (HandleIndex = 0; HandleIndex < HandleCount; HandleIndex++) {
    Fv = NULL;
    if (EFI_ERROR (gBS->HandleProtocol (Handles[HandleIndex], &gEfiFirmwareVolume2ProtocolGuid, (VOID **)&Fv))) {
      continue;
    }

    // A key bigger than the buffer above would be read out of bounds, and DxeCore's
    // own FV2 instances declare sizeof (UINTN).
    if ((Fv->KeySize == 0) || (Fv->KeySize > sizeof (Key))) {
      continue;
    }

    ZeroMem (Key, sizeof (Key));
    FileType = EFI_FV_FILETYPE_ALL;

    while (mFvFileCount < CLOVER_FV_FILES) {
      if (EFI_ERROR (Fv->GetNextFile (Fv, Key, &FileType, &Name, &Attributes, &Size))) {
        break;
      }

      CopyGuid (&mFvFiles[mFvFileCount], &Name);
      mFvFileCount++;
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

  // Every slot and every bit band starts dark.  This pass has to precede the
  // registrations below, and it does: no notification can run until this entry point
  // returns, because the level being restored has to drop below the event's first.
  for (Index = 0; Index < ARRAY_SIZE (mSlots); Index++) {
    CloverCheckpointBar (mSlots[Index].Offset, CLOVER_COLOR_BLACK);
  }

  for (Index = 0; Index < ARRAY_SIZE (mBits); Index++) {
    CloverCheckpointBar (mBits[Index].Offset, CLOVER_COLOR_BLACK);
    mBitsShown[Index] = 0;
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

  EnumerateVolumeFiles ();

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
