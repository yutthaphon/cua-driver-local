# FL Studio 2025 (Image-Line) — app profile

**Identity.** `fl64.exe`; the window title is exactly `FL Studio 2025` (it does **not** carry the
project name). `cuad wins --window "FL Studio"` resolves it; `--app FL Studio` does not (the
process is `fl64.exe`). The installer also puts `FL Studio ASIO` in
`C:\Program Files\Image-Line\FL Studio 2025\`; the executable here is `fl64.exe`.

**Launch.** Normally *none* — the user's window already has a project loaded, and
`launch_app` on FL opens a second instance (`launch_if_missing` would then warn about the several
matching windows). Drive the window that is there; if a launch is truly needed, `launch_app` with
`path` = the FL shortcut and target the returned pid.

## The measured shape of the app

| Fact | Value / evidence |
| --- | --- |
| Accessibility tree | **empty**: `cuad ax --window "FL Studio"` → `FL64.exe — 'FL Studio 2025' pid=… elements=0/0 (no accessibility rows — screenshot-only or empty tree)`. FL draws its whole UI itself. |
| Menu bar | **not exposed**: `invoke_menu` with any first segment (`View`/`VIEW`/`File`/`OPTIONS`) → `{"code":"menu_path_unavailable","message":"menu path segment 0 was not found"}`. FL paints its own menu bar; it is not an `HMENU`. |
| Consequence | No `element_token` targets, no `--value` checks, no `text:` checks. **`run_steps` can only drive FL; it cannot prove anything inside it.** The proof is a screenshot (`cuad shot`) analysed outside the batch. |
| Screenshot | works, exact size: `include_accessibility_tree:false, max_image_dimension:0` returns the window at native 2558x1538 px (window bounds 2560x1540, DPI-scaled). The default (scaled) read is 1568x943. |
| Background input | clicks and `press_key` land with `delivery_mode:"background"` for **clicks**, but **keys do not**: `press_key pageup` in the background returns ok and changes nothing (`snap kw0 vs kw1: changed 14 px`). Foreground keys land (`changed 190241 px`). |
| Focus | FL routes keys to the *focused pane*. A click on the pane first (`click` at the ruler) then `press_key`/`hotkey` in the foreground is the working order. |

## Control map (each line was run)

```bash
cuad wins --window "FL Studio"                     # -> pid + window_id
cuad ax  --window "FL Studio"                      # -> elements=0/0 (no tree)
cuad shot --window "FL Studio" -o fl.png           # 1568x943 scaled; pass max_image_dimension:0 for 2558x1538
```

Coordinates below are **native 2558x1538** pixels of the maximised-window layout on this host
(2560x1600 display, 125% scale). They are a screenshot-space map, not an accessibility map — every
one of them is a *click coordinate*, so they must be re-measured if the layout changes.

| What | Where (native px) | How |
| --- | --- | --- |
| Playlist content area | x ≥ **716**; lanes from y≈139 down to y≈1333 | the waveform pixels start at x=716 in every captured view |
| Playlist clip lanes | y 139-157 (Japanese) … y 1270-1333 (Thai) in the full 9-lane view; band height 18-64 px | rows whose waveform pixels span >15-25 % of the content width |
| Track header column | x ≈ 470-716 (track names, colours), x < 470 is the Browser | |
| Ruler (bar numbers) | y ≈ 150-190 | numbers, not ticks; the label **spacing is not constant** in bars (`31, 65, 99, …, 705` increments of 32-36) so the ruler is not a scale source |
| Transport clock (`M:S:CS`) | x ≈ 840-1080, y 0-46 (the left edge moves with the layout; crop 880-1080 works for both layouts seen) | bright green digits on black, boxed; readable in a screenshot, one value per playhead move |
| Main transport / tempo | x ≈ 560-800 (tempo), x ≈ 1250-1900 (position sliders) | |
| Focus the playlist | click anywhere on a clip or the ruler (e.g. 1400,168) | FL's keys go to the focused pane |
| Playlist horizontal zoom | `press_key pageup` / `pagedown` (foreground) | measured: bar/label spacing 48.5 → 57.0 → 66.0 px per PgUp; the *view* also jumped (340230 px changed) |
| Playlist zoom levels | `shift+1`, `shift+2`, `shift+3`, `shift+4` (foreground) | measured spacings 40, 60, 239.5, 36 px (every one of them a *different* complete view; `shift+4` = "show all") |
| Playhead to song start | `press_key home` (foreground) | |
| Centre the view on the playhead | `shift+0` | documented in FL's manual; not separately measured |
| Playlist visible/not + max/min | `press_key f5` toggles the window; `press_key return` toggles max/min | measured: F5 changed 329486 px, a second F5 changed 1490418 px |
| Move the playhead | click the ruler at the target x | the transport clock changes (two clicks gave `0:00:00` and other values) |

## Pitfalls measured on this host

1. **A previous `run_steps` batch can leave FL minimized.** After a `bring_to_front`-free sequence
   the window went to `-32000,-32000` and every `get_window_state` failed with
   `cannot capture minimized window … it has no rendered content`. Fix: `bring_to_front` with the
   same pid/window_id, then read again (`{"landed_on_target": true, "restored": true}`).
2. **Background keys are silently dropped** (see the table). The driver says
   `📨 Sent pageup to pid … via PostMessage (not verified)`. Treat a background key on FL as a
   no-op and go straight to foreground for keys; for clicks background works.
3. **`cuad act`/`shot` need the *session* that owns the capture.** A raw `zoom` call from a
   different session fails with `{"code":"screenshot_context_missing","reason":"other_session"}`;
   keep one `session` label for a run and pass it to every call.
4. **Keys land on the focused pane, and focus is where the last click was.** Without a click the
   document window may be focused and PgUp/PgDn do nothing (`changed 14 px`).
5. **`shift+4`** ("show all") is not "fit to content": after it, the view spans ~1250 px of the
   content area for a 24-minute project, i.e. **~1.2 s/pixel**. Sub-second alignment can therefore
   **not** be checked by eye or by pixels at any of the four zoom levels — 0.5 s is half a pixel.
   Use the audio itself for anything tighter; FL's playlist is the visual reference.
6. **FL's waveform pixels do not encode the audio linearly enough to identify a clip.** Measured
   attempt: fitting each lane's pixel envelope (mean green brightness *and* vertical outline height)
   to each candidate file's RMS/dB envelope gave r ≈ 0.3-0.6 with wrong file assignments for every
   lane. Do not try to read the waveform amplitude; read the **clip geometry** (start/end in
   pixels) and the **transport clock** instead.
7. **The ruler's label spacing is not a fixed bar count**, so `px = k * (bar number)` fits are
   invalid. Calibrate from the transport clock: click two ruler positions, read the clock, and
   solve for (s per px, t0).
8. `run_steps`' step enum is only
   `click, double_click, right_click, set_value, type_text, press_key, hotkey, scroll, drag,
   move_cursor` — no `bring_to_front`, no screenshot step. A recipe cannot take screenshots or
   bring the window up; the caller does that with `cuad call bring_to_front` / `cuad shot`.

## Recipes

| Recipe | What it does | Notes |
| --- | --- | --- |
| `fl-playlist-focus` | click the ruler (gives the playlist the keyboard focus), then `home` | sub-recipe; the click is what makes every later key land |
| `fl-playlist-zoom` | `shift+N` (N = 1..4, `--var zoom=`) then `shift+0` | sub-recipe; measured label spacings 40 / 60 / 239.5 / 36 px |
| `fl-playlist-view` | wrapper: focus then zoom | `verified` 2026-10-15; `--var zoom=4` = whole-episode overview |

Every one of them was run three ways (`--dry-run`, run, re-run) and
`--window NoSuchApp2` fails at step 0 with `no window titled like "NoSuchApp2"` and exit 1.

Analysis helper: `tools/flplaylist.py` (`lanes` / `geometry` / `clock`) — counts the playlist's
clip lanes, reports each lane's start/end/width in pixels, and locates the transport clock. That
is the part a screenshot *can* be trusted for; see pitfall 6 for the part it cannot.

