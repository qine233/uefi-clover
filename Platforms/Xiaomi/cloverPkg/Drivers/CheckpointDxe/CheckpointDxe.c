/**
  DXE-dispatch checkpoint for the Xiaomi Mi Pad 4 8" LTE (clover).

  Round 10 read green (+0x40000, PEI took the memory map) and magenta (+0xC0000,
  the DXE core dispatched an ordinary driver) and no white.  Round 11 added nine
  cyan protocol bands and still reported nothing past magenta but three evenly
  spaced cyan, so the stop is inside the DXE dispatch and the ladder was not fine
  enough to say where.

  This driver is the recorder for the rest of the phase: one notify event per
  protocol, one band per protocol that appears, at an offset that identifies it.
  Position is the message, so a colour only has to separate the two families --
  cyan for the EDK II core and its architecture protocols, red for the Qualcomm
  chain the vendor blobs wait on (see Include/Checkpoint.h for how that chain was
  read out of the blobs' depex sections).

  RegisterProtocolNotify also reports instances that already exist, so a protocol
  the platform produced before this driver was dispatched still paints its band.

  The band positions and what they mean are in Include/Checkpoint.h.  Drawing
  nothing through the UEFI display stack and returning EFI_SUCCESS is the point:
  a bar here cannot be the reason a boot stops.

  @copyright  SPDX-License-Identifier: BSD-2-Clause-Patent
**/

#include <Uefi.h>
#include <Library/UefiDriverEntryPoint.h>
#include <Library/UefiBootServicesTableLib.h>
#include <Protocol/Cpu.h>
#include <Protocol/WatchdogTimer.h>
#include <Protocol/Timer.h>
#include <Protocol/RealTimeClock.h>
#include <Protocol/Variable.h>
#include <Protocol/VariableWrite.h>
#include <Protocol/BlockIo.h>
#include <Protocol/SimpleFileSystem.h>
#include <Protocol/Bds.h>
#include <Protocol/UsbIo.h>
#include <Protocol/GraphicsOutput.h>
// Protocol/FirmwareVolume2.h uses the Pi firmware-format types without including
// them, the way every EDK II header does: whoever wants it brings the Pi headers.
#include <Pi/PiFirmwareFile.h>
#include <Pi/PiFirmwareVolume.h>
#include <Protocol/FirmwareVolume2.h>
#include <Protocol/Runtime.h>
#include <Protocol/Security.h>

#include "../../Include/Checkpoint.h"

//
// The four Qualcomm protocols below are named by symbol in the vendor tree's
// .dec files, but no header this package can include declares them, and one of
// them is declared nowhere at all -- it only exists inside the blobs.  Copying
// the values out of the depex expressions is the honest form: these are the bytes
// the dispatch actually waits on, and a dependency on QcomPkg/Include would make
// a bring-up instrument fail to build for a packaging reason.
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

//
// In the order the DXE core is expected to reach them.
//
STATIC CONST struct {
  EFI_GUID   *Guid;
  UINT64     Offset;
  UINT32     Argb;
  CHAR8      *Name;
} mSlots[] = {
  { &gEfiCpuArchProtocolGuid,           0x00140000, CLOVER_COLOR_CYAN, "CpuDxe"          },
  { &gEfiWatchdogTimerArchProtocolGuid, 0x00180000, CLOVER_COLOR_CYAN, "WatchdogTimer"   },
  { &gEfiTimerArchProtocolGuid,         0x001C0000, CLOVER_COLOR_CYAN, "TimerDxe"        },
  { &gEfiRealTimeClockArchProtocolGuid, 0x00200000, CLOVER_COLOR_CYAN, "RealTimeClock"   },
  { &gEfiVariableWriteArchProtocolGuid, 0x00240000, CLOVER_COLOR_CYAN, "VariableRuntime" },
  { &gEfiBlockIoProtocolGuid,           0x00280000, CLOVER_COLOR_CYAN, "BlockIo (eMMC)"  },
  { &gEfiSimpleFileSystemProtocolGuid,  0x002C0000, CLOVER_COLOR_CYAN, "Fat volumes"     },
  { &gEfiBdsArchProtocolGuid,           0x00300000, CLOVER_COLOR_CYAN, "BdsDxe"          },
  { &gEfiUsbIoProtocolGuid,             0x00340000, CLOVER_COLOR_CYAN, "UsbBusDxe"       },

  // The Qualcomm chain, lowest offset first, in the order its depex sections can
  // be satisfied.  If the bands stop here, the vendor side of the FV is the wall.
  { &gEfiFirmwareVolume2ProtocolGuid,   0x00380000, CLOVER_COLOR_RED,  "FV enumeration"  },
  { &gEfiRuntimeArchProtocolGuid,       0x003C0000, CLOVER_COLOR_RED,  "RuntimeDxe"      },
  { &gEfiSecurityArchProtocolGuid,      0x00400000, CLOVER_COLOR_RED,  "SecurityStub"    },
  { &mSmemProtocolGuid,                 0x00440000, CLOVER_COLOR_RED,  "SmemDxe"         },
  { &mVendorFanInGuid,                  0x00480000, CLOVER_COLOR_RED,  "blob fan-in"     },
  { &mChipInfoProtocolGuid,             0x004C0000, CLOVER_COLOR_RED,  "ChipInfoDxe"     },
  { &mClockProtocolGuid,                0x00500000, CLOVER_COLOR_RED,  "ClockDxe"        },
  { &gEfiVariableArchProtocolGuid,      0x00540000, CLOVER_COLOR_RED,  "Variable read"   }
};

STATIC EFI_EVENT  mEvents[ARRAY_SIZE (mSlots) + 1];
STATIC VOID       *mRegistrations[ARRAY_SIZE (mSlots) + 1];

STATIC
VOID
EFIAPI
SlotAppeared (
  IN EFI_EVENT  Event,
  IN VOID       *Context
  )
{
  UINTN  Index = (UINTN)Context;

  CloverCheckpointBar (mSlots[Index].Offset, mSlots[Index].Argb);
}

STATIC
VOID
EFIAPI
GopAppeared (
  IN EFI_EVENT  Event,
  IN VOID       *Context
  )
{
  CloverCheckpointBar (0x00100000, CLOVER_COLOR_WHITE);
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

  // Register only.  Signalling an event here would run its callback
  // unconditionally and the band would stop meaning anything.
  if (!EFI_ERROR (gBS->CreateEvent (
                        EVT_NOTIFY_SIGNAL,
                        TPL_CALLBACK,
                        GopAppeared,
                        NULL,
                        &mEvents[0]
                        ))) {
    gBS->RegisterProtocolNotify (
           &gEfiGraphicsOutputProtocolGuid,
           mEvents[0],
           &mRegistrations[0]
           );
  }

  for (Index = 0; Index < ARRAY_SIZE (mSlots); Index++) {
    if (EFI_ERROR (gBS->CreateEvent (
                         EVT_NOTIFY_SIGNAL,
                         TPL_CALLBACK,
                         SlotAppeared,
                         (VOID *)Index,
                         &mEvents[Index + 1]
                         ))) {
      continue;
    }

    gBS->RegisterProtocolNotify (
           mSlots[Index].Guid,
           mEvents[Index + 1],
           &mRegistrations[Index + 1]
           );
  }

  return EFI_SUCCESS;
}
