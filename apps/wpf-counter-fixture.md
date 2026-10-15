# WPF counter fixture (`cua-lab/wpf_counter_fixture`)

The out-of-process proof harness for the minimized-window patch: a WPF app whose button
click bumps a counter and **writes it to a state file**, so a background UIA click can be
judged by app-owned state instead of by a read-back.

| | |
| --- | --- |
| Source | `%USERPROFILE%/source/repos/cua-lab/wpf_counter_fixture/` (`Program.cs`, `wpf_counter_fixture.csproj`) |
| Binary | `.../wpf_counter_fixture/bin/Debug/net10.0-windows/wpf_counter_fixture.exe` |
| Build | `dotnet build wpf_counter_fixture -v q --nologo` from `cua-lab/` (measured: 3.2 s, 0 warnings) |
| Window title | `CuaTestHarness WPF` |
| Process | `wpf_counter_fixture.exe` |
| State file | `argv[0]`; the recipe uses `%USERPROFILE%/source/repos/cua-lab/state-wpf-recipe.json` |
| Recipe | `wpf-minimized-increment` — 3 steps, verified 2026-10-15 |

## Controls (measured, 6 elements)

| Role | Label |
| --- | --- |
| Button | `Increment` (the fixture's only action) |
| Text | `counter=<n>` (updated by the click handler) |
| Button | `Minimize` / `Restore` — one toggling control, labelled by state; `Maximize` / `Close` beside it |
| TitleBar / MenuItem | `CuaTestHarness WPF` / `System` |

State file shape: `{"counter":<n>,"last":"loaded"|"click","pid":<pid>}` — `loaded` on start,
`click` after each click, overwritten wholesale, so it always names the driving process.
That pid field is what proves *which* instance a click landed on when several are running.

## What it proves (measured)

```bash
cuad run wpf-minimized-increment        # launch (fresh counter 0) → Minimize → Increment
```

```
ok   0 click  [2] Button "Minimize"   ✅ UIA Invoke (screen (567,243))
ok   1 click  [5] Button "Increment"  ✅ UIA Invoke (screen (-31759,-31880))
ok   2 expect 1 check(s) held                                    # text:counter=1
window stays iconic: 183x34 @-31992,-32000   (cuad wins)
state file: {"counter":1,"last":"click","pid":30472}             (the launched pid)
```

The click coordinate is off-screen (`-31759,-31880` — the minimized sentinel area), and the
app-owned counter still advanced: that is the whole point of the local patch. While iconic,
`right` / `count>1` / `foreground` on the same window are still refused with
`window_minimized` — see `probe_minimized_semantic.py` for that side of the contract.

## Pitfalls measured on this host

1. **The counter is cumulative.** A recipe run against a live window needs
   `--var expected=<current+1>`; the recipe's default `expected=1` assumes a fresh launch.
2. **`text:` is a substring match** — `counter=1` would also match a `counter=1x` row. A fresh
   launch (counter 0) is what makes the default unambiguous.
3. **Two instances share the title.** Measured: a stale fixture (pid 32424, its own state
   file) at `@168,160` and a freshly launched one (pid 30472). A plain
   `cuad act --window "CuaTestHarness WPF"` can drive either, so the recipe launches and pins
   the returned pid/window_id; the state file then proves the right instance moved.
4. **`Minimize` and `Restore` are one toggling button, not two controls.** The frame button is
   labelled `Minimize` while restored and `Restore` while iconic (the `observe` diff shows the
   row swap). So a "minimize" step is a move, not an assertion: replaying it on an
   already-iconic window fails with `no Button "Minimize" … nearest: [2] Button "Restore"`.
   Checks on the toggle are the cheapest way to prove the window really parked or came back
   (`wpf-minimize` / `wpf-restore` do exactly that).
5. **Kill what you launched**: `cuad call kill_app '{"pid":<pid>,"session":"omp"}'` works only
   for a process this runtime launched (`foreign_process_termination_denied` otherwise), which
   is exactly the case for this fixture.

## Related fixtures

`cua-lab/uia_minimized_invoke/` (raw UIA `Invoke` without the driver) and
`cua-lab/uia_minimized_probe.ps1` answer the same question one layer below the driver; use
them when the question is "does Windows deliver this at all", not "does the driver".
