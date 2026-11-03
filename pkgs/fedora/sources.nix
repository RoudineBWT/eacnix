# Pinned Fedora artifacts. Bump kernel, grub and shim together, from the same
# release, and refresh ./kernel-config from the new kernel-core RPM.
let
  koji = "https://kojipkgs.fedoraproject.org/packages";
in
{
  release = "fc45";

  kernel = rec {
    version = "7.2.15";
    release = "300.fc45";
    modDirVersion = "${version}-${release}.x86_64";
    # Vanilla source of the same upstream version. Userspace tools in
    # kernelPackages (turbostat, cpupower, perf, ...) build from `kernel.src`;
    # Fedora's patches don't matter to them, and the kernel itself never
    # builds from this.
    upstream = {
      url = "https://cdn.kernel.org/pub/linux/kernel/v${builtins.head (builtins.splitVersion version)}.x/linux-${version}.tar.xz";
      hash = "sha256-0Pax1zJMk3zK61xMpwhL/Pcdsu2z4tOjHwrYOmgYCas=";
    };
    rpms = {
      core = {
        url = "${koji}/kernel/${version}/${release}/x86_64/kernel-core-${modDirVersion}.rpm";
        hash = "sha256-DyTYIlKFpTBzshhKGlqoAURGBIqg8w3ex6X/uuRAFfo=";
      };
      modules-core = {
        url = "${koji}/kernel/${version}/${release}/x86_64/kernel-modules-core-${modDirVersion}.rpm";
        hash = "sha256-YGswUlQ0xXNGiHZ9gq1orUtPsXKurwIt1FjDxYh8Bbc=";
      };
      modules = {
        url = "${koji}/kernel/${version}/${release}/x86_64/kernel-modules-${modDirVersion}.rpm";
        hash = "sha256-cdeBZmQt43YzU86g18LQNZUrH4xblintoV9T2UGOizQ=";
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
