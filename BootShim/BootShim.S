/*
 * Overlay copy of upstream Mu-Silicium BootShim/BootShim.S.  The one change is the
 * ARM64 Image Size: it covers the shim as well as the firmware volume.  Upstream
 * writes FD_SIZE alone; the UniXNU boot image step checks the header against the
 * bytes it actually puts in the kernel field, and the boot-chain contract says the
 * header describes the pair.
 *
 * Stage 0 of the bring-up ladder is painted here: red over the whole window ABL
 * is scanning.  It is the only signal that says ABL jumped into this shim at
 * all -- a screen still on the Mi splash cannot tell "not entered" from
 * "entered and hung before the first DXE driver".  The firmware's own colours
 * (green once the GOP exists, blue once BDS has entered) replace it.
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
  /* Stage 0: paint the whole scanned window red, two pixels per store.
     x1 holds _Payload and must survive; x7-x9 are ours to use.  The constants
     are assembled by hand because an ldr = literal for the two-pixel word lands
     in a pool after _Payload, where the firmware volume is appended. */
  movz  x7, #0x9D40, lsl #16      /* 0x9D400000, Display Reserved */
  movz  x8, #0x00FF, lsl #48
  movk  x8, #0x00FF, lsl #16      /* 0x00FF0000 twice: red, red */
  movz  x9, #0x9DCC, lsl #16      /* 0x9DCCA000, one past the window */
_Paint:
  str   x8, [x7], #8
  cmp   x7, x9
  b.lo  _Paint

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
