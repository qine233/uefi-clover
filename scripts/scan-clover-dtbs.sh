#!/bin/bash
# Summarise every DTB cut out of the device's boot image: name, model,
# compatible, qcom,msm-id / qcom,board-id.  Runs in the build guest, where dtc
# and fdtget live.
cd "${1:?usage: scan-clover-dtbs.sh <dir of .dtb>}" || exit 1
for f in *.dtb; do
  model=$(fdtget "$f" / model 2>/dev/null)
  compat=$(fdtget "$f" / compatible 2>/dev/null)
  msmid=$(fdtget -t s "$f" / qcom,msm-id 2>/dev/null | tr -s ' ')
  boardid=$(fdtget -t s "$f" / qcom,board-id 2>/dev/null | tr -s ' ')
  printf '%s\t%s\t%s\t%s\t%s\n' "$f" "$compat" "$model" "$msmid" "$boardid"
done
