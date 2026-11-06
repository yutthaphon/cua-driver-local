# MetaTrader 5 (terminal64.exe)

Source-built driver knowledge for driving MT5 on this host. First measured 2026-10-26 on
build 5.0.0.6230, window `1090143 - VTMarkets-Demo … [XAUUSD-VIP,M15]`.
**Re-measured 2026-11-06 with `agent-desktop`: the accessibility story below is new and
replaces the old "no UIA at all" conclusion.**

Two driver generations appear in this file:

| Tool | What it can do |
| --- | --- |
| `agent-desktop` (`desktop_*` MCP tools) | **preferred.** Reads a real UIA tree, resolves elements by name, clicks semantically (no cursor, no focus steal), detects and presses dialog buttons |
| `cuad` / `cua-driver-local` (`cuad.py`, `ccdrv`) | coordinate `SendInput`, app launch, screenshots; MT5 exposes nothing to it — `get_window_state` returns `elements=0/0` |

## Identity

| | |
| --- | --- |
| Process | `terminal64.exe` (NOT `terminal.exe`; both can exist) |
| Window | one per chart, title `<account> - <broker> - [SYMBOL,TF]` |
| Dialogs | **separate top-level windows** of the same process — `Properties of <SYM>,<TF>`, `<Script> <ver> (<SYM>,<TF>)`, `Indicators`, … Each gets its own window id, so re-list after opening one |
| Class | `MetaQuotes::MetaTrader::5.00` |
| Accessibility | **exposed — but only through agent-desktop.** `cua-driver`'s `get_window_state` returns `elements=0/0`, `degraded:true`; `agent-desktop`'s `desktop_snapshot` reads a full UIA tree (~170 nodes). See the revised section below. |
| Data folder | `%APPDATA%\MetaQuotes\Terminal\<instance-id>\` |
| MetaEditor | `C:\Program Files\MetaTrader 5\MetaEditor64.exe` |

## Accessibility: use agent-desktop, not coordinate clicks (measured 2026-11-06, build 6230)

The 2026-10-26 note said "there is no UIA tree, every interaction is a coordinate click".
**That is wrong for this host.** Re-measured with `agent-desktop` on the same build:

| Surface | What agent-desktop sees |
| --- | --- |
| Whole terminal | `desktop_snapshot` → ~167–170 nodes, `complete:false` with subtrees |
| Navigator | `role: outline` (a real `SysTreeView32`), root `treeitem` "MetaTrader 5" with 7 children: Accounts, Indicators, Expert Advisors, Scripts, Services, Market, VPS; every leaf is a `treeitem` carrying a `Click`/`Select`/`ScrollTo` action and its `value` |
| Market Watch | `role: listbox` with `option` rows |
| Strategy Tester | a `role: dialog` panel of buttons + `tablist` (Overview / Agents / Journal). Most buttons carry a name (`Single`, `Indicator`, `Visualize`, `Stress & Delays`, …); the first one has *only* `automation_id 3734` and no name, so it is clickable by ref but not findable by name — and clicking it did not open anything, so its purpose is unconfirmed |
| Chart area | a bare `role: group` — the chart itself is drawn, so nothing inside it is readable |
| Market Watch title | carries the server clock, e.g. `Market Watch: 18:47:56` — a free liveness read |

Consequences:

- **Read first, click second.** Take `desktop_snapshot` and look for a name before falling
  back to coordinates. `cuad--window <title>` coordinate clicks are the *last* resort: in the
  2026-11-06 session a desktop-scope click aimed at the Navigator tree landed on an unrelated
  HWND, and another landed on an unrelated script dialog.
- **`treeitem`s advertise `Click` but do not accept it.** Clicking the Services →
  `VertaMTF_Core` node returned `POLICY_DENIED` ("direct semantic delivery is unavailable and
  physical fallback is denied"); the same with `headed: true` returned `ACTION_FAILED`. So a
  service/script/indicator still has to be *activated by the user* — reading the tree is fine,
  starting it is not.
- **Dictionary keys come for free.** `desktop_find` on the whole window times out
  (`TIMEOUT`, ~1300 nodes visited) — narrow it with `root: "@<snap>:eN"` or the app's own
  subtree instead of searching the terminal.

## Popups (Properties / attach / script inputs) — fully automatable

Measured 2026-11-06. MT5 dialogs are **separate top-level windows** of `terminal64.exe`, not
child controls of the chart window:

```
desktop_list_windows → {"app_name":"terminal64.exe","id":"w-22418158",
                        "title":"Properties of XAUUSD-VIP,M5","accessible":true,
                        "is_focused":true, "bounds":{940x620}}
```

That is the whole trick: **list windows, not chart children.** A modal dialog is its own
entry, so `desktop_wait` can block on it:

```bash
# 1. open it (F8 = chart properties; see the keyboard note below)
agent-desktop press f8 --window-id w-<chart> --headed
# 2. wait for the title — measured 162 ms
agent-desktop wait --window "Properties of XAUUSD-VIP,M5" --timeout-ms 10000
# 3. snapshot THAT window id, not the terminal
agent-desktop snapshot --window-id w-<dialog>
```

The dialog tree is complete and semantic:

```
role: window, role_description: dialog, states: ["focused","modal"]
├── role: dialog (the tab page: "Colors") with named comboboxes and their values
├── button "OK"      native_id automation_id=1   actions: Click, SetFocus
├── button "Cancel"  native_id automation_id=2   actions: Click, SetFocus
├── button "Help"    native_id automation_id=9   actions: Click, SetFocus
├── tablist: Common | Show | Colors   (Colors selected)
└── title bar group → "Context help", "Close"
```

- **`automation_id` 1 / 2 / 9 for OK / Cancel / Help** on the dialog measured. That is the
  Win32 `IDOK`/`IDCANCEL`/`IDHELP` convention, so it very likely repeats on MT5's other
  dialogs — but only this one was measured, so confirm with a snapshot before relying on it.
- Clicking is **semantic** (`InvokePattern.Invoke`, no cursor, no focus steal) and it works:
  measured OK closed the dialog and returned focus to the chart window. Verified by
  `desktop_list_windows` afterwards — the entry is gone.
- A script/EA input dialog also appeared as its own listed window in an earlier session
  (`QEP_Tests 1.00 (XAUUSD-VIP,M5)`, `accessible:true`). That is the popup you must accept
  after dragging a script/EA onto a chart; it was listed but not snapshotted, so its button
  ids are unconfirmed.
- Reading values works too: combobox `value` fields show the live setting
  (`"Green on Black"`, `"Black"`, `"White"`, …), so a dialog can be *audited* without
  changing anything — open, snapshot, then Cancel.

### Keyboard needs `--headed`

| Attempt | Result |
| --- | --- |
| typed `desktop_press` `ctrl+i` (strict headless) | `delivered_unverified`, **no dialog appeared** |
| raw `press f8 --window-id w-<chart> --headed` | dialog opened (verified by `list_windows`) |
| raw `press ctrl+i --window-id w-<chart> --headed` | **still no dialog** — Ctrl+I is not a working entry point on this build |

Only the headed `F8` path is proven; the headless-vs-headed difference for `f8` specifically was
not isolated (headless was tested with `ctrl+i`).

So: send keys with `--headed` **after** `desktop_focus_window`, and use `F8` (chart
properties) as the reliable way to raise a dialog for automation tests. `desktop_press`'s
`delivered_unverified` is exactly what it says.

### Starting the automated-trading Service

`Services` in the Navigator can be *read* but not activated (see above), and the startup ini
does **not** work for it:

```ini
[StartUp]
Service=VertaMTF_Core
```

MT5's own log then says `Startup successfully initialized from start config` and **nothing
starts** (measured twice, 2026-11-06 22:00 and 22:01). The user must double-click the service
in the Navigator once. After that the terminal log shows
`Services service 'VertaMTF_Core' started` and the service's own log lands under
`MQL5\Files\...`. Do not try to fake this with clicks — ask the user.

## Launch with a startup config (this is the workhorse)

```bash
cuad call launch_app '{"path":"C:\\Program Files\\MetaTrader 5\\terminal64.exe","additional_arguments":["/config:D:\\path\\run.ini"]}'
```

`run.ini` (ANSI or UTF-8, `[StartUp]` section):

```ini
[StartUp]
Symbol=XAUUSD-VIP
Period=M15
Script=PatternCast\Tests\ProbeRunner
ScriptParameters=InpRun=1||InpVerbose=true
```

- `Script=`, `Indicator=` (attaches to the new chart), `Expert=`, `Profile=`, `Template=`.
- Parameters are separated by `||`, **not** `,`.
- **A `/` anywhere in `ScriptParameters` breaks the line** — the terminal reads it as a
  switch. `InpPath=PatternCast/Tests` silently truncates. Hardcode such paths in the
  source instead (measured: three failed launches before this was identified).
- `Script=` is relative to `MQL5\Scripts`, `Indicator=` to `MQL5\Indicators`, and the
  path must match the junction layout exactly, not the on-disk layout. On this host
  `MQL5\Scripts\PatternCast` is a junction to `D:\PatternCast\PatternCast\Tests`, so a
  script living at `Tests\T01_AtrExact.mq5` is `Script=PatternCast\T01_AtrExact` — writing
  `PatternCast\Tests\T01_AtrExact` silently does nothing (the terminal starts, no script
  runs, no log line, no error). Check what the junction exposes before naming a script:
  `powershell -c "Get-ChildItem <MQL5>\Scripts\PatternCast | Select Name"`.
- `iCustom()` inside a script takes a path relative to `MQL5\Indicators`, with
  **backslashes**, and it must include the `Tests` subfolder if that is where it lives:
  `iCustom(_Symbol, PERIOD_CURRENT, "PatternCast\\Tests\\PanelProbe")`.

`launch_app` returns the pid immediately and `windows` empty for the first few seconds;
the chart window appears ~8–15 s later. Poll `cuad wins` once, then work.

## Coordinate model (the part that costs calls)

> **Superseded for reading.** Everything below is only needed for the *chart canvas*
> (drawn, not in UIA) or when `agent-desktop` is unavailable. Navigator, Market Watch,
> Strategy Tester and every dialog are readable and clickable by name — start there.


Measured: **one chart pixel == one screen pixel** for a maximised window on this display,
so the only unknown is the chart **origin**. Two numbers solve it:

```
screen_x = origin_x + chart_x      screen_y = origin_y + chart_y
```

Get them from the app itself, not from a screenshot guess: have the indicator log
`CHARTEVENT_CLICK`'s `lparam`/`dparam` (which are chart-local) for one click, then

```
origin = screen_coord_of_that_click - chart_coord_logged
```

Measured on this host: `origin = (359, 95)` for the chart at 2560x1540, and the origin
moves when the Market Watch panel or a toolbar changes width — re-derive it, do not
remember it.

Do **not** try to derive the scale from a screenshot: the PNG the driver returns is
downscaled (1568 px for a 2560 px window = 0.6125), and mixing that factor with chart
pixels produced a 1.17x error that wasted a dozen clicks.

## Transport rules (measured failures)

| Attempt | Result |
| --- | --- |
| `click` with `x,y` + window scope, no capture | `screenshot_context_missing` — a window-scoped pixel click needs a capture of *that* window in the same session |
| `get_window_state` then `click` in one `run_steps` | read is `skipped` ("a read between actions cannot change the later steps"), so the click still has no capture |
| `capture_id` from `cuad shot` in a previous `cuad call` | `capture_not_found` / `capture_generation_mismatch` — each `cuad call` is a new client; captures do not survive it |
| **`click` with `scope:"desktop"` + `delivery_mode:"foreground"`** | **works** — `SendInput` at absolute screen coords |

Consequences:

1. **Bring the window to the front first.** `bring_to_front` then verify `now_fg_hwnd`
   equals `target_hwnd`. A desktop-scope click goes to whatever window is under the
   point; before focusing, clicks landed on an unrelated HWND and MT5 never saw them.
2. Focus **after** every relaunch: `bring_to_front {"pid":…,"window_id":…}` — take the
   `window_id` from a fresh `cuad wins`, it changes on every launch.
3. `alt+F4` to close needs `delivery_mode:"foreground"`:
   `run_steps {"delivery_mode":"foreground","steps":[{"tool":"hotkey","args":{"keys":["alt","f4"],"delivery_mode":"foreground","pid":N}}]}`
   (one action per step; `{"type":"hotkey","keys":…,"delivery_mode":…}` is rejected as
   `invalid_batch: one action per step`).
4. `kill_app` refuses with `foreign_process_termination_denied` unless this runtime
   launched the process. A terminal started by an earlier session cannot be killed;
   close it with alt+F4, or leave it and target its window.

## Chart-object clicks work, but the top-left corner does not

Measured with a probe that creates `OBJ_BITMAP_LABEL` (z 1) + six `OBJ_BUTTON` (z 10):

- A coordinate click on a button delivers `CHARTEVENT_OBJECT_CLICK` with `sparam` =
  the object name. **6/6 tabs**, each with its own index. A canvas under the buttons
  does not swallow them when the buttons carry a higher `OBJPROP_ZORDER`.
- Clicking the already-active tab still fires the event (`changed=0` in the log); the
  program must ignore it — that is a design rule, not a platform one.
- **MT5's own symbol/timeframe label occupies chart-local y 0…~30 and x 0…~250 and
  swallows clicks.** A panel anchored `CORNER_LEFT_UPPER` at y=8 was dead across its
  first tab; the same panel at y=48 received all six. Any clickable chrome must start
  below that label (or use `CORNER_RIGHT_UPPER`).

## Reading results

Prefer app-owned state over the screen:

- `MQL5\Files\PatternCast\…` — the indicator's own CSV/log output (with `FILE_COMMON`
  it lands under the shared `Terminal\Common\Files` instead; the probes here use the
  instance folder).
- `MQL5\Logs\YYYYMMDD.log` — the Experts tab, UTF-8-ish with a two-letter prefix column;
  `grep -a "PC|"` is the reliable filter.
- `MQL5\Tester\…` for strategy-tester runs.

A screenshot is still needed for anything the program cannot report: whether an object
is *drawn* where it claims, whether a panel overlaps something, whether a theme looks
right. `cuad shot --window "<chart title>" -o "D:\abs\path.png"` — the path must be a
Windows absolute path; `/d/...` is written literally and lands in the CWD.

## Compiling without the GUI

```powershell
& 'C:\Program Files\MetaTrader 5\MetaEditor64.exe' /compile:"D:\…\X.mq5" /log:"%TEMP%\X.log"
```

The log is **UTF-16LE**; read it with `-Encoding Unicode`. Parse `Result: N errors, M
warnings` and treat a warning as a failure when the build gate says so. MetaEditor
returns exit code 1 for a failed compile but the log is the authority.

## Keyboard shortcuts (official, metatrader5.com/en/terminal/help/start_advanced/hotkeys)

These are the platform's own hotkeys, read from the vendor documentation. The ones that matter
for driving MT5 from the outside are the **window-independent** block: those fire whatever has
focus, which is exactly the property a driver needs.

### Independent of the active window (the useful set)

| Keys | Action |
| --- | --- |
| `Ctrl+I` | **Indicators List** — the dialog has an `Add` button, so this is the reliable way to attach an indicator without the Navigator |
| `Ctrl+B` | Objects List |
| `Ctrl+W` / `Ctrl+F4` | **Close the current chart window** — a popped-out VPS or extra chart is a chart window, so this closes it |
| `Ctrl+F6` / `Ctrl+Shift+F6` | previous / next chart window |
| `Alt+W` | open chart managing window |
| `F8` | chart setup |
| `F7` | properties of the EA/indicator **attached to** a chart — needs an attachment to already exist |
| `F11` | fullscreen (hides every window except the chart; a re-enter hides manually opened windows again and does not save the change) |
| `Ctrl+N` | open/close Navigator (a toggle: pressing it twice closes it again) |
| `Ctrl+M` / `Ctrl+T` / `Ctrl+R` | Market Watch / Toolbox / Tester, all toggles |
| `Ctrl+O` | Settings |
| `Esc` | close dialog windows |
| `F4` | MetaEditor |

### Navigator window (when IT has focus)

| Keys | Action |
| --- | --- |
| `Enter` | opens the selected expert/indicator/script **in MetaEditor** — it does NOT attach it to a chart |
| `Delete` | delete the selected item |
| `Insert` | new account |
| `G` | show/hide grid in Favorites |

So: **the Navigator cannot attach an indicator by keyboard.** `Enter` edits it. That is why the
attach path is `Ctrl+I` -> `Add`, not the Navigator.

> **Measured correction (2026-11-06):** `Ctrl+I` did **not** open the Indicators List on this
> build, even with `--headed` delivery and the chart window confirmed focused — no window
> appeared within 4 s. `F8` did open `Properties of <symbol>,<tf>` reliably. So treat the table
> above as the vendor's documentation, not as a verified map; verify a hotkey with
> `desktop_wait --window <expected title>` before building a flow on it.

### Chart window (when IT has focus)

Arrows scroll (Up/Down are *fast* scroll), `Page Up/Down` fast scroll, `Home`/`End` jump to the
start/end of history, `+`/`-` zoom, `Delete` deletes selected objects, `Backspace` deletes the
most recent objects, `Enter` opens the fast navigation bar, `NumPad 5` restores the vertical scale.

**`End` jumps the chart to the end of history — and in the Navigator it jumps the tree selection
to the last item**, which is how a Navigator sitting on `Scripts` ends up showing the last script
instead of the indicators. Measured the hard way.

## What works and what does not (measured 2026-10-26, build 5.0.0.6230)

One session's worth of negative results, so the next visit does not repeat them.
**Re-measured 2026-11-06 with agent-desktop: the "no accessibility" rows below are wrong
for this host — see "Accessibility" at the top. They hold for `cua-driver` only.**

| Attempt | Result |
| --- | --- |
| `click` with `x,y` + `scope:"desktop"` + `delivery_mode:"foreground"` on a **toolbar button** | **works** — clicked `M5` and the chart switched timeframe (the toolbar button highlights) |
| the same click **without** `pid` | lands on whatever HWND is under the point: the summary names the HWND it used, and it was an unrelated window (`0x330fee`). Always pass `pid`. |
| `right_click` tool with window-local `x,y` | refused `screenshot_context_missing` / `window_never_read` even after a `get_window_state` step in the same batch, because that read comes back `degraded` and yields no capture |
| `invoke_menu` on `["Charts","Indicators List"]` | refused `menu_path_unavailable: segment 0 was not found` — MT5 exposes **no UIA menus at all**, so the menu bar cannot be driven by name |
| `press_key` F7 / PageDown into the Navigator | no visible effect; the Navigator's tree is not reachable by keys. `type_text` reports success (`SendInput`) but the tree does not filter |
| `stop-Process terminal64` to get a clean state | **do not**. MT5 restores the previous profile, which turns the user's maximised single chart into a tiled workspace, and it destroys whatever the user had focused |

**Left-click reaches MT5; right-click menus open but cannot be captured.** Measured with the
user watching: a desktop-scope right-click on the chart DOES open the context menu, and the menu
closes as soon as foreground moves — so a `cuad shot` issued as a separate call races the user's
own window switch. Treat a menu screenshot as unreliable evidence, and prefer app-owned state.

**The reliable ways to get an indicator onto a chart, in order:**

1. Ask the user to drag it from the Navigator (one gesture, no automation risk).
2. `/config:` with `Indicator=PatternCast\\PatternCast` at launch time — but a launch reuses an
   already running terminal (pitfall 1), so this needs the terminal closed first.
3. `ChartApplyTemplate(0, "PCProbe.tpl")` from a script, with a `.tpl` under
   `MQL5\\Profiles\\Templates\\` that names the indicator. The script still has to be started,
   which is the same problem one level down.

**The drag-then-OK popup itself is automatable (measured 2026-11-06).** What is not
automatable is the *drag*: the destination is the chart canvas, which has no UIA element, and
dragging from a Navigator `treeitem` fails (pitfall 10). But when a drag (or a script launch)
raises the input/properties dialog, it is a normal accessible window and the OK button can be
pressed by name — see "Popups" above. So the split is:

- **user**: one drag from Navigator onto the chart (or one double-click to start a service);
- **agent**: everything the dialog needs afterwards — detect by title, read the tab values,
  press OK (`automation_id 1`) or Cancel (`automation_id 2`).

`ChartIndicatorsTotal(0, 0)` is the app-owned check for "is it attached", and it is worth putting
in any probe: it answers the question without a screenshot.

## Why there is no `recipes/mt5-*.json`

A launch-only flow cannot be expressed in the recipe schema: `cuad run` rejects a recipe
whose `steps` are empty and which includes nothing, and `bring_to_front` accepts only
`pid`/`window_id` (no window-title selector), so it cannot be a step in a batch that has
not yet observed the pid the launch returned. The launch therefore stays a two-call
sequence in the profile:

```bash
PID=$(cuad call launch_app '{"path":"…terminal64.exe","additional_arguments":["/config:…"]}' | jq -r .pid)
sleep 15
cuad wins | grep -i xauusd          # read window_id
cuad call bring_to_front '{"pid":PID,"window_id":WID}'
```

Write a recipe for MT5 only once a flow's every step can name its target without a pid
handoff — for example a batch of desktop-scope clicks at absolute coordinates, templated
through `--var`.

**A dialog flow *is* expressible with agent-desktop** (window titles, not pids), e.g.

```bash
agent-desktop press f8 --window-id w-<chart> --headed
agent-desktop wait   --window "Properties of XAUUSD-VIP,M5"
agent-desktop click  @<snap>:e44        # OK
```

It is not stored as a recipe yet because the chart window id changes on every terminal
start, and the profile's window-id handoff has the same problem the `cuad` launch does.
Record the flow here and fill in the id at call time.

## Pitfalls that cost a round trip

1. A `/config` restart reuses an **already running** terminal instead of starting a
   second one: the second `launch_app` returned the *same* pid and the new ini was
   ignored. Close the terminal first (alt+F4) when the ini must take effect.
2. Two terminals cannot share one data folder — the second launch attaches to the first.
   This also voids any cross-terminal CAS test on a single machine.
3. The window title changes when the chart's symbol or timeframe changes; target by
   `--window "XAUUSD-VIP"` (a substring) or by pid, not by the full title.
4. `SymbolParameters` with an enum value must use the numeric or the exact short name;
   a wrong enum silently keeps the default.
5. After alt+F4 the process lingers a few seconds; `tasklist | grep terminal64` before
   relaunching, and give the new instance ~15 s before looking for its window.
6. **A dialog is a new top-level window with a new id — re-list, do not reuse the chart's.**
   Measured: `Properties of XAUUSD-VIP,M5` = `w-22418158` while the chart was `w-17829668`;
   after Cancel and a second F8 the dialog came back as `w-22876910`. Snapshot the *dialog*
   id, otherwise every ref resolves against the terminal and the buttons are not found.
7. **`desktop_press` (strict headless) does not reach MT5's accelerators.** `ctrl+i` and `f8`
   both returned `delivered_unverified` and opened nothing; the raw
   `press … --window-id … --headed` worked. Send keys headed, after `focus_window`.
8. **A misplaced desktop-scope click can land in a *dialog*.** Aiming at the Navigator tree
   produced an unrelated script dialog window (`QEP_Tests 1.00 (…)`) that then had to be
   dismissed with `press escape --headed`. Prefer named refs; if coordinates are unavoidable,
   list windows afterwards to check nothing unexpected opened.
9. **`desktop_find` on the whole terminal times out**, even with a 20 s budget: ~1 300 nodes
   visited, `TIMEOUT`. Scope it (`root: "@<snap>:eN"`) or use a subtree snapshot.
10. **A `treeitem`'s advertised `Click` is not honoured.** Activating a Navigator leaf returned
    `POLICY_DENIED` (semantic delivery unavailable, physical fallback denied) and, with
    `headed`, `ACTION_FAILED`. Reading the tree works; *starting* a service/script/indicator
    that way does not.
