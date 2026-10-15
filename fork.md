# The fork: identity, and how to store/re-apply this work

The one product change on this machine is published to the user's own fork. Everything below
was read from the clone on 2026-10-15, not recalled.

| | |
| --- | --- |
| Fork | `https://github.com/yutthaphon/cua.git` — the clone's `fork` remote |
| Upstream | `https://github.com/trycua/cua.git` — the clone's `origin` (partial clone, `blob:none`, promisor) |
| Branch | `local/windows-driver-fixes` |
| Commit | `3b5e8ba0f80c3de835b30b28f574f5d6c8558d3b` |
| Base | `d74a9cab3fb2` — the commit the installed `0.35.4` binary was built from |
| Fork sync | `git rev-list --left-right --count fork/local/windows-driver-fixes...HEAD` → `0 0` (in sync) |
| Working tree | clean (`git diff --stat HEAD` empty) |
| Compare | https://github.com/trycua/cua/compare/main...yutthaphon:cua:local/windows-driver-fixes |
| Upstream issue | https://github.com/trycua/cua/issues/2015 |
| Patch | `$env:USERPROFILE\source\repos\patches/0001-fix-cua-driver-scope-the-minimized-window-click-refu.patch` |

Clone: `$env:USERPROFILE\source\repos\cua` — **sparse** (`core.sparseCheckout=true`), the
checkout list is exactly:

```
libs/cua-driver
libs/cua/crates/cua-telemetry
libs/cua/crates/cua-teleport
libs/images
scripts/ci
```

That sparseness (plus `blob:none`) is why clone/fetch here are cheap: only the driver subtree
and its build inputs are materialized. Re-create it on a fresh machine with
`git sparse-checkout set <those paths>` after cloning the fork.

## Store the work (already done; this is the recipe)

```powershell
cd $env:USERPROFILE\source\repos\cua
git status -sb                                  # expect: no ahead/behind vs fork/...
git push fork local/windows-driver-fixes        # publish; `-u` once to set upstream
```

The clone's `fork` remote points at `yutthaphon/cua`; `origin` is upstream and is never
pushed to. No PR is opened from here — the fork branch plus issue #2015 is the record.

Regenerate the replayable patch after any edit to the branch (the sync script also does it):

```powershell
git format-patch d74a9cab3fb2..HEAD -o $env:USERPROFILE\source\repos\patches
```

## Re-apply / refresh against upstream

```powershell
pwsh -NoProfile -File $env:USERPROFILE\source\repos\scripts/sync-upstream.ps1
#   fetch origin, print ahead/behind, list the local commits, diff each touched file
#   against upstream, regenerate ../patches — pushes nothing
pwsh -NoProfile -File $env:USERPROFILE\source\repos\scripts/sync-upstream.ps1 -Rebase
#   move the work onto origin/main; then rebuild, and re-run the E2E cell, because the
#   installed binary is no longer the verified one
```

## Rebuild + reinstall the patched product from the fork tree

```powershell
pwsh -NoProfile -File $env:USERPROFILE\source\repos\scripts\install-patched-driver.ps1
#   restores libs/cua-driver/rust/Cargo.lock before and after the build, runs
#   libs/cua-driver/scripts/install-local.ps1, prints the provenance it installed
python $env:USERPROFILE\source\repos\cua-lab\verify_install.py     # expect 17/17
```

`install-patched-driver.ps1` exists because the machine-wide `msvc_spectre_libs` stand-in in
`~/.cargo/config.toml` makes cargo rewrite `Cargo.lock` on every build, and the installer
records the source commit from `git status` *before* building — restoring the lock first is
what keeps the installed product reporting the clean commit `3b5e8ba0f` instead of
`<sha>-dirty`. Install the Visual Studio "MSVC Spectre-mitigated libs" component and the
cargo patch can go away.

Provenance check after any reinstall: `cuad doctor` must print
`git: 3b5e8ba0f80c` (or whatever the branch head now is) — if it prints a `-dirty` sha, the
lock hygiene above did not hold, and the installed binary cannot be traced to a commit.

## Ship it upstream (only when asked)

`patches/0001-*.patch` replays on a clean clone of `main`. One upstream hunk touches the same
file (`check_permissions`'s input schema) and does not overlap; rebase first, re-run the E2E
cell on the rebased build, then open the PR referencing issue #2015.
