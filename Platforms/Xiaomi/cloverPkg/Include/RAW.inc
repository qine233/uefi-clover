##
#  clover: configuration blobs carried in the firmware volume.
#
#  The four files are extracted from the tablet's own stock firmware, the same
#  way upstream extracts them for lavender; see proprietary-files.txt.
#  SecParti.cfg describes the on-disk layout the Qualcomm drivers expect, and it
#  is the file to re-check first if the ESP or userdata is not enumerated.
#
#  The FREEFORM GUIDs are deliberately the ones upstream already uses for these
#  same four blobs (lavender and gta4l agree on SecParti.cfg, QcomChargerCfg.cfg
#  and BATTERY.PROVISION).  Prebuilt vendor drivers in Binaries/clover locate
#  configuration blobs inside the firmware volume by GUID, so an invented GUID
#  would silently look like "file not found" at runtime; keeping the upstream
#  value is what makes an SDM660 driver binary behave.  A firmware volume only
#  needs its GUIDs unique within one image, and only clover is built from here.
#
#  SPDX-License-Identifier: BSD-2-Clause-Patent
##

  FILE FREEFORM = A1E235DE-E825-4591-9623-C43175811826 {
    SECTION RAW = Binaries/clover/RawFiles/SecParti.cfg
    SECTION UI = "SecParti.cfg"
  }

  FILE FREEFORM = F12A1F3D-4318-A006-5F7F-3FAAF6DBB4B5 {
    SECTION RAW = Binaries/clover/RawFiles/tracer_event.cfg
    SECTION UI = "tracer_event.cfg"
  }

  FILE FREEFORM = 45FE4B7C-150C-45DA-A021-4BEB2048EC6F {
    SECTION RAW = Binaries/clover/RawFiles/QcomChargerCfg.cfg
    SECTION UI = "QcomChargerCfg.cfg"
  }

  FILE FREEFORM = F780C779-DD7C-47CD-BD1A-5EB414C51704 {
    SECTION RAW = Binaries/clover/RawFiles/BATTERY.PROVISION
    SECTION UI = "BATTERY.PROVISION"
  }
