"""Shared local infrastructure: global config, paths, encoding fixes, templates.

Everything here is offline (no network): loading ``config.yaml``, path
normalisation for Git-Bash/WSL quirks, the per-shell command templates, and
the small validators the transfer/connection/pool modules share.
"""
import io
import os
import re
import socket
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

import yaml

# Force UTF-8 output on Windows
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# The package lives inside the project dir; config/known_hosts sit next to it.
SCRIPT_DIR = Path(__file__).parent.parent.resolve()
CONFIG_PATH = SCRIPT_DIR / "config.yaml"
KNOWN_HOSTS_PATH = SCRIPT_DIR / "known_hosts"
_KNOWN_HOSTS_LOCK = threading.Lock()

HOST_KEY_MODES = ("tofu", "strict", "insecure")

# Control characters that must never appear in a generated remote command.
_FORBIDDEN_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _safe_relpath(raw, field: str) -> str:
    """Validate a remote-relative path fragment (e.g. a script name).

    Rejects absolute paths, backslashes, parent-directory traversal,
    empty segments and control characters. Returns the normalised
    slash-separated path.
    """
    s = str(raw)
    if not s or "\\" in s or s.startswith("/") or _FORBIDDEN_CHARS_RE.search(s):
        raise ValueError(f"Invalid {field}: {raw!r}")
    parts = s.split("/")
    for part in parts:
        if part in ("", ".", ".."):
            raise ValueError(f"Invalid {field}: {raw!r}")
    return "/".join(parts)


def _resolve_proxy(server_proxy: Optional[dict],
                   global_proxy_cfg: dict) -> Optional[dict]:
    """Resolve the effective proxy for a server.

    Per-server proxy wins; otherwise use the global SOCKS5 proxy when it is
    enabled. Shared by ``SSHConnection.__init__`` and ``_connect_once`` so
    both agree on the precedence rules.
    """
    if server_proxy:
        return dict(server_proxy)
    if global_proxy_cfg.get("enabled"):
        return {
            "host": global_proxy_cfg.get("host", "127.0.0.1"),
            "port": global_proxy_cfg.get("port", 1080),
        }
    return None


class SSHOperationError(OSError):
    """A remote operation failed, with enough context for an MCP response."""


def _operation_failure(operation: str, target: str, timeout: float,
                       exc: Exception) -> SSHOperationError:
    """Turn low-level socket/Paramiko exceptions into actionable diagnostics."""
    is_timeout = isinstance(exc, (TimeoutError, socket.timeout))
    kind = "timed out" if is_timeout else "failed"
    detail = str(exc).strip() or type(exc).__name__
    return SSHOperationError(
        f"SSH {operation} {kind} for {target} after {timeout} seconds "
        f"({type(exc).__name__}: {detail})"
    )


def _repair_surrogateescaped_command(command: str) -> str:
    """Restore UTF-8 text that a Windows code page decoded with surrogateescape.

    MCP arguments should already be valid Unicode. Some Windows stdio bridges,
    however, decode UTF-8 command bytes with the active ANSI code page and use
    ``surrogateescape`` for undecodable bytes. The resulting string contains
    low surrogates and Paramiko cannot encode it as UTF-8. Re-encoding with the
    same Windows code page reconstructs the original bytes.

    Valid Unicode commands are returned unchanged. A command containing low
    surrogates that cannot be repaired is rejected instead of being silently
    altered or sent to the wrong remote shell.
    """
    if not any(0xDC80 <= ord(char) <= 0xDCFF for char in command):
        return command

    encodings = []
    if sys.platform == "win32":
        import locale
        encodings.append(locale.getpreferredencoding(False))
    encodings.extend(("gbk", "cp936"))

    seen = set()
    for encoding in encodings:
        key = encoding.lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            repaired = command.encode(encoding, errors="surrogateescape").decode("utf-8")
            repaired.encode("utf-8")
            return repaired
        except (LookupError, UnicodeError):
            continue

    raise ValueError(
        "Command contains invalid surrogate-escaped text and could not be "
        "restored as UTF-8"
    )


def _normalize_path(raw: str) -> str:
    """Normalize a path string for the current OS.

    Converts Windows-style drive paths (e.g. 'D:\\agents\\servers') to WSL
    /mnt/<drive>/... form when running under Linux. No-op elsewhere.
    """
    if not raw:
        return raw
    s = str(raw).replace("\\", "/")

    # Convert Windows path to WSL path when running under Linux
    if sys.platform == "linux":
        # Match "X:/..." pattern
        if len(s) >= 2 and s[1] == ":" and s[0].isalpha():
            drive = s[0].lower()
            rest = s[2:].lstrip("/")
            return f"/mnt/{drive}/{rest}"
        return s

    # Convert WSL path to Windows path when running under Windows
    if sys.platform == "win32":
        # Match "/mnt/X/..." pattern
        if s.startswith("/mnt/"):
            parts = s.split("/", 3)
            if len(parts) >= 4:
                drive = parts[2].upper()
                rest = parts[3]
                return f"{drive}:/{rest}"
        return s

    return s


def unmangle_msys_argv(argv: list) -> list:
    """Undo Git-Bash MSYS2 argument path rewriting when invoked from it.

    Git-Bash rewrites any look-like-POSIX argument before launching a
    NATIVE Windows program: an upload-file remote path ``/home/bit/x``
    arrives as ``<msys-root>/home/bit/x``, and ``/tmp/x`` arrives as
    ``<temp>/x`` (Git-Bash mounts /tmp at %TEMP%). Both rewrites are then
    sent literally to a Linux peer, which fails with a bare ENOENT from
    SFTP. Two ``cygpath`` probes reproduce the exact rewrites; the added
    prefixes are stripped back off. Noop outside Git-Bash, so
    cmd/PowerShell/MCP invocations and plain POSIX argv are untouched.

    Trade-off: inside Git-Bash only, a Windows-server path that really
    starts with the msys root or %TEMP% is rewritten to /... — rare and
    visible in the error message; run from cmd/PowerShell to avoid it.
    """
    if len(argv) <= 1 or sys.platform != "win32" or not os.environ.get("MSYSTEM"):
        return argv
    probe_base = "msys_argv_probe_zxk"
    prefixes = []
    for probe, replacement in (("/" + probe_base, "/"),
                               ("/tmp/" + probe_base, "/tmp")):
        try:
            out = subprocess.run(
                ["cygpath", "-w", "-m", probe],
                capture_output=True, text=True, timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            break
        if out.returncode != 0:
            continue
        converted = out.stdout.strip().replace("\\", "/")
        # Match on the probe basename only: the /tmp mount maps to
        # %TEMP%, so the converted form no longer contains "/tmp".
        # Keep the leading slash so the stripped prefix has no trailing
        # separator ("<msys-root>", not "<msys-root>/").
        if not converted.endswith("/" + probe_base):
            continue
        prefix = converted[: -(len(probe_base) + 1)]
        if prefix and all(prefix != p for p, _ in prefixes):
            prefixes.append((prefix, replacement))
    if not prefixes:
        return argv
    fixed = [argv[0]]
    for arg in argv[1:]:
        for prefix, replacement in sorted(prefixes, key=lambda pr: -len(pr[0])):
            if arg == prefix:
                arg = replacement
                break
            if arg.startswith(prefix + "/"):
                arg = replacement.rstrip("/") + arg[len(prefix):]
                break
        fixed.append(arg)
    return fixed


def load_yaml(path: str) -> dict:
    """Load a YAML config file."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {p}")
    text = p.read_text(encoding="utf-8-sig")
    return yaml.safe_load(text) or {}


def load_global_config() -> dict:
    """Load global configuration (proxy, timeout, etc.)"""
    if not CONFIG_PATH.exists():
        return {"proxy": {"enabled": False}, "server": {"timeout": 30}}
    return load_yaml(str(CONFIG_PATH))


global_config: dict = load_global_config()

# servers_dir can be configured in config.yaml (absolute or relative to config file)
_servers_dir_cfg = _normalize_path(global_config.get("servers_dir", "servers"))
SERVERS_DIR = (CONFIG_PATH.parent / _servers_dir_cfg).resolve() if _servers_dir_cfg else SCRIPT_DIR / "servers"


# Command templates keyed by shell type.
# Available placeholders: path, src, dst, tmp, target, mode, user
# All placeholder values are shell-quoted centrally by SSHConnection._cmd;
# templates must NOT add their own quotes around placeholders.
CMD_TEMPLATES = {
    "bash": {
        "mkdir":        "mkdir -p {path}",
        "file_exists":  "test -f {path}",
        "run_script":   "bash {path}",
        "chmod":        "chmod {mode} {path}",
        "stat_owner":   "stat -c '%U:%G' {path}",
        "stat_mode":    "stat -c '%a' {path}",
        "rm_dir":       "rm -rf {path}",
        "cp_r":         "cp -r {src} {dst}",
        "move":         "mv {tmp} {target}",
        "chown":        "chown {user} {path}",
        "chown_r":      "chown -R {user}:{user} {path}",
        "list_dir":     "ls -la {path}",
        "install":      (
            "if [ -e {target} ]; then "
            "OWN=$(stat -c '%u:%g' {target}); "
            "MODE=$(stat -c '%a' {target}); "
            "mv {tmp} {target} && "
            "chown $OWN {target} && "
            "chmod $MODE {target}; "
            "else "
            "PARENT=$(dirname {target}); "
            "OWN=$(stat -c '%u:%g' \"$PARENT\"); "
            "mv {tmp} {target} && "
            "chown $OWN {target} && "
            "chmod 755 {target}; "
            "fi"
        ),
        "tmp_prefix":   "/tmp",
    },
    "cmd": {
        "mkdir":        "mkdir {path} 2>nul",
        "file_exists":  "if exist {path} (echo exists) else exit 1",
        "run_script":   "call {path}",
        "chmod":        "",  # no-op on Windows cmd
        "stat_owner":   "echo n/a",
        "stat_mode":    "echo n/a",
        "rm_dir":       "rmdir /S /Q {path}",
        "cp_r":         "xcopy /Y {src} {dst} /E /I",
        "move":         "move /y {tmp} {target}",
        "chown":        "",  # no-op
        "chown_r":      "",  # no-op
        "list_dir":     "dir {path} /Q",
        "install":      "move /y {tmp} {target}",
        "tmp_prefix":   "%TEMP%",
    },
    "powershell": {
        "mkdir":        "New-Item -ItemType Directory -Path {path} -Force",
        "file_exists":  "if (Test-Path {path}) { exit 0 } else { exit 1 }",
        "run_script":   "& {path}",
        "chmod":        "",  # no-op
        "stat_owner":   "echo n/a",
        "stat_mode":    "echo n/a",
        "rm_dir":       "Remove-Item -Recurse -Force {path}",
        "cp_r":         "Copy-Item -Recurse {src} {dst}",
        "move":         "Move-Item -Force {tmp} {target}",
        "chown":        "",  # no-op
        "chown_r":      "",  # no-op
        "list_dir":     "Get-ChildItem -Path {path} | Format-List",
        "install":      "Move-Item -Force {tmp} {target}",
        "tmp_prefix":   "$env:TEMP",
    },
}
