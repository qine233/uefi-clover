/**
  Configuration map for the Xiaomi Mi Pad 4 8" LTE (clover, Qualcomm SDM660).

  Every entry is a [ConfigParameters] key of the uefiplat.cfg inside this
  tablet's own xbl partition
  (UniXNU-clover/facts/<serial>-<stamp>/fw/xbl-uefiplat.txt), with the value the
  device carries.  That file is what the Qualcomm SEC parses, so these are not
  board facts inferred from a sibling design: they are the numbers the prebuilt
  drivers in Binaries/clover were shipped to read.

  Six keys the device publishes are left out because none of them is a
  configuration entry our build consumes: ConfigParameterCount,
  PlatConfigFileName, OsTypeString, SpecialLogPartition, DefaultChargerApp and
  DefaultBDSBootApp.  The last of those, "LinuxLoader", is the stock ABL image
  and is exactly the boot target UniXNU replaces.

  EnableSecurityHoleForSplashPartition is kept on: UniXNU takes the splash
  region over from the stock ABL, and the Qualcomm stack refuses to map that
  partition into the UEFI address space unless the hole is allowed.

  NumCpus 4 with NumActiveCores 8 is what the device states, and the two
  together are not a contradiction: the first counts clusters, the second
  cores.  /proc/cpuinfo from the tablet agrees, with eight CPUs whose parts are
  0x801 (four Kryo 260 Silver, Cortex-A53 licensed) and 0x800 (four Kryo 260
  Gold, Cortex-A73 licensed) -- StarlordPkg's PcdCoreCount|8, PcdClusterCount|2.

  @copyright  SPDX-License-Identifier: BSD-2-Clause-Patent
**/

#include <Library/ConfigurationMapLib.h>

#include "../../Include/Checkpoint.h"

STATIC
EFI_CONFIGURATION_ENTRY_DESCRIPTOR
gConfigurationDescriptor[] = {
  // Configuration Map
  {"NumCpusFuseAddr", 0x5C04C},
  {"EnableShell", 0x1},
  {"SharedIMEMBaseAddr", 0x146BF000},
  {"DloadCookieAddr", 0x01FD3000},
  {"DloadCookieValue", 0x10},
  {"MemoryCaptureModeOffset", 0x1C},
  {"AbnormalResetOccurredOffset", 0x24},
  {"DBIDumpDDRBase", 0x9FFD0000},
  {"NumCpus", 4},
  {"NumActiveCores", 8},
  {"MaxLogFileSize", 0x400000},
  {"USBHS1_Config", 0x0},
  {"UsbFnIoRevNum", 0x00010001},
  {"PwrBtnShutdownFlag", 0x0},
  {"Sdc1GpioConfigOn", 0x1E92},
  {"Sdc2GpioConfigOn", 0x1E92},
  {"Sdc1GpioConfigOff", 0xA00},
  {"Sdc2GpioConfigOff", 0xA00},
  {"EnableSDHCSwitch", 0x1},
  {"PSHoldOffset", 0xC000},
  {"PSHoldSHFT", 0x0},
  {"GCCResetValueAddress", 0x146BF028},
  {"SecurityFlag", 0xC4},
  {"TzAppsRegnAddr", 0x86D00000},
  {"TzAppsRegnSize", 0x02200000},
  {"EnableLogFsSyncInRetail", 0x0},
  {"EnableSecurityHoleForSplashPartition", 0x1}
};

VOID
GetConfigurationMap (
  OUT EFI_CONFIGURATION_ENTRY_DESCRIPTOR **ConfigurationDescriptor,
  OUT UINT8                               *ConfigurationDescriptorCount)
{
  STATIC UINTN  mCalls;

  // Pass Data
  *ConfigurationDescriptor      = gConfigurationDescriptor;
  *ConfigurationDescriptorCount = ARRAY_SIZE (gConfigurationDescriptor);

  // Stage 2 of Include/Checkpoint.h.  This library is linked into both Sec and
  // PlatformPeiLib, so the first caller is whichever of them runs first and a
  // yellow bar alone does not prove PEI was reached -- which is why stage 1 is a
  // different module.  Round 10 never showed yellow; treat this band as a bonus,
  // not as a stage boundary.
  if (mCalls++ == 0) {
    CloverCheckpointBar (0x00080000, CLOVER_COLOR_YELLOW);
  }
}
