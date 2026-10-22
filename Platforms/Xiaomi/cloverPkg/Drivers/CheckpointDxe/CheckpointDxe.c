/**
  DXE-dispatch checkpoint for the Xiaomi Mi Pad 4 8" LTE (clover).

  Round 10 read green (+1 MiB, PEI took the memory map) and magenta (+3 MiB, the DXE
  core dispatched an ordinary driver) and no white, which put the stop somewhere in
  DXE dispatch and gave no way to say where.  This driver is now the recorder for the
  rest of the phase: it registers a protocol-notify event per milestone and paints one
  cyan band per protocol that appears, at an offset that identifies it.  Position is
  the message, so a single colour is enough and the bands are unambiguous even when
  several arrive in the same second.

  RegisterProtocolNotify also reports instances that already exist, so a protocol the
  platform produced before this driver was dispatched still paints its band.

  The band positions and what they mean are in Include/Checkpoint.h.  Drawing nothing
  through the UEFI display stack and returning EFI_SUCCESS is the point: a bar here
  cannot be the reason a boot stops.

  @copyright  SPDX-License-Identifier: BSD-2-Clause-Patent
**/

#include <Uefi.h>
#include <Library/UefiDriverEntryPoint.h>
#include <Library/UefiBootServicesTableLib.h>
#include <Protocol/Cpu.h>
#include <Protocol/WatchdogTimer.h>
#include <Protocol/Timer.h>
#include <Protocol/RealTimeClock.h>
#include <Protocol/VariableWrite.h>
#include <Protocol/BlockIo.h>
#include <Protocol/SimpleFileSystem.h>
#include <Protocol/Bds.h>
#include <Protocol/UsbIo.h>
#include <Protocol/GraphicsOutput.h>

#include "../../Include/Checkpoint.h"

//
// In the order the DXE core is expected to reach them.
//
STATIC CONST struct {
  EFI_GUID        *Guid;
  UINT64          Offset;
  CONST CHAR8     *Name;
} mSlots[] = {
  { &gEfiCpuArchProtocolGuid,           0x00140000, "CpuDxe"          },
  { &gEfiWatchdogTimerArchProtocolGuid, 0x00180000, "WatchdogTimer"   },
  { &gEfiTimerArchProtocolGuid,         0x001C0000, "TimerDxe"        },
  { &gEfiRealTimeClockArchProtocolGuid, 0x00200000, "RealTimeClock"   },
  { &gEfiVariableWriteArchProtocolGuid, 0x00240000, "VariableRuntime" },
  { &gEfiBlockIoProtocolGuid,           0x00280000, "BlockIo (eMMC)"  },
  { &gEfiSimpleFileSystemProtocolGuid,  0x002C0000, "Fat volumes"     },
  { &gEfiBdsArchProtocolGuid,           0x00300000, "BdsDxe"          },
  { &gEfiUsbIoProtocolGuid,             0x00340000, "UsbBusDxe"       }
};

STATIC EFI_EVENT  mEvents[ARRAY_SIZE (mSlots)];
STATIC VOID       *mRegistrations[ARRAY_SIZE (mSlots)];

STATIC
VOID
EFIAPI
SlotAppeared (
  IN EFI_EVENT  Event,
  IN VOID       *Context
  )
{
  UINTN  Index = (UINTN)Context;

  CloverCheckpointBar (mSlots[Index].Offset, CLOVER_COLOR_CYAN);
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
