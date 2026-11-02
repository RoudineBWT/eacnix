#!/usr/bin/env python3
"""Report when Bazzite's stable images move to a newer kernel than the one pinned.

Bazzite's pins (pkgs/bazzite/sources.nix) can't be bumped blindly: the NVIDIA
userspace hashes must match the exact version of Universal Blue's kmod-nvidia.
So this script only *watches*: for each kernel flavour it reads the kernel of
the current Bazzite stable image (its `ostree.linux` label), and when it differs
from the pin it resolves what it can (akmods layer digests, the kmod-nvidia
version, the kernel tarball hash) and writes a report to
bazzite-report.md, to be opened as an issue by the workflow.

Under GitHub Actions it sets the output `changed` (true/false). Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
import tarfile
import urllib.error
import urllib.parse
import urllib.request

from pinlib import get_field, get_layer, hex_to_sri, http_get, http_open

GHCR = "https://ghcr.io"
ACCEPT = ", ".join([
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.docker.distribution.manifest.v2+json",
])

# flavour -> (Bazzite image whose kernel it follows, tag templates of the akmods images)
FLAVORS = {
    "ogc": {
        "image": "bazzite",
        "akmods": ("akmods", "ogc-{rel}-{mod}"),
        "nvidia": ("akmods-nvidia-open", "ogc-{rel}-{mod}"),
    },
    "ogc-lts": {
        "image": "bazzite-nvidia",
        "akmods": ("akmods", "ogc-lts-{rel}-{mod}"),
        "nvidia": ("akmods-nvidia-lts", "ogc-lts-{rel}-{mod}"),
    },
}


class _DropAuthOnRedirect(urllib.request.HTTPRedirectHandler):
    """ghcr.io redirects blobs to a storage host that rejects the bearer token."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urllib.parse.urlparse(newurl).netloc != urllib.parse.urlparse(req.full_url).netloc:
            new.headers.pop("Authorization", None)
            new.unredirected_hdrs.pop("Authorization", None)
        return new


OPENER = urllib.request.build_opener(_DropAuthOnRedirect)


def token(repo: str) -> str:
    url = f"{GHCR}/token?service=ghcr.io&scope=repository:ublue-os/{repo}:pull"
    return json.loads(http_get(url))["token"]


def manifest(repo: str, ref: str, tok: str) -> dict:
    """Image manifest for `ref` (tag or digest); a multi-arch index is resolved to linux/amd64."""
    url = f"{GHCR}/v2/ublue-os/{repo}/manifests/{ref}"
    doc = json.loads(http_get(url, {"Authorization": f"Bearer {tok}", "Accept": ACCEPT}, opener=OPENER))
    if "manifests" in doc:
        for m in doc["manifests"]:
            p = m.get("platform", {})
            if p.get("os") == "linux" and p.get("architecture") == "amd64":
                return manifest(repo, m["digest"], tok)
        raise SystemExit(f"{repo}:{ref}: no linux/amd64 manifest")
    return doc


def image_labels(repo: str, ref: str, tok: str) -> dict:
    m = manifest(repo, ref, tok)
    cfg = json.loads(http_get(f"{GHCR}/v2/ublue-os/{repo}/blobs/{m['config']['digest']}",
                              {"Authorization": f"Bearer {tok}"}, opener=OPENER))
    return (cfg.get("config") or {}).get("Labels") or {}


def single_layer(repo: str, tag: str, tok: str) -> str | None:
    """Digest of the only layer of an akmods image, or None if the tag doesn't exist."""
    try:
        layers = manifest(repo, tag, tok)["layers"]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    if len(layers) != 1:
        raise SystemExit(f"{repo}:{tag}: expected one layer, got {len(layers)}")
    return layers[0]["digest"].removeprefix("sha256:")


KMOD = re.compile(r"kmod-nvidia-.+?\.x86_64-(?P<nv>\d+(?:\.\d+)+)-\d+\.fc\d+\.x86_64\.rpm$")


def nvidia_version(repo: str, digest: str, tok: str) -> str | None:
    """kmod-nvidia's NVIDIA version, read from the file names inside the layer (streamed)."""
    resp = http_open(f"{GHCR}/v2/ublue-os/{repo}/blobs/sha256:{digest}",
                     {"Authorization": f"Bearer {tok}"}, opener=OPENER, timeout=600)
    with resp, tarfile.open(fileobj=resp, mode="r|*") as tf:
        for member in tf:
            m = KMOD.search(member.name.rsplit("/", 1)[-1])
            if m:
                return m.group("nv")
    return None


def kernel_tarball_sri(version: str) -> str | None:
    major = version.split(".")[0]
    try:
        sums = http_get(f"https://cdn.kernel.org/pub/linux/kernel/v{major}.x/sha256sums.asc").decode()
    except urllib.error.URLError:
        return None
    m = re.search(rf"^([0-9a-f]{{64}})\s+linux-{re.escape(version)}\.tar\.xz$", sums, re.M)
    return hex_to_sri(m.group(1)) if m else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sources", default="pkgs/bazzite/sources.nix")
    ap.add_argument("--tag", default="stable", help="Bazzite image tag to follow")
    args = ap.parse_args()

    text = Path(args.sources).read_text(encoding="utf-8")
    fedora = get_field(text, [], "release")  # the top-level `release = "44";`

    sections: list[str] = []
    moved: list[str] = []
    for flavor, cfg in FLAVORS.items():
        pinned_mod = f'{get_field(text, [flavor, "kernel"], "version")}-{get_field(text, [flavor, "kernel"], "release")}.x86_64'
        tok = token(cfg["image"])
        labels = image_labels(cfg["image"], args.tag, tok)
        live_mod = (labels.get("ostree.linux") or "").strip()
        if not live_mod:
            print(f"{flavor}: {cfg['image']}:{args.tag} has no ostree.linux label, skipping", file=sys.stderr)
            continue
        if live_mod == pinned_mod:
            print(f"{flavor}: current ({pinned_mod})")
            continue
        print(f"{flavor}: {pinned_mod} -> {live_mod}")
        moved.append(f"{flavor} {live_mod.removesuffix('.x86_64')}")

        version, release = live_mod.removesuffix(".x86_64").split("-", 1)
        lines = [
            f"### `{flavor}`: `{pinned_mod}` → `{live_mod}`",
            "",
            f"Bazzite `{cfg['image']}:{args.tag}` (image created {labels.get('org.opencontainers.image.created', 'unknown')}).",
            "",
            "Replace in `pkgs/bazzite/sources.nix`, flavour `" + flavor + "`:",
            "",
            "```nix",
            f'version = "{version}";',
            f'release = "{release}";',
        ]
        sri = kernel_tarball_sri(version)
        lines.append(f'# upstream.hash = "{sri}";' if sri else "# upstream.hash: not found in cdn.kernel.org's sha256sums.asc, prefetch the tarball")

        for key in ("akmods", "nvidia"):
            repo, tag_tpl = cfg[key]
            tag = tag_tpl.format(rel=fedora, mod=live_mod)
            digest = single_layer(repo, tag, tok)
            if digest is None:
                lines.append(f"# {key}: ghcr.io/ublue-os/{repo}:{tag} not published yet")
                continue
            lines.append(f"# ghcr.io/ublue-os/{repo}:{tag}")
            lines.append(f'{"nvidia.akmods" if key == "nvidia" else "kernel.akmods"} = layer "{repo}" "{digest}";')
            if key == "nvidia":
                nv = nvidia_version(repo, digest, tok)
                lines.append(f'# nvidia.version = "{nv}";' if nv else "# nvidia.version: no kmod-nvidia rpm found in the layer")
        lines += [
            "```",
            "",
            "Still manual: NVIDIA's userspace hashes (`sha256_64bit`, `settingsSha256`, `persistencedSha256`) for the new "
            "`nvidia.version` (nixpkgs' `nvidiaPackages.mkDriver` arguments), then `kmod = ...` follows the new names.",
            "",
        ]
        sections.append("\n".join(lines))

    if not sections:
        emit(changed="false")
        return 0

    report = [
        "Bazzite's stable images moved past the pinned kernel(s).",
        "",
        *sections,
        "Steps (from the README): update `pkgs/bazzite/sources.nix`, run "
        "`nix build .#bazzite-kernel.vendored && cp result/* pkgs/bazzite/ogc/` (and `.#bazzite-lts-kernel` into "
        "`pkgs/bazzite/ogc-lts/`), then `nix flake check -L`.",
    ]
    Path("bazzite-report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    emit(changed="true", title="bazzite: new kernel (" + ", ".join(moved) + ")")
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
