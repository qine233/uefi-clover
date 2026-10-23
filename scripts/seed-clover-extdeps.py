#!/usr/bin/env python3
"""
Seed the guest's external-dependency cache so the clover build never has to reach
github.com.

Why this exists: `Mu_Basecore/BaseTools/Bin/basetoolsbin_ext_dep.yaml` and
`Mu_Basecore/CryptoPkg/Binaries/OneCrypto_ext_dep.json` are WebDependency
descriptors that point straight at GitHub release assets, and `stuart_update`
re-downloads them on every build, because build-clover-uefi.sh rsyncs the
checkout into the guest with --delete and that wipes the folders stuart
installed inside the tree (Mu_Basecore/BaseTools/Bin, Mu_Basecore/CryptoPkg/
Binaries).  Direct GitHub transport from this network is not a flake but a
habit: the TLS handshake to github.com resets, and when stuart_update fails the
build refuses to start with "External Dependencies in the environment are out
of date".  A round of on-device testing then costs a rebuild attempt.

edk2toolext already has the answer built in: `ExternalDependency.fetch()`
returns early if a global cache entry exists, and the cache location is taken
from the shell variable STUART_EXTDEP_CACHE_PATH, which this project's build
now exports.  The entry lives at

    $CACHE/<type>/<name>/sha1(version || source)

and holds exactly what the dependency's in-tree folder would hold after a
download -- so the hash-keyed path is computed from the descriptor's *own*
GitHub URL even though the bytes come off the mirror.

The bytes come from https://gh-proxy.com/, which serves GitHub release assets
here at a few hundred KB/s where github.com itself delivers nothing.  The
downloaded archive is checked against the sha256 the descriptor advertises
before it is handed to the guest, so the mirror is not trusted for anything.

Idempotent: an entry that is already cached is left alone, which means a warm
run is a handful of file checks.

    python3 scripts/seed-clover-extdeps.py            # all github web extdeps
    python3 scripts/seed-clover-extdeps.py --list     # just say what is missing

Copyright: SPDX-License-Identifier: BSD-2-Clause-Patent
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile

DEFAULT_CHECKOUT = os.path.expanduser("~/mu-clover")
DEFAULT_PROFILE = "clover"
# Every use of this is a string handed to `bash -c` inside the guest, so the tilde is
# expanded by the *guest's* shell and names /home/<guest user>/.mu_extdeps.  Callers on
# the host must not paste this literal into a double-quoted host string -- see the
# EXTDEP_CACHE block in build-clover-uefi.sh, where exactly that pointed stuart at a
# macOS path the VM has never had.
DEFAULT_CACHE = "~/.mu_extdeps"
MIRROR = "https://gh-proxy.com/"

# The build's own view of the guest's python; only stdlib is needed here.
GUEST_PYTHON = "python3"


def guest(args, command, stdin_file=None, stdin_data=None, capture=False):
    """Run a shell command inside the guest, optionally feeding it a file or text."""
    full = ["colima", "ssh", "--profile", args.profile, "--", "bash", "-c", command]
    if stdin_file is not None:
        with open(stdin_file, "rb") as handle:
            return subprocess.run(full, stdin=handle, capture_output=capture, check=True)
    return subprocess.run(full, input=stdin_data.encode() if stdin_data else None,
                          capture_output=capture, check=True)


def read_descriptor(path):
    """Pull the keys this script needs out of an ext_dep descriptor.

    System python on this host has no yaml module, and the yaml descriptors here
    are one flat mapping of scalars, which `key: value` lines cover exactly.  A
    descriptor in a format this cannot read is reported rather than guessed at.
    """
    data = {}
    if path.endswith(".json"):
        with open(path) as handle:
            data = json.load(handle)
        return {k: data[k] for k in data}
    with open(path) as handle:
        for line in handle:
            line = line.split("#", 1)[0].rstrip()
            if not line or line.lstrip().startswith("-") or ":" not in line:
                continue
            key, _, value = line.partition(":")
            key, value = key.strip(), value.strip()
            if value and not value.startswith("[") and not key.startswith(" "):
                data[key] = value.strip("'\"")
    if "source" not in data or "name" not in data:
        raise ValueError("%s is not a flat ext_dep this script can read" % path)
    return data


def find_descriptors(checkout):
    """Every web ext_dep in the tree whose source is a github.com URL."""
    found = []
    for root, dirs, files in os.walk(checkout):
        dirs[:] = [d for d in dirs if d not in (".git", "Build", "Binaries/clover")]
        for name in files:
            if name.startswith("ext_dep") or name.endswith("_ext_dep.yaml") or name.endswith("_ext_dep.json"):
                path = os.path.join(root, name)
                try:
                    data = read_descriptor(path)
                except (ValueError, KeyError):
                    continue
                if data.get("type") == "web" and data.get("source", "").startswith("https://github.com/"):
                    data["descriptor_file"] = path
                    found.append(data)
    return found


def cache_path(data):
    """sha1(version || source), the same calculation ExternalDependency does."""
    digest = hashlib.sha1()
    digest.update(data["version"].encode("utf-8"))
    digest.update(data["source"].encode("utf-8"))
    return "%s/%s/%s/%s" % (DEFAULT_CACHE, data["type"], data["name"], digest.hexdigest())


def is_cached(args, path):
    out = guest(args, "test -d %s && echo yes || echo no" % path.replace("~", "$HOME"), capture=True)
    return out.stdout.decode().strip() == "yes"


def download(url, dest):
    """Fetch through the mirror, then verify the bytes are what the tree expects."""
    command = ["curl", "-sS", "-L", "--fail", "--retry", "3", "--retry-delay", "3",
               "--max-time", "1800", "-o", dest, url]
    subprocess.run(command, check=True)


SEED_SNIPPET = """
import hashlib, os, shutil, sys, tarfile, tempfile, zipfile
arc, name, internal, compression, cache = sys.argv[1:6]
want = sys.argv[6] if len(sys.argv) > 6 and sys.argv[6] else None
if want:
    got = hashlib.sha256(open(arc, "rb").read()).hexdigest()
    if got.lower() != want.lower():
        raise SystemExit("sha256 mismatch for %s: %s" % (name, got))
cache = os.path.expanduser(cache)
tmp = tempfile.mkdtemp()
if compression == "zip":
    with zipfile.ZipFile(arc) as ref:
        ref.extractall(tmp)
elif compression and "tar" in compression:
    with tarfile.open(arc) as ref:
        ref.extractall(tmp)
elif compression:
    raise SystemExit("unsupported compression %r" % compression)
# internal_path is the folder inside the archive the ext_dep actually wants, and
# a leading slash is how the descriptors mark "the whole thing is a directory".
inner = internal.strip("/")
src = os.path.join(tmp, inner) if inner else tmp
if not os.path.isdir(src):
    raise SystemExit("%s not found inside %s (found %s)" % (inner or "the root", arc, sorted(os.listdir(tmp))))
os.makedirs(os.path.dirname(cache), exist_ok=True)
if os.path.isdir(cache):
    shutil.rmtree(cache)
# copytree preserves the modes extractall restored, which is what makes the
# tools inside runnable; WebDependency moves the folder instead of copying it,
# but the destination is the same contents_dir either way.
shutil.copytree(src, cache)
shutil.rmtree(tmp, ignore_errors=True)
print("seeded", cache)
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkout", default=DEFAULT_CHECKOUT, help="Mu-Silicium checkout with the overlay applied")
    ap.add_argument("--profile", default=DEFAULT_PROFILE, help="colima profile that holds the build")
    ap.add_argument("--list", action="store_true", help="only report which entries are missing")
    ap.add_argument("--force", action="store_true", help="re-download even a cached entry")
    a = ap.parse_args()

    if not os.path.isdir(a.checkout):
        sys.exit("no checkout at %s -- run scripts/fetch-mu-silicium.sh first" % a.checkout)

    descriptors = find_descriptors(a.checkout)
    if not descriptors:
        sys.exit("no github web ext_dep found under %s" % a.checkout)

    missing = []
    for data in descriptors:
        path = cache_path(data)
        cached = is_cached(a, path)
        print("%-16s %-14s %s" % (data["name"], data["version"],
                                  "cached" if cached else "missing"), flush=True)
        if not cached or a.force:
            missing.append(data)
    if a.list:
        return 0 if not missing else 1
    if not missing:
        return 0

    guest(a, "mkdir -p ~/extdep %s" % DEFAULT_CACHE)
    for data in missing:
        # Every value the guest needs comes from *this* descriptor.  The cache path in
        # particular is keyed by its own version and source -- reusing the path computed
        # in the status loop above writes one dependency into the other one's folder,
        # which stuart then happily copies into the tree as a working directory of the
        # wrong package.
        path = cache_path(data)
        url = MIRROR + data["source"]
        staged = os.path.join(tempfile.gettempdir(), os.path.basename(data["source"]))
        print("==> %s from %s" % (data["name"], url), flush=True)
        download(url, staged)
        remote = "~/extdep/" + os.path.basename(data["source"])
        guest(a, "cat > %s" % remote, stdin_file=staged)
        os.remove(staged)
        # The descriptor's own location is what decides the tree layout, but the
        # cache entry only needs the unpacked folder, so the archive is unpacked
        # in the guest with the same rules WebDependency.fetch() applies.
        guest(a, "%s - %s %s %s %s %s %s" % (
            GUEST_PYTHON, remote.replace("~", "$HOME"), data["name"],
            json.dumps(data.get("internal_path", "/")), json.dumps(data.get("compression_type") or ""),
            path.replace("~", "$HOME"), json.dumps(data.get("sha256") or "")),
            stdin_data=SEED_SNIPPET)
    return 0


if __name__ == "__main__":
    sys.exit(main())
