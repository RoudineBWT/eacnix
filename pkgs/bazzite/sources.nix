# Pinned Bazzite artifacts. Bazzite takes its kernel and signed kmods from
# Universal Blue's akmods images on ghcr.io: the Open Gaming Collective
# ("ogc") kernel, re-signed by Universal Blue, with the kernel RPMs under
# /kernel-rpms. Bazzite builds two kernel flavours: `ogc` for most images
# (and `-nvidia-open`), and `ogc-lts` for `bazzite-nvidia`, whose proprietary
# NVIDIA modules Universal Blue builds only for the LTS kernel.
#
# Bump each flavour to the kernel of a current Bazzite image (its
# `ostree.linux` label: `bazzite` for ogc, `bazzite-nvidia` for ogc-lts),
# then refresh ./<flavour>/kernel-config and kernel-modules.list (see
# ../vendor-kernel.nix).
#
# Each image has a single layer. It's fetched by its OCI digest, which is
# also its sha256, so the pin is exactly the layer Bazzite's build uses.
# ghcr.io serves public blobs to any bearer token; "QQ==" is the usual
# placeholder. ghcr.io prunes old akmods tags after a few months, so an old
# pin stops being fetchable unless it's already in a Nix store or cache.
let
  layer = repo: digest: {
    url = "https://ghcr.io/v2/ublue-os/${repo}/blobs/sha256:${digest}";
    curlOptsList = [
      "-H"
      "Authorization: Bearer QQ=="
    ];
    sha256 = digest;
  };
in
{
  release = "44";

  # Bazzite stable 44.20261012.1 (ghcr.io/ublue-os/bazzite:stable@sha256:5d49529c…).
  ogc = rec {
    flavor = "ogc";
    kernel = rec {
      version = "7.3.4";
      release = "ogc8.1.fc45";
      modDirVersion = "${version}-${release}.x86_64";
      # Vanilla source of the same upstream version, for kernelPackages tools.
      upstream = {
        url = "https://cdn.kernel.org/pub/linux/kernel/v7.x/linux-${version}.tar.xz";
        hash = "sha256-sRtt+Clejpkf8EC3GqpJlKi1XKojtrCSkH8ZW1hA/R8=";
      };
      # ghcr.io/ublue-os/akmods:ogc-<fcNN>-${modDirVersion}
      # @sha256:eb2de16215cbbd38bca0b1929bbfac1b157312655cfa7e138d8d213fe077ef5e
      akmods = layer "akmods" "f7a7e0a6d2861790d0807a47f4c889db7b88a2b6c77b03db52dcba8045f5415e";
    };

    # Universal Blue's builds of NVIDIA's open kernel modules for this kernel,
    # signed with the same MOK, and NVIDIA's userspace at the exact same
    # version (the driver refuses modules of another version).
    nvidia = rec {
      proprietary = false;
      version = "620.70.06";
      # ghcr.io/ublue-os/akmods-nvidia-open:ogc-<fcNN>-${kernel.modDirVersion}
      # @sha256:c94ae195e720e52ccab0e9e1c1261081613b621d64d58018f6d03c0a0e2ad1c1
      akmods = layer "akmods-nvidia-open" "c852c930de5be297cd8d84a469e6108bb09d23b1e2b84cf0abfeb4750e65dc09";
      # nixpkgs' nvidiaPackages.mkDriver arguments (nixpkgs' new_feature).
      userspace = {
        inherit version;
        sha256_64bit = "sha256-KRGOOr0IwHVZvMo9nHYjjQOUkK8DYqLlvPy+cgSv1LE=";
        settingsSha256 = "sha256-CFBRmXFJ9eAf5BRlHMBolahz1Pshr9giI7zcZC29oZ8=";
        persistencedSha256 = "sha256-FpGzhArrvR1nEt8lKDzNEnbvHvGP36gL1dINvpDAkpA=";
      };
    };
  };

  # Bazzite stable 44.20261012.1, NVIDIA image
  # (ghcr.io/ublue-os/bazzite-nvidia:stable@sha256:3d13e825…).
  ogc-lts = rec {
    flavor = "ogc-lts";
    kernel = rec {
      version = "6.18.60";
      release = "ogc1.2.fc45";
      modDirVersion = "${version}-${release}.x86_64";
      upstream = {
        url = "https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-${version}.tar.xz";
        hash = "sha256-PC9E72rMAhp61ETZoubsHvSI/wk2h5PQAEpggPadYh4=";
      };
      # ghcr.io/ublue-os/akmods:ogc-lts-<fcNN>-${modDirVersion}
      # @sha256:a728c03d80b502817db6b02a5606c48be9052d294995b9e0e2611e144d6f86e6
      akmods = layer "akmods" "0a200a0fb46b1edec8f7e315e31660d630146bc83c5706fe8158eb374b4ce0ad";
    };

    # Universal Blue's builds of NVIDIA's proprietary kernel modules (the 580
    # branch, the last to support Maxwell, Pascal, and Volta), signed with
    # the same MOK, and NVIDIA's userspace at the exact same version.
    nvidia = rec {
      proprietary = true;
      version = "580.196.07";
      # ghcr.io/ublue-os/akmods-nvidia-lts:ogc-lts-<fcNN>-${kernel.modDirVersion}
      # @sha256:5503b8fa2b2f3496b1803a17d826ba6b345e387911f31e576ba4fc9b9f4af3f3
      akmods = layer "akmods-nvidia-lts" "fdad5c96eeb78197359057a8fbc94d488541f60826e9dfd4223d4bbccac28ece";
      # nixpkgs' nvidiaPackages.mkDriver arguments (nixpkgs' legacy_580).
      userspace = {
        inherit version;
        sha256_64bit = "sha256-CqsFGNtTz3PEEtx/MrvIUMqV6DnYkj0N5L/0LByRac4=";
        settingsSha256 = "sha256-j7ENxh4VYIirMJSVVs2ei+NQULW5an8s4VQEwhVAqhc=";
        persistencedSha256 = "sha256-s7nI5BlnUwwPVoDjdete6B2wjDcoVgDd0UK9aZBrk00=";
      };
    };
  };
}
