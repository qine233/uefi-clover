/*
 * Overlay copy of upstream Mu-Silicium BootShim/BootShim.S, with one addition:
 * _Start paints ABL's own splash framebuffer red before it relocates the
 * firmware volume.
 *
 * Every on-device round so far has been read off a logo, and the logo cannot
 * answer the only question that matters: did ABL jump to us at all.  A frozen
 * Mi splash is also what "never jumped" looks like, because ABL drew the logo
 * and nothing ever replaced it.  This makes that observable: the panel is
 * already scanning out 0x9D400000 (the device's own map calls the window
 * 0x9D400000 + 0x02400000, "Display Reserved", and stock xbl draws the logo
 * into it), so writing there needs no display driver at all -- if the screen
 * changes colour, BootShim ran.  Paint happens first, before the relocation
 * loop, so a crash inside the FD still leaves the mark behind.
 *
 * Colour is 0xFF0000FF: red if the framebuffer is RGBA, blue if BGRA, and
 * neither is a colour the Mi splash uses.
 *
 * To drop the probe, delete this file and BootShim/ from COPIED in
 * scripts/apply-clover-overlay.py; upstream's version then survives untouched.
 * Nothing here is clover-specific except the address, so do not reuse this
 * checkout for another board with the probe still in place.
 */

.equ SPLASH_BASE, 0x9D400000   /* ABL's live splash framebuffer, from the device map */
.equ SPLASH_FILL, 0x00800000   /* 8 MiB: under the 1200x1920x4 = 9.2 MiB framebuffer */

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
  /* Bring-up probe.  x7-x9 only: x0..x3 belong to whoever loaded us, and the
   * relocation below reads x1 and clobbers x2-x6. */
  ldr   x7, =SPLASH_BASE
  ldr   x8, =SPLASH_FILL
  add   x8, x7, x8
  mov   w9,  #0x00ff
  movk  w9,  #0xff00, lsl 16    /* w9 = 0xFF0000FF */

_PaintLoop:
  stp   x9, x9, [x7], #16
  cmp   x7, x8
  b.lo  _PaintLoop

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
