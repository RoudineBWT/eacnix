# Pinned Fedora artifacts. Bump kernel, grub and shim together, from the same
# release, and refresh ./kernel-config from the new kernel-core RPM.
let
  koji = "https://kojipkgs.fedoraproject.org/packages";
in
{
  release = "fc45";

  kernel = rec {
    version = "7.3.4";
    release = "300.fc45";
    modDirVersion = "${version}-${release}.x86_64";
    # Vanilla source of the same upstream version. Userspace tools in
    # kernelPackages (turbostat, cpupower, perf, ...) build from `kernel.src`;
    # Fedora's patches don't matter to them, and the kernel itself never
    # builds from this.
    upstream = {
      url = "https://cdn.kernel.org/pub/linux/kernel/v${builtins.head (builtins.splitVersion version)}.x/linux-${version}.tar.xz";
      hash = "sha256-sRtt+Clejpkf8EC3GqpJlKi1XKojtrCSkH8ZW1hA/R8=";
    };
    rpms = {
      core = {
        url = "${koji}/kernel/${version}/${release}/x86_64/kernel-core-${modDirVersion}.rpm";
        hash = "sha256-sREI3ElbmIO1Xrpf5eSH1AkGB2x6WYTwwlQ9jVYFzK8=";
      };
      modules-core = {
        url = "${koji}/kernel/${version}/${release}/x86_64/kernel-modules-core-${modDirVersion}.rpm";
        hash = "sha256-M2Mx8XLkPfjLhPEcET02nfXzemxl1HTmuIvS3F2Gjow=";
      };
      modules = {
        url = "${koji}/kernel/${version}/${release}/x86_64/kernel-modules-${modDirVersion}.rpm";
        hash = "sha256-vphg3aA3uN+/H7Ws/wNmDRz3u+0kEyao3wqSFCS5fKw=";
      };
    };
  };

  grub = rec {
    version = "2.12";
    release = "83.fc45";
    rpm = {
      url = "${koji}/grub2/${version}/${release}/x86_64/grub2-efi-x64-${version}-${release}.x86_64.rpm";
      hash = "sha256-wglogYbUAyN/R5tmaTH4d4z7OwcAqzDdmb9H85YbWuw=";
    };
  };

  shim = rec {
    version = "16.1";
    release = "10";
    rpm = {
      url = "${koji}/shim/${version}/${release}/x86_64/shim-x64-${version}-${release}.x86_64.rpm";
      hash = "sha256-UMqK0PCJOptp0leyMsw4/lctfyyBS8muxN9eSSgAzcc=";
    };
  };
}
