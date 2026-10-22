#!/bin/bash
# Compile clover firmware inside a Linux VM, because the EDK II link step needs
# ELF tools (ld.lld + gcc-aarch64-linux-gnu) that this macOS host does not have,
# and Mu-Silicium's Building.md documents only the Linux and Windows routes.
#
# The VM is colima on the Apple Virtualization backend (vz is its default, so
# there is no QEMU to install).  The checkout stays on the Mac; the build runs
# on the VM's own ext4, because an EDK II build writes tens of thousands of
# small files and virtiofs makes that miserable.
#
# Idempotent: re-running repeats only the steps that are still missing.
#
#   CHECKOUT   Mu-Silicium checkout with the clover overlay applied
#   IMAGE      ubuntu-...-docker.raw.gz from abiosoft/colima-core, already on disk
#   APT_MIRROR / PIP_INDEX   used because the defaults are unusably slow here
set -euo pipefail

CHECKOUT=${CHECKOUT:-"$HOME/mu-clover"}
IMAGE=${IMAGE:-"$HOME/.cache/clover-img/ubuntu-24.04-minimal-cloudimg-arm64-docker.raw.gz"}
PROFILE=${PROFILE:-clover}
APT_MIRROR=${APT_MIRROR:-https://mirrors.ustc.edu.cn/ubuntu-ports}
# Measured from inside the VM: USTC and TUNA both answer 403 for pypi wheels,
# tencent is fastest and pip verifies the sha256 the index advertises anyway.
PIP_INDEX=${PIP_INDEX:-https://mirrors.cloud.tencent.com/pypi/simple}
VM_CPUS=${VM_CPUS:-6}
VM_MEMORY=${VM_MEMORY:-6}
VM_DISK=${VM_DISK:-45}

export PATH="$HOME/.local/bin:$PATH"
# This host's Xcode license is unsigned, so command line tools must be named.
export DEVELOPER_DIR=${DEVELOPER_DIR:-/Library/Developer/CommandLineTools}
GUEST=~/mu-build

ssh() { colima ssh --profile "$PROFILE" -- "$@"; }

# ------------------------------------------------------------------ virtual machine
if ! colima status --profile "$PROFILE" >/dev/null 2>&1; then
  [ -f "$IMAGE" ] || { echo "no $IMAGE -- see README.md, colima-core release asset" >&2; exit 1; }
  echo "==> starting $PROFILE"
  # -i feeds the image as a local file: colima's own downloader has to resolve a
  # github.com redirect, which stalls on this network.
  colima start "$PROFILE" --vm-type vz --runtime docker --disk-image "$IMAGE" \
      --cpus "$VM_CPUS" --memory "$VM_MEMORY" --disk "$VM_DISK" \
    || colima start "$PROFILE" --vm-type vz --runtime docker --disk-image "$IMAGE" \
         --force-disk-image --cpus "$VM_CPUS" --memory "$VM_MEMORY" --disk "$VM_DISK"
fi

# -------------------------------------------------------------------- build guest
echo "==> provisioning the guest"
# Runs as the guest user (passwordless sudo on the colima image) so that the
# venv lands in its home, the same place the build later reads it from.
ssh env APT_MIRROR="$APT_MIRROR" PIP_INDEX="$PIP_INDEX" bash -s <<'GUEST'
set -euo pipefail
if [ ! -e /etc/apt/sources.list.d/clover-mirrored ]; then
  # 24.04 keeps its sources in deb822 form; the cloud image points at
  # ports.ubuntu.com for arm64, which is far slower here than the USTC mirror.
  sudo bash -c 'for f in /etc/apt/sources.list.d/ubuntu.sources /etc/apt/sources.list; do
    [ -f "$f" ] && sed -i "s|http://ports.ubuntu.com/ubuntu-ports|'"${APT_MIRROR}"'|g" "$f"
  done; touch /etc/apt/sources.list.d/clover-mirrored'
fi
export DEBIAN_FRONTEND=noninteractive
sudo apt-get update -q
# Mu-Silicium setup_env.sh installs exactly this set for apt; git-core and
# python3-distutils no longer exist in 24.04, device-tree-compiler is added
# because the clover board step wants a .dtb next to the .dts.
sudo apt-get install -y -qq --no-install-recommends \
    git build-essential clang llvm lld uuid-dev nasm gcc-aarch64-linux-gnu \
    python3 python3-git python3-pip python3-venv gettext gnupg ca-certificates \
    curl rsync device-tree-compiler mono-devel
[ -x "$HOME/.venv-edk2/bin/python" ] || python3 -m venv "$HOME/.venv-edk2"
# stuart_setup recurses into the openssl submodule's own submodules
# (cloudflare-quiche -> boringssl), and a direct github.com fetch stalls on this
# network.  Route every github.com clone in the guest through the mirror.
git config --global url."https://gh-proxy.com/https://github.com/".insteadOf https://github.com/
"$HOME/.venv-edk2/bin/pip" install -q --index-url "$PIP_INDEX" \
    'edk2-pytool-library~=0.23.17' 'edk2-pytool-extensions~=0.31.2' \
    'antlr4-python3-runtime==4.13.2' 'regex==2026.9.29' 'pefile~=2024.8.26' coloredlogs
echo "guest: $(clang --version | head -1) | $(ld.lld --version | head -1) | $("$HOME/.venv-edk2/bin/python" --version)"
GUEST

# ---------------------------------------------------------------------- copy tree
[ -d "$CHECKOUT/Platforms/Xiaomi/cloverPkg" ] || { echo "$CHECKOUT has no cloverPkg; run apply-clover-overlay.py first" >&2; exit 1; }
# Re-play the overlay first, so an edit in the overlay repository is what builds.
OVERLAY=${OVERLAY:-"$HOME/uefi-clover"}
if [ -f "$OVERLAY/scripts/apply-clover-overlay.py" ]; then
  echo "==> re-applying the overlay from $OVERLAY"
  python3 "$OVERLAY/scripts/apply-clover-overlay.py" --uefi "$CHECKOUT" --no-check
fi
echo "==> syncing $CHECKOUT into the guest"
# Quoted so ~ means the guest's home. Bare, the host shell expands it first and
# mkdir creates an empty mu-build in the mounted tree instead.
ssh bash -c 'mkdir -p ~/mu-build'
# Anchor both excludes to the workspace root. Unanchored, rsync also skipped
# Mu_Basecore/BaseTools/Conf/, which holds target/tools_def/build_rule.template
# -- stuart_build then died with "Template File Missing <ws>/Conf/target.txt".
ssh rm -rf ~/mu-build/Conf
ssh bash -c 'rsync -a --delete --exclude /Build/ --exclude /Conf/ '"$CHECKOUT"'/ ~/mu-build/'
# After the sync, and never before it: stuart_update installs its external
# dependencies inside the tree (Mu_Basecore/CryptoPkg/Binaries, Mu_Basecore/
# BaseTools/Bin), and the rsync above would delete them again.
echo "==> stuart_update"
ssh bash -c 'cd ~/mu-build && ~/.venv-edk2/bin/python Platforms/Xiaomi/cloverPkg/DeviceBuild.py --update -t RELEASE 2>&1 | tail -n 8'

# ------------------------------------------------------------------------ compile
echo "==> build_uefi.py -d clover"
ssh bash -c 'cd ~/mu-build && set -o pipefail && ~/.venv-edk2/bin/python build_uefi.py -d clover 2>&1 | tail -n 300'

echo "==> artifacts"
ssh bash -c 'ls -l ~/mu-build/Mu-clover* ~/mu-build/Build/cloverPkg/RELEASE_CLANGPDB/FV 2>/dev/null || true'

# --------------------------------------------------------------- stock geometry
# build_uefi.py packs the image with mkbootimg's *generic* defaults, because
# every key it forwards comes from [boot_image] in clover.toml and the only key
# upstream defines there is header_version: page size ends up 2048 and the load
# base 0x10000000.  Those are the AOSP defaults, not clover's -- this tablet's
# own boot header says 4096 and base 0, and it is a header v0 ABL, the one
# generation that may compute section offsets from its own page size instead of
# the header's.  Re-pack against the tablet's stock dump so the question cannot
# matter; pack-clover-bootimg.py explains the rest.
STOCK=${STOCK:-$(ls "$HOME"/UniXNU-clover/facts/*/img/unixnu-boot.img 2>/dev/null | tail -1)}
if [ -n "$STOCK" ] && [ -f "$STOCK" ]; then
  mkdir -p ~/clover-out
  echo "==> copying Mu-clover.img out and repacking with $STOCK"
  ssh bash -c 'cat ~/mu-build/Mu-clover.img' > ~/clover-out/Mu-clover.img
  python3 "$(dirname "$0")/pack-clover-bootimg.py" \
      --mu ~/clover-out/Mu-clover.img --stock "$STOCK" \
      --out ~/clover-out/Mu-clover-v0.img
else
  echo "==> no stock boot dump found (set STOCK=...); skipping the geometry repack"
fi
