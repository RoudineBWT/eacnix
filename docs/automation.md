# Keeping the pins current

The EAC path runs a vendor's signed kernel, grub and shim, pinned by hash in
`pkgs/<vendor>/sources.nix`. Three workflows keep those pins from going stale.
None of them pushes to a binary cache: the artifacts are fetched from their
vendors (Koji, ghcr.io) every time.

| Workflow | When | What it does |
|---|---|---|
| `check-pins.yml` | weekly, on PRs touching `pkgs/` or `scripts/` | Runs the script tests, then builds every pinned artifact (`nix build .#fedora-kernel …`) so a pin that can't be fetched any more fails here. On the weekly run a failure opens (or comments on) an issue labelled `pins`. |
| `bump-fedora.yml` | weekly, or by hand | `scripts/bump_fedora.py` finds the newest kernel, grub and shim of the pinned Fedora release on Koji (kernel and grub only if they reached Fedora's release/updates repos), downloads the RPMs, rewrites the pins and hashes. The workflow then refreshes `kernel-config` and `kernel-modules.list` (`nix build .#fedora-kernel.vendored`), runs `nix flake check`, and opens a pull request (a draft if the checks failed). |
| `watch-bazzite.yml` | weekly | `scripts/watch_bazzite.py` reads the `ostree.linux` label of Bazzite's `bazzite` (flavour `ogc`) and `bazzite-nvidia` (`ogc-lts`) stable images. If it differs from the pin it opens an issue (label `bump`) with the new kernel string, the akmods layer digests, the `kmod-nvidia` version and the kernel tarball hash, ready to paste. |

## Why Bazzite is only watched

Universal Blue builds NVIDIA's modules per kernel, and NVIDIA's userspace hashes
(`sha256_64bit`, `settingsSha256`, `persistencedSha256`) have to match the exact
version of its `kmod-nvidia`. Those hashes can't be derived from the registry, so
a blind bump would build a driver that refuses its own modules. The watcher does
the lookups and leaves the last step to a person. The steps are in the README
("To bump a vendor").

## Setup

1. Settings → Actions → General → **Allow GitHub Actions to create and approve
   pull requests** (needed by `bump-fedora.yml`).
2. Run each workflow once from the Actions tab (*Run workflow*) to check it works
   on your repository. Labels (`pins`, `bump`) are created on first use.
3. A pull request opened with the default token does not trigger other
   workflows. That's why `bump-fedora.yml` runs `nix flake check` itself.

## Running the scripts by hand

```bash
python3 scripts/bump_fedora.py --dry-run     # report only, writes nothing
python3 scripts/bump_fedora.py               # rewrites pkgs/fedora/sources.nix, writes bump-summary.md
python3 scripts/watch_bazzite.py             # writes bazzite-report.md when a newer kernel exists
python3 -m unittest discover -s scripts -v   # offline tests (network mocked)
```

`bump_fedora.py` never goes backwards (a stale mirror can't downgrade a pin) and
only accepts builds present in Fedora's release/updates repositories, unless run
with `--allow-unstable`. If those repositories can't be listed it says so in the
pull request instead of failing.

## Limits

- The parsing and rewriting of the pinned files and both scripts' decision logic
  are covered by offline tests. The calls to Koji, the Fedora mirrors, ghcr.io and
  cdn.kernel.org are not: they depend on those services' page and API formats,
  so the first runs should be watched.
- The pull request is a proposal. A bump changes which signed boot chain the EAC
  entry runs: read the diff, and boot the new entry (`eacnix-check`) before
  relying on it.
- `check-pins.yml` can only tell that a pin is *gone*, not that it is *outdated*;
  the bump workflows cover that.
