##
#  clover: the DXE modules the dispatch order pins to the front.
#
#  Derived from Mu-Silicium's lavenderPkg Include/APRIORI.inc (same SDM660 SoC
#  package). Two changes beyond the Binaries/lavender -> Binaries/clover path:
#
#    * UFSDxe is not started. The Mi Pad 4 8" LTE stores everything on eMMC 5.1
#      (sdhc_1 @ 0x0C0C4000, CQE + HS400ES); its stock firmware has no UFS
#      stack, so requiring that blob would only break the build.
#    * The display is not driven by this volume at all: the vendor DisplayDxe
#      blob and DisplayReEnablerDxe are left out, and CloverGopDxe publishes a
#      GraphicsOutput over the window ABL is already scanning.
#
#  SPDX-License-Identifier: BSD-2-Clause-Patent
##

APRIORI DXE {
  INF MdeModulePkg/Core/Dxe/DxeMain.inf
  INF MdeModulePkg/Universal/PCD/Dxe/Pcd.inf

  # First rung of the DXE ladder: magenta on the panel once the dispatcher is
  # in the APRIORI list at all.  It has to stay above ClockDxe.
  INF cloverPkg/Drivers/CloverLadderDxe/CloverLadderEarly.inf

  INF Binaries/clover/QcomPkg/Drivers/EnvDxe/EnvDxe.inf

  INF MdeModulePkg/Universal/ReportStatusCodeRouter/RuntimeDxe/ReportStatusCodeRouterRuntimeDxe.inf
  INF MdeModulePkg/Universal/StatusCodeHandler/RuntimeDxe/StatusCodeHandlerRuntimeDxe.inf
  INF MdeModulePkg/Core/RuntimeDxe/RuntimeDxe.inf
  INF ArmPkg/Drivers/CpuDxe/CpuDxe.inf
  INF ArmPkg/Drivers/ArmGicDxe/ArmGicDxe.inf
  INF ArmPkg/Drivers/TimerDxe/TimerDxe.inf
  INF MdeModulePkg/Universal/WatchdogTimerDxe/WatchdogTimer.inf
  INF MdeModulePkg/Universal/SecurityStubDxe/SecurityStubDxe.inf

  INF Binaries/clover/QcomPkg/Drivers/SmemDxe/SmemDxe.inf
  INF Binaries/clover/QcomPkg/Drivers/DALSYSDxe/DALSYSDxe.inf
  INF Binaries/clover/QcomPkg/Drivers/HWIODxe/HWIODxe.inf
  INF Binaries/clover/QcomPkg/Drivers/ChipInfoDxe/ChipInfoDxe.inf
  INF Binaries/clover/QcomPkg/Drivers/PlatformInfoDxe/PlatformInfoDxe.inf

  INF EmbeddedPkg/MetronomeDxe/MetronomeDxe.inf

  INF Binaries/clover/QcomPkg/Drivers/GLinkDxe/GLinkDxe.inf
  INF Binaries/clover/QcomPkg/Drivers/ULogDxe/ULogDxe.inf
  INF Binaries/clover/QcomPkg/Drivers/NpaDxe/NpaDxe.inf
  #
  # ClockDxe is the clock producer SdccDxe waits on.  Without it the eMMC host driver
  # does not get past its first register access, and the block devices the ESP and
  # userdata live on never appear.
  #
  INF Binaries/clover/QcomPkg/Drivers/ClockDxe/ClockDxe.inf

  # Second rung: yellow once ClockDxe has returned.  Its position alone carries
  # the meaning, so it stays immediately below ClockDxe.
  INF cloverPkg/Drivers/CloverLadderDxe/CloverLadderLate.inf

  INF MdeModulePkg/Universal/Disk/DiskIoDxe/DiskIoDxe.inf
  INF MdeModulePkg/Universal/Disk/PartitionDxe/PartitionDxe.inf

  # eMMC: SdccDxe is the driver that produces BLOCK_IO for the ESP and userdata.
  INF Binaries/clover/QcomPkg/Drivers/SdccDxe/SdccDxe.inf
  # INF Binaries/clover/QcomPkg/Drivers/UFSDxe/UFSDxe.inf   # clover has no UFS

  INF FatPkg/EnhancedFatDxe/Fat.inf

  INF MdeModulePkg/Universal/Disk/UnicodeCollation/EnglishDxe/EnglishDxe.inf
  INF MdeModulePkg/Universal/Variable/RuntimeDxe/VariableRuntimeDxe.inf
  INF EmbeddedPkg/EmbeddedMonotonicCounter/EmbeddedMonotonicCounter.inf
  INF MdeModulePkg/Universal/ResetSystemRuntimeDxe/ResetSystemRuntimeDxe.inf
  INF EmbeddedPkg/RealTimeClockRuntimeDxe/RealTimeClockRuntimeDxe.inf
  INF MdeModulePkg/Universal/PrintDxe/PrintDxe.inf
  INF MdeModulePkg/Universal/DevicePathDxe/DevicePathDxe.inf
  INF MdeModulePkg/Universal/CapsuleRuntimeDxe/CapsuleRuntimeDxe.inf
  INF MdeModulePkg/Universal/HiiDatabaseDxe/HiiDatabaseDxe.inf

  # Third rung: yellow once the storage and variable block above has returned,
  # just before BdsDxe.  Position is the message.
  INF cloverPkg/Drivers/CloverLadderDxe/CloverLadderBds.inf

  INF MdeModulePkg/Universal/BdsDxe/BdsDxe.inf

  # Tail bands.  The yellow mark above says dispatch reached the top of the
  # tail; these nine say how far through it the dispatcher got, one black band
  # each on the yellow screen.  They only order, so their positions are the
  # whole message: keep each one immediately below the block it reports on.
  INF cloverPkg/Drivers/CloverLadderDxe/CloverTail1.inf

  INF Binaries/clover/QcomPkg/Drivers/TLMMDxe/TLMMDxe.inf
  INF Binaries/clover/QcomPkg/Drivers/I2CDxe/I2CDxe.inf
  INF Binaries/clover/QcomPkg/Drivers/SPMIDxe/SPMIDxe.inf
  INF Binaries/clover/QcomPkg/Drivers/SPIDxe/SPIDxe.inf
  INF Binaries/clover/QcomPkg/Drivers/PmicDxe/PmicDxeLa.inf
  INF Binaries/clover/QcomPkg/Drivers/AdcDxe/AdcDxe.inf
  INF Binaries/clover/QcomPkg/Drivers/QcomChargerDxe/QcomChargerDxeLA.inf
  INF Binaries/clover/QcomPkg/Drivers/UsbfnDwc3Dxe/UsbfnDwc3Dxe.inf

  INF cloverPkg/Drivers/CloverLadderDxe/CloverTail2.inf

  INF MdeModulePkg/Bus/Usb/UsbBusDxe/UsbBusDxe.inf
  INF MdeModulePkg/Bus/Usb/UsbKbDxe/UsbKbDxe.inf
  INF MdeModulePkg/Bus/Usb/UsbMassStorageDxe/UsbMassStorageDxe.inf

  INF cloverPkg/Drivers/CloverLadderDxe/CloverTail3.inf

  INF Binaries/clover/QcomPkg/Drivers/UsbMsdDxe/UsbMsdDxe.inf
  INF Binaries/clover/QcomPkg/Drivers/UsbDeviceDxe/UsbDeviceDxe.inf
  INF Binaries/clover/QcomPkg/Drivers/UsbConfigDxe/UsbConfigDxe.inf
  INF Binaries/clover/QcomPkg/Drivers/ButtonsDxe/ButtonsDxe.inf
  INF Binaries/clover/QcomPkg/Drivers/TsensDxe/TsensDxe.inf

  INF cloverPkg/Drivers/CloverLadderDxe/CloverTail4.inf

  # No display driver here, by design.  The vendor DisplayDxe blob and
  # DisplayReEnablerDxe are not in the volume either (DXE.inc): they reprogram
  # the MDSS pipeline and the panel that ABL handed over, which is the opposite
  # of what a framebuffer owner wants.

  INF Binaries/clover/QcomPkg/Drivers/TzDxe/TzDxeLA.inf
  INF cloverPkg/Drivers/CloverLadderDxe/CloverTail5.inf
  INF Binaries/clover/QcomPkg/Drivers/LimitsDxe/LimitsDxe.inf
  INF cloverPkg/Drivers/CloverLadderDxe/CloverTail6.inf
  INF Binaries/clover/QcomPkg/Drivers/HashDxe/HashDxe.inf
  INF cloverPkg/Drivers/CloverLadderDxe/CloverTail7.inf
  INF Binaries/clover/QcomPkg/Drivers/RNGDxe/RngDxe.inf

  INF cloverPkg/Drivers/CloverLadderDxe/CloverTail8.inf

  # Serial first: the UniXNU menu and the kernel console both run over
  # blsp1_uart2 at 115200 before the panel path is proven on this unit.
  INF EmbeddedPkg/SimpleTextInOutSerial/SimpleTextInOutSerial.inf
  INF MdeModulePkg/Universal/Console/ConPlatformDxe/ConPlatformDxe.inf
  INF MdeModulePkg/Universal/Console/ConSplitterDxe/ConSplitterDxe.inf

  INF cloverPkg/Drivers/CloverLadderDxe/CloverTail9.inf

  # Right before the console driver that needs it: the volume's only GOP
  # producer, over the window ABL left scanning.  Without it
  # GraphicsConsoleDxe's depex is unsatisfiable and the only console is the
  # serial port on blsp1_uart2, which this unit has no cable for.
  INF cloverPkg/Drivers/CloverGopDxe/CloverGopDxe.inf
  INF MdeModulePkg/Universal/Console/GraphicsConsoleDxe/GraphicsConsoleDxe.inf
}
