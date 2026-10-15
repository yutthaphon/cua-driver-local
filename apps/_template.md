# App profiles: the per-application knowledge layer

One file per application, `apps/<app>.md`, written the first time that app is driven.
It is the thing that stops the next session from re-deriving the same selectors.

Profiles are **not** skills: they live inside `cua-driver-local` because omp discovers
skills exactly one level under `~/.agents/skills/` (`<root>/<name>/SKILL.md`) — a nested
`cua-driver-local/<app>/SKILL.md` is never discovered, and a top-level skill per app would
advertise a dozen descriptions that all say "drive a Windows app". Progressive disclosure
instead: `SKILL.md` → `apps/<app>.md` (read on demand) → `recipes/<app>-*.json` (runnable).

## What a profile must carry

1. **Identity** — how the app resolves to a window: title substring, process name, AUMID,
   `exe` path. Say which selector actually works; that is the part that costs a round trip.
2. **Launch line** — the exact `launch_app` arguments (and whether a launch is even needed).
3. **Control map** — the steps that reach each thing the task needs, in `cuad act` syntax.
   Confirm every entry by running it; mark anything unprobed `[INFERENCE]`.
4. **Proof source** — the app-owned state that proves an action landed (a state file, a
   document, a field value). "The step returned ok" is not proof (SKILL.md pitfall 10).
5. **Pitfalls measured on this host** — with the observed error code or refusal text.
6. **Recipe** — the name of the `recipes/*.json` written from the profile, and its date.

## Adding an app (the loop that produced the existing profiles)

```bash
cuad wins --window "<Title>"          # does it resolve by title? by app?           (1)
cuad call launch_app '{...}'          # background launch; read the windows array   (2)
cuad ax --window "<Title>"            # control map: role, label, value, actions   (3)
cuad act --window "<Title>" ...       # one batch; fix the failing step, re-run     (4)
cuad ax --window "<Title>" --query X  # confirm app-owned state, not just ok=true  (5)
# then: write the profile, and `cuad run <name>` a recipe distilled from step 4
```

Extend the profile in place. Never fork a second profile for the same app: one file per
app, updated, is the whole point.
