---
name: cua-driver-local
description: >
  Drive native Windows GUI apps on THIS machine with the source-built, patched cua-driver-local
  product, normally through the fast `cuad` shell client. Use when the user asks to operate,
  automate, drive, or verify a real application's window on this host (click/type/read a GUI),
  or to continue earlier Cua driver work. Covers the install layout, the local Windows patch
  (semantic clicks on minimized windows), the measured pitfalls that waste calls, the per-app
  profiles (`apps/`) and replayable saved flows (`recipes/`, `cuad run`), and the fork that
  stores the patch. Drive a known app from its profile + recipe instead of re-deriving it.
---

# cua-driver-local (this machine)

Machine overlay for the driver's own skill pack. The pack (`cua-driver`, stashed at
`~/.cua-driver-local/packages/current/Skills/cua-driver/`, i.e. the `~/.agents/skills/cua-driver`
junction) holds the full loop, per-OS guides and failure maps — read it at that path for
anything beyond the shortcuts below. It is listed in `skills.ignoredSkills`, so omp never
advertises it: its every command says `cua-driver …`, which resolves through PATH to the
*unpatched* release binary on this host. This file only adds what is specific to this host.

Its companions live in this skill directory: `apps/<app>.md` (per-app knowledge, written on
first contact), `recipes/<name>.json` (saved flows, replayed with `cuad run`), and `fork.md`
(the fork branch that stores the patch, plus push/rebase/reinstall). Read the app profile before
driving that app; run the recipe before re-deriving a flow.

**This directory is itself a git repo**, pushed to
`https://github.com/yutthaphon/cua-driver-local` (private, branch `main`, remote `origin`).
The live skill directory *is* the checkout — there is no second copy to drift. After any edit
(a new profile, a fixed recipe, a new pitfall), commit and push from here:

```bash
cd "$USERPROFILE/.agents/skills/cua-driver-local"
git add -A && git commit -m "..." && git push
```

The driver patch is separate: it lives in the `yutthaphon/cua` fork, see `fork.md`.

## What is installed

| Thing | Path | Identity |
| --- | --- | --- |
| Source-built, patched driver | `%LOCALAPPDATA%\Programs\Cua\cua-driver-local\bin\cua-driver-local.exe` (junction → `~\.cua-driver-local\packages\current`) | `cua-driver-local`, state home `~\.cua-driver-local`, autostart task `cua-driver-local-serve` |
| Published release driver | `%LOCALAPPDATA%\Programs\Cua\cua-driver\bin\cua-driver.exe` | `cua-driver`, state home `~\.cua-driver` — **unpatched** |
| Fast client (this skill) | `~\.agents\skills\cua-driver-local\tools\cuad.py` (+ `cuad.cmd`, both on PATH) | speaks the local product's JSON contract |
| Raw client (this skill) | `~\.agents\skills\cua-driver-local\tools\ccdrv.py` (+ `ccdrv.cmd`) | passthrough to either product, `--bin local\|release` |
| Rebuild + reinstall | `%USERPROFILE%\source\repos\scripts\install-patched-driver.ps1` | one command; prints the provenance it installed |
| Build/install story | `%USERPROFILE%\source\repos\LOCAL-PATCHES.md` | clone, patch, rebuild, rollback |
| Fork write-up (this skill) | `~\.agents\skills\cua-driver-local\fork.md` | fork/remote identity, push, rebase, reinstall, provenance check |
| Per-app knowledge (this skill) | `~\.agents\skills\cua-driver-local\apps\<app>.md` | what each app needs, measured; template `apps/_template.md` |
| Saved flows (this skill) | `~\.agents\skills\cua-driver-local\recipes\*.json` | replayable `run_steps` batches: `cuad recipes`, `cuad run <name>` |
| Probe scripts + fixtures | `%USERPROFILE%\source\repos\cua-lab\` | `verify_install.py`, `probe_minimized_semantic.py`, `wpf_counter_fixture`, `uia_minimized_invoke` |

Always drive **`cua-driver-local`**. The release binary on the same machine lacks the
local patch, so behavior differs for minimized windows.

## Fast loop with `cuad`

`cuad` resolves the target window for you (title-based, which is what works for packaged
apps), starts the daemon when needed, keeps one default session label, and prints compact
rows instead of JSON. `--json` on any command prints the raw driver response.

```bash
python "$USERPROFILE/.agents/skills/cua-driver-local/tools/cuad.py" wins --window Calculator   # windows
python "$USERPROFILE/.agents/skills/cua-driver-local/tools/cuad.py" ax   --window Calculator   # tree, 1 line/element
python "$USERPROFILE/.agents/skills/cua-driver-local/tools/cuad.py" act  --window Calculator \
    --click Clear --click Six --click "Multiply by" --click Seven --click Equals \
    --expect "text:Display is 42"
python "$USERPROFILE/.agents/skills/cua-driver-local/tools/cuad.py" shot --window Calculator -o calc.png
python "$USERPROFILE/.agents/skills/cua-driver-local/tools/cuad.py" verify --window Calculator "text:Display is 42"
python "$USERPROFILE/.agents/skills/cua-driver-local/tools/cuad.py" call list_windows '{}'          # raw tool call
python "$USERPROFILE/.agents/skills/cua-driver-local/tools/cuad.py" desc run_steps                   # schema
python "$USERPROFILE/.agents/skills/cua-driver-local/tools/cuad.py" recipes                          # saved flows
python "$USERPROFILE/.agents/skills/cua-driver-local/tools/cuad.py" run wpf-minimized-increment      # replay one
python "$USERPROFILE/.agents/skills/cua-driver-local/tools/cuad.py" run calc-42 --dry-run            # payload only
```

`cuad.cmd` in the same directory lets shells that resolve `.cmd` use `cuad ...` directly;
that directory is on the User PATH, so `cuad version` works from a fresh shell
(and `cuad.cmd`/`ccdrv.cmd` are the entry points for `cmd`/PowerShell). If neither works
in the harness shell, call the driver binary through `python` (`subprocess`), which is
the locally proven path for `.exe` invocation — that is exactly what both tools do.

`ccdrv` (same directory) is the lower-level escape hatch: a passthrough to either product
with auto-start and `@file`/`-` JSON, for when you want the raw response or the release
binary for comparison.

```bash
ccdrv --bin local status                       # local build (patched)
ccdrv --bin release status                     # published release, for comparison
ccdrv call get_desktop_state '{}'
ccdrv json run_steps @steps.json
ccdrv list-windows '{"on_screen_only":true}'   # any tool as `ccdrv <kebab-name> [json]`
```

`act` step flags run in the order written; targets are `[role:]label[#nth]`. Anything
longer than a handful of steps, or anything needing a branch/loop, belongs in `run_steps`
JSON or `run_script` — send those with `cuad call run_steps @steps.json`.

| Flag | Step it adds |
| --- | --- |
| `--click` / `--rightclick` / `--doubleclick TARGET` | the click variant |
| `--set TARGET=VALUE` | `set_value` (the reliable way to fill a field) |
| `--type TEXT [--into TARGET]` | `type_text` |
| `--key enter` / `--key ctrl+s` | `press_key` / `hotkey` |
| `--expect` / `--wait` / `--gone CHECK` | a check after / before / for absence |
| `--value TARGET=TEXT` / `--value-is TARGET=VALUE` | precision checks on a field's value |
| `--shot PATH` | a break-out screenshot of the window (after the batch) |

Exit codes: `act`, `verify`, and `wins`/`ax` return 0 when the thing held, 1 otherwise, so
they compose in scripts. `cuad call` returns 1 only when the call itself could not be
completed — a structured refusal is data, printed and exited 0.

Check syntax is `text:<substring>` (any row of the tree, **substring and
case-insensitive** — `text:Z` matches far more than a `Z`) or `[role:]label`, plus
`--value` / `--value-is` for a field's own value. Prefer `--value` for anything numeric or
short; reserve `text:` for distinctive strings.

## Saved flows: `recipes/` and `apps/`

**Before driving an app, read its profile; before re-deriving a flow, run its recipe.**

```bash
cuad recipes                             # name, step count, verified date, target
cuad run <name>                          # replay; exit 0 only when the checks held
cuad run <name> --dry-run                # print the resolved run_steps payload
cuad run <name> --var k=v                # fill a {{k}} placeholder
cuad run <name> --no-launch              # drive the window that is already there
```

`recipes/<name>.json` is `{description, window|pid|app, launch?, launch_if_missing?,
include?, observe?, vars?, verified, notes, steps[]}`; it is ordinary `run_steps` JSON, so it
can be sent to `cuad call run_steps @file` too. Selectors on the command line override the
recipe's. `apps/<app>.md` holds what a profile must carry (identity, launch line, control map,
the app-owned state that proves an action, measured pitfalls) — `apps/_template.md` is the
checklist, `apps/calculator.md` / `character-map.md` / `wpf-counter-fixture.md` are the
three written so far.

**Writing a new recipe, or splitting one into sub-recipes: follow `recipes/README.md`.** It
carries the schema, the naming rule (`<app>-<action>.json`), the sub-recipe/wrapper split
(a sub-recipe has no `launch`; a wrapper owns the launch, the target and `verified`, and lists
its sub-recipes in `include`, whose steps run first), and the 9-step loop that ends in a
verified recipe. Two things from it are load-bearing:

- **Paths in a recipe must not name a user directory.** `cuad` resolves `%VAR%`/`$VAR`/`~`
  before dispatch, so write `%USERPROFILE%/source/repos/cua-lab/...`,
  `%SystemRoot%/System32/charmap.exe`, `~/.agents/skills/...`. This repo is public and the
  SKILL/app docs use the same convention (`$env:USERPROFILE` inside PowerShell fences, which
  is the syntax that actually expands there).
- **A recipe is written only from a run that passed** — dry-run, run, re-run, and a run with a
  wrong `--var` that fails with exit 1 — then `verified` gets that date.

Rules that keep the layer useful:

- **A launch pins the target.** With `launch`, the recipe drives the pid/window_id
  `launch_app` just returned — not the title — because a second instance of the same app
  shares the title and the driver would otherwise resolve the frontmost match (often an
  older window) inside the batch. `launch_if_missing` skips the launch when exactly one
  window matches (and pins it); with several matches it warns and falls back to
  frontmost-by-title, since the recipe cannot know which copy the caller meant.
- **Packaged apps: never put an AUMID in `app`.** `app` matches process names, so
  `app: Microsoft.WindowsCalculator_8wekyb3d8bbwe!App` is refused with
  `no window of app … (apps with windows: ApplicationFrameHost.exe)`. Launch by `name` and
  target by `window` title.
- **Write a recipe only from a run that passed**, record `verified` with the date and the
  command, and put the unproven parts in `notes` — a recipe that claims more than it proved
  is worse than no recipe.
- **Extend the profile in place** on the next visit; a second file for the same app defeats
  the point (see the loop in `apps/_template.md`).

## Measured pitfalls (each one cost a round trip)

1. **One read per turn per window.** Every `get_window_state` replaces the previous
   snapshot and invalidates its tokens; acting on the old token returns
   `stale_element_token`. `cuad act` avoids this entirely — the driver re-reads inside the
   batch. If you must hold a token, keep the read and the action in the same turn.
2. **Packaged (UWP) apps resolve by window title, not by app name.** Calculator's process
   is `ApplicationFrameHost.exe`; `--app Calculator` finds nothing while
   `--window Calculator` works. `cuad` prefers `--window` for exactly this reason.
3. **`launch_app` and `kill_app` must share one `session` label.** A kill from another
   session (or none) refuses with `foreign_process_termination_denied`. Launch by `path`
   or `name`; `aumid` launches come back with the broker/`ApplicationFrameHost` pid, which
   a later kill may not match.
4. **Minimized (iconic) windows: semantics yes, coordinates no** — the local patch.
   Windows parks a minimized window at `(-32000,-32000)`, so any coordinate transport
   silently no-ops; the driver refuses those shapes with `window_minimized`. A *semantic*
   background click (single left/middle, non-Chromium) is delivered through UIA and works
   while the window stays minimized. Consequences:
   - `click` with `delivery_mode:"background"`, single left, on a minimized window: works.
   - right click, `count>1`, `delivery_mode:"foreground"`, or a Chromium target while
     minimized: refused with `window_minimized`; `bring_to_front` first if you need it.
   - Screenshots of minimized windows still fail (`no rendered content`); the accessibility
     tree reads fine.
5. **Never start an app with `Start-Process`, `start`, `& app.exe`, or Win+key shell
   shortcuts** — they activate the target. Use `launch_app` (it goes through
   `SW_SHOWNOACTIVATE`). Verify the user's foreground app is untouched when the task says
   background.
6. **Background first, foreground only on a refusal.** Escalate the one refused action to
   `delivery_mode:"foreground"`; a refusal is not permission to escalate by itself.
7. **Chromium/Electron page content** needs the `browser_*` tools, not native clicks;
   attaching an existing logged-in profile needs the daemon started with
   `serve --grant existing-profile`, otherwise `browser_consent_required`.
8. **Kill/close what you opened.** `kill_app` with the launch session, or
   `hotkey alt+f4` and let the app close cleanly; `taskkill` on a user's app is data loss.
9. **Background `type_text` into a classic Win32 edit is dropped, and it says so.** The
   call returns `ok` with a message about the value not containing the text after dispatch
   (measured on Character Map's edit: `PostMessage` delivered, value unchanged). Fill fields
   with `set_value` (`cuad act --set ...`), which lands through UIA `ValuePattern`, or
   re-send that one action with `delivery_mode:"foreground"`. Do not treat the `ok` status
   as proof for keystroke input — read the field back (`--value`).
10. **A `cuad`/driver step that "succeeds" is not proof.** Effects land in app-owned state;
    read it back (`cuad ax --query`, `--value`, a state file, or the app's own document).
11. **One app can expose several live `window_id`s with the same title**, and stale ids
    linger after the window is gone (measured: one Calculator process listed 6 windows at
    the same bounds, z-order 21–26). `cuad` therefore picks the frontmost non-minimized
    match and says so on stderr; pin `--pid`/`--window-id` when it matters, and prefer a
    fresh `cuad wins` over a remembered id.
12. **An ended session label rejects every call until it is started again, and nothing starts
    it for you.** After any run that ends the label (`end_session`, or another session's
    `end_session` on a shared default), `cuad act`/`ax`/`verify` printed `FAIL: None/None
    steps` with exit 1 while the real reason — `session has ended; … Call start_session with
    session 'omp'` — sat on the driver's stderr. `cuad up` does not fix it. `cuad` now revives
    the label and retries the call once (see `revive_session` in `call_tool`), and prints that
    reason instead of `None/None` when a step report is missing. `ccdrv` does neither: start it
    yourself with `ccdrv call start_session '{"session":"<label>"}'`.
13. **`app` never resolves a packaged (UWP) app.** `app` matches `app_name` (the process), so
    an AUMID is refused: `no window of app "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App"
    (apps with windows: ApplicationFrameHost.exe)`. Launch by `name`, target by `--window`
    title — and do not put the AUMID in a recipe's `app` field.
14. **A duplicate-title window can be a dead one.** Measured on this host: two live
    `Calculator` windows, the `CalculatorApp.exe` one (pid 23336, window 4066302) answering
    every read with `degraded:true / ax_tree_empty` (`nodes_visited=1`, `walk_elapsed_ms=315`)
    while the `ApplicationFrameHost` window showed 39 elements. `--window Calculator` alone
    takes the frontmost match and can land on the dead one, so `cuad run` launches and pins
    when the recipe asks for it (pitfall 11 is the general form).
15. **`--value` / `--value-is` are `TARGET=VALUE`, and TARGET is `[role:]label`.** Two
    measured traps: naming the role alone (`--value "Edit=!"` on Character Map) fails with
    `element "Edit" is shown … found no addressable match`, because the label is
    `Characters to copy :`; and dropping the `=` (`--value "Edit:Characters to copy :!"`)
    is not a failed check but a rejected batch —
    `invalid_batch: expect 1: `value_contains` must be a non-empty string`. The value side is
    tolerant: `--value-is` passed against a row reporting `"!\r"` (trailing `\r` ignored),
    and failed with the row quoted for a genuinely different value.
16. **A polite close is `--click` on the window's own frame button.** Measured on Calculator:
    clicking `Close Calculator` on each frame window ended both `CalculatorApp.exe`
    instances, while the shared `ApplicationFrameHost.exe` (pid 10280) kept serving its
    `Settings` window — closing one UWP window does not take the host down with it.

## Verify, then stop

Prove the outcome from app-owned state: a fixture/state file, `cuad ax --query <name>` /
`cuad act --value "<target>=<text>"` (both exit 1 when the check fails), or
`cuad verify --window <title> "text:<distinctive string>"`. A saved flow already carries its
checks, so `cuad run <name>` is the cheapest proof for anything it covers. Stop after the
proof; `end_session` for the run, and do not `cua-driver-local stop` a daemon other work may
be using.

The installed product's own end-to-end check (daemon, packaged-app flow, and the
minimized-window patch) lives at
`%USERPROFILE%\source\repos\cua-lab\verify_install.py` — run it after any reinstall.

## When something fails

| Symptom | Move |
| --- | --- |
| `daemon is not running` | `cuad up` (or `cua-driver-local autostart kick`) |
| `stale_element_token` | re-read, or use `cuad act` (one batch, fresh read inside) |
| `window_minimized` | semantics only — see pitfall 4; `bring_to_front` for coordinates |
| `background_unavailable` | one action with `delivery_mode:"foreground"` |
| `element_not_found` / wrong window | `cuad wins --window <title>` then pass `--pid`/`--window-id` |
| `session has ended` (before the fix: `FAIL: None/None steps`) | `cuad` revives the label itself; for `ccdrv`, `ccdrv call start_session '{"session":"<label>"}'` — see pitfall 12 |
| `degraded:true` / `ax_tree_empty` | the read hit a canvas/custom-drawn surface or a duplicate dead window; `cuad wins` to see the copies, then pin `--pid`/`--window-id` or let a recipe's `launch` pin the fresh window — see pitfalls 11/14 |
| `foreign_process_termination_denied` | `kill_app` only terminates what this runtime launched; close through the UI (`--click "<Close button>"` on the frame window) |
| `invalid_batch: … must be a non-empty string` | a `--value`/`--value-is` target lost its `=`; form is `TARGET=VALUE` with `TARGET=[role:]label` — see pitfall 15 |
| Odd environment result | `cuad doctor`, then `cua-driver-local status` |
| Need the full tool schema | `cuad desc <tool>`; `cuad tools <pattern>` lists them |
| Need what a previous session learned about an app | `apps/<app>.md`, then `cuad recipes` |
