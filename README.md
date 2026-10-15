# cua-driver-local

An omp/agent skill that drives native Windows GUI apps on one machine through a
source-built, patched `cua-driver-local` product — plus the knowledge layer that
stops the next session from re-deriving an app.

It is the machine overlay for the driver's own skill pack: install layout, the
local Windows patch (semantic clicks on a *minimized* window), the measured
pitfalls that each cost a round trip, per-app profiles, and replayable recipes.

## Layout

| Path | What |
| --- | --- |
| `SKILL.md` | the skill: install layout, the `cuad` fast loop, measured pitfalls, failure table |
| `apps/<app>.md` | per-application knowledge: identity, launch line, control map, the app-owned state that proves an action, measured pitfalls |
| `apps/_template.md` | the checklist and the loop used to write one |
| `recipes/*.json` | saved `run_steps` batches, replayed with `cuad run <name>` |
| `recipes/README.md` | recipe schema, naming, sub-recipe composition, the authoring loop |
| `fork.md` | the `yutthaphon/cua` fork holding the driver patch: push, rebase, reinstall, provenance |
| `tools/cuad.py` | fast client: window resolution by title, batched actions, compact reads, recipes |
| `tools/ccdrv.py` | raw passthrough to either product (`--bin local\|release`) |

## Quickstart

```bash
cuad recipes                                  # saved flows
cuad run wpf-minimized-increment              # replay one; exit 0 only if the checks held
cuad wins --window Calculator                 # what resolves this app
cuad ax --window Calculator --actionable      # control map, one line per element
cuad act --window Calculator --click Clear --click Six --click "Multiply by" \
    --click Seven --click Equals --expect "text:Display is 42"
```

## Verified flows

| Recipe | What it proves | Verified |
| --- | --- | --- |
| `calc-42` | packaged app, background clicks, display read-back | 2026-10-15 |
| `charmap-copy-first` (+ `charmap-select`) | classic Win32 edit, launch-if-missing, field-value check | 2026-10-15 |
| `wpf-minimized-increment` (+ `wpf-minimize`, `wpf-increment`) | composed sub-recipes; a semantic click lands while the window stays iconic | 2026-10-15 |
| `wpf-minimize` / `wpf-restore` | the frame button toggles label; proves the park and the way back | 2026-10-15 |

## Machine-specific by design

`SKILL.md` describes one machine: paths under `%USERPROFILE%` and `%LOCALAPPDATA%`, the
daemon's named pipe, and the measured behaviors of the apps installed here. The driver patch
itself lives in the [`yutthaphon/cua`](https://github.com/yutthaphon/cua) fork, not in this
repo — see `fork.md`. Paths inside recipes use `%VAR%`/`$VAR`/`~`, which `cuad` resolves
before dispatch, so a recipe does not carry a user directory; the prose docs follow the same
convention.
