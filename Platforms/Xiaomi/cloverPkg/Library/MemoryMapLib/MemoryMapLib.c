/**
  Memory map for the Xiaomi Mi Pad 4 8" LTE (clover, Qualcomm SDM660).

  Every row is copied from the uefiplat.cfg inside this tablet's own xbl
  partition (UniXNU-clover/facts/<serial>-<stamp>/fw/xbl-uefiplat.txt), in the
  order the firmware writes it, because that file is what the Qualcomm SEC hands
  the stock UEFI.  It is not an interpretation of the board: the prebuilt drivers
  in Binaries/clover were compiled against these numbers and SecParti.cfg and
  friends are read out of the same volume.

  What the map says about the device:

    * Stock UEFI lives in the low 512 MiB; the rows stop at 0xA0000000.  "DXE
      Heap" (0x94000000 + 0x09400000, 148 MiB) is the only Conventional row, so
      that is the memory the vendor firmware, its allocators and a Boot-Services
      payload of our own all share.
    * Nothing above 0x80000000 + 512 MiB appears at all.  The 4 GiB unit's second
      bank (0x100000000 + 0x7E4C0000, from the device tree) is therefore neither
      used nor reserved by UEFI; make-clover-adt.py is what describes both banks
      to XNU.
    * The gaps are deliberate: 0x85800000..0x86000000 and the whole
      0x86200000..0x94000000 span, which the Android tree fills with qseecom,
      modem_fw and the TrustZone apps window (TzAppsRegnAddr = 0x86D00000 +
      0x02200000 in [ConfigParameters]).  Unlisted means unseeable, and that is
      how the stock firmware avoids TrustZone without a single reservation row.
    * The DXE Heap runs up to 0x9D400000, straight through the Android tree's
      adsp_mba (0x94900000) and cdsp_fw (0x94B00000) PIL windows.  Stock does the
      same; those windows only become real when the Android kernel loads that
      firmware, which a UniXNU boot never does.
    * "Display Reserved" is 0x9D400000 + 0x02400000.  The stock xbl boots in
      front of us and its DisplayDxe drew the splash into that window, so it is
      the address SimpleFbDxe reports and the value UniXNU's display-base and the
      ADT's framebuffer0 node have to carry.  Some downstream clover device trees
      move cont_splash_mem to 0x9D500000 -- that is the Android kernel's
      reservation for a splash the kernel itself does not inherit, and it
      contradicts the firmware on this unit, so 0x9D400000 wins.

  @copyright  SPDX-License-Identifier: BSD-2-Clause-Patent
**/

#include <Library/MemoryMapLib.h>

#include "../../Include/Checkpoint.h"

STATIC
EFI_MEMORY_REGION_DESCRIPTOR
gMemoryDescriptor[] = {
  // Name, Address, Length, HobOption, ResourceType, ResourceAttribute, MemoryType, ArmAttribute

  // DDR Regions: the device's own [MemoryMap], row for row.
  {"Kernel",           0x80000000, 0x05800000, AddMem, SYS_MEM, SYS_MEM_CAP,   Reserv, WRITE_BACK_XN},
  {"SMEM",             0x86000000, 0x00200000, AddMem, MEM_RES, UNCACHEABLE,   Reserv, UNCACHED_UNBUFFERED_XN},
  {"DXE Heap",         0x94000000, 0x09400000, AddMem, SYS_MEM, SYS_MEM_CAP,   Conv,   WRITE_BACK_XN},
  {"Display Reserved", 0x9D400000, 0x02400000, AddMem, MEM_RES, WRITE_THROUGH, LdData, WRITE_THROUGH_XN},
  {"FV Region",        0x9F800000, 0x00200000, AddMem, SYS_MEM, SYS_MEM_CAP,   BsData, WRITE_BACK_XN},
  {"ABOOT FV",         0x9FA00000, 0x00200000, AddMem, SYS_MEM, SYS_MEM_CAP,   Reserv, WRITE_BACK_XN},
  {"UEFI FD",          0x9FC00000, 0x00300000, AddMem, SYS_MEM, SYS_MEM_CAP,   BsData, WRITE_BACK},
  {"SEC Heap",         0x9FF00000, 0x0008C000, AddMem, SYS_MEM, SYS_MEM_CAP,   BsData, WRITE_BACK_XN},
  {"CPU Vectors",      0x9FF8C000, 0x00001000, AddMem, SYS_MEM, SYS_MEM_CAP,   BsData, WRITE_BACK},
  {"MMU PageTables",   0x9FF8D000, 0x00003000, AddMem, SYS_MEM, SYS_MEM_CAP,   BsData, WRITE_BACK_XN},
  {"UEFI Stack",       0x9FF90000, 0x00040000, AddMem, SYS_MEM, SYS_MEM_CAP,   BsData, WRITE_BACK_XN},
  {"DBI Dump",         0x9FFD0000, 0x00027000, AddMem, SYS_MEM, SYS_MEM_CAP,   RtData, WRITE_BACK_XN},
  {"Log Buffer",       0x9FFF7000, 0x00008000, AddMem, SYS_MEM, SYS_MEM_CAP,   RtData, WRITE_BACK_XN},
  {"Info Blk",         0x9FFFF000, 0x00001000, AddMem, SYS_MEM, SYS_MEM_CAP,   RtData, WRITE_BACK_XN},

  // Other and Register Regions: the same device's [RegisterMap], in the order
  // the firmware lists it.
  {"IMEM Base",          0x14680000, 0x00040000, NoHob,  MMAP_IO, INITIALIZED, Conv,   NS_DEVICE},
  {"IMEM Cookie Base",   0x146BF000, 0x00001000, AddDev, MMAP_IO, INITIALIZED, Conv,   NS_DEVICE},
  {"QDSS_STM",           0x16000000, 0x01000000, AddDev, MMAP_IO, INITIALIZED, Conv,   NS_DEVICE},
  {"UFS_RUMI",           0x00620000, 0x00020000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"BOOT_CONFIG",        0x00070000, 0x00010000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"GCC CLK CTL",        0x00100000, 0x000B0000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
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
  {"PMIC ARB SPMI",      0x08000000, 0x02800000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"GPUCC",              0x05065000, 0x00009000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"QDSS_QDSS",          0x06000000, 0x00100000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"HMSS_QLL",           0x06400000, 0x00200000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"USB30_PRIM",         0x0A800000, 0x0011B000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"USB_RUMI",           0x0A920000, 0x00010000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"PERIPH_SS",          0x0C000000, 0x00200000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"MMSS",               0x0C800000, 0x00800000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"QTIMER",             0x17900000, 0x00030000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"APCS_GIC500_GICD",   0x17A00000, 0x00010000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"APCS_GIC500_GICR",   0x17B00000, 0x00100000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"APCS_CC",            0x17800000, 0x00100000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
  {"QDSS",               0x15060000, 0x00020000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE}
};

VOID
GetMemoryMap (
  OUT EFI_MEMORY_REGION_DESCRIPTOR **MemoryDescriptor,
  OUT UINT8                         *MemoryDescriptorCount)
{
  STATIC UINTN  mCalls;

  // Pass Data
  *MemoryDescriptor      = gMemoryDescriptor;
  *MemoryDescriptorCount = ARRAY_SIZE (gMemoryDescriptor);

  // Stage 1 of Include/Checkpoint.h.  The first caller is MemoryInitPeiLib, which
  // is PEI building the resource HOBs, so a green bar here means we got out of SEC.
  // Later callers (MemoryMapHelperLib from DXE) hit the same guard and leave it.
  if (mCalls++ == 0) {
    CloverCheckpointBar (0x00040000, CLOVER_COLOR_GREEN);
  }
}
