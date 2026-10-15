# Calculator (Windows 11 packaged app)

| | |
| --- | --- |
| Window title | `Calculator` — the only selector that works |
| AUMID | `Microsoft.WindowsCalculator_8wekyb3d8bbwe!App` (returned by `launch_app`) |
| Processes | `ApplicationFrameHost.exe` (hosts the window, `app_name` on its rows) and `CalculatorApp.exe` (content) |
| Launch | `{"name":"Calculator"}` → `active:false`, window arrives in the same response |
| Recipe | `calc-42` — 6 steps, verified 2026-10-15 |

## Control map (measured)

Buttons are named for their function; the display is a `Text` row.

```bash
cuad act --window Calculator --click Clear --click Six --click "Multiply by" \
    --click Seven --click Equals --expect "text:Display is 42"
```

| Need | Step |
| --- | --- |
| digits | `--click Six`, `--click Seven`, … (`Zero`…`Nine`) |
| operators | `--click "Multiply by"`, `--click "Divide by"`, `--click "Minus"`, `--click "Plus"`, `--click Equals` |
| reset | `--click Clear` (also `Clear entry`, `Backspace`) |
| read the display | `--expect "text:Display is 42"` (`Text "Display is <n>"`, actions `[invoke]`) |
| close | `--click "Close Calculator"` on the window's own frame |

Do not hardcode the `[n]` indices from an `ax` dump: they are per-snapshot. Roles+labels
resolve inside the batch.

## Pitfalls measured on this host

1. **`--app` cannot resolve it.** The AUMID is not a process name — the driver answers
   `no window of app "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App" (apps with windows:
   ApplicationFrameHost.exe)`. Target by `--window Calculator`.
2. **Several live windows can carry the title `Calculator`**, and a *sick* one answers
   every read with `degraded:true / ax_tree_empty` (measured: `CalculatorApp.exe` pid 23336,
   window 4066302, `nodes_visited=1`, `walk_elapsed_ms=315`, while the `ApplicationFrameHost`
   window for the same app returned 39 elements). A bare `--window Calculator` takes the
   frontmost match and can land on the dead one; that is why the recipe **launches and pins**
   (`launch` without `launch_if_missing`, then the steps carry the returned pid/window_id).
3. **`kill_app` is refused for a window this runtime did not launch**
   (`foreign_process_termination_denied`, standard mode). Close through the UI instead:
   `--click "Close Calculator"` on the frame window. Measured: closing the frame windows
   also ends the `CalculatorApp.exe` content process.
4. **Background delivery works and the app is never activated** (`active:false` on launch,
   UIA `Invoke` on the buttons). No foreground escalation is needed for the 6×7 flow.

## Notes

- `Display is <n>` is numeric and short: prefer `--value-is` on that row when the check must
  not accept a longer string, since `text:` is a substring match.
- Closing the Calculator frame windows ends the `CalculatorApp.exe` content process (measured:
  both instances gone after three `Close Calculator` clicks) but not the shared frame host:
  `ApplicationFrameHost.exe` pid 10280 kept serving its `Settings` window (id 1510228)
  afterwards. Still check `cuad wins --pid <pid>` before a close when other windows share the
  host, since the frame host is a per-app (not per-session) process.
