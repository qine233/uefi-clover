/** @file
  clover: two whole-panel marks that bracket DXE dispatch.

  The red panel proves ABL jumped into BootShim, and the green one proves
  CloverGopDxe installed a GraphicsOutput.  Between those two points sit ninety
  lines of APRIORI, and this board has already been measured stopping in the
  middle of them: with the stock ClockDxe blob the dispatcher loaded file 38
  and never returned from it.  A red screen cannot say whether that is still
  where it stops.

  So each mark repaints the whole panel a solid colour when it is dispatched,
  and the last colour on screen names how far the dispatcher got:

    red      BootShim ran; the dispatcher never reached the top of APRIORI
    magenta  the dispatcher reached the first mark
    yellow   ClockDxe returned -- the second mark sits right after it
    green    the GOP exists, so GraphicsConsoleDxe can start
    menu     stage 1

  The same source builds both modules; CLOVER_LADDER_EARLY picks the colour and
  the INF picks the slot in APRIORI.inc.  Position is the entire message, so the
  two INFs have to stay on either side of ClockDxe.

  Copyright (c) 2026, UniXNU contributors. All rights reserved.
  SPDX-License-Identifier: BSD-2-Clause-Patent
**/

#include <Uefi.h>

#include <Library/BaseMemoryLib.h>
#include <Library/DebugLib.h>
#include <Library/UefiBootServicesTableLib.h>

//
// The window uefiplat.cfg calls "Display Reserved", already being scanned by
// the display pipeline ABL started.
//
#define CLOVER_FRAMEBUFFER_BASE    ((UINTN)0x9D400000)
#define CLOVER_PANEL_WIDTH         1200
#define CLOVER_PANEL_HEIGHT        1920

//
// Pixel byte 0 is blue, byte 1 green, byte 2 red.
//
#if defined (CLOVER_LADDER_EARLY)
#define CLOVER_LADDER_WORD    0x00FF00FFu   /* magenta: red and blue */
#define CLOVER_LADDER_NAME    "magenta"
#else
#define CLOVER_LADDER_WORD    0x0000FFFFu   /* yellow: red and green */
#define CLOVER_LADDER_NAME    "yellow"
#endif

EFI_STATUS
EFIAPI
CloverLadderDxeEntry (
  IN EFI_HANDLE        ImageHandle,
  IN EFI_SYSTEM_TABLE  *SystemTable
  )
{
  UINTN  Row;
  UINTN  RowOffset;

  for (Row = 0; Row < CLOVER_PANEL_HEIGHT; Row++) {
    RowOffset = CLOVER_FRAMEBUFFER_BASE + Row * CLOVER_PANEL_WIDTH * sizeof (UINT32);
    SetMem32 ((VOID *)RowOffset, CLOVER_PANEL_WIDTH * sizeof (UINT32), CLOVER_LADDER_WORD);
  }

  DEBUG ((DEBUG_INFO, "CloverLadderDxe: dispatched, panel painted %a\n", CLOVER_LADDER_NAME));
  return EFI_SUCCESS;
}
