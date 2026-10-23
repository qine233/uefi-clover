##
#  clover: the firmware volume contents.
#
#  The same module set as Mu-Silicium's lavenderPkg Include/DXE.inc, with the
#  binary paths pointed at Binaries/clover, the UFS driver dropped (eMMC board)
#  and the UniXNU loaders appended.
#
#  SPDX-License-Identifier: BSD-2-Clause-Patent
##

  INF MdeModulePkg/Core/Dxe/DxeMain.inf
  INF MdeModulePkg/Universal/PCD/Dxe/Pcd.inf
  INF ArmPkg/Drivers/CpuDxe/CpuDxe.inf
  INF MdeModulePkg/Core/RuntimeDxe/RuntimeDxe.inf
  INF MdeModulePkg/Universal/SecurityStubDxe/SecurityStubDxe.inf

  # Stage 3 of Include/Checkpoint.h, the black pass that draws the rest of the
  # ladder, the seven index bands below it and the three marks under those;
  # APRIORI.inc starts it third so the magenta bar means the DXE core reached an
  # ordinary driver.
  INF cloverPkg/Drivers/CheckpointDxe/CheckpointDxe.inf

  INF Binaries/clover/QcomPkg/Drivers/TzDxe/TzDxeLA.inf

  INF MdeModulePkg/Universal/WatchdogTimerDxe/WatchdogTimer.inf
  INF MdeModulePkg/Universal/CapsuleRuntimeDxe/CapsuleRuntimeDxe.inf
  INF MdeModulePkg/Universal/ReportStatusCodeRouter/RuntimeDxe/ReportStatusCodeRouterRuntimeDxe.inf
  INF MdeModulePkg/Universal/StatusCodeHandler/RuntimeDxe/StatusCodeHandlerRuntimeDxe.inf
  INF MdeModulePkg/Universal/Variable/RuntimeDxe/VariableRuntimeDxe.inf
  INF EmbeddedPkg/EmbeddedMonotonicCounter/EmbeddedMonotonicCounter.inf
  INF EmbeddedPkg/SimpleTextInOutSerial/SimpleTextInOutSerial.inf
  INF MdeModulePkg/Universal/ResetSystemRuntimeDxe/ResetSystemRuntimeDxe.inf
  INF EmbeddedPkg/RealTimeClockRuntimeDxe/RealTimeClockRuntimeDxe.inf
  INF EmbeddedPkg/MetronomeDxe/MetronomeDxe.inf
  INF MdeModulePkg/Universal/PrintDxe/PrintDxe.inf
  INF MdeModulePkg/Universal/DevicePathDxe/DevicePathDxe.inf
  INF MdeModulePkg/Universal/Console/ConPlatformDxe/ConPlatformDxe.inf
  INF MdeModulePkg/Universal/Console/ConSplitterDxe/ConSplitterDxe.inf
  INF MdeModulePkg/Universal/Console/GraphicsConsoleDxe/GraphicsConsoleDxe.inf
  INF MdeModulePkg/Universal/HiiDatabaseDxe/HiiDatabaseDxe.inf

  INF Binaries/clover/QcomPkg/Drivers/EnvDxe/EnvDxe.inf

  INF ArmPkg/Drivers/ArmGicDxe/ArmGicDxe.inf
  INF ArmPkg/Drivers/TimerDxe/TimerDxe.inf

  INF Binaries/clover/QcomPkg/Drivers/ChipInfoDxe/ChipInfoDxe.inf
  INF Binaries/clover/QcomPkg/Drivers/GLinkDxe/GLinkDxe.inf
  INF Binaries/clover/QcomPkg/Drivers/SmemDxe/SmemDxe.inf
  INF Binaries/clover/QcomPkg/Drivers/ULogDxe/ULogDxe.inf
  INF Binaries/clover/QcomPkg/Drivers/NpaDxe/NpaDxe.inf

  INF MdeModulePkg/Universal/Disk/DiskIoDxe/DiskIoDxe.inf
  INF MdeModulePkg/Universal/Disk/PartitionDxe/PartitionDxe.inf
  INF FatPkg/EnhancedFatDxe/Fat.inf
  INF MdeModulePkg/Universal/Disk/UnicodeCollation/EnglishDxe/EnglishDxe.inf

  INF Binaries/clover/QcomPkg/Drivers/DALSYSDxe/DALSYSDxe.inf
  #
  # Round 17: back in, and the round-16 experiment is closed.  With this file out of the
  # volume the queue ran four rows further than it ever had and then stopped inside
  # SdccDxe, which is FVMAIN file 42 on that build -- the eMMC host driver does not
  # survive a boot with no clock producer, so removing the driver cannot teach this
  # panel anything more.  Round 17 asks a different question of the same hang: what the
  # CPU was told when it stopped, which CheckpointDxe now paints out of the exception
  # context.  Restoring the file also restores the numbering, so a round-17 photograph
  # is decoded against a fv-order.py re-exported with ClockDxe present.
  #
  INF Binaries/clover/QcomPkg/Drivers/ClockDxe/ClockDxe.inf
  INF Binaries/clover/QcomPkg/Drivers/HWIODxe/HWIODxe.inf
  INF Binaries/clover/QcomPkg/Drivers/I2CDxe/I2CDxe.inf
  INF Binaries/clover/QcomPkg/Drivers/SPIDxe/SPIDxe.inf
  INF Binaries/clover/QcomPkg/Drivers/SPMIDxe/SPMIDxe.inf

  # The eMMC host controller. SdccDxe enumerates mmcblk boot device partitions
  # and is what gives UniXNU a BLOCK_IO for the ESP and for userdata.
  INF Binaries/clover/QcomPkg/Drivers/SdccDxe/SdccDxe.inf

  # INF Binaries/clover/QcomPkg/Drivers/UFSDxe/UFSDxe.inf   # clover has no UFS

  INF Binaries/clover/QcomPkg/Drivers/TLMMDxe/TLMMDxe.inf

!if $(USE_CUSTOM_DISPLAY_DRIVER) == 1
  INF Binaries/clover/QcomPkg/Drivers/DisplayDxe/DisplayDxe.inf
  INF QcomPkg/Drivers/DisplayReEnablerDxe/DisplayReEnablerDxe.inf
!else
  INF SiliciumPkg/Drivers/SimpleFbDxe/SimpleFbDxe.inf
!endif

  INF Binaries/clover/QcomPkg/Drivers/PlatformInfoDxe/PlatformInfoDxe.inf
  INF Binaries/clover/QcomPkg/Drivers/ButtonsDxe/ButtonsDxe.inf
  INF Binaries/clover/QcomPkg/Drivers/PmicDxe/PmicDxeLa.inf
  INF Binaries/clover/QcomPkg/Drivers/ChargerExDxe/ChargerExDxe.inf
  INF Binaries/clover/QcomPkg/Drivers/QcomChargerDxe/QcomChargerDxeLA.inf
  INF Binaries/clover/QcomPkg/Drivers/AdcDxe/AdcDxe.inf
  INF Binaries/clover/QcomPkg/Drivers/TsensDxe/TsensDxe.inf
  INF Binaries/clover/QcomPkg/Drivers/LimitsDxe/LimitsDxe.inf
  INF Binaries/clover/QcomPkg/Drivers/UsbfnDwc3Dxe/UsbfnDwc3Dxe.inf

  # No XhciDxe / XhciPciEmulationDxe, which upstream takes from Binaries/generic:
  # SDM660 has the DWC3 USB 2.0 device controller only, and the tablet's own
  # firmware volume confirms it -- 68 AArch64 modules, not one of them XHCI.  The
  # USB modules below are the gadget side plus a host stack that will simply find
  # no root hub.

  INF MdeModulePkg/Bus/Usb/UsbBusDxe/UsbBusDxe.inf
  INF MdeModulePkg/Bus/Usb/UsbKbDxe/UsbKbDxe.inf
  INF MdeModulePkg/Bus/Usb/UsbMassStorageDxe/UsbMassStorageDxe.inf

  INF Binaries/clover/QcomPkg/Drivers/UsbMsdDxe/UsbMsdDxe.inf
  INF Binaries/clover/QcomPkg/Drivers/UsbDeviceDxe/UsbDeviceDxe.inf
  INF Binaries/clover/QcomPkg/Drivers/UsbConfigDxe/UsbConfigDxe.inf
  INF Binaries/clover/QcomPkg/Drivers/HashDxe/HashDxe.inf
  INF Binaries/clover/QcomPkg/Drivers/RNGDxe/RngDxe.inf

  INF MdeModulePkg/Universal/BdsDxe/BdsDxe.inf

!ifdef $(UNIXNU_BUILD)
  #
  # UniXNU: the menu application, the driver that registers its Boot#### option,
  # and DarwinBoot, the loader that validates and hands the payload plus the
  # Apple device tree to XNU. These paths resolve through the UniXNU driver's
  # PACKAGES_PATH entries {tree}/package and {tree}/drivers/DarwinBoot.
  #
  INF UniXNUPkg/Application/UniXNU/UniXNU.inf
  INF UniXNUPkg/Driver/UniXNUDxe/UniXNUDxe.inf
  INF DarwinBootPkg/Driver/DarwinBoot.inf
!endif
