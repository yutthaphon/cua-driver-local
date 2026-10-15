# Recipes: the per-app playbook

A recipe is a saved, verified `run_steps` batch for one app. The point is to pay for an app's
discovery once: next session runs `cuad run <name>` and reads its profile, instead of
re-deriving selectors from an accessibility dump.

```
apps/<app>.md      what the app needs (read this first)
recipes/<app>-*.json   flows you can execute
cuad run <name>    replay one; exit 0 only when its checks held
```

## Naming

`<app>-<action>.json`, lowercase, hyphenated: `calc-42`, `charmap-copy-first`,
`wpf-minimized-increment`. The name is what a future session greps for, so lead with the app.
Grouping is by prefix, so a directory per app is unnecessary.

## Schema

| Key | Meaning |
| --- | --- |
| `name` | same as the file stem; used in messages |
| `description` | one line: what the batch does and what it checks |
| `window` / `app` / `pid` / `window_id` | the target. Prefer `window` (title) — it is the only selector that works for packaged apps; `app` matches process names, never an AUMID |
| `launch` | `launch_app` arguments; the launch **pins** the pid/window_id it creates |
| `launch_if_missing` | with `launch`: skip the launch when exactly one window already matches, and pin it; with several, warn and fall back to frontmost-by-title |
| `include` | sub-recipes whose steps run first, in order (see below) |
| `vars` | defaults for `{{placeholders}}`; the command line overrides them |
| `observe` | default `true`: ask the driver for the end-of-batch diff |
| `verified` | `YYYY-MM-DD` of the last passing run, or `null` with the reason in `notes` |
| `notes` | the measured traps, preconditions and caveats — this is the part that saves calls |
| `steps` | the `run_steps` batch; may be empty when `include` supplies the steps |

Selectors on the command line override the recipe's (`--window`, `--pid`, `--window-id`), so a
recipe stays usable when the app is running under another instance.

## Sub-recipes: one behavior per file

A **sub-recipe** is a recipe with no `launch` block: one small behavior, runnable on its own
and reusable inside a bigger flow. A wrapper **includes** sub-recipes and owns the launch and
the target:

| | Sub-recipe | Wrapper |
| --- | --- | --- |
| Job | one behavior, e.g. "click Select, check the field" | the flow, e.g. "bring the app up, then do that" |
| `launch` | never | owns it |
| `window`/`app` | names the window so it can run standalone | owns the target that the launch pins |
| `verified` | date of its own passing run | date of the composed run |
| `steps` | its steps | may be empty; `include` supplies the rest |

Rules of composition:

- Included steps run **first**, in the order the names are listed:
  `"include": ["wpf-minimize", "wpf-increment"]` → Minimize, then Increment.
- Included `vars` become defaults; the wrapper's `vars` and `--var` override them.
- `launch`, `launch_if_missing`, `window`/`app`/`pid`, `observe` and `verified` are **not**
  inherited — a wrapper states them, so what a flow does stays readable in one file.
- Nesting is allowed to 8 levels; a cycle is caught by that depth limit.
- A sub-recipe must stay runnable alone (`cuad run wpf-increment --var expected=4`), otherwise
  it is a snippet pretending to be a recipe — put snippets in the profile instead.

When to split: the moment two flows need the same steps, or one flow is a prelude plus a
behavior. When *not* to split: a single self-contained flow — `calc-42` is one file with its
launch, five clicks and the check, and that is correct.

## Paths: keep the machine out of the recipe

Recipes are committed to a public repo, so they must not carry one machine's user directory.
Use `%VAR%` / `$VAR` / `~`, which `cuad` resolves at dispatch (`os.path.expandvars` then
`os.path.expanduser`):

| Write | Instead of |
| --- | --- |
| `%USERPROFILE%/source/repos/cua-lab/...` | `C:/Users/<name>/source/repos/cua-lab/...` |
| `%SystemRoot%/System32/charmap.exe` | `C:/Windows/System32/charmap.exe` |
| `~/.agents/skills/cua-driver-local/...` | the absolute home path |

The same applies to `apps/*.md` and these docs.

## The loop that produces a recipe

Start from `apps/_template.md`; a recipe is written only from a run that passed.

```bash
cuad wins --window "<Title>"                       # 1. what resolves the window?
cuad call launch_app '{"name":"<App>", ...}'       # 2. does it come up in the background?
cuad ax --window "<Title>" --actionable            # 3. control map: role, label, actions
cuad act --window "<Title>" --click X --value "Y=Z"   # 4. one batch; fix the failing step
```

5. **Distil** the working command line into the recipe: one step per flag, `expect` last.
6. **Add the proof**: check app-owned state, not the step's `ok` — a field value
   (`--value`/`--value-is`), a distinctive `text:`, or a file the app writes.
7. **Re-run it three ways** before recording a date:

```bash
cuad run <name> --dry-run            # the payload is the batch you meant
cuad run <name>                      # passes: exit 0, every step ok
cuad run <name>                      # a second time: proves idempotence or documents it
cuad run <name> --var <k>=<wrong>    # fails with exit 1 (a check that cannot fail is not a check)
```

8. Set `verified` to that date, and put every leftover trap in `notes` — including the
   precondition the default vars assume (`wpf-increment` assumes a fresh counter).
9. Update the app profile with what the recipe taught you, then commit both together.

## Verified flows

| Recipe | What it proves | Verified |
| --- | --- | --- |
| `calc-42` | packaged app, background clicks, display read-back | 2026-10-15 |
| `charmap-copy-first` (+ `charmap-select`) | classic Win32 edit, launch-if-missing, `--value` check | 2026-10-15 |
| `wpf-minimized-increment` (+ `wpf-minimize`, `wpf-increment`) | composed sub-recipes; semantic click lands while the window stays iconic | 2026-10-15 |
| `wpf-minimize` / `wpf-restore` | the frame button toggles label; proves the park and the way back | 2026-10-15 |
