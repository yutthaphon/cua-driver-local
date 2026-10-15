#!/usr/bin/env python3
"""ccdrv - control the cua-driver MCP daemons from any shell.

Thin, dependency-free wrapper for the *installed* products on this machine:

  local  ->  %LOCALAPPDATA%\\Programs\\Cua\\cua-driver-local\\bin\\cua-driver-local.exe
  release->  %LOCALAPPDATA%\\Programs\\Cua\\cua-driver\\bin\\cua-driver.exe

Why it exists: the harness shell cannot exec a bare `.exe` from PATH or a
relative path (`command not found` even though the file is a valid PE), and
PowerShell re-encodes piped JSON. This runs the binary as real argv with stdin
used only for large JSON, and returns the child's exit code.

Usage:
  ccdrv [--bin local|release|PATH] <driver args...>
  ccdrv json <tool> <json|@file|->
  ccdrv call <tool> [json]
  ccdrv <tool-kebab-name> [json]      # shorthand for `call <tool>`
  ccdrv up | down | status | doctor | version | config | autostart ...

Driver subcommands pass straight through; anything else is treated as a tool
name, so `ccdrv list-windows '{}'` and `ccdrv json list_windows '{}'` agree.

Examples:
  ccdrv --bin local status
  ccdrv --bin release version           # the published product, for comparison
  ccdrv call list_windows '{"on_screen_only":true}'
  ccdrv json run_steps @steps.json
  ccdrv list-windows
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

LOCALAPPDATA = os.environ.get("LOCALAPPDATA", "")
PRODUCTS = {
    "local": os.path.join(LOCALAPPDATA, "Programs", "Cua", "cua-driver-local", "bin", "cua-driver-local.exe"),
    "release": os.path.join(LOCALAPPDATA, "Programs", "Cua", "cua-driver", "bin", "cua-driver.exe"),
}
SOCKET = r"\\.\pipe\cua-driver-local"
ENV_HOME = "CUA_DRIVER_RS_HOME"


def resolve(argv: list[str]) -> tuple[str, list[str]]:
    if argv and argv[0] == "--bin":
        if len(argv) < 2:
            sys.exit("ccdrv: --bin needs local|release|<path>")
        choice = argv[1]
        return PRODUCTS.get(choice, choice), argv[2:]
    env = os.environ.get("CCDRV_BIN")
    if env:
        return env, argv
    for name in ("local", "release"):
        if os.path.exists(PRODUCTS[name]):
            return PRODUCTS[name], argv
    sys.exit("ccdrv: no cua-driver binary found; pass --bin <path>")


def invoke(exe: str, args: list[str], stdin_text: str | None = None) -> int:
    env = os.environ.copy()
    if os.path.basename(exe).startswith("cua-driver-local") and ENV_HOME not in env:
        env[ENV_HOME] = os.path.join(os.environ.get("USERPROFILE", ""), ".cua-driver-local")
    proc = subprocess.run(
        [exe, *args],
        input=stdin_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    return proc.returncode


def load_json(text: str | None) -> str:
    if not text:
        return "{}"
    if text == "-":
        return sys.stdin.read()
    if text.startswith("@"):
        path = text[1:]
        if not os.path.exists(path):
            sys.exit(f"ccdrv: no JSON file at {path}")
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    return text


# Driver subcommands that are not tool calls. Anything else is treated as a
# tool name (kebab-case, so `ccdrv list-windows '{}'`).
SUBCOMMANDS = {
    "autostart", "channel", "check-update", "config", "cursor", "cursor-theme",
    "describe", "diagnose", "doctor", "down", "extension", "history",
    "list-tools", "manifest", "mcp", "mcp-config", "perception", "permissions",
    "recording", "revoke", "sessions", "skills", "status", "stop", "telemetry",
    "up", "update", "version",
}


def main() -> int:
    exe, rest = resolve(sys.argv[1:])
    if not rest:
        sys.exit(__doc__)

    head, *tail = rest

    if head in ("up", "start"):
        code = invoke(exe, ["status"])
        if code == 0:
            return 0
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        log_path = os.path.join(os.environ.get("TEMP", "."), "ccdrv-serve.log")
        with open(log_path, "ab") as handle:
            subprocess.Popen([exe, "serve"], stdout=handle, stderr=handle,
                             stdin=subprocess.DEVNULL, creationflags=flags, close_fds=True)
        import time
        for _ in range(80):
            time.sleep(0.25)
            if invoke(exe, ["status"]) == 0:
                return 0
        print(f"ccdrv: daemon did not start (log: {log_path})", file=sys.stderr)
        return 1

    if head in ("down", "stop"):
        return invoke(exe, ["stop"])
    if head == "version":
        return invoke(exe, ["--version"])
    if head in SUBCOMMANDS:
        return invoke(exe, [head, *tail])

    if head == "json":
        if not tail:
            sys.exit("ccdrv json <tool> <json|@file|->")
        tool, *maybe_json = tail
        js = load_json(maybe_json[0] if maybe_json else None)
        try:
            json.loads(js)
        except json.JSONDecodeError as error:
            sys.exit(f"ccdrv: invalid JSON for {tool}: {error}")
        return invoke(exe, ["call", tool], js)

    if head == "call":
        if not tail:
            sys.exit("ccdrv call <tool> [json]")
        tool, *maybe_json = tail
        js = load_json(maybe_json[0] if maybe_json else None)
        return invoke(exe, ["call", tool], js)

    # Shortcuts: ccdrv <tool-kebab> [json]
    js = load_json(tail[0] if tail else None)
    try:
        json.loads(js)
    except json.JSONDecodeError as error:
        sys.exit(f"ccdrv: invalid JSON for {head}: {error}")
    return invoke(exe, ["call", head.replace("-", "_")], js)


if __name__ == "__main__":
    sys.exit(main())
