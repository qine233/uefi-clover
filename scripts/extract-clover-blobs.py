#!/usr/bin/env python3
"""Carve the prebuilt DXE binaries the clover overlay needs out of the tablet.

clover has no `uefi` partition.  Its UEFI firmware volume lives as a gzip stream
inside the `xbl` partition, which the Qualcomm SEC decompresses into DRAM at
boot, so `xbl` is where the blobs come from:

    scripts/extract-clover-blobs.py --xbl facts/.../fw/p-xbl.bin
    scripts/extract-clover-blobs.py --fv  facts/.../fw/xbl-gzip-0xa89b0.bin --list

What gets written is decided by this repository's own FDF includes, never by
guesswork: every `INF Binaries/clover/...inf` in Include/APRIORI.inc, every
`INF Binaries/clover/...inf` in Include/DXE.inc and every
`SECTION RAW = Binaries/clover/...` in Include/RAW.inc is one output file set.
Each module is then located inside the firmware volume by its FILE_GUID, which is
stable across Xiaomi's SDM660 boards (verified against the published lavender
binaries: SdccDxe carries F10F76DB-42C1-533F-34A8-69BE24653110 in both), and the
stub INF is regenerated from the [Defines] block upstream uses for that GUID.

Both INF branches of the `!if $(USE_CUSTOM_DISPLAY_DRIVER)` guards are extracted,
so flipping the flag in clover.dsc does not need a re-dump.

Output goes to <checkout>/Binaries/clover, or to ./Binaries/clover in this
repository when no --checkout is given.  That directory is gitignored: the blobs
are the tablet's proprietary firmware, and proprietary-files.txt is the
reviewable record of them.

Exit status is 1 if any requested blob could not be produced.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import struct
import sys
import zlib

REPO = pathlib.Path(__file__).resolve().parents[1]
PKG = REPO / "Platforms" / "Xiaomi" / "cloverPkg"
INCLUDE = PKG / "Include"

FFS2_GUID = "8C8CE578-8A3D-4F1C-9935-896185C32DD3"

# Section type byte -> EDK II name.  Only the ones a prebuilt module carries.
SECTION_NAMES = {0x01: "COMPRESSION", 0x02: "GUID_DEFINED", 0x05: "PEI_DEPEX",
                 0x07: "SMM_DEPEX", 0x10: "PE32", 0x11: "PIC", 0x12: "TE",
                 0x13: "DXE_DEPEX", 0x14: "VERSION", 0x15: "USER_INTERFACE",
                 0x16: "compat16", 0x17: "FV_IMAGE", 0x19: "RAW", 0x1C: "FIXED_LOAD",
                 0x1D: "OPT_EXEC"}

# (FILE_GUID, path under Binaries/<device>/, BASE_NAME, MODULE_TYPE, ENTRY_POINT,
#  [Binaries.AARCH64] entries)
#
# Transcribed from Project-Silicium/Device-Binaries, lavender branch -- the other
# SDM660 Xiaomi board, same QcomPkg.  It is the authority for the two things the
# firmware volume cannot tell us (MODULE_TYPE and whether the module's INF has a
# [Depex] at all) and for the directory names the drivers are filed under, which
# do not always match the path baked into the binary.  Upstream ships
# ButtonsDxe/ClockDxe/UsbMsdDxe as *.patched.efi; that is their own local edit, so
# the table below names the plain .efi and this script writes the stock bytes.
UPSTREAM = [
    ("DE371F7C-DEC4-4D21-ADF1-593ABCC15882", "ArmPkg/Drivers/ArmGic/ArmGicDxe.inf", "ArmGicDxe", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|ArmGicDxe.depex;PE32|ArmGicDxe.efi"),
    ("B8D9777E-D72A-451F-9BDB-BAFB52A68415", "ArmPkg/Drivers/CpuDxe/CpuDxe.inf", "ArmCpuDxe", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|CpuDxe.depex;PE32|CpuDxe.efi"),
    ("49EA041E-6752-42CA-B0B1-7344FE2546B7", "ArmPkg/Drivers/TimerDxe/TimerDxe.inf", "ArmTimerDxe", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|TimerDxe.depex;PE32|TimerDxe.efi"),
    ("4C6E0267-C77D-410D-8100-1495911A989D", "EmbeddedPkg/MetronomeDxe/MetronomeDxe.inf", "MetronomeDxe", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|MetronomeDxe.depex;PE32|MetronomeDxe.efi"),
    ("B336F62D-4135-4A55-AE4E-4971BBF0885D", "EmbeddedPkg/RealTimeClockRuntimeDxe/RealTimeClockRuntimeDxe.inf", "RealTimeClock", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|RealTimeClockRuntimeDxe.depex;PE32|RealTimeClockRuntimeDxe.efi"),
    ("961578FE-B6B7-44C3-AF35-6BC705CD2B1F", "FatPkg/EnhancedFatDxe/Fat.inf", "Fat", "UEFI_DRIVER", "",
            "PE32|Fat.efi"),
    ("D6A2CB7F-6A18-4E2F-B43B-9920A733700A", "MdeModulePkg/Core/Dxe/DxeMain.inf", "DxeCore", "DXE_CORE", "",
            "PE32|DxeMain.efi"),
    ("B601F8C4-43B7-4784-95B1-F4226CB40CEE", "MdeModulePkg/Core/RuntimeDxe/RuntimeDxe.inf", "RuntimeDxe", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|RuntimeDxe.depex;PE32|RuntimeDxe.efi"),
    ("42857F0A-13F2-4B21-8A23-53D3F714B840", "MdeModulePkg/Universal/CapsuleRuntimeDxe/CapsuleRuntimeDxe.inf", "CapsuleRuntimeDxe", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|CapsuleRuntimeDxe.depex;PE32|CapsuleRuntimeDxe.efi"),
    ("51CCF399-4FDF-4E55-A45B-E123F84D456A", "MdeModulePkg/Universal/Console/ConPlatformDxe/ConPlatformDxe.inf", "ConPlatformDxe", "UEFI_DRIVER", "",
            "PE32|ConPlatformDxe.efi"),
    ("408EDCEC-CF6D-477C-A5A8-B4844E3DE281", "MdeModulePkg/Universal/Console/ConSplitterDxe/ConSplitterDxe.inf", "ConSplitterDxe", "UEFI_DRIVER", "",
            "PE32|ConSplitterDxe.efi"),
    ("CCCB0C28-4B24-11D5-9A5A-0090273FC14D", "MdeModulePkg/Universal/Console/GraphicsConsoleDxe/GraphicsConsoleDxe.inf", "GraphicsConsoleDxe", "UEFI_DRIVER", "",
            "PE32|GraphicsConsoleDxe.efi"),
    ("9B680FCE-AD6B-4F3A-B60B-F59899003443", "MdeModulePkg/Universal/DevicePathDxe/DevicePathDxe.inf", "DevicePathDxe", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|DevicePathDxe.depex;PE32|DevicePathDxe.efi"),
    ("CD3BAFB6-50FB-4FE8-8E4E-AB74D2C1A600", "MdeModulePkg/Universal/Disk/UnicodeCollation/EnglishDxe/EnglishDxe.inf", "EnglishDxe", "UEFI_DRIVER", "",
            "PE32|EnglishDxe.efi"),
    ("907125C0-A5F1-11E3-A3FE-A3198B49350C", "MdeModulePkg/Universal/FvSimpleFileSystemDxe/FvSimpleFileSystemDxe.inf", "FvSimpleFileSystem", "UEFI_DRIVER", "",
            "PE32|FvSimpleFileSystemDxe.efi"),
    ("348C4D62-BFBD-4882-9ECE-C80BB1C4783B", "MdeModulePkg/Universal/HiiDatabaseDxe/HiiDatabaseDxe.inf", "HiiDatabase", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|HiiDatabaseDxe.depex;PE32|HiiDatabaseDxe.efi"),
    ("79E4A61C-ED73-4312-94FE-E3E7563362A9", "MdeModulePkg/Universal/PrintDxe/PrintDxe.inf", "PrintDxe", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|PrintDxe.depex;PE32|PrintDxe.efi"),
    ("D93CE3D8-A7EB-4730-8C8E-CC466A9ECC3C", "MdeModulePkg/Universal/ReportStatusCodeRouter/RuntimeDxe/ReportStatusCodeRouterRuntimeDxe.inf", "ReportStatusCodeRouterRuntimeDxe", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|ReportStatusCodeRouterRuntimeDxe.depex;PE32|ReportStatusCodeRouterRuntimeDxe.efi"),
    ("6C2004EF-4E0E-4BE4-B14C-340EB4AA5891", "MdeModulePkg/Universal/StatusCodeHandler/RuntimeDxe/StatusCodeHandlerRuntimeDxe.inf", "StatusCodeHandlerRuntimeDxe", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|StatusCodeHandlerRuntimeDxe.depex;PE32|StatusCodeHandlerRuntimeDxe.efi"),
    ("02B01AD5-7E59-43E8-A6D8-238180613A5A", "MdeModulePkg/Universal/Variable/EmuRuntimeDxe/EmuVariableRuntimeDxe.inf", "EmuVariableRuntimeDxe", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|EmuVariableRuntimeDxe.depex;PE32|EmuVariableRuntimeDxe.efi"),
    ("F099D67F-71AE-4C36-B2A3-DCEB0EB2B7D8", "MdeModulePkg/Universal/WatchdogTimerDxe/WatchdogTimer.inf", "WatchdogTimer", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|WatchdogTimer.depex;PE32|WatchdogTimer.efi"),
    ("068AAE46-BDC6-4073-85D5-31C5EEF19A15", "MiPkg/Protocol/MiToken/MiToken.inf", "MiTokenDxe", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|MiToken.depex;PE32|MiToken.efi"),
    ("EEE9C2B1-16CA-4F34-87EA-2E6D1E160CC4", "QcomPkg/Application/QcomChargerApp/QcomChargerApp.inf", "QcomChargerApp", "UEFI_APPLICATION", "",
            "PE32|QcomChargerApp.efi"),
    ("C2F9A4F5-F7B4-43E7-BA99-5EA804CC103A", "QcomPkg/Drivers/ASN1X509Dxe/ASN1X509Dxe.inf", "ASN1X509Dxe", "UEFI_DRIVER", "",
            "PE32|ASN1X509Dxe.efi"),
    ("5A5CB8CA-9382-4E0C-B383-77FB517CD9EB", "QcomPkg/Drivers/AdcDxe/AdcDxe.inf", "AdcDxe", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|AdcDxe.depex;PE32|AdcDxe.efi"),
    ("5BD181DB-0487-4F1A-AE73-820E165611B3", "QcomPkg/Drivers/ButtonsDxe/ButtonsDxe.inf", "ButtonsDxe", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|ButtonsDxe.depex;PE32|ButtonsDxe.efi"),
    ("2E3042F3-2BB9-463F-8866-56D75B7C4AB0", "QcomPkg/Drivers/ChargerExDxe/ChargerExDxe.inf", "ChargerExDxe", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|ChargerExDxe.depex;PE32|ChargerExDxe.efi"),
    ("10E193DF-9966-44E7-B17C-59DD831E20FC", "QcomPkg/Drivers/ChipInfoDxe/ChipInfoDxe.inf", "ChipInfo", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|ChipInfoDxe.depex;PE32|ChipInfoDxe.efi"),
    ("4DB5DEA6-5302-4D1A-8A82-677A683B0D29", "QcomPkg/Drivers/ClockDxe/ClockDxe.inf", "ClockDxe", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|ClockDxe.depex;PE32|ClockDxe.efi"),
    ("8E9BD160-B184-11DF-94E2-0800200C9A66", "QcomPkg/Drivers/DALSYSDxe/DALSYSDxe.inf", "DALSys", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|DALSYSDxe.depex;PE32|DALSYSDxe.efi"),
    ("6B38F7B4-AD98-40E9-9093-ACA2B5A253C4", "QcomPkg/Drivers/DiskIoDxe/DiskIoDxe.inf", "DiskIoDxe", "UEFI_DRIVER", "",
            "PE32|DiskIoDxe.efi"),
    ("4138022F-06C7-4F79-9C94-7E33B511A4E7", "QcomPkg/Drivers/DisplayDxe/DisplayDxe.inf", "DisplayDxe", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|DisplayDxe.depex;PE32|DisplayDxe.efi"),
    ("37795BA0-E1CF-4ED5-BD8B-16DF6BCB1E1A", "QcomPkg/Drivers/EmbeddedMonotonicCounter/EmbeddedMonotonicCounter.inf", "EmbeddedMonotonicCounter", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|EmbeddedMonotonicCounter.depex;PE32|EmbeddedMonotonicCounter.efi"),
    ("90A49AFD-422F-08AE-9611-E788D3804845", "QcomPkg/Drivers/EnvDxe/EnvDxe.inf", "EnvDxe", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|EnvDxe.depex;PE32|EnvDxe.efi"),
    ("ED15FFD5-BC96-4107-9118-95366600188E", "QcomPkg/Drivers/FontDxe/FontDxe.inf", "FontDxe", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|FontDxe.depex;PE32|FontDxe.efi"),
    ("7942A7EB-B7D5-4E2E-B908-831E4DE55B58", "QcomPkg/Drivers/GLinkDxe/GLinkDxe.inf", "GlinkDxe", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|GLinkDxe.depex;PE32|GLinkDxe.efi"),
    ("AF9763A2-033B-4109-8E17-56A98D380C92", "QcomPkg/Drivers/HWIODxe/HWIODxe.inf", "HWIODxeDriver", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|HWIODxe.depex;PE32|HWIODxe.efi"),
    ("3ADF8DDA-1850-44C5-8C63-BB991849BC6F", "QcomPkg/Drivers/HashDxe/HashDxe.inf", "HashDxe", "UEFI_DRIVER", "",
            "PE32|HashDxe.efi"),
    ("04DE8591-D2B3-4077-BBBE-B12070094EB6", "QcomPkg/Drivers/I2CDxe/I2CDxe.inf", "I2C", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|I2CDxe.depex;PE32|I2CDxe.efi"),
    ("F09AD92E-4E91-490F-AB99-E69939B840B2", "QcomPkg/Drivers/LimitsDxe/LimitsDxe.inf", "LimitsDxe", "UEFI_DRIVER", "",
            "PE32|LimitsDxe.efi"),
    ("409D636E-8DBB-46DF-AE8F-D8D69F0A5A2F", "QcomPkg/Drivers/MdtpDxe/MdtpDxe.inf", "MdtpDxe", "UEFI_DRIVER", "",
            "PE32|MdtpDxe.efi"),
    ("88ABF42E-EFA7-4D72-A9C8-8B29ACDCF64F", "QcomPkg/Drivers/MpPowerDxe/MpPowerDxe.inf", "MpPowerDxe", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|MpPowerDxe.depex;PE32|MpPowerDxe.efi"),
    ("CB29F4D1-7F37-4692-A416-93E82E219711", "QcomPkg/Drivers/NpaDxe/NpaDxe.inf", "NpaDxe", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|NpaDxe.depex;PE32|NpaDxe.efi"),
    ("1FA1F39E-FEFF-4AAE-BD7B-38A070A3B609", "QcomPkg/Drivers/PartitionDxe/PartitionDxe.inf", "PartitionDxe", "UEFI_DRIVER", "",
            "PE32|PartitionDxe.efi"),
    ("B105211B-BBBD-4ADD-A3B0-D1CF4A52154C", "QcomPkg/Drivers/PlatformInfoDxe/PlatformInfoDxe.inf", "PlatformInfoDxeDriver", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|PlatformInfoDxe.depex;PE32|PlatformInfoDxe.efi"),
    ("5776232E-082D-4B75-9A0E-FE1D13F7A5D9", "QcomPkg/Drivers/PmicDxe/PmicDxeLa.inf", "PmicDxe", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|PmicDxeLa.depex;PE32|PmicDxeLa.efi"),
    ("5A50AA81-C3AE-4608-A0E3-41A2E69BAF94", "QcomPkg/Drivers/QcomBds/QcomBds.inf", "QcomBds", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|QcomBds.depex;PE32|QcomBds.efi"),
    ("4BCE7F36-428E-4393-99E3-7E0844404DBA", "QcomPkg/Drivers/QcomChargerDxe/QcomChargerDxeLA.inf", "QcomChargerDxeLA", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|QcomChargerDxeLA.depex;PE32|QcomChargerDxeLA.efi"),
    ("B003D837-44CC-B38B-7811-DEB5EBBD74D8", "QcomPkg/Drivers/QdssDxe/QdssDxe.inf", "QdssDxe", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|QdssDxe.depex;PE32|QdssDxe.efi"),
    ("B0D3689E-11F8-43C6-8ECE-023A29CEC35B", "QcomPkg/Drivers/RNGDxe/RngDxe.inf", "RngDxe", "UEFI_DRIVER", "",
            "PE32|RngDxe.efi"),
    ("3AE17DB7-3CC5-4B89-9304-9549211057EF", "QcomPkg/Drivers/ResetRuntimeDxe/ResetRuntimeDxe.inf", "ResetRuntimeDxe", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|ResetRuntimeDxe.depex;PE32|ResetRuntimeDxe.efi"),
    ("7A32BD23-F735-4F57-AA1A-447D2FE3BE0D", "QcomPkg/Drivers/SPIDxe/SPIDxe.inf", "SPI", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|SPIDxe.depex;PE32|SPIDxe.efi"),
    ("2A7B4BEF-80CD-49E1-B473-374BA4D673FC", "QcomPkg/Drivers/SPMIDxe/SPMIDxe.inf", "SPMI", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|SPMIDxe.depex;PE32|SPMIDxe.efi"),
    ("F10F76DB-42C1-533F-34A8-69BE24653110", "QcomPkg/Drivers/SdccDxe/SdccDxe.inf", "SdccDxe", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|SdccDxe.depex;PE32|SdccDxe.efi"),
    ("32C71E68-83A8-46ED-AED1-094E71B12057", "QcomPkg/Drivers/SecRSADxe/SecRSADxe.inf", "SecRSADxe", "UEFI_DRIVER", "",
            "PE32|SecRSADxe.efi"),
    ("5E0EAE60-EAED-4D75-B8BF-EDBBAABC3F09", "QcomPkg/Drivers/SecurityDxe/SecurityDxe.inf", "SecurityDxe", "UEFI_DRIVER", "",
            "PE32|SecurityDxe.efi"),
    ("857A8741-0EEC-43BD-9482-27D14ED47D72", "QcomPkg/Drivers/SimpleTextInOutSerialDxe/SimpleTextInOutSerial.inf", "SimpleTextInOutSerial", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|SimpleTextInOutSerial.depex;PE32|SimpleTextInOutSerial.efi"),
    ("F541D663-4A48-40AA-AABF-FF158CCAE34C", "QcomPkg/Drivers/SmemDxe/SmemDxe.inf", "SmemDxe", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|SmemDxe.depex;PE32|SmemDxe.efi"),
    ("8681CC5A-0DF6-441E-B4B8-E915C538F067", "QcomPkg/Drivers/TLMMDxe/TLMMDxe.inf", "DALTLMM", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|TLMMDxe.depex;PE32|TLMMDxe.efi"),
    ("F09AD92E-485C-9CDB-3E05-3385C38F94CC", "QcomPkg/Drivers/TsensDxe/TsensDxe.inf", "TsensDxe", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|TsensDxe.depex;PE32|TsensDxe.efi"),
    ("6925FAD3-E243-4B69-AD61-3F978C8ABC60", "QcomPkg/Drivers/TzDxe/TzDxeLA.inf", "TzDxe", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|TzDxeLA.depex;PE32|TzDxeLA.efi"),
    ("0D35CD8E-97EA-4F9A-96AF-0F0D89F76567", "QcomPkg/Drivers/UFSDxe/UFSDxe.inf", "UFSDxe", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|UFSDxe.depex;PE32|UFSDxe.efi"),
    ("E43128A8-8692-42B6-8AFA-676158578D18", "QcomPkg/Drivers/ULogDxe/ULogDxe.inf", "ULogDxe", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|ULogDxe.depex;PE32|ULogDxe.efi"),
    ("CD823A4D-7DEC-4531-AE5D-4134FA4127B8", "QcomPkg/Drivers/UsbConfigDxe/UsbConfigDxe.inf", "UsbConfigDxe", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|UsbConfigDxe.depex;PE32|UsbConfigDxe.efi"),
    ("3299A266-15F0-4346-8318-716336736D3E", "QcomPkg/Drivers/UsbDeviceDxe/UsbDeviceDxe.inf", "UsbDeviceDxe", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|UsbDeviceDxe.depex;PE32|UsbDeviceDxe.efi"),
    ("5AF77F10-90DF-4E7E-8325-A17EC09D5443", "QcomPkg/Drivers/UsbMsdDxe/UsbMsdDxe.inf", "UsbMsdDxe", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|UsbMsdDxe.depex;PE32|UsbMsdDxe.efi"),
    ("94F8A6A7-DC34-4101-88C1-99179CCEAE83", "QcomPkg/Drivers/UsbfnDwc3Dxe/UsbfnDwc3Dxe.inf", "UsbfnDwc3Dxe", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|UsbfnDwc3Dxe.depex;PE32|UsbfnDwc3Dxe.efi"),
    ("A25F5839-4D55-428F-8F0B-5CE1D565F53E", "QcomPkg/Drivers/VerifiedBootDxe/VerifiedBootDxe.inf", "VerifiedBootDxe", "DXE_DRIVER", "EfiEntry",
            "DXE_DEPEX|VerifiedBootDxe.depex;PE32|VerifiedBootDxe.efi"),
]

UPSTREAM_BY_PATH = {row[1]: row for row in UPSTREAM}
UPSTREAM_BY_GUID = {row[0]: row for row in UPSTREAM}


def note(mark: str, message: str) -> None:
    print(f"  {mark}  {message}")


def align(value: int, boundary: int) -> int:
    return (value + boundary - 1) & ~(boundary - 1)


def format_guid(raw: bytes) -> str:
    """EFI_GUID is mixed-endian: the first three fields are little endian."""
    d1, d2, d3 = struct.unpack_from("<IHH", raw)
    return ("%08X-%04X-%04X-%s-%s" % (d1, d2, d3, raw[8:10].hex().upper(),
                                      raw[10:16].hex().upper())).upper()


def find_fv(blob: bytes, problems: list) -> bytes | None:
    """Return the firmware volume inside a raw partition image.

    SEC gunzips this stream into the FV Region before handing control to DXE, so
    the only reliable markers are the FFS2 file-system GUID and the _FVH
    signature Qualcomm prefixes the volume with an 8-byte cookie, which is why the
    header fields are located relative to the volume start rather than the stream.
    """
    candidates = [m.start() for m in re.finditer(b"\x1f\x8b\x08", blob)]
    for offset in candidates:
        try:
            out = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(blob[offset:])
        except zlib.error:
            continue
        fv = as_fv(out, problems, f"gzip at {offset:#x}")
        if fv is not None:
            note("*", f"firmware volume is the gzip stream at {offset:#x} "
                      f"({len(out)} bytes out)")
            return fv
    problems.append("no gzip stream in the image expands to an EDK II firmware "
                    "volume; is this really the xbl partition?")
    return None


def as_fv(data: bytes, problems: list, where: str) -> bytes | None:
    """Validate a buffer as a firmware volume and return it, or None."""
    hit = data.find(b"_FVH")
    if hit < 0 or hit < 0x28:
        return None
    base = hit - 0x28
    if format_guid(data[base + 0x10:base + 0x20]) != FFS2_GUID:
        return None
    length = struct.unpack_from("<Q", data, base + 0x20)[0]
    if length > len(data) - base:
        return None
    header_length = struct.unpack_from("<H", data, base + 0x30)[0]
    if header_length < 0x48 or base + header_length > length:
        return None
    note("*", f"{where}: firmware volume at {base:#x}, {length:#x} bytes, "
              f"header {header_length:#x}, attributes {struct.unpack_from('<I', data, base + 0x2c)[0]:#010x}")
    return data[base:base + length]


def iter_files(fv: bytes):
    """Walk the FFS file records.

    Qualcomm keeps the standard EDK II fields two bytes late: the type byte sits
    where the specification puts the first Size byte, attributes hold 0xAA, and
    the state byte is where the size ends.  The 24-bit size counts the record
    header itself, so the next file starts at align8(start + size); reading the
    size as payload-only makes every record look like it overlaps its neighbour by
    0x18, which is what sent the first attempt down a dead end.
    """
    header_length = struct.unpack_from("<H", fv, 0x30)[0]
    end = len(fv)
    offset = align(header_length, 8)
    while offset + 24 <= end:
        state_ok = fv[offset + 17] == 0xAA and fv[offset + 19] == 0 and fv[offset + 23] == 0xF8
        if not state_ok:
            # A 16-byte free-space marker, or the padding that closes the volume.
            if fv[offset:offset + 16] == b"\xff" * 16:
                offset += 16
                continue
            break
        size = int.from_bytes(fv[offset + 20:offset + 23], "little")
        if size < 24 or offset + size > end:
            break
        yield {"offset": offset, "guid": format_guid(fv[offset:offset + 16]),
               "type": fv[offset + 18], "size": size}
        offset = align(offset + size, 8)


def iter_sections(fv: bytes, ffs: dict):
    """Yield (type, payload) for one file.  Sections advance by align4(size)."""
    cursor = ffs["offset"] + 24
    stop = ffs["offset"] + ffs["size"]
    while cursor + 4 <= stop:
        size = int.from_bytes(fv[cursor:cursor + 3], "little")
        kind = fv[cursor + 3]
        if size < 4 or cursor + size > ffs["offset"] + ffs["size"] + 4:
            # Trailing alignment padding inside the record, not a broken file:
            # keep everything already parsed rather than discarding the module.
            break
        yield kind, fv[cursor + 4:cursor + align(size, 4)][:size - 4]
        cursor = align(cursor + size, 4)


def ui_name(payload: bytes) -> str:
    text = payload.decode("utf-16-le", errors="replace").split("\x00")[0]
    return text if re.fullmatch(r"[ -~]{1,64}", text) else ""


def describe(payload: bytes) -> str:
    """Name a PE32 payload after the build path its vendor baked into .text."""
    match = re.search(rb"Build/Sdm660LA_Core/RELEASE_CLANG38LINUX/AARCH64/([ -~]+?)\x00",
                      payload)
    return match.group(1).decode() if match else ""


def is_pe32(payload: bytes) -> bool:
    if not payload.startswith(b"MZ") or len(payload) < 0x1000:
        return False
    new_exe = struct.unpack_from("<I", payload, 0x3C)[0]
    return payload[new_exe:new_exe + 4] == b"PE\x00\x00" and \
        struct.unpack_from("<H", payload, new_exe + 4)[0] == 0xAA64


def inventory(fv: bytes) -> list:
    """Every file in the volume, with its sections resolved."""
    files = []
    for ffs in iter_files(fv):
        entry = {"guid": ffs["guid"], "type": ffs["type"], "offset": ffs["offset"],
                 "size": ffs["size"], "ui": "", "pdb": "", "pe32": None,
                 "depex": None, "raw": None, "kinds": []}
        for kind, payload in iter_sections(fv, ffs):
            name = SECTION_NAMES.get(kind, f"{kind:#04x}")
            entry["kinds"].append(name)
            if kind == 0x15 and not entry["ui"]:
                entry["ui"] = ui_name(payload)
            elif kind == 0x10:
                entry["pe32"] = payload
                entry["pdb"] = describe(payload)
            elif kind == 0x13:
                entry["depex"] = payload
            elif kind == 0x19 and entry["raw"] is None:
                entry["raw"] = payload
        files.append(entry)
    return files


def read_requests(problems: list) -> tuple:
    """The blob paths this overlay's own firmware volume description asks for."""
    inf, raw = [], []
    for name in ("APRIORI.inc", "DXE.inc"):
        path = INCLUDE / name
        if not path.is_file():
            problems.append(f"Include/{name} is missing")
            continue
        for line in path.read_text().splitlines():
            line = line.split("#")[0]
            m = re.search(r"\bINF\s+(Binaries/clover/\S+\.inf)", line)
            if m and m.group(1) not in inf:
                inf.append(m.group(1))
    path = INCLUDE / "RAW.inc"
    if path.is_file():
        for line in path.read_text().splitlines():
            line = line.split("#")[0]
            m = re.search(r"SECTION\s+RAW\s*=\s*(Binaries/clover/\S+)", line)
            if m and m.group(1) not in raw:
                raw.append(m.group(1))
    return inf, raw


def stub_inf(row) -> str:
    """A prebuilt-module INF in the shape EDK II and upstream both use."""
    guid, rel, base, mtype, entry, bins = row
    lines = ["[Defines]",
             "  INF_VERSION                    = 0x0001001B",
             f"  BASE_NAME                      = {base}",
             f"  FILE_GUID                      = {guid}",
             f"  MODULE_TYPE                    = {mtype}",
             "  VERSION_STRING                 = 1.0"]
    if entry:
        lines.append(f"  ENTRY_POINT                    = {entry}")
    lines.append("")
    lines.append("[Binaries.AARCH64]")
    for spec in bins.split(";"):
        kind, filename = spec.split("|")
        lines.append(f"  {kind}|{filename}|*")
    if any(spec.startswith("DXE_DEPEX|") for spec in bins.split(";")):
        lines += ["", "[Depex]", "  TRUE"]
    return "\n".join(lines) + "\n"


def write(path: pathlib.Path, data: bytes, written: list, dry: bool) -> None:
    written.append((path, len(data)))
    if dry:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--xbl", type=pathlib.Path,
                        help="a raw dump of the xbl partition; the firmware volume "
                             "is found inside it as a gzip stream")
    source.add_argument("--fv", type=pathlib.Path,
                        help="the already decompressed firmware volume")
    parser.add_argument("--checkout", type=pathlib.Path,
                        help="Mu-Silicium workspace to populate; the blobs land in "
                             "<checkout>/Binaries/clover")
    parser.add_argument("--out", type=pathlib.Path,
                        help="write into this directory instead (default: "
                             "./Binaries/clover in this repository, which is gitignored)")
    parser.add_argument("--list", action="store_true",
                        help="print the firmware volume inventory and write nothing")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    problems: list = []
    blob = (args.xbl if args.xbl else args.fv).expanduser().resolve()
    if not blob.is_file():
        print(f"{blob} is not a file", file=sys.stderr)
        return 1
    data = blob.read_bytes()

    fv = data if args.fv else None
    if args.fv:
        fv = as_fv(data, problems, blob.name)
        if fv is None:
            # A volume dumped without the Qualcomm cookie in front of it still has
            # _FVH at 0x28, so as_fv finds it; anything else is the wrong file.
            problems.append(f"{blob.name} is not an EDK II firmware volume "
                            "(no FFS2 GUID in front of an _FVH header)")
            return report(problems, [], 0, 0)
    else:
        fv = find_fv(data, problems)
        if fv is None:
            return report(problems, [], 0, 0)

    files = inventory(fv)
    by_guid = {}
    for ffs in files:
        by_guid.setdefault(ffs["guid"], ffs)
    by_name = {ffs["ui"]: ffs for ffs in files if ffs["ui"]}

    if args.list:
        print(f"{'GUID':38} {'off':>8} {'size':>8}  sections")
        for ffs in files:
            label = ffs["ui"] or ffs["pdb"] or "unnamed"
            print(f"{ffs['guid']:38} {ffs['offset']:#8x} {ffs['size']:#8x}  "
                  f"{','.join(ffs['kinds']) or '-'}  {label}")
        note("*", f"{len(files)} files, {len(by_guid)} GUIDs, "
                  f"{sum(1 for f in files if f['pe32'])} PE32 images")
        return 0

    wanted_inf, wanted_raw = read_requests(problems)
    out = args.out or (args.checkout / "Binaries" / "clover" if args.checkout
                       else REPO / "Binaries" / "clover")
    out = out.expanduser().resolve()

    written: list = []
    missing = []
    for request in wanted_inf:
        rel = request[len("Binaries/clover/"):]
        row = UPSTREAM_BY_PATH.get(rel)
        if row is None:
            problems.append(f"{request} is not a module upstream describes; "
                            "add it to UPSTREAM or fix the include")
            continue
        ffs = by_guid.get(row[0])
        if ffs is None:
            missing.append(rel)
            continue
        target = out / rel
        for spec in row[5].split(";"):
            kind, filename = spec.split("|")
            if kind == "PE32":
                payload = ffs["pe32"]
                if payload is None or not is_pe32(payload):
                    problems.append(f"{rel}: the volume has no AArch64 PE32 section "
                                    f"for {row[0]}")
                    continue
                write(target.parent / filename, payload, written, args.dry_run)
            elif kind == "DXE_DEPEX":
                if ffs["depex"] is None:
                    problems.append(f"{rel} declares {filename} but the volume has no "
                                    "DXE_DEPEX section for it")
                    continue
                write(target.parent / filename, ffs["depex"], written, args.dry_run)
        write(target, stub_inf(row).encode(), written, args.dry_run)

    for request in wanted_raw:
        rel = request[len("Binaries/clover/"):]
        name = pathlib.PurePosixPath(rel).name
        ffs = by_name.get(name)
        if ffs is None or ffs["raw"] is None:
            missing.append(rel)
            continue
        write(out / rel, ffs["raw"], written, args.dry_run)

    for rel in sorted(missing):
        problems.append(f"Binaries/clover/{rel} is asked for by the overlay but is "
                        "not in the volume")

    # Anything in the volume that a clover build could use but nobody asked for is
    # worth a line: it is how a driver gets noticed before it gets missed.
    extra = [ffs for ffs in files
             if ffs["pe32"] is not None and ffs["guid"] not in UPSTREAM_BY_GUID]
    note("*", f"{len(files)} files in the volume, {len(wanted_inf)} INF + "
              f"{len(wanted_raw)} RAW requested, {len(written)} files written to {out}")
    if extra:
        note("-", f"{len(extra)} PE32 modules in the volume have no entry in UPSTREAM "
                  "(stock-only drivers, or a renamed module): "
                  + ", ".join((f["ui"] or f["pdb"].split('/')[-1] or f["guid"])
                              for f in extra[:12])
                  + (" ..." if len(extra) > 12 else ""))
    return report(problems, [], len(written), 0)


def report(problems: list, warnings: list, written: int, checked: int) -> int:
    for message in warnings:
        note("!", message)
    for message in problems:
        note("x", message)
    if problems:
        print(f"\n{len(problems)} error(s); {written} files written")
        return 1
    print(f"\nok: {written} blob files written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
