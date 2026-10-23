/** @file
  clover: a Graphics Output Protocol over the framebuffer ABL is already
  scanning out.

  This unit's screen comes up before our code runs: ABL starts MDSS, the
  nt51021 panel and the pm660l backlight, and paints the Mi splash into the
  "Display Reserved" window at 0x9D400000.  Nothing in this volume reprograms
  any of it.  The vendor DisplayDxe blob and DisplayReEnablerDxe used to be
  linked in (the USE_CUSTOM_DISPLAY_DRIVER = 1 branch, the choice lavender
  makes), and the earlier bring-up measured what that costs: the checkpoint
  bands this firmware painted appeared and then went away, and the panel ended
  up blank while the backlight stayed on.  The blob had taken MDSS over and
  stopped scanning the window our writes land in.  Two owners of one panel
  cannot both be right, and the one that only writes is the one whose output
  can be predicted, so the blob is gone.

  What is left is that no other driver in this volume produces
  EFI_GRAPHICS_OUTPUT_PROTOCOL: SimpleFbDxe, the stock driver that would
  publish one over an inherited framebuffer, is not built either, because its
  own job is exactly what this file does with constants read off the unit
  instead of a memory-map lookup.  Without a GOP, GraphicsConsoleDxe never
  starts and the only console is SimpleTextInOutSerial over blsp1_uart2 (no
  cable on this unit), and UniXNU's UI falls from Graphics to Text -- the
  serial console -- and draws an 80x25 menu nobody can see.

  So publish the protocol here.  The buffer, geometry and pixel order are not
  guesses: clover.dsc declares 1200x1920 (PcdFrameBufferWidth/Height) from the
  panel's own device tree, the splash window is the one uefiplat.cfg reserves,
  and the memory order was read off the unit's own firmware -- 0xFF0000FF
  displays blue, so byte 0 is blue and the format is
  PixelBlueGreenRedReserved8BitPerColor.  One mode, no mode changes: the panel
  is not switchable, and a consumer that asks for another mode is asking for
  something this board cannot do.

  Blt is the whole protocol for a framebuffer like this. Implemented: video
  fill, buffer to video, video to buffer and video to video. UniXNU only uses
  fill and buffer to video; GraphicsConsoleDxe uses buffer to video and reads
  the panel back with video to buffer when it redraws a character cell.

  The panel is a liveness ladder, because "the Mi splash is still there"
  cannot tell "our code never ran" from "our code ran and never drew". Red is
  painted by BootShim before it copies a byte, so red means ABL jumped into the
  shim. Green is painted here once the GOP is installed, so green means DXE
  dispatch reached this driver. The UniXNU menu paints over green, and the Mi
  splash means ABL never entered the shim at all.

  There is deliberately no third colour for BDS. BdsDxe sits above this driver
  in APRIORI.inc and installs its arch protocol in its entry point, which runs
  before the dispatcher reaches this driver; CoreRegisterProtocolNotify does not
  report interfaces that already exist, so a notification here would fire only
  if something reinstalled the protocol, and would say nothing in the normal
  case.

  Copyright (c) 2026, UniXNU contributors. All rights reserved.
  SPDX-License-Identifier: BSD-2-Clause-Patent
**/

#include <Uefi.h>

#include <Library/BaseMemoryLib.h>
#include <Library/DebugLib.h>
#include <Library/MemoryAllocationLib.h>
#include <Library/UefiBootServicesTableLib.h>

#include <Protocol/GraphicsOutput.h>

//
// The window uefiplat.cfg calls "Display Reserved"; the display blob has already
// initialised the panel by the time this driver is dispatched.
//
#define CLOVER_FRAMEBUFFER_BASE    ((EFI_PHYSICAL_ADDRESS)0x9D400000)

//
// The panel's own geometry, from dsi-panel-nt51021-boe-video.dtsi and the two
// PCDs clover.dsc already sets for SimpleFbDxe's benefit.
//
#define CLOVER_PANEL_WIDTH         1200
#define CLOVER_PANEL_HEIGHT        1920

#define CLOVER_BYTES_PER_PIXEL     (sizeof (EFI_GRAPHICS_OUTPUT_BLT_PIXEL))

STATIC EFI_GRAPHICS_OUTPUT_MODE_INFORMATION  mCloverModeInfo = {
  0,                                              // Version
  CLOVER_PANEL_WIDTH,                             // HorizontalResolution
  CLOVER_PANEL_HEIGHT,                            // VerticalResolution
  PixelBlueGreenRedReserved8BitPerColor,          // PixelFormat
  { 0, 0, 0, 0 },                                 // PixelInformation
  CLOVER_PANEL_WIDTH                              // PixelsPerScanLine
};

STATIC EFI_GRAPHICS_OUTPUT_PROTOCOL_MODE  mCloverMode = {
  1,                                              // MaxMode
  0,                                              // Mode
  &mCloverModeInfo,                               // Info
  sizeof (mCloverModeInfo),                       // SizeOfInfo
  CLOVER_FRAMEBUFFER_BASE,                        // FrameBufferBase
  (UINTN)CLOVER_PANEL_WIDTH * CLOVER_PANEL_HEIGHT * CLOVER_BYTES_PER_PIXEL
};

STATIC
EFI_GRAPHICS_OUTPUT_BLT_PIXEL *
PixelAt (
  IN UINTN  X,
  IN UINTN  Y
  )
{
  return (EFI_GRAPHICS_OUTPUT_BLT_PIXEL *)(UINTN)(
          CLOVER_FRAMEBUFFER_BASE +
          ((UINTN)Y * CLOVER_PANEL_WIDTH + X) * CLOVER_BYTES_PER_PIXEL);
}

STATIC
BOOLEAN
InsidePanel (
  IN UINTN  X,
  IN UINTN  Y,
  IN UINTN  Width,
  IN UINTN  Height
  )
{
  return (BOOLEAN)((X + Width <= CLOVER_PANEL_WIDTH) && (Y + Height <= CLOVER_PANEL_HEIGHT));
}

STATIC
VOID
FillRect (
  IN UINTN                            X,
  IN UINTN                            Y,
  IN UINTN                            Width,
  IN UINTN                            Height,
  IN EFI_GRAPHICS_OUTPUT_BLT_PIXEL    *Pixel
  )
{
  UINT64  Value;
  UINTN   Row;

  if ((Width == 0) || (Height == 0)) {
    return;
  }

  //
  // One SetMem32 per row: a full-panel clear through here is 1920 calls, which
  // is what a menu repaint costs at worst.
  //
  Value = *(UINT32 *)Pixel;
  for (Row = 0; Row < Height; Row++) {
    SetMem32 (PixelAt (X, Y + Row), Width * CLOVER_BYTES_PER_PIXEL, (UINT32)Value);
  }
}

STATIC
VOID
PaintPanel (
  IN UINT8  Blue,
  IN UINT8  Green,
  IN UINT8  Red
  )
{
  EFI_GRAPHICS_OUTPUT_BLT_PIXEL  Pixel;

  Pixel.Blue     = Blue;
  Pixel.Green    = Green;
  Pixel.Red      = Red;
  Pixel.Reserved = 0;
  FillRect (0, 0, CLOVER_PANEL_WIDTH, CLOVER_PANEL_HEIGHT, &Pixel);
}

STATIC
EFI_STATUS
EFIAPI
CloverGopQueryMode (
  IN  EFI_GRAPHICS_OUTPUT_PROTOCOL        *This,
  IN  UINT32                              ModeNumber,
  OUT UINTN                               *SizeOfInfo,
  OUT EFI_GRAPHICS_OUTPUT_MODE_INFORMATION **Info
  )
{
  if ((SizeOfInfo == NULL) || (Info == NULL)) {
    return EFI_INVALID_PARAMETER;
  }

  if (ModeNumber != 0) {
    return EFI_UNSUPPORTED;
  }

  *Info = AllocateCopyPool (sizeof (mCloverModeInfo), &mCloverModeInfo);
  if (*Info == NULL) {
    return EFI_OUT_OF_RESOURCES;
  }

  *SizeOfInfo = sizeof (mCloverModeInfo);
  return EFI_SUCCESS;
}

//
// There is one mode and the panel is already in it. Asking for mode 0 is not a
// failure, and asking for anything else is.
//
STATIC
EFI_STATUS
EFIAPI
CloverGopSetMode (
  IN EFI_GRAPHICS_OUTPUT_PROTOCOL  *This,
  IN UINT32                        ModeNumber
  )
{
  if (ModeNumber != 0) {
    return EFI_UNSUPPORTED;
  }

  mCloverMode.Mode = 0;
  return EFI_SUCCESS;
}

STATIC
EFI_STATUS
EFIAPI
CloverGopBlt (
  IN EFI_GRAPHICS_OUTPUT_PROTOCOL       *This,
  IN EFI_GRAPHICS_OUTPUT_BLT_PIXEL      *BltBuffer OPTIONAL,
  IN EFI_GRAPHICS_OUTPUT_BLT_OPERATION  BltOperation,
  IN UINTN                              SourceX,
  IN UINTN                              SourceY,
  IN UINTN                              DestinationX,
  IN UINTN                              DestinationY,
  IN UINTN                              Width,
  IN UINTN                              Height,
  IN UINTN                              Delta OPTIONAL
  )
{
  UINTN  Row;
  UINTN  Stride;
  UINTN  SourceDelta;

  if ((Width == 0) || (Height == 0)) {
    return EFI_INVALID_PARAMETER;
  }

  switch (BltOperation) {
    case EfiBltVideoFill:
      if (BltBuffer == NULL) {
        return EFI_INVALID_PARAMETER;
      }

      if (!InsidePanel (DestinationX, DestinationY, Width, Height)) {
        return EFI_INVALID_PARAMETER;
      }

      FillRect (DestinationX, DestinationY, Width, Height, BltBuffer);
      return EFI_SUCCESS;

    case EfiBltBufferToVideo:
      if (BltBuffer == NULL) {
        return EFI_INVALID_PARAMETER;
      }

      if (!InsidePanel (DestinationX, DestinationY, Width, Height)) {
        return EFI_INVALID_PARAMETER;
      }

      Stride = (Delta != 0) ? (Delta / CLOVER_BYTES_PER_PIXEL) : Width;
      for (Row = 0; Row < Height; Row++) {
        CopyMem (
          PixelAt (DestinationX, DestinationY + Row),
          BltBuffer + (SourceY + Row) * Stride + SourceX,
          Width * CLOVER_BYTES_PER_PIXEL
          );
      }

      return EFI_SUCCESS;

    case EfiBltVideoToBltBuffer:
      if (BltBuffer == NULL) {
        return EFI_INVALID_PARAMETER;
      }

      if (!InsidePanel (SourceX, SourceY, Width, Height)) {
        return EFI_INVALID_PARAMETER;
      }

      SourceDelta = (Delta != 0) ? (Delta / CLOVER_BYTES_PER_PIXEL) : Width;
      for (Row = 0; Row < Height; Row++) {
        CopyMem (
          BltBuffer + (DestinationY + Row) * SourceDelta + DestinationX,
          PixelAt (SourceX, SourceY + Row),
          Width * CLOVER_BYTES_PER_PIXEL
          );
      }

      return EFI_SUCCESS;

    case EfiBltVideoToVideo:
      if (!InsidePanel (SourceX, SourceY, Width, Height) ||
          !InsidePanel (DestinationX, DestinationY, Width, Height))
      {
        return EFI_INVALID_PARAMETER;
      }

      //
      // Row by row, and top-down or bottom-up depending on which side is higher,
      // so an overlapping copy does not read rows it has already written.
      //
      for (Row = 0; Row < Height; Row++) {
        CopyMem (
          PixelAt (DestinationX, (DestinationY < SourceY) ? (DestinationY + Row) : (DestinationY + Height - 1 - Row)),
          PixelAt (SourceX, (DestinationY < SourceY) ? (SourceY + Row) : (SourceY + Height - 1 - Row)),
          Width * CLOVER_BYTES_PER_PIXEL
          );
      }

      return EFI_SUCCESS;

    default:
      return EFI_INVALID_PARAMETER;
  }
}

STATIC EFI_GRAPHICS_OUTPUT_PROTOCOL  mCloverGop = {
  CloverGopQueryMode,
  CloverGopSetMode,
  CloverGopBlt,
  &mCloverMode
};

EFI_STATUS
EFIAPI
CloverGopDxeEntry (
  IN EFI_HANDLE        ImageHandle,
  IN EFI_SYSTEM_TABLE  *SystemTable
  )
{
  EFI_STATUS  Status;
  EFI_HANDLE  Handle;

  Handle = NULL;
  Status = gBS->InstallMultipleProtocolInterfaces (
                  &Handle,
                  &gEfiGraphicsOutputProtocolGuid,
                  &mCloverGop,
                  NULL
                  );
  DEBUG ((
    DEBUG_INFO,
    "CloverGopDxe: %ux%u at 0x%lx, %u bytes: %r\n",
    CLOVER_PANEL_WIDTH,
    CLOVER_PANEL_HEIGHT,
    (UINT64)CLOVER_FRAMEBUFFER_BASE,
    (UINT32)mCloverMode.FrameBufferSize,
    Status
    ));
  if (EFI_ERROR (Status)) {
    return Status;
  }

  PaintPanel (0, 0xFF, 0);

  return EFI_SUCCESS;
}
