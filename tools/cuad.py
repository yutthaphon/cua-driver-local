#!/usr/bin/env python3
"""cuad - fast, opinionated shell client for the local cua-driver product.

Why this exists next to `cua-driver-local` itself:

  * One-shot targeting. The driver's invariant is "read a window, then act on a
    snapshot-bound element token, and re-read next turn". Doing that by hand is
    three round trips and two id fields. `cuad act` sends a `run_steps` batch
    where the driver resolves `--app` / `--window` / role+name itself, so a
    whole small flow is one call and no token bookkeeping.
  * Window resolution that matches how people name apps. `--window Calculator`
    matches the window title, which is the only reliable knob for packaged
    (UWP) apps: their process is ApplicationFrameHost.exe, so `--app Calculator`
    cannot resolve.
  * Compact reads. `cuad ax` prints the accessibility tree as one line per
    element (index, role, label, value, actions, token) instead of a JSON blob,
    and can write the screenshot straight to a file.
  * Daemon lifecycle. `cuad up` starts the local daemon when it is not running,
    so no call ever fails with "daemon is not running".

Everything is stdlib-only and speaks the driver's own JSON contract; `--json`
on any command prints the raw response. See LOCAL-PATCHES.md for the install
layout, and `cuad --help` for the command list.

Usage examples:
  cuad up
  cuad wins --window Calculator
  cuad ax --window Calculator
  cuad act --window Calculator --click Clear --click Six --click "Multiply by" --click Seven --click Equals --expect "text:Display is 42"
  cuad shot --window Calculator -o calc.png
  cuad recipes                       # saved run_steps batches in ../recipes/
  cuad run wpf-minimized-increment   # replay one; launches if the recipe says so
  cuad run calc-42 --var product=42  # fill the recipe's {{product}} placeholder
  cuad run calc-42 --dry-run         # print the payload instead of driving
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time

DEFAULT_BIN = os.path.join(
    os.environ.get("LOCALAPPDATA", ""),
    "Programs", "Cua", "cua-driver-local", "bin", "cua-driver-local.exe",
)
EXE_SUFFIX = ".exe" if os.name == "nt" else ""


def driver_binary() -> str:
    """The local product first, then anything named cua-driver-local on PATH."""
    env = os.environ.get("CUAD_BIN")
    if env:
        return env
    if os.path.exists(DEFAULT_BIN):
        return DEFAULT_BIN
    from shutil import which

    found = which("cua-driver-local")
    if found:
        return found
    sys.exit(
        f"cuad: no cua-driver-local binary found.\n"
        f"  looked for {DEFAULT_BIN}\n"
        f"  install it with libs/cua-driver/scripts/install-local.ps1 (see LOCAL-PATCHES.md),\n"
        f"  or point CUAD_BIN at a build."
    )


BIN = driver_binary()


def read_stdin_json(text: str) -> str:
    if text == "-":
        return sys.stdin.read()
    if text.startswith("@"):
        with open(text[1:], encoding="utf-8") as handle:
            return handle.read()
    return text


def run_driver(argv: list[str], stdin_text: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [BIN, *argv],
        input=stdin_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


NO_SESSION = {"start_session", "end_session"}

def revive_session(session: str | None) -> bool:
    """Start an ended session label again. `start_session` is idempotent
    (it reports `revived:true` for a label that had ended)."""
    if not session:
        return False
    proc = run_driver(["call", "start_session"], json.dumps({"session": session}))
    return proc.returncode == 0

def call_tool(tool: str, args: dict, screenshot_out: str | None = None) -> dict:
    """One tool call against the daemon.

    Most tools answer with a JSON envelope; a few (kill_app, end_session) print a
    one-line confirmation instead, which is success, not a parse failure.

    A label that has ended rejects every call with `session has ended` until it
    is started again, and nothing in the daemon starts it. Revive it and retry
    once, so a label someone ended earlier (or a fresh shell reusing "omp") does
    not turn into a dead client.
    """
    argv = ["call", tool]
    if screenshot_out:
        argv += ["--screenshot-out-file", screenshot_out]
    payload = json.dumps(args)
    proc = run_driver(argv, payload)
    if (tool not in NO_SESSION
            and "session has ended" in (proc.stderr or "")
            and revive_session(args.get("session"))):
        proc = run_driver(argv, payload)
    out = (proc.stdout or "").strip()
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        if proc.returncode == 0 and out:
            return {"status": "ok", "text": out}
        return {
            "status": "failed",
            "_raw": out[:2000],
            "_stderr": (proc.stderr or "").strip()[:2000],
            "_exit": proc.returncode,
        }


def emit(payload, as_json: bool, render) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        render(payload)


# ── daemon lifecycle ─────────────────────────────────────────────────────────

def daemon_running() -> bool:
    proc = run_driver(["status"])
    text = f"{proc.stdout}\n{proc.stderr}"
    if "daemon is not running" in text.lower() or "not running" in text.lower():
        return False
    return proc.returncode == 0 and "is running" in text.lower()


def daemon_status_text() -> str:
    proc = run_driver(["status"])
    return (proc.stdout or proc.stderr or "").strip()


def ensure_daemon(wait_s: float = 20.0) -> bool:
    if daemon_running():
        return True
    log = os.path.join(os.environ.get("TEMP", "."), "cuad-daemon.log")
    with open(log, "ab") as handle:
        subprocess.Popen(
            [BIN, "serve"],
            stdout=handle,
            stderr=handle,
            stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0),
            close_fds=True,
        )
    deadline = time.time() + wait_s
    while time.time() < deadline:
        if daemon_running():
            return True
        time.sleep(0.25)
    print(f"cuad: daemon did not come up within {wait_s:.0f}s (log: {log})", file=sys.stderr)
    return False


# ── window resolution ────────────────────────────────────────────────────────

def fetch_windows() -> list[dict]:
    result = call_tool("list_windows", {})
    rows = result.get("windows") or result.get("_legacy_windows") or []
    return [row for row in rows if isinstance(row, dict)]


def app_name_of(row: dict) -> str:
    """Window rows name the process as `app_name`; older shapes used `app`."""
    return (row.get("app_name") or row.get("app") or "").lower()


def match_windows(rows: list[dict], *, app: str | None, window: str | None,
                  pid: int | None) -> list[dict]:
    out = rows
    if pid is not None:
        out = [row for row in out if row.get("pid") == pid]
    if window:
        needle = window.lower()
        out = [row for row in out if needle in (row.get("title") or "").lower()]
    if app:
        needle = app.lower()
        # Accept the bare stem too, so `--app charmap` matches charmap.exe.
        out = [
            row for row in out
            if needle in app_name_of(row)
            or app_name_of(row).removesuffix(EXE_SUFFIX) == needle
        ]
    return out


def resolve_window(args) -> dict:
    """Pick the single window a read/screenshot should use.

    A title can match several entries: the driver keeps stale ids for windows it
    has seen, and repeated launches of one app produce several live hosts. The
    rule is the same one the driver applies when a step names a window by title —
    take the frontmost on-screen window that is not minimized — and say so on
    stderr, with the alternatives, so the caller can pin `--pid/--window-id`
    when it matters.
    """
    pid = getattr(args, "pid", None)
    window_id = getattr(args, "window_id", None)
    if pid and window_id:
        return {"pid": pid, "window_id": window_id}
    rows = fetch_windows()
    if window_id:
        for row in rows:
            if row.get("window_id") == window_id:
                return {"pid": row["pid"], "window_id": window_id}
        sys.exit(f"cuad: no window with window_id={window_id}")
    matches = match_windows(rows, app=getattr(args, "app", None),
                            window=getattr(args, "window", None), pid=pid)
    if not matches:
        selector = getattr(args, "window", None) or getattr(args, "app", None) or f"pid={pid}"
        sys.exit(f"cuad: no window matched {selector!r} — try `cuad wins`")
    on_screen = [row for row in matches
                 if row.get("is_on_screen", True) and not row.get("minimized")]
    candidates = on_screen or matches
    candidates.sort(key=lambda row: row.get("z_index") or 0, reverse=True)
    chosen = candidates[0]
    if len(matches) > 1:
        others = ", ".join(f"{row['pid']}:{row['window_id']}" for row in candidates[1:4])
        print(
            f"cuad: {len(matches)} windows matched; using the frontmost "
            f"pid={chosen['pid']} window_id={chosen['window_id']} "
            f"({chosen.get('title')!r})" + (f"; others: {others}" if others else ""),
            file=sys.stderr,
        )
    return {"pid": chosen["pid"], "window_id": chosen["window_id"]}


# ── renderers ────────────────────────────────────────────────────────────────

def render_windows(rows: list[dict]) -> None:
    if not rows:
        print("(no windows)")
        return
    width = max(len(row.get("title") or "") for row in rows)
    for row in sorted(rows, key=lambda r: (r.get("pid") or 0, r.get("z_index") or 0)):
        flags = "min" if row.get("minimized") else "   "
        # Newer responses nest `bounds`; the legacy shape is flat.
        bounds = row.get("bounds") or row
        geometry = ""
        if bounds.get("width"):
            geometry = (
                f"{bounds.get('width')}x{bounds.get('height')}"
                f" @{bounds.get('x')},{bounds.get('y')}"
            )
        app = app_name_of(row).removesuffix(EXE_SUFFIX)
        print(
            f"{row.get('pid'):>7}  {row.get('window_id'):>9}  {flags}  "
            f"{(row.get('title') or '')[:width]:<{width}}  {app:<22}  {geometry}"
        )


def render_ax(payload: dict, elements: list[dict], *, shot: str | None,
              header: dict) -> None:
    if payload.get("status") == "refused":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    app = header.get("app_name") or "?"
    title = header.get("window_title") or ""
    counts = ""
    if "element_count" in header:
        counts = (
            f"  elements={header.get('returned_element_count')}/{header.get('element_count')}"
            f"{' (truncated)' if header.get('truncated') else ''}"
        )
    print(f"# {app} — {title!r}  pid={header.get('pid')} window_id={header.get('window_id')}{counts}")
    print(f"# snapshot={header.get('snapshot_id')} token=<snapshot>[:N]")
    if header.get("tree_diff"):
        print(header["tree_diff"])
    if shot:
        print(f"# screenshot -> {shot}")
    if not elements:
        print("(no accessibility rows — screenshot-only or empty tree)")
        return
    for row in elements:
        value = row.get("value")
        shown = "" if value in (None, "") else f" ={json.dumps(value, ensure_ascii=False)}"
        actions = row.get("actions") or []
        acts = f" [{'|'.join(actions)}]" if actions else ""
        enabled = "" if row.get("enabled", True) else " (disabled)"
        label = row.get("label") or row.get("name") or ""
        print(
            f"[{row.get('element_index'):>3}] {row.get('role'):<14} "
            f"{json.dumps(label, ensure_ascii=False):<40}{shown}{acts}{enabled}"
        )


def render_steps(payload: dict) -> None:
    if payload.get("status") == "refused":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if payload.get("steps") is None and payload.get("total") is None:
        reason = (payload.get("_stderr") or payload.get("message")
                  or payload.get("_raw") or "").strip().splitlines()
        print(f"FAIL: {reason[0] if reason else 'the driver returned no step report'}")
        return
    ok = payload.get("ok")
    executed = payload.get("executed")
    total = payload.get("total")
    for step in payload.get("steps") or []:
        mark = "ok  " if step.get("ok") else "FAIL"
        detail = step.get("message") or ""
        target = ((step.get("target") or {}).get("element") or "")
        print(f"{mark} {step.get('index')} {step.get('tool'):<12} {target}  {detail}")
    print(f"{'PASS' if ok else 'FAIL'}: {executed}/{total} steps")
    observation = payload.get("observation")
    if observation:
        state = observation.get("state") or {}
        print(f"observe: ok={observation.get('ok')} {observation.get('message') or ''}".rstrip())
        if state.get("tree_diff"):
            print(state["tree_diff"])
        elif state.get("tree_markdown"):
            print(state["tree_markdown"])


# ── act DSL ──────────────────────────────────────────────────────────────────
#
# Each CLI flag appends one ordered step, so the command line reads in the same
# order the driver will run it. Target syntax: `[role:]label[#nth]`, and for
# --set the first `=` splits the target from the value.

class StepCollector(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        steps = getattr(namespace, "steps", None)
        if steps is None:
            steps = []
            setattr(namespace, "steps", steps)
        kind = option_string.lstrip("-")
        if kind == "type":
            # `--into` may be written after `--type`, so the target is resolved
            # when the batch is assembled, not here.
            steps.append({"__into__": values})
        elif kind == "click":
            steps.append({"click": target_spec(values)})
        elif kind == "rightclick":
            steps.append({"right_click": target_spec(values)})
        elif kind == "doubleclick":
            steps.append({"double_click": target_spec(values)})
        elif kind == "key":
            if "+" in values:
                steps.append({"hotkey": {"keys": [part.strip() for part in values.split("+")]}})
            else:
                steps.append({"press_key": {"key": values}})
        elif kind == "set":
            spec, _, value = values.partition("=")
            steps.append({"set_value": {**target_spec(spec), "value": value}})
        elif kind == "scroll":
            steps.append({"scroll": {**target_spec(values), "direction": "down"}})
        elif kind in ("expect", "wait", "gone"):
            check = check_spec(values)
            if kind == "gone":
                check["gone"] = True
            step = {}
            if kind == "wait":
                step["wait_for"] = check
            else:
                step["expect"] = [check]
            steps.append(step)
        elif kind in ("value", "value-is"):
            spec, _, wanted = values.partition("=")
            key = "value" if kind == "value-is" else "value_contains"
            steps.append({"expect": [{**target_spec(spec), key: wanted}]})
        elif kind == "shot":
            steps.append({"__shot__": {"path": values}})
        else:  # pragma: no cover - argparse owns the flag set
            raise SystemExit(f"cuad: unsupported step flag {option_string}")
        setattr(namespace, "steps", steps)


def target_spec(spec: str) -> dict:
    role = None
    nth = None
    if "#" in spec:
        spec, _, tail = spec.rpartition("#")
        if tail.isdigit():
            nth = int(tail)
    if ":" in spec:
        head, _, tail = spec.partition(":")
        if head and tail:
            role, spec = head.strip(), tail.strip()
    out: dict = {"name": spec.strip()}
    if role:
        out["role"] = role
    if nth is not None:
        out["nth"] = nth
    return out


def check_spec(spec: str) -> dict:
    if ":" in spec:
        head, _, tail = spec.partition(":")
        if head.lower() == "text":
            return {"text": tail.strip()}
    return target_spec(spec)


def normalize_checks(step: dict) -> dict:
    for key in ("expect", "wait_for"):
        value = step.get(key)
        if value is None:
            continue
        checks = value if isinstance(value, list) else [value]
        cleaned = []
        for check in checks:
            cleaned.append({k: v for k, v in check.items() if v is not None})
        step[key] = cleaned if key == "expect" else cleaned[0]
    return step


def run_act(args) -> int:
    steps = list(getattr(args, "steps", None) or [])
    shots = [step["__shot__"]["path"] for step in steps if "__shot__" in step]
    resolved = []
    for step in steps:
        if "__into__" in step:
            # `--into` is a modifying flag on --type, not its own step.
            text = step["__into__"]
            resolved.append({"type_text": {**target_spec(args.into), "text": text}}
                            if args.into else {"type_text": {"text": text}})
        elif "__shot__" not in step:
            resolved.append(step)
    steps = resolved
    target = {}
    for key in ("pid", "window_id", "app", "window"):
        value = getattr(args, key, None)
        if value:
            target[key] = value
    if not target:
        sys.exit("cuad act: name the target with --window/--app/--pid/--window-id")

    exit_code = 0
    if steps:
        payload = {
            **target,
            "session": args.session,
            "steps": [normalize_checks(step) for step in steps],
        }
        if args.observe:
            payload["observe"] = {}
        result = call_tool("run_steps", payload)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            render_steps(result)
        exit_code = 0 if result.get("ok") else 1

    for path in shots:
        window = resolve_window(args)
        shot = call_tool(
            "get_window_state",
            {**window, "include_accessibility_tree": False, "session": args.session},
            screenshot_out=path,
        )
        if not args.json:
            print(f"screenshot -> {path}  (capture={shot.get('capture_id', 'n/a')})")
        if shot.get("status") == "failed":
            exit_code = 1
    return exit_code


# ── recipes ──────────────────────────────────────────────────────────────────
#
# A recipe is a saved, verified `run_steps` batch: `<skill>/recipes/<name>.json`
# holding {name, description, window|pid|window_id|app, vars?, observe?, steps}.
# It exists so an app flow studied once is replayed, not re-derived. Selectors
# on the command line beat the recipe's, `--var key=value` fills `{{key}}`.
#
# Recipes compose: an `include` list splices other recipes' steps in first, so a
# large flow is built from the small per-app recipes (see recipes/README.md).
# Paths in a recipe may use `%VAR%`, `$VAR` and `~`, resolved before dispatch,
# so a shared recipe never hardcodes one machine's user directory.

RECIPES_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "recipes")
)
PLACEHOLDER = re.compile(r"\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}")
MAX_INCLUDE_DEPTH = 8

def recipe_names() -> list[str]:
    if not os.path.isdir(RECIPES_DIR):
        return []
    return sorted(
        entry[:-5] for entry in os.listdir(RECIPES_DIR) if entry.endswith(".json")
    )

def load_recipe(name: str) -> dict:
    if not name or "/" in name or "\\" in name or name.startswith("."):
        sys.exit(f"cuad: {name!r} is not a recipe name")
    path = os.path.join(RECIPES_DIR, f"{name}.json")
    try:
        with open(path, encoding="utf-8") as handle:
            recipe = json.load(handle)
    except FileNotFoundError:
        sys.exit(f"cuad: no recipe {name!r} in {RECIPES_DIR} (`cuad recipes` lists them)")
    except (OSError, json.JSONDecodeError) as exc:
        sys.exit(f"cuad: recipe {name} is unreadable: {exc}")
    if not isinstance(recipe.get("steps"), list):
        sys.exit(f"cuad: recipe {name} has no `steps` list ({path})")
    if not recipe["steps"] and not recipe.get("include"):
        sys.exit(f"cuad: recipe {name} has no steps and includes nothing ({path})")
    return recipe

def parse_vars(pairs: list[str] | None) -> dict:
    values: dict = {}
    for pair in pairs or []:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            sys.exit(f"cuad: --var wants key=value, got {pair!r}")
        values[key] = value
    return values

def resolve_includes(recipe: dict, name: str, depth: int = 0) -> dict:
    """Splice every `include`d recipe's steps and vars in, ahead of this one's.

    Included vars are defaults (this recipe and the command line still win), and
    the included steps run first, in the order the names are listed.
    """
    names = recipe.get("include") or []
    if not isinstance(names, list) or not all(isinstance(item, str) for item in names):
        sys.exit(f"cuad run {name}: `include` must be a list of recipe names")
    if not names:
        return recipe
    if depth >= MAX_INCLUDE_DEPTH:
        sys.exit(f"cuad run {name}: `include` nested more than {MAX_INCLUDE_DEPTH} deep")
    steps: list = []
    defaults: dict = {}
    for child_name in names:
        child = resolve_includes(load_recipe(child_name), child_name, depth + 1)
        defaults.update(child.get("vars") or {})
        steps.extend(child["steps"])
    defaults.update(recipe.get("vars") or {})
    return {**recipe, "vars": defaults, "steps": [*steps, *recipe["steps"]]}

def expand(value, values: dict, missing: set):
    """Fill `{{name}}` inside string leaves, then resolve `%VAR%`/`$VAR`/`~` paths."""
    if isinstance(value, dict):
        return {key: expand(item, values, missing) for key, item in value.items()}
    if isinstance(value, list):
        return [expand(item, values, missing) for item in value]
    if isinstance(value, str):
        def fill(match):
            key = match.group(1)
            if key in values:
                return values[key]
            missing.add(key)
            return match.group(0)
        filled = PLACEHOLDER.sub(fill, value)
        if "%" in filled or "$" in filled:
            filled = os.path.expandvars(filled)
        if filled.startswith("~"):
            filled = os.path.expanduser(filled)
        return filled
    return value

def render_recipes(rows: list[dict]) -> None:
    if not rows:
        print(f"(no recipes in {RECIPES_DIR})")
        return
    width = max(len(row["name"]) for row in rows)
    for row in rows:
        if row.get("error"):
            print(f"{row['name']:<{width}}  unreadable  {row['error']}")
            continue
        print(
            f"{row['name']:<{width}}  {row['steps']} step(s)  "
            f"verified={row['verified']:<11} {row['target']}"
            f"{'  [launches]' if row.get('launch') else ''}"
            f"{'  [+' + ', '.join(row['includes']) + ']' if row.get('includes') else ''}"
            f"  {row['description']}"
        )

def cmd_recipes(args) -> int:
    rows = []
    for name in recipe_names():
        try:
            recipe = resolve_includes(load_recipe(name), name)
        except SystemExit as exc:  # unreadable file: list it, do not fail the listing
            rows.append({"name": name, "error": str(exc)})
            continue
        rows.append({
            "name": name,
            "steps": len(recipe["steps"]),
            "verified": recipe.get("verified") or "unverified",
            "target": recipe.get("window") or recipe.get("app") or str(recipe.get("pid") or ""),
            "description": recipe.get("description", ""),
            "vars": recipe.get("vars") or {},
            "launch": isinstance(recipe.get("launch"), dict),
            "includes": recipe.get("include") or [],
        })
    emit(rows, args.json, render_recipes)
    return 0

def launch_target(launch: dict, session: str, name: str) -> dict:
    """Run a recipe's (already resolved) `launch` block; return its pid/window_id."""
    request = {**launch, "session": session}
    result = call_tool("launch_app", request)
    if result.get("status") in ("refused", "failed"):
        refusal = result.get("refusal") or {}
        sys.exit(
            f"cuad run {name}: launch_app {result.get('status')}: "
            f"{refusal.get('message') or result.get('_raw') or result}"
        )
    windows = [row for row in (result.get("windows") or []) if isinstance(row, dict)]
    pid = result.get("pid")
    if not windows and pid:
        # The activation settles before the window materializes; poll briefly.
        deadline = time.monotonic() + 10.0
        while not windows and time.monotonic() < deadline:
            time.sleep(0.4)
            windows = [row for row in fetch_windows() if row.get("pid") == pid]
    if not windows:
        sys.exit(f"cuad run {name}: launch_app reported pid {pid} but no window appeared")
    window = windows[0]
    # `launch_app`'s rows carry no pid (list_windows shape minus pid); the
    # process id is the call's own `pid` field.
    pid = window.get("pid") or pid
    if pid is None:
        sys.exit(f"cuad run {name}: launch_app returned no pid for {window.get('title')!r}")
    print(
        f"launched pid={pid} window_id={window.get('window_id')} "
        f"{window.get('title')!r} (session {session})",
        file=sys.stderr,
    )
    return {"pid": pid, "window_id": window["window_id"]}

def cmd_run(args) -> int:
    recipe = resolve_includes(load_recipe(args.name), args.name)
    values = {key: str(value) for key, value in (recipe.get("vars") or {}).items()}
    values.update(parse_vars(args.var))
    missing: set = set()
    steps = expand(recipe["steps"], values, missing)
    launch = (
        expand(recipe["launch"], values, missing)
        if isinstance(recipe.get("launch"), dict)
        else None
    )
    if missing:
        names = ", ".join(sorted(missing))
        sys.exit(f"cuad run {args.name}: no value for {names} (pass --var {sorted(missing)[0]}=...)")
    target = {}
    for key in ("pid", "window_id", "window", "app"):
        value = getattr(args, key) if getattr(args, key, None) is not None else recipe.get(key)
        if value:
            target[key] = value
    launched = None
    skip_launch = False
    if launch is not None and not args.no_launch:
        if recipe.get("launch_if_missing"):
            present = match_windows(
                fetch_windows(),
                app=recipe.get("app"),
                window=recipe.get("window"),
                pid=recipe.get("pid"),
            )
            if len(present) == 1:
                skip_launch = True
                if not args.dry_run:
                    row = present[0]
                    print(
                        f"recipe {args.name}: already up "
                        f"(pid={row.get('pid')} window_id={row.get('window_id')}); not launching",
                        file=sys.stderr,
                    )
                target = {**target, "pid": present[0]["pid"],
                          "window_id": present[0]["window_id"]}
            elif present:
                skip_launch = True
                ids = ", ".join(str(row.get("window_id")) for row in present)
                print(
                    f"recipe {args.name}: {len(present)} instances already match "
                    f"{recipe.get('app') or recipe.get('window')} (window_ids {ids}); not "
                    "launching, and the steps resolve the frontmost by title — close the "
                    "extras to make this deterministic",
                    file=sys.stderr,
                )
        if not skip_launch and not args.dry_run:
            launched = launch_target(launch, args.session, args.name)
            # A launch makes the window this run just created the target, whatever
            # the recipe's title says: a second instance of the same app shares the
            # title, and the driver would otherwise pick the frontmost match (often
            # an older window) inside the batch. `launch_if_missing` deliberately
            # leaves `launched` empty so an existing window keeps being driven.
            target = {**launched, "app": recipe["app"]} if recipe.get("app") else launched
    if not target and not launched:
        sys.exit(
            f"cuad run {args.name}: recipe names no target; pass "
            "--window/--app/--pid/--window-id"
        )
    payload = {**target, "session": args.session, "steps": steps}
    if recipe.get("observe", True) and not args.no_observe:
        payload["observe"] = {}
    if args.dry_run:
        if launch is not None and not args.no_launch and not skip_launch:
            payload["launch"] = launch
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print(f"recipe {args.name}: {recipe.get('description', '')}".rstrip(), file=sys.stderr)
    result = call_tool("run_steps", payload)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        render_steps(result)
    return 0 if result.get("ok") else 1

# ── command handlers ─────────────────────────────────────────────────────────

def cmd_up(args) -> int:
    if ensure_daemon():
        print(daemon_status_text())
        return 0
    return 1


def cmd_down(args) -> int:
    proc = run_driver(["stop"])
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    return proc.returncode


def cmd_status(args) -> int:
    if args.json:
        proc = run_driver(["status", "--json"])
        if proc.returncode == 0 and proc.stdout.strip().startswith("{"):
            print(proc.stdout.strip())
            return 0
        print(json.dumps({"raw": daemon_status_text()}, ensure_ascii=False, indent=2))
        return 0
    print(daemon_status_text())
    return 0


def cmd_version(args) -> int:
    proc = run_driver(["--version"])
    sys.stdout.write(proc.stdout or proc.stderr)
    return proc.returncode


def cmd_doctor(args) -> int:
    proc = run_driver(["doctor"] + (["--json"] if args.json else []))
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    return proc.returncode


def cmd_tools(args) -> int:
    proc = run_driver(["list-tools"])
    text = (proc.stdout or proc.stderr or "").strip()
    if args.pattern:
        needle = args.pattern.lower()
        text = "\n".join(line for line in text.splitlines() if needle in line.lower())
    if args.json:
        rows = []
        for line in text.splitlines():
            name, _, description = line.partition("  ")
            rows.append({"name": name.strip(), "description": description.strip()})
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    elif text:
        print(text)
    return proc.returncode


def cmd_desc(args) -> int:
    proc = run_driver(["describe", args.tool])
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    return proc.returncode


def cmd_call(args) -> int:
    payload = read_stdin_json(args.json_args) if args.json_args else "{}"
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as error:
        sys.exit(f"cuad: arguments are not valid JSON: {error}")
    result = call_tool(args.tool, parsed, screenshot_out=args.screenshot_out)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result.get("status") == "failed" else 0


def cmd_wins(args) -> int:
    rows = fetch_windows()
    rows = match_windows(rows, app=args.app, window=args.window, pid=args.pid)
    if args.on_screen_only:
        rows = [row for row in rows if row.get("is_on_screen", True)]
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        render_windows(rows)
    return 0 if rows else 1


def cmd_ax(args) -> int:
    window = resolve_window(args)
    tool_args: dict = {**window, "session": args.session, "tree_format": "elements"}
    if args.query:
        tool_args["query"] = args.query
    if args.max_elements:
        tool_args["max_elements"] = args.max_elements
    if args.diff:
        tool_args["since"] = "latest"
    if args.full:
        tool_args["tree_format"] = "both"
    if args.no_screenshot:
        tool_args["include_screenshot"] = False
    result = call_tool("get_window_state", tool_args, screenshot_out=args.out)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    elements = result.get("elements") or []
    if args.actionable:
        elements = [row for row in elements if row.get("actions")]
    render_ax(result, elements, shot=args.out, header=result)
    return 0


def cmd_shot(args) -> int:
    window = resolve_window(args)
    result = call_tool(
        "get_window_state",
        {**window, "include_accessibility_tree": False, "session": args.session},
        screenshot_out=args.out,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        size = ""
        if result.get("screenshot_width"):
            size = f" {result['screenshot_width']}x{result['screenshot_height']}"
        print(f"{args.out}{size}  capture={result.get('capture_id', 'n/a')}")
        if result.get("screenshot_error"):
            print(f"note: {result['screenshot_error']}")
            return 1
    return 0


def cmd_verify(args) -> int:
    check = check_spec(args.check)
    if args.gone:
        check["gone"] = True
    target = {
        key: getattr(args, key)
        for key in ("pid", "window_id", "app", "window")
        if getattr(args, key, None)
    }
    step: dict = {"expect": [check]}
    if args.wait:
        step["wait_for"] = check
    payload = {**target, "session": args.session, "steps": [step]}
    if args.observe:
        payload["observe"] = {}
    result = call_tool("run_steps", payload)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        render_steps(result)
    return 0 if result.get("ok") else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cuad",
        description="Fast shell client for the local cua-driver product.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Usage examples:", 1)[1] if "Usage examples:" in __doc__ else None,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def selector(p, *, with_target=True):
        p.add_argument("--app", help="process/executable name substring")
        p.add_argument("--window", help="window title substring (reliable for UWP)")
        p.add_argument("--pid", type=int)
        p.add_argument("--window-id", type=int, dest="window_id")
        if with_target:
            p.add_argument("--session", default=os.environ.get("CUAD_SESSION", "omp"),
                           help="session label (default: omp)")
        p.add_argument("--json", action="store_true")

    p = sub.add_parser("up", help="start the local daemon if it is not running")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_up)

    p = sub.add_parser("down", help="stop the local daemon")
    p.set_defaults(func=cmd_down)

    p = sub.add_parser("status", help="daemon status")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("version", help="installed binary version")
    p.set_defaults(func=cmd_version)

    p = sub.add_parser("doctor", help="run the driver's environment checks")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("tools", help="list MCP tools")
    p.add_argument("pattern", nargs="?", help="only lines containing this substring")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_tools)

    p = sub.add_parser("desc", help="describe one tool (schema included)")
    p.add_argument("tool")
    p.set_defaults(func=cmd_desc)

    p = sub.add_parser("call", help="raw tool call; JSON argument or @file or -")
    p.add_argument("tool")
    p.add_argument("json_args", nargs="?", help="JSON object, @file, or - for stdin")
    p.add_argument("--screenshot-out", dest="screenshot_out")
    p.set_defaults(func=cmd_call)

    p = sub.add_parser("wins", help="list windows, compact")
    selector(p, with_target=False)
    p.add_argument("--on-screen-only", action="store_true", dest="on_screen_only")
    p.set_defaults(func=cmd_wins)

    p = sub.add_parser("ax", help="accessibility snapshot, compact one line per element")
    selector(p)
    p.add_argument("--query", help="project the tree to rows matching this substring")
    p.add_argument("--max-elements", type=int, dest="max_elements")
    p.add_argument("--diff", action="store_true", help="only rows changed since the last read")
    p.add_argument("--full", action="store_true", help="also return the markdown tree")
    p.add_argument("--actionable", action="store_true", help="only rows with actions")
    p.add_argument("-o", "--out", help="write the screenshot to this file")
    p.add_argument("--no-screenshot", action="store_true", dest="no_screenshot")
    p.set_defaults(func=cmd_ax)

    p = sub.add_parser("shot", help="screenshot straight to a file")
    selector(p)
    p.add_argument("-o", "--out", required=True)
    p.set_defaults(func=cmd_shot)

    p = sub.add_parser(
        "act",
        help="one name-targeted run_steps batch; flags run in the order written",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "target syntax: [role:]label[#nth]   (e.g. 'button:Save', 'textfield:Email#1', 'Save')\n"
            "checks:        'text:Thanks' or [role:]label\n"
            "example:       cuad act --window Calculator --click Clear --click Six --expect 'text:Display is 42'"
        ),
    )
    selector(p)
    p.add_argument("--click", action=StepCollector, metavar="TARGET")
    p.add_argument("--rightclick", action=StepCollector, metavar="TARGET")
    p.add_argument("--doubleclick", action=StepCollector, metavar="TARGET")
    p.add_argument("--type", action=StepCollector, metavar="TEXT")
    p.add_argument("--into", default=None,
                   help="target for --type, e.g. --into textfield:Email")
    p.add_argument("--key", action=StepCollector, metavar="KEY",
                   help="'enter' or a combo like 'ctrl+s'")
    p.add_argument("--set", action=StepCollector, metavar="TARGET=VALUE")
    p.add_argument("--scroll", action=StepCollector, metavar="TARGET")
    p.add_argument("--expect", action=StepCollector, metavar="CHECK")
    p.add_argument("--wait", action=StepCollector, metavar="CHECK")
    p.add_argument("--gone", action=StepCollector, metavar="CHECK")
    p.add_argument("--value", action=StepCollector, metavar="TARGET=TEXT",
                   help="check that a field's value contains TEXT")
    p.add_argument("--value-is", action=StepCollector, metavar="TARGET=VALUE",
                   help="check that a field's value equals VALUE")
    p.add_argument("--shot", action=StepCollector, metavar="PATH")
    p.add_argument("--no-observe", action="store_false", dest="observe",
                   help="skip the end-of-batch diff read")
    p.set_defaults(func=run_act, steps=None, observe=True)

    p = sub.add_parser("verify", help="one check, exit 0 when it holds")
    selector(p)
    p.add_argument("check", help="'text:Thanks' or [role:]label")
    p.add_argument("--gone", action="store_true", help="pass when the target is absent")
    p.add_argument("--wait", action="store_true", help="wait up to the driver's check timeout")
    p.add_argument("--observe", action="store_true")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("recipes", help="list the saved recipe batches (run_steps JSON)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_recipes)

    p = sub.add_parser("run", help="replay a saved recipe: cuad run <name> [--var k=v]")
    p.add_argument("name")
    p.add_argument("--var", action="append", metavar="KEY=VALUE",
                   help="fill a placeholder in the recipe; repeatable")
    selector(p)
    p.add_argument("--dry-run", action="store_true", dest="dry_run",
                   help="print the resolved run_steps payload instead of sending it")
    p.add_argument("--no-launch", action="store_true", dest="no_launch",
                   help="drive the window that is already there; skip the recipe's launch")
    p.add_argument("--no-observe", action="store_true", dest="no_observe",
                   help="skip the end-of-batch diff read")
    p.set_defaults(func=cmd_run)

    return parser


NEEDS_DAEMON = {"ax", "shot", "act", "verify", "wins", "call", "run"}


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = build_parser()
    args = parser.parse_args()
    if args.command in NEEDS_DAEMON and not ensure_daemon():
        return 1
    if args.command == "act" and not args.steps:
        print(
            "cuad act: give at least one step "
            "(--click/--rightclick/--doubleclick/--type/--key/--set/--scroll/--expect/--wait/"
            "--gone/--value/--value-is/--shot)",
            file=sys.stderr,
        )
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
