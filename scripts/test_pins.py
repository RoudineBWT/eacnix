"""Offline tests for the pin automation: parsing, rewriting and the two scripts' flows (network mocked)."""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import bump_bazzite  # noqa: E402
import bump_fedora  # noqa: E402
import pinlib  # noqa: E402
import watch_bazzite  # noqa: E402

wb = watch_bazzite

FEDORA = (HERE / "fixtures/fedora-sources.nix").read_text()
BAZZITE = (HERE / "fixtures/bazzite-sources.nix").read_text()


class Basics(unittest.TestCase):
    def test_hex_to_sri_known_vector(self):
        # sha256 of the empty string
        self.assertEqual(
            pinlib.hex_to_sri("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"),
            "sha256-47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU=",
        )

    def test_versions(self):
        self.assertGreater(pinlib.version_key("7.2.11"), pinlib.version_key("7.2.9"))
        self.assertGreater(pinlib.version_key("7.10.0"), pinlib.version_key("7.9.9"))
        self.assertGreater(pinlib.release_key("300.fc45"), pinlib.release_key("99.fc45"))
        self.assertEqual(pinlib.release_key("7"), 7)

    def test_listing(self):
        html = '<a href="?C=N">Name</a><a href="/packages/">Parent</a><a href="7.2.11/">7.2.11/</a><a href="x%20y.rpm">x</a>'
        self.assertEqual(pinlib.parse_listing(html), ["7.2.11/", "x y.rpm"])


class Rewrite(unittest.TestCase):
    def test_read_fedora(self):
        self.assertEqual(pinlib.get_field(FEDORA, [], "release"), "fc45")
        self.assertEqual(pinlib.get_field(FEDORA, ["kernel"], "version"), "7.2.11")
        self.assertEqual(pinlib.get_field(FEDORA, ["kernel"], "release"), "300.fc45")
        self.assertEqual(pinlib.get_field(FEDORA, ["grub"], "release"), "81.fc45")
        self.assertEqual(pinlib.get_field(FEDORA, ["shim"], "version"), "16.1")
        self.assertTrue(pinlib.get_field(FEDORA, ["kernel", "rpms", "modules-core"], "hash").startswith("sha256-"))

    def test_modules_is_not_modules_core(self):
        a = pinlib.get_field(FEDORA, ["kernel", "rpms", "modules"], "hash")
        b = pinlib.get_field(FEDORA, ["kernel", "rpms", "modules-core"], "hash")
        c = pinlib.get_field(FEDORA, ["kernel", "rpms", "core"], "hash")
        self.assertEqual(len({a, b, c}), 3)

    def test_set_same_value_is_identity(self):
        for path, field in ((["kernel"], "version"), (["kernel", "rpms", "core"], "hash"), (["grub", "rpm"], "hash"), (["shim"], "release")):
            old = pinlib.get_field(FEDORA, path, field)
            self.assertEqual(pinlib.set_field(FEDORA, path, field, old), FEDORA)

    def test_set_changes_exactly_one_line(self):
        new = pinlib.set_field(FEDORA, ["kernel", "rpms", "modules"], "hash", "sha256-NEW=")
        a, b = FEDORA.splitlines(), new.splitlines()
        self.assertEqual(len(a), len(b))
        self.assertEqual([i for i, (x, y) in enumerate(zip(a, b)) if x != y].__len__(), 1)
        self.assertEqual(pinlib.get_field(new, ["kernel", "rpms", "modules"], "hash"), "sha256-NEW=")
        # neighbours untouched
        self.assertEqual(
            pinlib.get_field(new, ["kernel", "rpms", "modules-core"], "hash"),
            pinlib.get_field(FEDORA, ["kernel", "rpms", "modules-core"], "hash"),
        )

    def test_bazzite_flavours_do_not_mix(self):
        self.assertEqual(pinlib.get_field(BAZZITE, ["ogc", "kernel"], "release"), "ogc3.1.fc44")
        self.assertEqual(pinlib.get_field(BAZZITE, ["ogc-lts", "kernel"], "release"), "ogc1.1.fc44")
        self.assertEqual(pinlib.get_layer(BAZZITE, ["ogc", "kernel"])[0], "akmods")
        self.assertEqual(pinlib.get_layer(BAZZITE, ["ogc", "nvidia"])[0], "akmods-nvidia-open")
        self.assertEqual(pinlib.get_layer(BAZZITE, ["ogc-lts", "nvidia"])[0], "akmods-nvidia-lts")
        self.assertEqual(pinlib.get_field(BAZZITE, [], "release"), "44")


class BumpFedoraFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.src = Path(self.tmp) / "sources.nix"
        self.src.write_text(FEDORA)
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, self.old_cwd)

    def run_main(self, builds):
        """builds: pkg -> (version, release) returned as the newest build."""
        def fake_latest(pkg, *a, **k):
            return builds[pkg]
        with mock.patch.object(bump_fedora, "latest_build", fake_latest), \
             mock.patch.object(bump_fedora, "stable_listing", lambda *a: set()), \
             mock.patch.object(bump_fedora, "sri_of_url", lambda url: "sha256-" + url.rsplit("/", 1)[-1][:10] + "="), \
             mock.patch.object(bump_fedora, "kernel_tarball_sri", lambda v: f"sha256-tarball-{v}="), \
             mock.patch.object(sys, "argv", ["bump", "--sources", str(self.src)]):
            return bump_fedora.main()

    def test_no_change(self):
        rc = self.run_main({"kernel": ("7.2.11", "300.fc45"), "grub2": ("2.12", "81.fc45"), "shim": ("16.1", "7")})
        self.assertEqual(rc, 0)
        self.assertEqual(self.src.read_text(), FEDORA)
        self.assertFalse((Path(self.tmp) / "bump-summary.md").exists())

    def test_never_downgrades(self):
        self.run_main({"kernel": ("7.2.9", "300.fc45"), "grub2": ("2.12", "80.fc45"), "shim": ("16.1", "6")})
        self.assertEqual(self.src.read_text(), FEDORA)

    def test_bump_rewrites_all_three(self):
        self.run_main({"kernel": ("7.3.1", "301.fc45"), "grub2": ("2.12", "82.fc45"), "shim": ("16.1", "8")})
        new = self.src.read_text()
        self.assertEqual(pinlib.get_field(new, ["kernel"], "version"), "7.3.1")
        self.assertEqual(pinlib.get_field(new, ["kernel"], "release"), "301.fc45")
        self.assertEqual(pinlib.get_field(new, ["kernel", "upstream"], "hash"), "sha256-tarball-7.3.1=")
        self.assertEqual(pinlib.get_field(new, ["grub"], "release"), "82.fc45")
        self.assertEqual(pinlib.get_field(new, ["shim"], "release"), "8")
        # every hash was replaced, and the file keeps its shape
        for path in (["kernel", "rpms", "core"], ["kernel", "rpms", "modules-core"], ["kernel", "rpms", "modules"], ["grub", "rpm"], ["shim", "rpm"]):
            self.assertNotEqual(pinlib.get_field(new, path, "hash"), pinlib.get_field(FEDORA, path, "hash"))
        self.assertEqual(len(new.splitlines()), len(FEDORA.splitlines()))
        self.assertIn("7.3.1-301.fc45", (Path(self.tmp) / "bump-summary.md").read_text())

    def test_kernel_only(self):
        self.run_main({"kernel": ("7.2.12", "300.fc45"), "grub2": ("2.12", "81.fc45"), "shim": ("16.1", "7")})
        new = self.src.read_text()
        self.assertEqual(pinlib.get_field(new, ["kernel"], "version"), "7.2.12")
        self.assertEqual(pinlib.get_field(new, ["grub", "rpm"], "hash"), pinlib.get_field(FEDORA, ["grub", "rpm"], "hash"))


class WatchBazziteFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.src = Path(self.tmp) / "sources.nix"
        self.src.write_text(BAZZITE)
        self.out = Path(self.tmp) / "github_output"
        self.out.write_text("")
        patcher = mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(self.out)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, self.old_cwd)

    def run_main(self, live):
        labels = lambda repo, ref, tok: {"ostree.linux": live[repo], "org.opencontainers.image.created": "2026-11-01"}
        with mock.patch.object(watch_bazzite, "token", lambda repo: "t"), \
             mock.patch.object(watch_bazzite, "image_labels", labels), \
             mock.patch.object(watch_bazzite, "single_layer", lambda repo, tag, tok: "ab" * 32), \
             mock.patch.object(watch_bazzite, "nvidia_version", lambda repo, d, tok: "615.99.01"), \
             mock.patch.object(watch_bazzite, "kernel_tarball_sri", lambda v: f"sha256-{v}="), \
             mock.patch.object(sys, "argv", ["watch", "--sources", str(self.src)]):
            return watch_bazzite.main()

    def test_current_means_no_report(self):
        rc = self.run_main({"bazzite": "7.2.9-ogc3.1.fc44.x86_64", "bazzite-nvidia": "6.18.56-ogc1.1.fc44.x86_64"})
        self.assertEqual(rc, 0)
        self.assertFalse((Path(self.tmp) / "bazzite-report.md").exists())

    def test_new_kernel_is_reported(self):
        self.run_main({"bazzite": "7.3.0-ogc4.1.fc44.x86_64", "bazzite-nvidia": "6.18.56-ogc1.1.fc44.x86_64"})
        report = (Path(self.tmp) / "bazzite-report.md").read_text()
        self.assertIn("7.3.0-ogc4.1.fc44.x86_64", report)
        self.assertIn("ogc-44-7.3.0-ogc4.1.fc44.x86_64", report)
        self.assertIn("615.99.01", report)
        self.assertIn("akmods-nvidia-open", report)
        self.assertNotIn("6.18.56", report.split("###")[0] + "".join(report.split("###")[2:]))  # lts flavour untouched
        self.assertEqual(self.src.read_text(), BAZZITE)  # the watcher never edits the pins
        self.assertEqual(self.out.read_text().strip(), "changed=true\ntitle=bazzite: new kernel (ogc 7.3.0-ogc4.1.fc44)")

    def test_kmod_name_regex(self):
        m = watch_bazzite.KMOD.search("kmod-nvidia-7.2.9-ogc3.1.fc44.x86_64-615.78.08-1.fc44.x86_64.rpm")
        self.assertEqual(m.group("nv"), "615.78.08")


class BumpBazziteFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.src = Path(self.tmp) / "sources.nix"
        self.src.write_text(BAZZITE)
        self.out = Path(self.tmp) / "github_output"
        self.out.write_text("")
        patcher = mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(self.out)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, self.old_cwd)
        self.prefetched = []

    def run_main(self, live, nv="615.78.08", layer=lambda repo, tag, tok: "cd" * 32, tarball=lambda v: f"sha256-{v}="):
        labels = lambda repo, ref, tok: {"ostree.linux": live[repo], "org.opencontainers.image.created": "2026-11-01"}

        def prefetch(url, unpack=False):
            self.prefetched.append(url)
            return "sha256-" + url.rsplit("/", 1)[-1][:8] + "="

        with mock.patch.object(wb, "token", lambda repo: "t"), \
             mock.patch.object(wb, "image_labels", labels), \
             mock.patch.object(wb, "single_layer", layer), \
             mock.patch.object(wb, "nvidia_version", lambda repo, d, tok: nv), \
             mock.patch.object(wb, "kernel_tarball_sri", tarball), \
             mock.patch.object(bump_bazzite, "nix_prefetch", prefetch), \
             mock.patch.object(sys, "argv", ["bump", "--sources", str(self.src)]):
            return bump_bazzite.main()

    CURRENT = {"bazzite": "7.2.9-ogc3.1.fc44.x86_64", "bazzite-nvidia": "6.18.56-ogc1.1.fc44.x86_64"}

    def test_current_changes_nothing(self):
        self.assertEqual(self.run_main(self.CURRENT), 0)
        self.assertEqual(self.src.read_text(), BAZZITE)
        self.assertEqual(self.out.read_text().strip(), "changed=false\ntodo=false")

    def test_never_downgrades(self):
        self.run_main({**self.CURRENT, "bazzite": "7.2.8-ogc3.1.fc44.x86_64"})
        self.assertEqual(self.src.read_text(), BAZZITE)

    def test_same_nvidia_keeps_userspace_hashes(self):
        self.run_main({**self.CURRENT, "bazzite": "7.3.0-ogc4.1.fc44.x86_64"})
        new = self.src.read_text()
        self.assertEqual(pinlib.get_field(new, ["ogc", "kernel"], "version"), "7.3.0")
        self.assertEqual(pinlib.get_field(new, ["ogc", "kernel"], "release"), "ogc4.1.fc44")
        self.assertEqual(pinlib.get_field(new, ["ogc", "kernel", "upstream"], "hash"), "sha256-7.3.0=")
        self.assertEqual(pinlib.get_layer(new, ["ogc", "kernel"]), ("akmods", "cd" * 32))
        self.assertEqual(pinlib.get_layer(new, ["ogc", "nvidia"]), ("akmods-nvidia-open", "cd" * 32))
        self.assertEqual(self.prefetched, [])
        # the other flavour is untouched
        self.assertEqual(pinlib.get_field(new, ["ogc-lts", "kernel"], "version"), "6.18.56")
        self.assertEqual(pinlib.get_layer(new, ["ogc-lts", "kernel"]), pinlib.get_layer(BAZZITE, ["ogc-lts", "kernel"]))
        self.assertEqual(len(new.splitlines()), len(BAZZITE.splitlines()))
        self.assertIn("ogc 7.3.0-ogc4.1.fc44", self.out.read_text())
        self.assertIn("branch=bump/bazzite-ogc-7.3.0-ogc4.1.fc44", self.out.read_text())
        self.assertIn("7.3.0-ogc4.1.fc44", (Path(self.tmp) / "bump-summary.md").read_text())

    def test_new_nvidia_recomputes_userspace_hashes(self):
        self.run_main({**self.CURRENT, "bazzite": "7.3.0-ogc4.1.fc44.x86_64"}, nv="615.99.01")
        new = self.src.read_text()
        self.assertEqual(pinlib.get_field(new, ["ogc", "nvidia"], "version"), "615.99.01")
        self.assertEqual(len(self.prefetched), 3)
        self.assertTrue(self.prefetched[0].endswith("NVIDIA-Linux-x86_64-615.99.01.run"))
        for field in ("sha256_64bit", "settingsSha256", "persistencedSha256"):
            self.assertNotEqual(pinlib.get_field(new, ["ogc", "nvidia", "userspace"], field),
                                pinlib.get_field(BAZZITE, ["ogc", "nvidia", "userspace"], field))
        self.assertEqual(len(new.splitlines()), len(BAZZITE.splitlines()))

    def test_unpublished_akmods_goes_to_todo(self):
        self.run_main({**self.CURRENT, "bazzite": "7.3.0-ogc4.1.fc44.x86_64"}, layer=lambda repo, tag, tok: None)
        self.assertEqual(self.src.read_text(), BAZZITE)
        self.assertIn("isn't published yet", (Path(self.tmp) / "bazzite-todo.md").read_text())
        self.assertIn("changed=false\ntodo=true\ntodo_title=bazzite: manual bump needed (ogc 7.3.0-ogc4.1.fc44)", self.out.read_text())

    def test_major_kernel_change_goes_to_todo(self):
        self.run_main({**self.CURRENT, "bazzite": "8.0.1-ogc1.1.fc44.x86_64"})
        self.assertEqual(self.src.read_text(), BAZZITE)
        self.assertIn("major version changed", (Path(self.tmp) / "bazzite-todo.md").read_text())

    def test_failed_prefetch_goes_to_todo(self):
        def boom(url, unpack=False):
            raise FileNotFoundError("nix")
        with mock.patch.object(bump_bazzite, "nix_prefetch", boom):
            labels = lambda repo, ref, tok: {"ostree.linux": {**self.CURRENT, "bazzite": "7.3.0-ogc4.1.fc44.x86_64"}[repo]}
            with mock.patch.object(wb, "token", lambda repo: "t"), \
                 mock.patch.object(wb, "image_labels", labels), \
                 mock.patch.object(wb, "single_layer", lambda *a: "cd" * 32), \
                 mock.patch.object(wb, "nvidia_version", lambda *a: "615.99.01"), \
                 mock.patch.object(wb, "kernel_tarball_sri", lambda v: "sha256-x="), \
                 mock.patch.object(sys, "argv", ["bump", "--sources", str(self.src)]):
                bump_bazzite.main()
        self.assertEqual(self.src.read_text(), BAZZITE)
        self.assertIn("userspace hashes", (Path(self.tmp) / "bazzite-todo.md").read_text())


if __name__ == "__main__":
    unittest.main()
