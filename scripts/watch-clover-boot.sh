#!/bin/bash
# Time a clover boot attempt from the build host, so a round does not depend on
# catching a screen with the corner of an eye.
#
# The tablet is told apart by how it shows up on USB:
#   fastboot -> `fastboot devices` answers, and ioreg has its "Android" node
#   android  -> `adb devices` answers
#   absent   -> neither.  A UEFI-stage or hung tablet enumerates as nothing at all,
#               so "absent" is a state in its own right, not a gap in the sampling.
#
# Two traps this works around: `fastboot devices` blocks when nothing is attached,
# and `system_profiler SPUSBDataType` returns 0 bytes from this shell, so it can
# never be used as a census -- ioreg is.
#
#   ./watch-clover-boot.sh [seconds]        default 120
#
# Start it *before* `fastboot reboot`.
set -uo pipefail

export PATH="/opt/homebrew/bin:$PATH"
SERIAL=${SERIAL:-81ffcaaa}
WATCH=${1:-120}

adb start-server >/dev/null 2>&1
state() {
  if [ "$(adb devices 2>/dev/null | grep -c "^$SERIAL")" -gt 0 ]; then
    echo android
    return
  fi
  if [ "$(ioreg -p IOUSB -l -w0 2>/dev/null | grep -c "\"USB Serial Number\" = \"$SERIAL\"")" -gt 0 ]; then
    # The node is up but adb says no: either fastboot, or a bootloader that has
    # enumerated without handing over to adb yet.
    if timeout 1 fastboot -s "$SERIAL" getvar product >/dev/null 2>&1; then echo fastboot; else echo usb; fi
  else
    echo absent
  fi
}

prev=""
start=$(date +%s)
until=$((start + WATCH))
while [ "$(date +%s)" -lt $until ]; do
  s=$(state)
  now=$(($(date +%s) - start))
  if [ "$s" != "$prev" ]; then
    printf '%4ds  %s\n' "$now" "$s"
    prev=$s
  fi
  sleep 0.2
done
printf '%4ds  (watch ended, last state %s)\n' "$(($(date +%s) - start))" "$prev"
