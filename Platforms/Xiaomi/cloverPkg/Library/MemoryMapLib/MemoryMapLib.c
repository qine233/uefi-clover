/**
  Memory map for the Xiaomi Mi Pad 4 8" LTE (clover, Qualcomm SDM660).

  The DDR half is rebuilt from clover's own device tree rather than copied from
  lavender, because the two boards place the splash buffer differently:
  clover-overlay.dtsi moves cont_splash_mem to 0x9d500000 (+0x2400000), one
  megabyte above lavender's 0x9d400000, and the 4 GiB unit maps its second bank
  at 0x1800000000, which this first bring-up does not describe.

  Region            Address      Length      Source
  ----------------  -----------  ----------  ------------------------------------
  Kernel            0x80000000   0x05800000  sdm660-common.dtsi (wlan_msa tail)
  Boot Removed      0x85800000   0x00800000  removed_regions, no-map
  SMEM              0x86000000   0x00200000  smem_mem
  TZ APPS           0x86D00000   0x02200000  qcom_seecom, = TzAppsRegn* in
                                              Library/ConfigurationMapLib
  Modem FW          0x8AC00000   0x07E00000  modem_fw_mem
  PIL Reserved      0x92A00000   0x02700000  the clover overlay's adsp_fw_mem
                                              (0x1f00000) + pil_mba_mem
                                              (0x94900000+0x200000) +
                                              cdsp_fw_mem (0x94b00000+0x600000),
                                              which are contiguous up to
                                              0x95100000
  DXE Heap          0x95100000   0x08400000  the free run between the PIL block
                                              and the splash base
  Display Reserved  0x9D500000   0x02400000  cont_splash_mem, UniXNU display-base
  FV Region         0x9F900000   0x00100000  squeezed to 1 MiB by the moved splash
  ABOOT FV          0x9FA00000   0x00200000  as lavender
  UEFI FD           0x9FC00000   0x00300000  Resources/Configs/clover.toml

  Two facts about the top of the low bank, both from the device tree:

    * pstore_reserve_mem (0x9fe00000 + 0x100000) falls inside the UEFI FD, which
      is where the FD has always been on SDM660 boards. Linux pstore therefore
      has no home under UniXNU; a panic goes to the UART instead.
    * removed_regions1 (0x86200000 + 0x2d00000, so up to 0x88f00000) is only
      partly reserved. Its upper 0x2200000 is qcom_seecom, the TrustZone apps
      window the boot firmware writes, and that part is kept as TZ APPS. The
      11 MiB in front of it is where the Android kernel parks its reusable
      qseecom_mem (0x1400000) and qseecom_ta_mem (0x1000000) CMA pools, and
      nothing fills them until that kernel runs, so the gap between SMEM and TZ
      APPS is handed back to UEFI. It is the one hole in the DDR half of this
      table and it is on purpose.

    removed_regions (0x85800000 + 0x800000) is the opposite case: no-map in both
    trees, and neither device tree says what lives there, only that the boot
    loader asked for it. It stays reserved as Boot Removed until a dump from the
    tablet identifies it; giving 8 MiB back is not worth guessing about.

  @copyright  SPDX-License-Identifier: BSD-2-Clause-Patent
**/

#include <Library/MemoryMapLib.h>

STATIC
EFI_MEMORY_REGION_DESCRIPTOR
gMemoryDescriptor[] = {
  // Name, Address, Length, HobOption, ResourceType, ResourceAttribute, MemoryType, ArmAttribute

  // DDR Regions
  {"Kernel",           0x80000000, 0x05800000, AddMem, SYS_MEM, SYS_MEM_CAP, Reserv, WRITE_BACK_XN},
  {"Boot Removed",     0x85800000, 0x00800000, AddMem, MEM_RES, UNCACHEABLE, Reserv, UNCACHED_UNBUFFERED_XN},
  {"SMEM",             0x86000000, 0x00200000, AddMem, MEM_RES, UNCACHEABLE, Reserv, UNCACHED_UNBUFFERED_XN},
  {"TZ APPS",          0x86D00000, 0x02200000, AddMem, MEM_RES, UNCACHEABLE, Reserv, UNCACHED_UNBUFFERED_XN},
  {"Modem FW",         0x8AC00000, 0x07E00000, AddMem, MEM_RES, UNCACHEABLE, Reserv, UNCACHED_UNBUFFERED_XN},
  {"PIL Reserved",     0x92A00000, 0x02700000, AddMem, MEM_RES, UNCACHEABLE, Reserv, UNCACHED_UNBUFFERED_XN},
  {"DXE Heap",         0x95100000, 0x08400000, AddMem, SYS_MEM, SYS_MEM_CAP, Conv,   WRITE_BACK_XN},
  {"Display Reserved", 0x9D500000, 0x02400000, AddMem, MEM_RES, SYS_MEM_CAP, Reserv, WRITE_THROUGH_XN},
  {"FV Region",        0x9F900000, 0x00100000, AddMem, SYS_MEM, SYS_MEM_CAP, BsData, WRITE_BACK_XN},
  {"ABOOT FV",         0x9FA00000, 0x00200000, AddMem, SYS_MEM, SYS_MEM_CAP, Reserv, WRITE_BACK_XN},
  {"UEFI FD",          0x9FC00000, 0x00300000, AddMem, SYS_MEM, SYS_MEM_CAP, BsData, WRITE_BACK},
  {"SEC Heap",         0x9FF00000, 0x0008C000, AddMem, SYS_MEM, SYS_MEM_CAP, BsData, WRITE_BACK_XN},
  {"MMU PageTables",   0x9FF8D000, 0x00003000, AddMem, SYS_MEM, SYS_MEM_CAP, BsData, WRITE_BACK_XN},
  {"UEFI Stack",       0x9FF90000, 0x00040000, AddMem, SYS_MEM, SYS_MEM_CAP, BsData, WRITE_BACK_XN},
  {"DBI Dump",         0x9FFD0000, 0x00027000, AddMem, SYS_MEM, SYS_MEM_CAP, RtData, WRITE_BACK_XN},
  {"Log Buffer",       0x9FFF7000, 0x00008000, AddMem, SYS_MEM, SYS_MEM_CAP, RtData, WRITE_BACK_XN},
  {"Info Blk",         0x9FFFF000, 0x00001000, AddMem, SYS_MEM, SYS_MEM_CAP, RtData, WRITE_BACK_XN},

  // TODO-DEVICE: the 4 GiB unit maps a second bank at 0x1800000000. It is not
  // described here on purpose; the first bring-up only needs the low bank, and
  // board.toml [payload] dram_size stays 0x80000000 to match this map.

  // Other Memory Regions
  {"IMEM Base",          0x14680000, 0x00040000, NoHob,  MMAP_IO, INITIALIZED, Conv,   NS_DEVICE},
  {"IMEM Cookie Base",   0x146BF000, 0x00001000, AddDev, MMAP_IO, INITIALIZED, Conv,   NS_DEVICE},
  {"QDSS_STM",           0x16000000, 0x01000000, AddDev, MMAP_IO, INITIALIZED, Conv,   NS_DEVICE},

  // Register Regions. These are the SDM660 blocks from StarlordPkg; clover's own
  // device tree puts sdhc_1 at 0x0C0C4000 and blsp1_uart2 at 0x0C170000, both
  // inside PERIPH_SS, apcs_glb at 0x17911000 inside APCS_CC, and the interrupt
  // controller at 0x17A00000 / 0x17B00000, matching PcdGic*Base.
  {"BOOT_CONFIG",        0x00070000, 0x00010000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"GCC CLK CTL",        0x00100000, 0x000B0000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"UFS_RUMI",           0x00620000, 0x00020000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"RPM MSG RAM",        0x00778000, 0x00008000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"SECURITY CONTROL",   0x00780000, 0x00007000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"PRNG_CFG_PRNG",      0x00790000, 0x00010000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"MPM2_SLP_CNTR",      0x010A3000, 0x00001000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"MPM2_TSENS0",        0x010AA000, 0x00001000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"MPM2_TSENS0_TM",     0x010AB000, 0x00001000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"MPM2_PSHOLD",        0x010AC000, 0x00001000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"MPM2_TSENS1",        0x010AD000, 0x00001000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"MPM2_TSENS1_TM",     0x010AE000, 0x00001000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"PCIE WRAPPER AHB",   0x01C00000, 0x00007000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"UFS UFS REGS",       0x01DA0000, 0x00020000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"CRYPTO0 CRYPTO",     0x01DC0000, 0x00040000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"TCSR_TCSR_REGS",     0x01FC0000, 0x00026000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"TLMM CSR",           0x03100000, 0x00C00000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"GPUCC",              0x05065000, 0x00009000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"QDSS_QDSS",          0x06000000, 0x00100000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"HMSS_QLL",           0x06400000, 0x00200000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"PMIC ARB SPMI",      0x08000000, 0x02800000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"USB30_PRIM",         0x0A800000, 0x0011B000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"USB_RUMI",           0x0A920000, 0x00010000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"PERIPH_SS",          0x0C000000, 0x00200000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"MMSS",               0x0C800000, 0x00800000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"QDSS",               0x15060000, 0x00020000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"APCS_CC",            0x17800000, 0x00100000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"QTIMER",             0x17900000, 0x00030000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"APCS_GIC500_GICD",   0x17A00000, 0x00010000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"APCS_GIC500_GICR",   0x17B00000, 0x00100000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE}
};

VOID
GetMemoryMap (
  OUT EFI_MEMORY_REGION_DESCRIPTOR **MemoryDescriptor,
  OUT UINT8                         *MemoryDescriptorCount)
{
  // Pass Data
  *MemoryDescriptor      = gMemoryDescriptor;
  *MemoryDescriptorCount = ARRAY_SIZE (gMemoryDescriptor);
}
