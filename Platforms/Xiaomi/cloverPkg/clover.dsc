##
#  Xiaomi Mi Pad 4 8" LTE (clover, SDM660) - UEFI platform description.
#
#  Based on Mu-Silicium's lavender.dsc (the other SDM660 / StarlordPkg board)
#  with the numbers taken from this tablet itself -- the device tree for the
#  silicon, and the uefiplat.cfg inside its own xbl partition for everything
#  the firmware addresses (UniXNU-clover/facts/<serial>-<stamp>/):
#
#    DRAM base            0x80000000              (sdm660-common.dtsi memory node)
#    GIC distributor      0x17A00000              (StarlordPkg PcdGicDistributorBase)
#    GIC redistributors   0x17B00000              (StarlordPkg PcdGicRedistributorsBase)
#    panel                1200 x 1920, 32 bpp     (dsi-panel-nt51021-boe-video.dtsi)
#    splash region        0x9D400000 + 0x02400000 ("Display Reserved" in uefiplat.cfg;
#                                                   clover-overlay.dtsi moves it to
#                                                   0x9D500000 for a kernel that draws
#                                                   its own splash, and loses)
#    UEFI FD              0x9FC00000 + 0x00300000 (Resources/Configs/clover.toml)
#
#  USE_CUSTOM_DISPLAY_DRIVER is 1, the choice lavender makes on this same silicon:
#  this unit's own DisplayDxe blob was extracted from its xbl, so the firmware
#  brings up MDSS, the nt51021 panel and the pm660l WLED backlight itself.  The
#  inherited-framebuffer route (= 0, SiliciumPkg SimpleFbDxe wrapping the ABL
#  splash) was tried first and cannot be judged from outside: the generic-geometry
#  image left the Mi splash frozen and the stock-geometry one left a black screen,
#  with no USB node either time -- "running, wrong framebuffer" and "not running"
#  look identical.  Driving the panel from our own code makes the screen a real
#  liveness signal.  UniXNU still takes the splash region over as its ADT
#  display-base.
#
#  Copyright (c) 2011 - 2022, ARM Limited. All rights reserved.
#  Copyright (c) 2014, Linaro Limited. All rights reserved.
#  Copyright (c) 2015 - 2020, Intel Corporation. All rights reserved.
#  Copyright (c) 2018, Bingxing Wang. All rights reserved.
#  Copyright (c) Microsoft Corporation.
#
#  SPDX-License-Identifier: BSD-2-Clause-Patent
##

################################################################################
#
# Defines Section - statements that will be processed to create a Makefile.
#
################################################################################
[Defines]
  PLATFORM_NAME                  = clover
  PLATFORM_GUID                  = E16774B1-7639-57FA-9F99-F20F4B7CFD15
  PLATFORM_VERSION               = 0.1
  DSC_SPECIFICATION              = 0x00010005
  OUTPUT_DIRECTORY               = Build/cloverPkg
  SUPPORTED_ARCHITECTURES        = AARCH64
  BUILD_TARGETS                  = RELEASE|DEBUG
  SKUID_IDENTIFIER               = DEFAULT
  FLASH_DEFINITION               = cloverPkg/clover.fdf
  USE_CUSTOM_DISPLAY_DRIVER      = 1

!include StarlordPkg/StarlordPkg.dsc.inc

[PcdsFixedAtBuild]
  #
  # DDR Memory
  #
  gArmTokenSpaceGuid.PcdSystemMemoryBase|0x80000000

  #
  # UEFI Stack
  #
  gArmPlatformTokenSpaceGuid.PcdCPUCoresStackBase|0x9FF90000
  gArmPlatformTokenSpaceGuid.PcdCPUCorePrimaryStackSize|0x40000

  #
  # SMBIOS
  #
  gSiliciumPkgTokenSpaceGuid.PcdSmbiosSystemManufacturer|"Xiaomi"
  gSiliciumPkgTokenSpaceGuid.PcdSmbiosSystemModel|"Mi Pad 4"
  gSiliciumPkgTokenSpaceGuid.PcdSmbiosSystemRetailModel|"clover"
  gSiliciumPkgTokenSpaceGuid.PcdSmbiosSystemRetailSku|"Mi_Pad_4_clover-lte"
  gSiliciumPkgTokenSpaceGuid.PcdSmbiosSystemBoardModel|"Mi Pad 4"

  #
  # Simple Frame Buffer
  #
  gSiliciumPkgTokenSpaceGuid.PcdFrameBufferWidth|1200
  gSiliciumPkgTokenSpaceGuid.PcdFrameBufferHeight|1920
  gSiliciumPkgTokenSpaceGuid.PcdFrameBufferColorDepth|32

  #
  # Platform PEI
  #
  gQcomPkgTokenSpaceGuid.PcdPlatformType|"LA"

[LibraryClasses]
  #
  # Memory Libraries
  #
  MemoryMapLib|cloverPkg/Library/MemoryMapLib/MemoryMapLib.inf

  #
  # QCOM Libraries
  #
  ConfigurationMapLib|cloverPkg/Library/ConfigurationMapLib/ConfigurationMapLib.inf

  #
  # UniXNU is only mapped when the firmware is built through the UniXNU driver:
  # it puts the UniXNU package and DarwinBoot on PACKAGES_PATH
  # ({tree}/package and {tree}/drivers/DarwinBoot) and passes -D UNIXNU_BUILD=1.
  # A plain "python3 build_uefi.py -d clover" build stays buildable without them.
  #
!ifdef $(UNIXNU_BUILD)
  UniXNULib|UniXNUPkg/Library/UniXNULib/UniXNULib.inf
!endif

[Components]
  #
  # ACPI Tables. Silicium-ACPI has no clover board directory yet, so no tables
  # are compiled; gta4l leaves the same line commented out for that reason.
  #
  #clover/AcpiTables.inf

!ifdef $(UNIXNU_BUILD)
  #
  # UniXNU boot manager: the menu application, the DXE driver that registers its
  # Boot#### option, and the DarwinBoot loader that hands the ADT over to XNU.
  # The matching INF lines are in Include/DXE.inc.
  #
  UniXNUPkg/Application/UniXNU/UniXNU.inf
  UniXNUPkg/Driver/UniXNUDxe/UniXNUDxe.inf
  DarwinBootPkg/Driver/DarwinBoot.inf
!endif
