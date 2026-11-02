#!/usr/bin/env python3
"""Bump the pinned Fedora kernel, grub and shim in pkgs/fedora/sources.nix.

Looks up the newest builds of Fedora's current release (the `release` pinned in
the file, e.g. fc45) on Koji, keeps only a kernel/grub that reached Fedora's
stable repositories (unless --allow-unstable), downloads the RPMs to compute
their hashes and rewrites the pins. The kernel-config refresh
(`nix build .#fedora-kernel.vendored`) is done by the workflow afterwards.

Writes bump-summary.md (the PR body) and, under GitHub Actions, the outputs
`changed`, `branch` and `title`. Standard library only.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
import urllib.error

from pinlib import (
    get_field,
    hex_to_sri,
    http_get,
    list_dirs,
    list_files,
    release_key,
    set_field,
    sri_of_url,
    version_key,
)

KOJI = "https://kojipkgs.fedoraproject.org/packages"
MIRROR = "https://dl.fedoraproject.org/pub/fedora/linux"
MAX_VERSIONS_SCANNED = 15


def stable_listing(fedora: str, letter: str) -> set[str] | None:
    """RPM file names in Fedora's release + updates repos, or None if neither can be listed."""
    names: set[str] = set()
    found = False
    for url in (
        f"{MIRROR}/releases/{fedora}/Everything/x86_64/os/Packages/{letter}/",
        f"{MIRROR}/updates/{fedora}/Everything/x86_64/Packages/{letter}/",
    ):
        try:
            names.update(list_files(url))
            found = True
        except urllib.error.HTTPError:
            continue
    return names if found else None


def latest_build(pkg: str, release_re: str, rpm_name, stable: set[str] | None, need_stable: bool):
    """Newest (version, release) of `pkg` whose x86_64 RPM exists (and is stable, if required)."""
    versions = [v for v in list_dirs(f"{KOJI}/{pkg}/") if re.fullmatch(r"\d+(\.\d+)+", v)]
    versions.sort(key=version_key, reverse=True)
    for v in versions[:MAX_VERSIONS_SCANNED]:
        releases = [r for r in list_dirs(f"{KOJI}/{pkg}/{v}/") if re.fullmatch(release_re, r)]
        for r in sorted(releases, key=release_key, reverse=True):
            name = rpm_name(v, r)
            if name not in list_files(f"{KOJI}/{pkg}/{v}/{r}/x86_64/"):
                continue
            if need_stable and stable is not None and name not in stable:
                continue
            return v, r
    raise SystemExit(f"no usable {pkg} build found for {release_re}")


def kernel_tarball_sri(version: str) -> str:
    major = version.split(".")[0]
    base = f"https://cdn.kernel.org/pub/linux/kernel/v{major}.x"
    try:
        sums = http_get(f"{base}/sha256sums.asc").decode()
        m = re.search(rf"^([0-9a-f]{{64}})\s+linux-{re.escape(version)}\.tar\.xz$", sums, re.M)
        if m:
            return hex_to_sri(m.group(1))
    except urllib.error.URLError:
        pass
    return sri_of_url(f"{base}/linux-{version}.tar.xz")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sources", default="pkgs/fedora/sources.nix")
    ap.add_argument("--dry-run", action="store_true", help="report only, don't write the file")
    ap.add_argument("--allow-unstable", action="store_true", help="accept builds not yet in Fedora's stable repos")
    args = ap.parse_args()

    text = Path(args.sources).read_text(encoding="utf-8")
    dist = get_field(text, [], "release")  # the top-level `release = "fc45";`
    fedora = dist[2:]

    cur_k = (get_field(text, ["kernel"], "version"), get_field(text, ["kernel"], "release"))
    cur_g = (get_field(text, ["grub"], "version"), get_field(text, ["grub"], "release"))
    cur_s = (get_field(text, ["shim"], "version"), get_field(text, ["shim"], "release"))

    stable_k = stable_listing(fedora, "k")
    stable_g = stable_listing(fedora, "g")
    note = []
    if stable_k is None:
        note.append(f"Fedora {fedora}'s release/updates repos could not be listed: stability of the kernel build was not checked.")

    new_k = latest_build("kernel", rf"\d+\.{dist}", lambda v, r: f"kernel-core-{v}-{r}.x86_64.rpm", stable_k, not args.allow_unstable)
    new_g = latest_build("grub2", rf"\d+\.{dist}", lambda v, r: f"grub2-efi-x64-{v}-{r}.x86_64.rpm", stable_g, not args.allow_unstable)
    new_s = latest_build("shim", r"\d+", lambda v, r: f"shim-x64-{v}-{r}.x86_64.rpm", None, False)

    # Never go backwards (a stale mirror or a pulled build must not downgrade a pin).
    def newer(new, cur):
        return (version_key(new[0]), release_key(new[1])) > (version_key(cur[0]), release_key(cur[1]))

    k = new_k if newer(new_k, cur_k) else cur_k
    g = new_g if newer(new_g, cur_g) else cur_g
    s = new_s if newer(new_s, cur_s) else cur_s

    if (k, g, s) == (cur_k, cur_g, cur_s):
        print(f"fedora pins are current: kernel {cur_k[0]}-{cur_k[1]}, grub {cur_g[0]}-{cur_g[1]}, shim {cur_s[0]}-{cur_s[1]}")
        emit(changed="false")
        return 0

    print(f"kernel {cur_k[0]}-{cur_k[1]} -> {k[0]}-{k[1]}")
    print(f"grub   {cur_g[0]}-{cur_g[1]} -> {g[0]}-{g[1]}")
    print(f"shim   {cur_s[0]}-{cur_s[1]} -> {s[0]}-{s[1]}")
    if args.dry_run:
        emit(changed="false")
        return 0

    new = text
    if k != cur_k:
        v, r = k
        mod = f"{v}-{r}.x86_64"
        new = set_field(new, ["kernel"], "version", v)
        new = set_field(new, ["kernel"], "release", r)
        new = set_field(new, ["kernel", "upstream"], "hash", kernel_tarball_sri(v))
        for key, pkg in (("core", "kernel-core"), ("modules-core", "kernel-modules-core"), ("modules", "kernel-modules")):
            url = f"{KOJI}/kernel/{v}/{r}/x86_64/{pkg}-{mod}.rpm"
            new = set_field(new, ["kernel", "rpms", key], "hash", sri_of_url(url))
    if g != cur_g:
        v, r = g
        new = set_field(new, ["grub"], "version", v)
        new = set_field(new, ["grub"], "release", r)
        new = set_field(new, ["grub", "rpm"], "hash", sri_of_url(f"{KOJI}/grub2/{v}/{r}/x86_64/grub2-efi-x64-{v}-{r}.x86_64.rpm"))
    if s != cur_s:
        v, r = s
        new = set_field(new, ["shim"], "version", v)
        new = set_field(new, ["shim"], "release", r)
        new = set_field(new, ["shim", "rpm"], "hash", sri_of_url(f"{KOJI}/shim/{v}/{r}/x86_64/shim-x64-{v}-{r}.x86_64.rpm"))

    Path(args.sources).write_text(new, encoding="utf-8")

    body = [
        f"Bump the pinned Fedora {fedora} artifacts (kernel, grub and shim move together).",
        "",
        "| Package | From | To |",
        "|---|---|---|",
        f"| kernel | `{cur_k[0]}-{cur_k[1]}` | `{k[0]}-{k[1]}` |",
        f"| grub2 | `{cur_g[0]}-{cur_g[1]}` | `{g[0]}-{g[1]}` |",
        f"| shim | `{cur_s[0]}-{cur_s[1]}` | `{s[0]}-{s[1]}` |",
        "",
        "Hashes were computed from the Koji RPMs; `pkgs/fedora/kernel-config` and `kernel-modules.list` are refreshed by the workflow.",
        "**Read the diff before merging**: these pins decide which signed boot chain the EAC entry runs.",
    ] + [f"\n> {n}" for n in note]
    Path("bump-summary.md").write_text("\n".join(body) + "\n", encoding="utf-8")

    emit(
        changed="true",
        branch=f"bump/fedora-{k[0]}-{k[1]}-{g[0]}-{g[1]}-{s[0]}-{s[1]}".replace("_", "-"),
        title=f"fedora: kernel {k[0]}-{k[1]}",
    )
    return 0


def emit(**kv: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        for key, value in kv.items():
            f.write(f"{key}={value}\n")


if __name__ == "__main__":
    sys.exit(main())
