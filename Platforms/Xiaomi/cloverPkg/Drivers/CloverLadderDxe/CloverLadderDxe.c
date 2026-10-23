/** @file
  clover: whole-panel marks that cut DXE dispatch into thirds, plus the black
  bands that bisect the tail.

  The red panel proves ABL jumped into BootShim, and the green one proves
  CloverGopDxe installed a GraphicsOutput.  Between those two points sit ninety
  lines of APRIORI.  Measured so far: with the stock ClockDxe blob the
  dispatcher never returned from it; with upstream's patched blob the cyan mark
  below ClockDxe appears; and the yellow mark just above BdsDxe appears, so the
  stop is in the tail, below BdsDxe.

  The ladder repaints the whole panel a solid colour when it is dispatched, and
  the last colour on screen names how far the dispatcher got:

    red      BootShim ran; the dispatcher never reached the top of APRIORI
    magenta  the dispatcher reached the first mark
    cyan     ClockDxe returned
    yellow   everything above BdsDxe returned, storage included
    green    the GOP exists, so GraphicsConsoleDxe can start
    menu     stage 1

  The tail is too long to bisect one colour at a time, and there is only one
  colour left before green.  So the tail probes do not repaint: each paints one
  black band on the yellow background at a row fixed by its index.  Count the
  bands and the last boundary crossed is known.  They are dispatched in
  APRIORI.inc order, so N bands means "every boundary up to N returned".  A
  band is never in the way of a later signal: CloverGopDxe's green fill covers
  all six at once, which is exactly the reading "the whole tail returned".

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
// Tail bands.  Six equal bands, well inside the panel and far enough apart to
// count at arm's length: rows 240, 480, 720, 960, 1200, 1440, each 120 rows
// tall.  Band 1 is the topmost.
//
#define CLOVER_BAND_TOP            240
#define CLOVER_BAND_PITCH          240
#define CLOVER_BAND_HEIGHT         120

//
// Pixel byte 0 is blue, byte 1 green, byte 2 red: 0xFF0000FF reads as blue on
// this panel, which is how the order was measured.
//
#if defined (CLOVER_TAIL_BAND)
#define CLOVER_BAND_WORD       0x00000000u   /* black */
#elif defined (CLOVER_LADDER_EARLY)
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

#if defined (CLOVER_TAIL_BAND)
  Row = CLOVER_BAND_TOP + (CLOVER_TAIL_BAND - 1) * CLOVER_BAND_PITCH;
  RowOffset = CLOVER_FRAMEBUFFER_BASE + Row * CLOVER_PANEL_WIDTH * sizeof (UINT32);
  SetMem32 ((VOID *)RowOffset,
            CLOVER_BAND_HEIGHT * CLOVER_PANEL_WIDTH * sizeof (UINT32),
            CLOVER_BAND_WORD);

  DEBUG ((DEBUG_INFO, "CloverTail: dispatched, band %d at row %d\n",
          CLOVER_TAIL_BAND, Row));
#else
  for (Row = 0; Row < CLOVER_PANEL_HEIGHT; Row++) {
    RowOffset = CLOVER_FRAMEBUFFER_BASE + Row * CLOVER_PANEL_WIDTH * sizeof (UINT32);
    SetMem32 ((VOID *)RowOffset, CLOVER_PANEL_WIDTH * sizeof (UINT32), CLOVER_LADDER_WORD);
  }

  DEBUG ((DEBUG_INFO, "CloverLadderDxe: dispatched, panel painted %a\n",
          CLOVER_LADDER_NAME));
#endif

  return EFI_SUCCESS;
}
