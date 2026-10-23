/*
 * Overlay copy of upstream Mu-Silicium BootShim/BootShim.S.  The one change is the
 * ARM64 Image Size: it covers the shim as well as the firmware volume.  Upstream
 * writes FD_SIZE alone; the UniXNU boot image step checks the header against the
 * bytes it actually puts in the kernel field, and the boot-chain contract says the
 * header describes the pair.
 *
 * Nothing is painted here.  Earlier builds filled ABL's splash framebuffer from
 * _Start to prove the entry was reached; that question is settled, and the panel
 * is now owned by the firmware's GraphicsOutput.
 */

_Head:
  adr   x1, _Payload    /* Set _Entry address */
  b     _Start          /* Jump to the real code */

#if REQUIRES_KERNEL_HEADER == 1
_StackBase:
  .quad FD_BASE         /* Text Offset */

_StackSize:
  .quad FD_SIZE + (_Payload - _Head)   /* Image Size: the shim and the volume it carries */
  .quad 0               /* Flags */
  .quad 0               /* Reserved */
  .quad 0               /* Reserved */
  .quad 0               /* Reserved */
  .ascii "ARM\x64"      /* ARM64 Magic */
  .long 0               /* Reserved */
#endif

_Start:
  mov   x4, x1
  ldr   x5, =FD_BASE
  cmp   x4, x5
  beq   _Entry
  ldr   x6,  =FD_SIZE

_CopyLoop:
  ldp   x2, x3, [x4], #16
  stp   x2, x3, [x5], #16
  subs  x6, x6, #16
  b.ne  _CopyLoop
  ldr   x5, =FD_BASE

_Entry:
  br    x5

_Dead:
  b     _Dead

.text
.align 4

_Payload:
