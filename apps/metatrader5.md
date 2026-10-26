# MetaTrader 5 (terminal64.exe)

Source-built driver knowledge for driving MT5 on this host. Measured 2026-10-26 on
build 5.0.0.6230, window `1090143 - VTMarkets-Demo … [XAUUSD-VIP,M15]`.

## Identity

| | |
| --- | --- |
| Process | `terminal64.exe` (NOT `terminal.exe`; both can exist) |
| Window | one per chart, title `<account> - <broker> - [SYMBOL,TF]` |
| Class | `MetaQuotes::MetaTrader::5.00` |
| Accessibility | **none** — `get_window_state` returns `elements=0/0`, `degraded:true` |
| Data folder | `%APPDATA%\MetaQuotes\Terminal\<instance-id>\` |
| MetaEditor | `C:\Program Files\MetaTrader 5\MetaEditor64.exe` |

Because there is no UIA tree, **every interaction is a coordinate click**. `element_token`,
`--click <name>`, `text:` checks and `cuad ax` all return nothing useful for a chart.

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
- `Script=` is relative to `MQL5\Scripts`, `Indicator=` to `MQL5\Indicators`. A script
  compiled under `MQL5\Scripts\PatternCast\Tests\X.ex5` is `PatternCast\Tests\X`.
- `iCustom()` inside a script takes a path relative to `MQL5\Indicators`, with
  **backslashes**, and it must include the `Tests` subfolder if that is where it lives:
  `iCustom(_Symbol, PERIOD_CURRENT, "PatternCast\\Tests\\PanelProbe")`.

`launch_app` returns the pid immediately and `windows` empty for the first few seconds;
the chart window appears ~8–15 s later. Poll `cuad wins` once, then work.

## Coordinate model (the part that costs calls)

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
