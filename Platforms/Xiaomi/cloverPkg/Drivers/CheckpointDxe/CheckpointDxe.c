/**
  DXE-dispatch checkpoint for the Xiaomi Mi Pad 4 8" LTE (clover).

  Round 10 read green (+0x40000, PEI took the memory map) and magenta (+0xC0000,
  the DXE core dispatched an ordinary driver) and no white.  Round 11 added nine
  cyan bands and reported three of them, evenly spaced.  Round 12 added eight red
  bands for the Qualcomm chain and reported three cyan and five red, no white --
  and that is where a counted ladder stops being useful, because a count identifies
  no band, and the two shapes that fit say opposite things.

  So this driver is positional.  Every slot in the table below is painted black at
  entry and recoloured only when the module that owns it has appeared, which means
  the screen always shows the whole ladder and the first black band down it is the
  first module that never dispatched.  Round 12's ambiguity was real: BdsDxe,
  VariableRuntimeDxe, DevicePathDxe and EmbeddedMonotonicCounter all carry
  Depex TRUE (read off the INFs under Mu_Basecore, not assumed), so they cannot be
  starved, and their dark bands could only mean the dispatch loop stopped -- unless
  the lit bands were never a prefix at all, which is exactly what a count hides.

  Order is the order the DXE core reaches things: the firmware volumes it
  enumerates from HOBs before the dispatch loop, then the architecture protocols,
  then the vendor chain the depex sections describe, then storage, then display,
  then BDS.  Cyan is EDK II, red is Qualcomm, white is GraphicsOutput, and black
  is a stage this boot did not reach.

  RegisterProtocolNotify also reports instances that already exist, so a protocol
  the platform produced before this driver was dispatched still paints its band --
  provided the black pass above runs first, which it does, since the notify
  callbacks cannot run until this entry point returns.

  Drawing nothing through the UEFI display stack and returning EFI_SUCCESS is the
  point: a bar here cannot be the reason a boot stops.

  @copyright  SPDX-License-Identifier: BSD-2-Clause-Patent
**/

#include <Uefi.h>
#include <Library/UefiDriverEntryPoint.h>
#include <Library/UefiBootServicesTableLib.h>

// Protocol/FirmwareVolume2.h uses the Pi firmware-format types without including
// them, the way every EDK II header does: whoever wants it brings the Pi headers,
// and has to bring them first.
#include <Pi/PiFirmwareFile.h>
#include <Pi/PiFirmwareVolume.h>
#include <Protocol/FirmwareVolume2.h>
#include <Protocol/Cpu.h>
#include <Protocol/Runtime.h>
#include <Protocol/Security.h>
#include <Protocol/WatchdogTimer.h>
#include <Protocol/VariableWrite.h>
#include <Protocol/Variable.h>
#include <Protocol/MonotonicCounter.h>
#include <Protocol/RealTimeClock.h>
#include <Protocol/Metronome.h>
#include <Protocol/Timer.h>
#include <Protocol/BlockIo.h>
#include <Protocol/DiskIo.h>
#include <Protocol/PartitionInfo.h>
#include <Protocol/SimpleFileSystem.h>
#include <Protocol/UnicodeCollation.h>
#include <Protocol/GraphicsOutput.h>
#include <Protocol/Bds.h>

#include "../../Include/Checkpoint.h"

//
// The six Qualcomm-side protocols below are named by symbol in the vendor tree's
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

// QcomPkg.dec: gQcomPmicVersionProtocolGuid, one of DisplayDxe's twelve terms.
STATIC EFI_GUID  mPmicVersionProtocolGuid = {
  0x4684800A, 0x2755, 0x4EDC, { 0xB4, 0x43, 0x7F, 0x8C, 0xEB, 0x32, 0x39, 0xD3 }
};

// EmbeddedPkg.dec: gHardwareInterruptProtocolGuid, which TimerDxe waits on.
STATIC EFI_GUID  mHardwareInterruptProtocolGuid = {
  0x2890B3EA, 0x053D, 0x1643, { 0xAD, 0x0C, 0xD6, 0x48, 0x08, 0xDA, 0x3F, 0xF1 }
};

//
// In the order the DXE core is expected to reach them.  Twenty-four bands from
// +0x140000 to +0x700000 on the 256 KiB pitch, each CLOVER_BAR_SIZE long, all
// inside the 8 MiB BootShim filled; scripts/check-clover-uefi.py fails the build
// if any of that stops being true.
//
STATIC CONST struct {
  EFI_GUID   *Guid;
  UINT64     Offset;
  UINT32     Argb;
  CHAR8      *Name;
} mSlots[] = {
  { &gEfiFirmwareVolume2ProtocolGuid,          0x00140000, CLOVER_COLOR_CYAN, "DxeCore: firmware volumes from HOBs"  },
  { &gEfiCpuArchProtocolGuid,                  0x00180000, CLOVER_COLOR_CYAN, "CpuDxe"                              },
  { &gEfiRuntimeArchProtocolGuid,              0x001C0000, CLOVER_COLOR_CYAN, "RuntimeDxe"                          },
  { &gEfiSecurityArchProtocolGuid,             0x00200000, CLOVER_COLOR_CYAN, "SecurityStubDxe"                     },
  { &gEfiWatchdogTimerArchProtocolGuid,        0x00240000, CLOVER_COLOR_CYAN, "WatchdogTimerDxe"                    },

  // VariableRuntimeDxe has Depex TRUE, so a black band here means the loop never
  // reached it, not that it waited.  Its second band is the variable store being
  // readable, which needs a firmware volume block behind it -- and this FV declares
  // no producer for one, so it is a real candidate for where the boot stops.
  { &gEfiVariableWriteArchProtocolGuid,        0x00280000, CLOVER_COLOR_CYAN, "VariableRuntimeDxe (Depex TRUE)"     },
  { &gEfiVariableArchProtocolGuid,             0x002C0000, CLOVER_COLOR_CYAN, "variable store readable"             },
  { &gEfiMonotonicCounterArchProtocolGuid,     0x00300000, CLOVER_COLOR_CYAN, "EmbeddedMonotonicCounter (TRUE)"     },
  { &gEfiRealTimeClockArchProtocolGuid,        0x00340000, CLOVER_COLOR_CYAN, "RealTimeClock (needs VariableArch)"  },
  { &gEfiMetronomeArchProtocolGuid,            0x00380000, CLOVER_COLOR_CYAN, "MetronomeDxe"                        },

  // The Qualcomm chain, in the order its depex sections can be satisfied.  The
  // fan-in GUID is named by ten blobs and declared by nothing in this tree, so it
  // has to come from one of them -- EnvDxe is the candidate, and it is early in the
  // volume, which is why this band sits above the GIC rather than below SMEM.
  { &mVendorFanInGuid,                         0x003C0000, CLOVER_COLOR_RED,  "the GUID ten blobs wait on"          },
  { &mHardwareInterruptProtocolGuid,           0x00400000, CLOVER_COLOR_CYAN, "ArmGicDxe"                           },
  { &gEfiTimerArchProtocolGuid,                0x00440000, CLOVER_COLOR_CYAN, "TimerDxe (needs the GIC)"            },
  { &mChipInfoProtocolGuid,                    0x00480000, CLOVER_COLOR_RED,  "ChipInfoDxe"                         },
  { &mSmemProtocolGuid,                        0x004C0000, CLOVER_COLOR_RED,  "SmemDxe"                             },
  { &mClockProtocolGuid,                       0x00500000, CLOVER_COLOR_RED,  "ClockDxe: display and eMMC wait on it" },

  // Storage, which is what UniXNU needs: SdccDxe has to reach BlockIo before
  // DiskIoDxe, PartitionDxe and the FAT driver have anything to attach to, so these
  // four bands are one dependent chain in time even though EDK II lists three of
  // them earlier in the volume.
  { &gEfiBlockIoProtocolGuid,                  0x00540000, CLOVER_COLOR_CYAN, "BlockIo (SdccDxe, the eMMC)"         },
  { &gEfiDiskIoProtocolGuid,                   0x00580000, CLOVER_COLOR_CYAN, "DiskIoDxe"                           },
  { &gEfiPartitionInfoProtocolGuid,            0x005C0000, CLOVER_COLOR_CYAN, "PartitionDxe: partitions parsed"     },
  { &gEfiSimpleFileSystemProtocolGuid,         0x00600000, CLOVER_COLOR_CYAN, "Fat volumes"                         },
  { &gEfiUnicodeCollation2ProtocolGuid,        0x00640000, CLOVER_COLOR_CYAN, "EnglishDxe"                          },

  { &gEfiGraphicsOutputProtocolGuid,           0x00680000, CLOVER_COLOR_WHITE, "the display: DisplayDxe or SimpleFbDxe" },
  { &mPmicVersionProtocolGuid,                 0x006C0000, CLOVER_COLOR_RED,  "PmicDxeLa"                           },

  // Depex TRUE, so this is the cleanest single bit of information the ladder holds:
  // a lit BDS band means the dispatch loop finished with something to do, and a dark
  // one with everything above it lit means it stopped on the way.
  { &gEfiBdsArchProtocolGuid,                  0x00700000, CLOVER_COLOR_CYAN, "BdsDxe (Depex TRUE)"                 }
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

  CloverCheckpointBar (mSlots[Index].Offset, mSlots[Index].Argb);
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

  // Every slot starts black.  This pass has to precede the registrations below,
  // and it does: the notify callbacks run at TPL_CALLBACK, the level this entry
  // point is already at, so none of them can start before this function returns.
  for (Index = 0; Index < ARRAY_SIZE (mSlots); Index++) {
    CloverCheckpointBar (mSlots[Index].Offset, CLOVER_COLOR_BLACK);
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

    gBS->RegisterProtocolNotify (
           mSlots[Index].Guid,
           mEvents[Index],
           &mRegistrations[Index]
           );
  }

  return EFI_SUCCESS;
}
