# Character Map (classic Win32 dialog)

| | |
| --- | --- |
| Window title | `Character Map` |
| Process | `charmap.exe` — both `--window "Character Map"` and `--app charmap` resolve |
| Path | `C:\Windows\System32\charmap.exe` |
| Launch | `{"path":"C:/Windows/System32/charmap.exe"}` |
| Recipe | `charmap-copy-first` — 2 steps, verified 2026-10-15 |

## Control map (measured — the tree is 15 elements)

| Role | Label | Value | Actions |
| --- | --- | --- | --- |
| Edit | `Characters to copy :` | the copied text | `set_value`, `text` |
| Button | `Select` | | `invoke` |
| CheckBox | `Advanced view` | | `invoke`, `toggle` |
| ComboBox | `Font :` | `"Arial"` | `expand`, `set_value` |
| Button | `Open` | | `invoke` |
| Hyperlink | `Help` | | `invoke` |
| `Line up` / `Page down` / `Line down` + ScrollBar | glyph-grid scroll | | `invoke` / `set_value` |
| TitleBar `Character Map`, MenuItem `System` | | `"Character Map"` | `set_value` / `expand` |

Verified one-shot (exit 0):

```bash
cuad act --window "Character Map" --click "Button:Select" \
    --value "Edit:Characters to copy :=!"
```

Element rows in `--json` carry the label as `label` (`"Characters to copy :"`); `cuad` step
targets spell it `[role:]name`, one and the same string.

The **glyph grid is custom-drawn** — no per-glyph UIA elements — and `Select` takes whatever
cell is highlighted. The default cell is `U+0021` (`!`), which is what the recipe relies on;
choosing another glyph is a keys/coordinates problem, not a name-target problem.

## Pitfalls measured on this host

1. **Target the label, never the role.** `--value "Edit=!"` fails with
   `element "Edit" is shown, value contains "!" expected … found no addressable match` —
   `Edit` is the role, and the label is `Characters to copy :`. `--value "Characters to copy :=!"`
   works label-only, `--value "Edit:Characters to copy :=!"` works role+label.
2. **`--value`/`--value-is` need the `=` separator after the target** — even when the label
   ends in `:`. Omitting it (`--value "Edit:Characters to copy :!"`) is not a failed check but
   a rejected batch: `invalid_batch: expect 1: `value_contains` must be a non-empty string`.
3. **Exact matching is fine here**: `--value-is "Edit:Characters to copy :=!"` passes although
   the row reads `value="!\r"` (the comparison ignores the trailing carriage return), and
   `…=xyz` fails with the row quoted. No need to fall back to `contains`.
4. **Replay is idempotent**: every `Select` appends the same characteragain
   (`!\r` → `!!\r`), so a `contains !` check keeps holding. This makes the app the cheap
   background-click smoke test; it also works while minimized (the patch contract).
5. **Launching while one is up leaves a second identical dialog** on the same coordinates
   (measured: two windows at `@26,80`, distinguishable only by id) — hence
   `launch_if_missing` in the recipe.
6. The dialog is a plain Win32 window with a real tree: `bring_to_front`, screenshots and
   foreground delivery are all available if a step is ever refused.
