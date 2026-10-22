/**
  Configuration map for the Xiaomi Mi Pad 4 8" LTE (clover, Qualcomm SDM660).

  The values are inherited from Mu-Silicium's lavenderPkg, the other SDM660 board
  on the same StarlordPkg SoC package, and each one that is really a board fact
  has been checked against clover's own device tree:

    SharedIMEMBaseAddr  0x146BF000   qcom,msm-imem@146bf000
    DloadCookieAddr     0x01FD3000   inside TCSR_TCSR_REGS (0x01FC0000 + 0x26000)
    DBIDumpDDRBase      0x9FFD0000   the DBI Dump entry of Library/MemoryMapLib
    GCCResetValueAddr   0x146BF028   the IMEM cookie block above
    TzAppsRegn*         0x86D00000 + 0x02200000   qcom_seecom, verbatim

  EnableSecurityHoleForSplashPartition is kept on: UniXNU takes the cont_splash
  region over from the stock ABL, and the Qualcomm stack refuses to map that
  partition into the UEFI address space unless the hole is allowed.

  TODO-DEVICE: NumCpus keeps lavender's 4 (with NumActiveCores 8). Confirm it
  against facts/<serial>-<stamp>/cpu/possible.txt from the tablet; Kryo 260 in
  this unit is 4x A53 + 4x A73, and StarlordPkg already publishes
  PcdCoreCount|8 and PcdClusterCount|2.

  @copyright  SPDX-License-Identifier: BSD-2-Clause-Patent
**/

#include <Library/ConfigurationMapLib.h>

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
  // Pass Data
  *ConfigurationDescriptor      = gConfigurationDescriptor;
  *ConfigurationDescriptorCount = ARRAY_SIZE (gConfigurationDescriptor);
}
