# Frozen copy for scripts/test_pins.py (the live pins move with every bump).
# Pinned Fedora artifacts. Bump kernel, grub and shim together, from the same
# release, and refresh ./kernel-config from the new kernel-core RPM.
let
  koji = "https://kojipkgs.fedoraproject.org/packages";
in
{
  release = "fc45";

  kernel = rec {
    version = "7.2.11";
    release = "300.fc45";
    modDirVersion = "${version}-${release}.x86_64";
    # Vanilla source of the same upstream version. Userspace tools in
    # kernelPackages (turbostat, cpupower, perf, ...) build from `kernel.src`;
    # Fedora's patches don't matter to them, and the kernel itself never
    # builds from this.
    upstream = {
      url = "https://cdn.kernel.org/pub/linux/kernel/v${builtins.head (builtins.splitVersion version)}.x/linux-${version}.tar.xz";
      hash = "sha256-uxuHHvlajeELP3t7rw4NdUq79iD4BLbK+GDyJqqXZH0=";
    };
    rpms = {
      core = {
        url = "${koji}/kernel/${version}/${release}/x86_64/kernel-core-${modDirVersion}.rpm";
        hash = "sha256-WWYrkMA0KhxwKoiwiInDdlIe0OPWj7TDmhtlXas7Rus=";
      };
      modules-core = {
        url = "${koji}/kernel/${version}/${release}/x86_64/kernel-modules-core-${modDirVersion}.rpm";
        hash = "sha256-NQqr9bPpgN+ghXNRz75pVD7f8UhHvWuwdE4ZBHp8zBw=";
      };
      modules = {
        url = "${koji}/kernel/${version}/${release}/x86_64/kernel-modules-${modDirVersion}.rpm";
        hash = "sha256-o7TRSTONDmY+yBbCOnm/vxWc+IkcKh/20Nxc9jz7+OE=";
      };
    };
  };

  grub = rec {
    version = "2.12";
    release = "81.fc45";
    rpm = {
      url = "${koji}/grub2/${version}/${release}/x86_64/grub2-efi-x64-${version}-${release}.x86_64.rpm";
      hash = "sha256-wglogYbUAyN/R5tmaTH4d4z7OwcAqzDdmb9H85YbWuw=";
    };
  };

  shim = rec {
    version = "16.1";
    release = "7";
    rpm = {
      url = "${koji}/shim/${version}/${release}/x86_64/shim-x64-${version}-${release}.x86_64.rpm";
      hash = "sha256-UMqK0PCJOptp0leyMsw4/lctfyyBS8muxN9eSSgAzcc=";
    };
  };
}
