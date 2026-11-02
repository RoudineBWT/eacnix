# Keeping the pins current

The EAC path runs a vendor's signed kernel, grub and shim, pinned by hash in
`pkgs/<vendor>/sources.nix`. Four workflows keep those pins from going stale.
None of them pushes to a binary cache: the artifacts are fetched from their
vendors (Koji, ghcr.io) every time.

| Workflow | When | What it does |
|---|---|---|
| `check-pins.yml` | weekly, on PRs touching `pkgs/` or `scripts/` | Runs the script tests, then builds every pinned artifact (`nix build .#fedora-kernel …`) so a pin that can't be fetched any more fails here. On the weekly run a failure opens (or comments on) an issue labelled `pins`. |
| `bump-fedora.yml` | weekly, or by hand | `scripts/bump_fedora.py` finds the newest kernel, grub and shim of the pinned Fedora release on Koji (kernel and grub only if they reached Fedora's release/updates repos), downloads the RPMs, rewrites the pins and hashes. The workflow then refreshes `kernel-config` and `kernel-modules.list` (`nix build .#fedora-kernel.vendored`), runs `nix flake check`, and, if it passes, commits the bump straight to the default branch. If the checks fail, it opens a draft pull request instead and leaves the default branch alone. |
| `bump-bazzite.yml` | weekly, or by hand | `scripts/bump_bazzite.py` reads the `ostree.linux` label of Bazzite's `bazzite` (flavour `ogc`) and `bazzite-nvidia` (`ogc-lts`) stable images. For a flavour that moved to a newer kernel it rewrites the kernel pins, the akmods layer digests and the `kmod-nvidia` version, and, if NVIDIA's version changed, computes its userspace hashes with `nix store prefetch-file`. The workflow then refreshes `kernel-config` and `kernel-modules.list`, runs `nix flake check`, and, if it passes, commits to the default branch (draft PR if the checks failed). A flavour it can't bump on its own becomes an issue (label `bump`). |
| `update-flake-lock.yml` | weekly (Sunday), or by hand | `nix flake update`, then `nix flake check`. If it passes, `flake.lock` is committed to the default branch; if not, it goes to the branch `bump/flake-lock` with a draft pull request (reused on the next run). Nothing is done when the lock didn't change. |

## Why Bazzite has an issue fallback

Universal Blue builds NVIDIA's modules per kernel, and NVIDIA's userspace hashes
(`sha256_64bit`, `settingsSha256`, `persistencedSha256`) have to match the exact
version of its `kmod-nvidia`. The registry doesn't hold them, so the script
downloads NVIDIA's `.run` and the `nvidia-settings` / `nvidia-persistenced`
sources for that version and hashes them with Nix (this is the one step that
needs `nix`). If that fails, if the akmods images aren't published yet, or if
the kernel's major version changed, nothing is written for that flavour and the
issue says why. The manual steps are in the README ("To bump a vendor").
The comments in `pkgs/bazzite/sources.nix` that quote an image tag or digest
are not updated by the script.

## Setup

1. Settings → Actions → General → **Allow GitHub Actions to create and approve
   pull requests** (needed by the failure fallback of `bump-fedora.yml`, `bump-bazzite.yml` and `update-flake-lock.yml`). If
   the default branch is protected, allow `github-actions[bot]` to push to it.
2. Run each workflow once from the Actions tab (*Run workflow*) to check it works
   on your repository. Labels (`pins`, `bump`) are created on first use.
3. Pushes and pull requests made with the default token do not trigger other
   workflows. That's why the bump and update workflows run `nix flake check` themselves.

## Running the scripts by hand

```bash
python3 scripts/bump_fedora.py --dry-run     # report only, writes nothing
python3 scripts/bump_fedora.py               # rewrites pkgs/fedora/sources.nix, writes bump-summary.md
python3 scripts/bump_bazzite.py --dry-run    # report only; without it, rewrites pkgs/bazzite/sources.nix
python3 scripts/watch_bazzite.py             # report only: writes bazzite-report.md when a newer kernel exists
python3 -m unittest discover -s scripts -v   # offline tests (network mocked)
```

`bump_fedora.py` never goes backwards (a stale mirror can't downgrade a pin) and
only accepts builds present in Fedora's release/updates repositories, unless run
with `--allow-unstable`. If those repositories can't be listed it says so in the
commit or PR text instead of failing.

## Limits

- The parsing and rewriting of the pinned files and both scripts' decision logic
  are covered by offline tests. The calls to Koji, the Fedora mirrors, ghcr.io and
  cdn.kernel.org are not: they depend on those services' page and API formats,
  so the first runs should be watched.
- A passing bump lands on the default branch without review. It changes which
  signed boot chain the EAC entry runs: read the commit, and boot the new entry
  (`eacnix-check`) before relying on it.
- `check-pins.yml` can only tell that a pin is *gone*, not that it is *outdated*;
  the bump workflows cover that.
