#!/bin/bash
# Fetch Mu-Silicium and every submodule a clover build needs.
#
# Why a script instead of `git clone --recursive`:
#   * Direct GitHub transport from this host stalls (0-22 KB/s); the
#     gh-proxy.com mirror runs at ~450 KB/s and answers fetch-by-SHA, so a
#     depth-1 clone of an exact commit works.
#   * Every commit is taken from the parent tree's own `git submodule status`,
#     never from a branch name, so the checkout is the exact tree Mu-Silicium
#     recorded.  Each fetch is asserted with `git rev-parse HEAD`.
#   * `Binaries` (Project-Silicium/Device-Binaries) is deliberately skipped: it
#     has no clover entry.  Those blobs come from this tablet's own xbl
#     partition -- see scripts/extract-clover-blobs.py.
#
# Real `.git` directories are kept rather than tarballs because UniXNU's build
# steps run `git apply` inside the checkout.
#
# Usage:  fetch-mu-silicium.sh [<destination>]
set -u

DST=${1:-"$HOME/mu-clover"}
MIRROR=${MIRROR:-https://gh-proxy.com/https://github.com}
# The Mu-Silicium commit this overlay was written against.
WANT=${WANT:-42fe563791e51bf5500c2e470ed294ca0c94b97c}
MARK="$DST/.fetched"

say () { echo "fetch: $*" >&2; }

# fetch <parent-dir> <submodule-path> <owner/repo> <sha>
fetch () {
  local parent=$1 path=$2 repo=$3 sha=$4 dest=$1/$2 attempt
  if [ -f "$MARK" ] && grep -qx "$path $sha" "$MARK"; then
    say "SKIP $path"
    return 0
  fi
  # Already at the wanted commit (re-run, or a hand-placed checkout): leave it.
  if [ "$(git -C "$dest" rev-parse HEAD 2>/dev/null)" = "$sha" ]; then
    mkdir -p "$(dirname "$MARK")"
    echo "$path $sha" >>"$MARK"
    say "HELD $path @ $sha"
    return 0
  fi
  mkdir -p "$dest"
  if [ ! -d "$dest/.git" ]; then
    git -C "$dest" init -q || return 1
  fi
  git -C "$dest" remote get-url origin >/dev/null 2>&1 \
    && git -C "$dest" remote set-url origin "$MIRROR/$repo.git" \
    || git -C "$dest" remote add origin "$MIRROR/$repo.git"
  for attempt in 1 2 3 4 5; do
    if git -C "$dest" -c http.lowSpeedLimit=2000 -c http.lowSpeedTime=90 \
         fetch -q --depth 1 origin "$sha"; then
      break
    fi
    [ "$attempt" = 5 ] && { say "FAIL $path"; return 1; }
    say "retry $attempt $path"
    sleep $((attempt * 4))
  done
  git -C "$dest" checkout -q FETCH_HEAD || { say "FAIL $path"; return 1; }
  if [ "$(git -C "$dest" rev-parse HEAD)" != "$sha" ]; then
    say "SHA_MISMATCH $path want=$sha got=$(git -C "$dest" rev-parse HEAD)"
    return 1
  fi
  mkdir -p "$(dirname "$MARK")"
  echo "$path $sha" >>"$MARK"
  say "OK   $path @ $sha"
}

# submodules <dir>: emit "<path> <owner/repo> <sha>" for every recorded submodule.
# `git submodule status` prefixes the SHA with "-" (not initialized), "+" (wrong
# commit checked out) or a blank -- the sign is attached, with no space.
submodules () {
  local dir=$1 line sha rest path url
  git -C "$dir" submodule status 2>/dev/null | while read -r line; do
    case $line in
      -*) sha=${line#-};;
      +*) sha=${line#+};;
      *)  sha=${line# };;
    esac
    sha=${sha%% *}
    rest=${line#* }
    path=${rest%% *}
    url=$(git config -f "$dir/.gitmodules" submodule."$path".url)
    [ -n "$url" ] || continue
    url=${url#https://github.com/}
    echo "$path ${url%.git} $sha"
  done
}

mkdir -p "$DST"

# 1. the superproject
if [ -d "$DST/.git" ]; then
  say "superproject already present at $(git -C "$DST" rev-parse HEAD 2>/dev/null || echo unknown)"
else
  fetch "$DST" "." Project-Silicium/Mu-Silicium "$WANT" || exit 1
fi

# 2. Mu-Silicium's submodules, minus the firmware blob dump
while read -r path repo sha; do
  if [ "$path" = "Binaries" ]; then
    say "SKIP Binaries (clover's blobs come from this device's xbl)"
    continue
  fi
  fetch "$DST" "$path" "$repo" "$sha" || exit 1
done < <(submodules "$DST")

# 3. one level deeper: mu_basecore vendors libfdt, mipisyst, brotli, oniguruma,
#    libspdm and the unit-test libraries.  edk2 validates every [Includes] line
#    of each .dec it parses, so a missing submodule directory aborts the build
#    with "File/directory not found in workspace" before anything compiles.
while read -r path repo sha; do
  fetch "$DST/Mu_Basecore" "$path" "$repo" "$sha" || exit 1
done < <(submodules "$DST/Mu_Basecore")

say "COMPLETE $(du -sh "$DST" | cut -f1) at $DST"
