/** @file
  clover: whole-panel marks that cut DXE dispatch into thirds.

  The red panel proves ABL jumped into BootShim, and the green one proves
  CloverGopDxe installed a GraphicsOutput.  Between those two points sit ninety
  lines of APRIORI.  Measured so far: with the stock ClockDxe blob the
  dispatcher never returned from it, and with upstream's patched blob the cyan
  mark below ClockDxe does appear -- so the stop has moved past the clock and
  sits somewhere in the storage and console tail.

  Each mark repaints the whole panel a solid colour when it is dispatched, and
  the last colour on screen names how far the dispatcher got:

    red      BootShim ran; the dispatcher never reached the top of APRIORI
    magenta  the dispatcher reached the first mark
    cyan     ClockDxe returned
    yellow   everything above BdsDxe returned, storage included
    green    the GOP exists, so GraphicsConsoleDxe can start
    menu     stage 1

  The same source builds all three modules; the INF's -D picks the colour and
  the INF's slot in APRIORI.inc picks the position.  Position is the entire
  message, so the three INFs have to stay around ClockDxe and BdsDxe.

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
// Pixel byte 0 is blue, byte 1 green, byte 2 red: 0xFF0000FF reads as blue on
// this panel, which is how the order was measured.
//
#if defined (CLOVER_LADDER_EARLY)
#define CLOVER_LADDER_WORD    0x00FF00FFu   /* magenta: blue + red */
#define CLOVER_LADDER_NAME    "magenta"
#elif defined (CLOVER_LADDER_BDS)
#define CLOVER_LADDER_WORD    0x00FFFF00u   /* yellow: green + red */
#define CLOVER_LADDER_NAME    "yellow"
#else
#define CLOVER_LADDER_WORD    0x0000FFFFu   /* cyan: blue + green */
#define CLOVER_LADDER_NAME    "cyan"
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
