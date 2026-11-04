#!/usr/bin/env python3
"""Bump the pinned Bazzite kernels in pkgs/bazzite/sources.nix.

For each kernel flavour (ogc, ogc-lts) it reads the kernel of Bazzite's current
stable image and, when that's newer than the pin, rewrites: the kernel version
and release, the vanilla tarball hash, the akmods layer digests (kernel and
NVIDIA) and the kmod-nvidia version. When the NVIDIA version changed it also
computes NVIDIA's userspace hashes with `nix store prefetch-file`, so it needs
`nix` on PATH in that case.

A flavour is left alone, and listed in bazzite-todo.md, whenever something
can't be resolved: the akmods images aren't published yet, no kmod-nvidia was
found, a hash couldn't be computed, or the kernel's major version changed (the
tarball URL in sources.nix is per major). The workflow turns that list into an
issue. Never goes backwards.

Under GitHub Actions it sets the outputs `changed`, `title`, `branch` (a bump
was written to the sources) and `todo`, `todo_title` (something needs a person).
Standard library only. The lookups are shared with watch_bazzite.py.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import watch_bazzite as wb
from pinlib import get_field, set_field, set_layer, version_key

NVIDIA_RUN = "https://download.nvidia.com/XFree86/Linux-x86_64/{v}/NVIDIA-Linux-x86_64-{v}.run"
NVIDIA_GH = "https://github.com/NVIDIA/{repo}/archive/{v}.tar.gz"


class Skip(Exception):
    """This flavour can't be bumped automatically."""


def release_key(release: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", release))


def nix_prefetch(url: str, unpack: bool = False) -> str:
    """SRI sha256 of `url` as Nix's fetchurl (or fetchzip, with unpack) would pin it."""
    cmd = ["nix", "store", "prefetch-file", "--json", "--hash-type", "sha256"]
    if unpack:
        cmd.append("--unpack")
    out = subprocess.run([*cmd, url], check=True, capture_output=True, text=True).stdout
    return json.loads(out)["hash"]


def userspace_hashes(nv: str) -> dict[str, str]:
    try:
        return {
            "sha256_64bit": nix_prefetch(NVIDIA_RUN.format(v=nv)),
            "settingsSha256": nix_prefetch(NVIDIA_GH.format(repo="nvidia-settings", v=nv), unpack=True),
            "persistencedSha256": nix_prefetch(NVIDIA_GH.format(repo="nvidia-persistenced", v=nv), unpack=True),
        }
    except (subprocess.CalledProcessError, OSError, KeyError, ValueError) as e:
        raise Skip(f"couldn't compute NVIDIA {nv}'s userspace hashes ({type(e).__name__}); "
                   "`nix` must be on PATH and NVIDIA's download reachable") from e


def plan(text: str, flavor: str, cfg: dict, fedora: str, tok: str, live_mod: str) -> tuple[str, list[str]]:
    """New text for one flavour, plus summary lines. Raises Skip."""
    version, release = live_mod.removesuffix(".x86_64").split("-", 1)
    lines = []
    rel = wb.tag_release(release, fedora)

    sri = wb.kernel_tarball_sri(version)
    if not sri:
        raise Skip(f"kernel {version}: no hash in cdn.kernel.org's sha256sums.asc")
    text = set_field(text, [flavor, "kernel"], "version", version)
    text = set_field(text, [flavor, "kernel"], "release", release)
    text = set_field(text, [flavor, "kernel", "upstream"], "hash", sri)

    digests = {}
    for key in ("akmods", "nvidia"):
        repo, tag_tpl = cfg[key]
        tag = tag_tpl.format(rel=rel, mod=live_mod)
        digest = wb.single_layer(repo, tag, tok)
        if digest is None:
            raise Skip(f"ghcr.io/ublue-os/{repo}:{tag} isn't published yet")
        digests[key] = (repo, digest)
    text = set_layer(text, [flavor, "kernel"], digests["akmods"][1])
    text = set_layer(text, [flavor, "nvidia"], digests["nvidia"][1])

    repo, digest = digests["nvidia"]
    nv = wb.nvidia_version(repo, digest, tok)
    if not nv:
        raise Skip(f"no kmod-nvidia rpm found in {repo}:{cfg['nvidia'][1].format(rel=rel, mod=live_mod)}")
    old_nv = get_field(text, [flavor, "nvidia"], "version")
    if nv != old_nv:
        text = set_field(text, [flavor, "nvidia"], "version", nv)
        for field, value in userspace_hashes(nv).items():
            text = set_field(text, [flavor, "nvidia", "userspace"], field, value)
        lines.append(f"- NVIDIA `{old_nv}` → `{nv}` (userspace hashes recomputed)")
    else:
        lines.append(f"- NVIDIA `{nv}` unchanged (userspace hashes kept)")
    return text, lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sources", default="pkgs/bazzite/sources.nix")
    ap.add_argument("--tag", default="stable", help="Bazzite image tag to follow")
    ap.add_argument("--force", action="store_true",
                    help="re-resolve flavours whose version already matches Bazzite's "
                         "(repairs a hand-edited pin whose akmods digests are stale)")
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    args = ap.parse_args()

    path = Path(args.sources)
    text = path.read_text(encoding="utf-8")
    fedora = get_field(text, [], "release")

    new = text
    summary: list[str] = []
    bumped: list[str] = []
    todo: list[str] = []
    todo_ids: list[str] = []
    for flavor, cfg in wb.FLAVORS.items():
        pin_ver = get_field(new, [flavor, "kernel"], "version")
        pin_rel = get_field(new, [flavor, "kernel"], "release")
        pinned_mod = f"{pin_ver}-{pin_rel}.x86_64"
        tok = wb.token(cfg["image"])
        labels = wb.image_labels(cfg["image"], args.tag, tok)
        live_mod = (labels.get("ostree.linux") or "").strip()
        if not live_mod:
            print(f"{flavor}: {cfg['image']}:{args.tag} has no ostree.linux label, skipping", file=sys.stderr)
            continue
        version, release = live_mod.removesuffix(".x86_64").split("-", 1)
        live_key = (version_key(version), release_key(release))
        pin_key = (version_key(pin_ver), release_key(pin_rel))
        if live_key == pin_key and not args.force:
            print(f"{flavor}: current ({pinned_mod})")
            continue
        if live_key < pin_key:
            print(f"{flavor}: Bazzite's {live_mod} is older than the pin {pinned_mod}, not going back")
            continue
        print(f"{flavor}: {pinned_mod} -> {live_mod}")
        try:
            if version.split(".")[0] != pin_ver.split(".")[0]:
                raise Skip(f"the kernel's major version changed ({pin_ver} → {version}); "
                           "the tarball URL in sources.nix is per major")
            new, lines = plan(new, flavor, cfg, fedora, tok, live_mod)
        except Skip as e:
            todo.append(f"- `{flavor}`: `{pinned_mod}` → `{live_mod}`: {e}")
            todo_ids.append(f"{flavor} {live_mod.removesuffix('.x86_64')}")
            continue
        bumped.append(f"{flavor} {version}-{release}")
        summary += [f"### `{flavor}`: `{pinned_mod}` → `{live_mod}`", "", *lines,
                    f"- Bazzite `{cfg['image']}:{args.tag}` (image created {labels.get('org.opencontainers.image.created', 'unknown')})", ""]

    if bumped and not args.dry_run:
        path.write_text(new, encoding="utf-8")
        Path("bump-summary.md").write_text(
            "Bazzite's stable images moved to a newer kernel.\n\n" + "\n".join(summary)
            + "\nThe vendored `kernel-config` and `kernel-modules.list` are refreshed by the workflow.\n",
            encoding="utf-8")
    if todo and not args.dry_run:
        Path("bazzite-todo.md").write_text(
            "Bazzite's stable images moved, but these flavours couldn't be bumped automatically:\n\n"
            + "\n".join(todo)
            + "\n\nSteps (from the README, \"To bump a vendor\"): update `pkgs/bazzite/sources.nix`, run "
            "`nix build .#bazzite-kernel.vendored && cp result/* pkgs/bazzite/ogc/` (and `.#bazzite-lts-kernel` into "
            "`pkgs/bazzite/ogc-lts/`), then `nix flake check -L`.\n", encoding="utf-8")

    if bumped:
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", "-".join(bumped)).strip("-")
        wb.emit(changed="true", title="bazzite: " + ", ".join(bumped), branch=f"bump/bazzite-{slug}")
    else:
        wb.emit(changed="false")
    if todo:
        wb.emit(todo="true", todo_title="bazzite: manual bump needed (" + ", ".join(todo_ids) + ")")
    else:
        wb.emit(todo="false")
    for line in todo:
        print("todo:", line, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
