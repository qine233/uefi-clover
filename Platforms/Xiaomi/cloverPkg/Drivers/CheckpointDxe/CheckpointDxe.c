/**
  DXE-dispatch checkpoint for the Xiaomi Mi Pad 4 8" LTE (clover).

  Stage 3 and stage 4 of Platforms/Xiaomi/cloverPkg/Include/Checkpoint.h: the
  magenta bar at +0x00300000 says the DXE core reached an ordinary driver, and the
  white bar at +0x00400000 says a GraphicsOutput protocol appeared, which is the
  vendor DisplayDxe blob coming up.  This driver takes nothing from the platform,
  draws nothing through the UEFI display stack and returns EFI_SUCCESS, so a bar
  here cannot be the reason a boot stops.

  @copyright  SPDX-License-Identifier: BSD-2-Clause-Patent
**/

#include <Uefi.h>
#include <Library/UefiDriverEntryPoint.h>
#include <Library/UefiBootServicesTableLib.h>

#include "../../Include/Checkpoint.h"

STATIC EFI_EVENT  mGopEvent;
STATIC VOID       *mGopRegistration;

STATIC
VOID
EFIAPI
GopAppeared (
  IN EFI_EVENT  Event,
  IN VOID       *Context
  )
{
  CloverCheckpointBar (0x00400000, CLOVER_COLOR_WHITE);
}

EFI_STATUS
EFIAPI
CheckpointDxeEntry (
  IN EFI_HANDLE        ImageHandle,
  IN EFI_SYSTEM_TABLE  *SystemTable
  )
{
  CloverCheckpointBar (0x00300000, CLOVER_COLOR_MAGENTA);

  // Register only.  Signalling the event here would run GopAppeared
  // unconditionally and the white bar would stop meaning anything; the callback
  // fires when the vendor DisplayDxe actually installs a GraphicsOutput.
  if (!EFI_ERROR (gBS->CreateEvent (
                        EVT_NOTIFY_SIGNAL,
                        TPL_CALLBACK,
                        GopAppeared,
                        NULL,
                        &mGopEvent
                        ))) {
    gBS->RegisterProtocolNotify (
           &gEfiGraphicsOutputProtocolGuid,
           mGopEvent,
           &mGopRegistration
           );
  }

  return EFI_SUCCESS;
}
