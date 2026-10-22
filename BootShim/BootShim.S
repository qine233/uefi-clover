/*
 * Overlay copy of upstream Mu-Silicium BootShim/BootShim.S, with one addition: a
 * bring-up probe at the top of _Start.
 *
 * Every on-device round up to eight was read off ABL's logo, and the logo cannot
 * answer the only question that matters: did ABL jump to us at all?  A frozen Mi
 * splash is also what "never jumped" looks like, because ABL drew the logo and
 * nothing replaced it.  This probe makes the entry observable on the panel itself.
 *
 * Round 9 read it: with kernel_compression = "gzip" the screen came up solid blue
 * and the tablet never returned to USB.  ABL decompresses the kernel section, so
 * rounds five through eight -- all of them "= none", raw code handed to a
 * decompressor -- proved nothing about the header, the framebuffer or the FD, and
 * the "no colour arrived" of round 7 was that encoding, not a faulted write.
 *
 * PROBE_MODE:
 *   PROBE_HANG   branch to self as the very first instruction.  Touches no memory,
 *                jumps nowhere, returns to nobody.  Only meaningful while the entry
 *                itself is in question; round 9 settled that, so the reading moved
 *                into the firmware, which is what cloverPkg/Include/Checkpoint.h is.
 *   PROBE_PAINT  paint ABL's splash framebuffer, then behave like upstream.  The
 *                panel is already scanning 0x9D400000 (the device map reserves
 *                0x9D400000 + 0x02400000 as "Display Reserved" and framebuffer0
 *                starts at that base), so the colour needs no display driver.  It
 *                also fixes the pixel layout for everything downstream: 0xFF0000FF
 *                displays blue, so words are ARGB8888 with blue in the low byte.
 *   PROBE_OFF    upstream's code, unchanged.
 *
 * To drop the probe entirely, delete this file and the BootShim/ entry in COPIED in
 * scripts/apply-clover-overlay.py; upstream's version then survives untouched.
 * Nothing here is clover-specific except the splash address, so do not reuse this
 * checkout for another board with PROBE_PAINT still selected.
 */

#define PROBE_OFF   0
#define PROBE_HANG  1
#define PROBE_PAINT 2

#define PROBE_MODE  PROBE_PAINT

#if PROBE_MODE == PROBE_PAINT
.equ SPLASH_BASE, 0x9D400000   /* ABL's live splash framebuffer, from the device map */
.equ SPLASH_FILL, 0x00800000   /* 8 MiB: under the 1200x1920x4 = 9.2 MiB framebuffer */
#endif

_Head:
  adr   x1, _Payload    /* Set _Entry address */
  b     _Start          /* Jump to the real code */

#if REQUIRES_KERNEL_HEADER == 1
_StackBase:
  .quad FD_BASE         /* Text Offset */

_StackSize:
  .quad FD_SIZE         /* Image Size */
  .quad 0               /* Flags */
  .quad 0               /* Reserved */
  .quad 0               /* Reserved */
  .quad 0               /* Reserved */
  .ascii "ARM\x64"      /* ARM64 Magic */
  .long 0               /* Reserved */
#endif

_Start:
#if PROBE_MODE == PROBE_HANG
  /* x0..x3 belong to whoever loaded us; nothing here reads or writes memory. */
  b     _Start
#elif PROBE_MODE == PROBE_PAINT
  /* x7-x9 only: the relocation below reads x1 and clobbers x2-x6. */
  ldr   x7, =SPLASH_BASE
  ldr   x8, =SPLASH_FILL
  add   x8, x7, x8
  mov   w9,  #0x00ff
  movk  w9,  #0xff00, lsl 16    /* w9 = 0xFF0000FF */

_PaintLoop:
  stp   x9, x9, [x7], #16
  cmp   x7, x8
  b.lo  _PaintLoop
#endif

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
