"""Connection domain: the SSHConnection object and command execution.

Owns the paramiko lifecycle (proxy fallback, host-key verification,
reconnect policy, per-command channels), the security filter and the
shell command templates. Transfer and job behaviour live in the mixed-in
modules ``transfer.py`` and ``jobs.py``.
"""
import re
import shlex
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional

import paramiko

from . import config
from .jobs import JobsMixin
from .transfer import TransferMixin


class SSHConnection(TransferMixin, JobsMixin):
    """SSH connection wrapper — proxy/direct auto-fallback, script upload & execution, command execution"""

    def __init__(self, cfg: dict, aliases: list = None,
                 yml_path: str = None):
        self.host = cfg["host"]
        self.port = int(cfg.get("port", 22))
        self.user = cfg["user"]
        self.password = cfg.get("password")
        self.key_path = config._normalize_path(cfg.get("key", "")) or None
        self.key_password = cfg.get("key_password")
        self.sudo_password = cfg.get("sudo_password") or cfg.get("password")
        self.timeout = int(cfg.get("timeout",
                                   config.global_config.get("server", {}).get("timeout", 30)))
        server_defaults = config.global_config.get("server", {})
        self.auto_reconnect = bool(
            cfg.get("auto_reconnect", server_defaults.get("auto_reconnect", True))
        )
        self.reconnect_interval = max(
            0.0,
            float(cfg.get(
                "reconnect_interval",
                server_defaults.get("reconnect_interval", 5),
            )),
        )
        self.reconnect_fast_attempts = 5
        self.reconnect_slow_interval = 60.0
        self.keepalive_interval = max(
            0,
            int(cfg.get("keepalive_interval", server_defaults.get("keepalive_interval", 15))),
        )
        self.scripts_dir = cfg.get("scripts_dir",
                                     f"/home/{cfg.get('user', 'root')}/scripts")
        self.scripts_local_dir = cfg.get("scripts_local_dir")
        # Background-job state lives on the remote, so jobs survive MCP
        # restarts; defaults to a hidden dir next to the scripts.
        self.jobs_dir = cfg.get("jobs_dir") or f"{self.scripts_dir}/.jobs"
        self.shell = cfg.get("shell", "bash")  # "bash", "cmd", "powershell"
        self._tpl = config.CMD_TEMPLATES[self.shell]
        self.aliases = aliases or []
        self._yml_path = yml_path

        # Security: command filtering (per-server overrides the global
        # 'security' section from config.yaml).
        sec_cfg = config.global_config.get("security", {}) or {}
        wl = cfg.get("whitelist")
        if wl is None:
            wl = sec_cfg.get("whitelist") or []
        bl = cfg.get("blacklist")
        if bl is None:
            bl = sec_cfg.get("blacklist") or []
        template = cfg.get("command_template")
        if not template:
            template = sec_cfg.get("command_template") or ""
        self.whitelist = [re.compile(p) for p in wl]
        self.blacklist = [re.compile(p) for p in bl]
        self.command_template = template

        # Host key verification: "tofu" (trust on first use, persist),
        # "strict" (known_hosts must contain the key), "insecure" (no check).
        host_key_mode = str(
            cfg.get("host_key_checking",
                    server_defaults.get("host_key_checking", "tofu"))
        ).lower()
        if host_key_mode not in config.HOST_KEY_MODES:
            raise ValueError(
                f"Invalid host_key_checking: {host_key_mode!r}; "
                f"expected one of {config.HOST_KEY_MODES}"
            )
        self.host_key_checking = host_key_mode

        # Security: path restrictions for upload/download
        self._allowed_paths = {
            "local": [str(Path(p).resolve()) for p in cfg.get("allowed_local_paths", [])],
            "remote": [str(p) for p in cfg.get("allowed_remote_paths", [])],
        }

        # Proxy config: per-server takes priority, then global fallback
        self.proxy = config._resolve_proxy(cfg.get("proxy"),
                                           config.global_config.get("proxy", {}) or {})

        self._client: Optional[paramiko.SSHClient] = None
        self._last_used = 0
        self._connect_lock = threading.Lock()
        self._connect_failures = 0
        self._reconnect_wakeup = threading.Event()
        self._reconnect_thread: Optional[threading.Thread] = None
        self._closed = False

    # ── connection lifecycle ───────────────────────────────────────

    def connect(self):
        """Connect for an explicit request, bypassing any reconnect cooldown."""
        with self._connect_lock:
            self._closed = False
            if self._client and self._is_alive():
                self._last_used = time.time()
                return
            try:
                self._connect_once()
            except Exception as exc:
                self._record_connect_failure()
                raise config._operation_failure(
                    "connection", f"{self.user}@{self.host}:{self.port}",
                    self.timeout, exc,
                ) from exc
            self._connect_failures = 0
            self._reconnect_wakeup.set()

    def _connect_once(self):
        """Perform one proxy/direct connection cycle."""
        # Per-server proxy wins; global proxy config is re-read live so
        # toggling proxy.enabled in config.yaml applies to new connections.
        proxy = config._resolve_proxy(self.proxy,
                                      config.load_global_config().get("proxy", {}) or {})

        if self._client:
            self._client.close()
            self._client = None

        # Check pysocks availability
        if proxy:
            import socks  # noqa: F401

        # Verify the server host key before authenticating, so a MITM never
        # sees the password or key passphrase.
        self._probe_host_key(proxy)

        # Try proxy connection first
        if proxy:
            try:
                self._connect_proxy_with(proxy)
                return
            except Exception as e:
                error_msg = f"Proxy connection failed ({type(e).__name__}: {e}), fallback to direct..."
                print(error_msg, file=sys.stderr)
                self._log_proxy_error(proxy, e)

        # Direct connection (fallback after proxy failure)
        self._connect_direct()

    def _make_client(self) -> paramiko.SSHClient:
        """Create an SSHClient preloaded with trusted host keys."""
        c = paramiko.SSHClient()
        c.load_system_host_keys()
        if config.KNOWN_HOSTS_PATH.exists():
            try:
                c.load_host_keys(str(config.KNOWN_HOSTS_PATH))
            except Exception as e:
                print(f"Warning: could not load {config.KNOWN_HOSTS_PATH}: {e}",
                      file=sys.stderr)
        if self.host_key_checking == "insecure":
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        else:
            c.set_missing_host_key_policy(paramiko.RejectPolicy())
        return c

    def _make_socket(self, proxy: Optional[dict]):
        """Open a TCP (optionally SOCKS5-proxied) socket to the server."""
        if proxy:
            import socks
            sock = socks.socksocket()
            sock.set_proxy(socks.SOCKS5, proxy["host"], int(proxy["port"]))
            sock.settimeout(self.timeout)
            sock.connect((self.host, self.port))
            return sock
        return socket.create_connection((self.host, self.port),
                                        timeout=self.timeout)

    def _probe_host_key(self, proxy: Optional[dict]):
        """Handshake without authenticating and verify/persist the host key."""
        if self.host_key_checking == "insecure":
            return
        sock = None
        transport = None
        try:
            sock = self._make_socket(proxy)
            transport = paramiko.Transport(sock)
            transport.banner_timeout = self.timeout
            transport.start_client()
            key = transport.get_remote_server_key()
        except paramiko.SSHException:
            raise
        except Exception as e:
            raise paramiko.SSHException(
                f"Host key probe to {self.host}:{self.port} failed: "
                f"{type(e).__name__}: {e}"
            ) from e
        finally:
            if transport is not None:
                transport.close()
            elif sock is not None:
                sock.close()
        self._check_or_record_host_key(key)

    def _host_key_display(self) -> str:
        if self.port == 22:
            return self.host
        return f"[{self.host}]:{self.port}"

    def _check_or_record_host_key(self, key):
        display = self._host_key_display()
        with config._KNOWN_HOSTS_LOCK:
            known = paramiko.HostKeys()
            if config.KNOWN_HOSTS_PATH.exists():
                try:
                    known.load(str(config.KNOWN_HOSTS_PATH))
                except Exception:
                    pass
            entry = known.lookup(display)
            stored = entry.get(key.get_name()) if entry else None
            if stored is not None:
                if stored.get_fingerprint() != key.get_fingerprint():
                    raise paramiko.SSHException(
                        f"Host key mismatch for {display}: the {key.get_name()} "
                        f"key changed (stored fingerprint "
                        f"{stored.get_fingerprint().hex()}, server presented "
                        f"{key.get_fingerprint().hex()}). Possible MITM; "
                        "refusing to connect."
                    )
                return
            if self.host_key_checking == "strict":
                raise paramiko.SSHException(
                    f"Unknown host key for {display} ({key.get_name()} "
                    f"{key.get_fingerprint().hex()}); host_key_checking is "
                    "'strict'. Seed known_hosts or use 'tofu'."
                )
            known.add(display, key.get_name(), key)
            try:
                config.KNOWN_HOSTS_PATH.parent.mkdir(parents=True, exist_ok=True)
                known.save(str(config.KNOWN_HOSTS_PATH))
            except Exception as e:
                print(f"Warning: could not persist known_hosts: {e}",
                      file=sys.stderr)

    def _record_connect_failure(self):
        """Record a failed cycle and ensure policy-controlled background retries."""
        self._connect_failures += 1
        if not self.auto_reconnect or self._closed:
            return
        if not self._reconnect_thread or not self._reconnect_thread.is_alive():
            self._reconnect_thread = threading.Thread(
                target=self._reconnect_loop,
                name=f"ssh-reconnect-{self.host}",
                daemon=True,
            )
            self._reconnect_thread.start()
        self._reconnect_wakeup.set()

    def _reconnect_loop(self):
        """Retry quickly for five failures, then once per minute."""
        while True:
            with self._connect_lock:
                if (
                    self._closed
                    or not self.auto_reconnect
                    or (self._client and self._is_alive())
                ):
                    return
                delay = (
                    self.reconnect_interval
                    if self._connect_failures < self.reconnect_fast_attempts
                    else self.reconnect_slow_interval
                )
                self._reconnect_wakeup.clear()

            # Explicit requests set this event after their immediate attempt,
            # restarting the policy delay without causing a duplicate attempt.
            if self._reconnect_wakeup.wait(delay):
                continue

            with self._connect_lock:
                if (
                    self._closed
                    or not self.auto_reconnect
                    or (self._client and self._is_alive())
                ):
                    return
                try:
                    self._connect_once()
                except Exception as exc:
                    self._connect_failures += 1
                    phase = (
                        "fast"
                        if self._connect_failures < self.reconnect_fast_attempts
                        else "60s cooldown"
                    )
                    print(
                        f"SSH reconnect failed "
                        f"(consecutive failures={self._connect_failures}, next={phase}): "
                        f"{type(exc).__name__}: {exc}",
                        file=sys.stderr,
                    )
                    continue
                self._connect_failures = 0
                return

    def _connect_proxy_with(self, proxy: dict):
        """Connect via SOCKS5 proxy.

        Negotiates on the authenticating transport itself and verifies its
        host key *before* sending credentials: the probe connection alone
        does not bind the authenticated session, since a server offering
        several key types could present an unverified type after probing.
        """
        sock = self._make_socket(proxy)
        transport = None
        try:
            c = paramiko.SSHClient()
            transport = paramiko.Transport(sock)
            transport.banner_timeout = self.timeout
            transport.auth_timeout = self.timeout
            transport.start_client()
            if self.host_key_checking != "insecure":
                self._check_or_record_host_key(transport.get_remote_server_key())
            self._transport_auth(transport)
            if not transport.is_authenticated():
                raise paramiko.AuthenticationException(
                    "Proxy SSH authentication incomplete; additional authentication required")
            transport.set_keepalive(self.keepalive_interval)
            c._transport = transport
            self._client = c
            self._last_used = time.time()
        except Exception:
            if transport is not None:
                transport.close()
            else:
                sock.close()
            raise

    def _transport_auth(self, transport):
        """Authenticate a negotiated Transport with this server's credentials."""
        kw = self._get_auth()
        if "password" in kw:
            transport.auth_password(self.user, kw["password"])
            return
        passphrase = kw.get("passphrase")
        key = None
        load_error = None
        classes = [paramiko.RSAKey, paramiko.ECDSAKey, paramiko.Ed25519Key]
        dss = getattr(paramiko, "DSSKey", None)
        if dss is not None:
            classes.append(dss)
        for kcls in classes:
            try:
                key = kcls.from_private_key_file(kw["key_filename"],
                                                 password=passphrase)
                break
            except (OSError, paramiko.PasswordRequiredException):
                raise
            except (paramiko.SSHException, ValueError) as exc:
                if load_error is None:
                    load_error = exc
        if key is None:
            raise paramiko.SSHException(
                f"could not load private key {kw['key_filename']}: {load_error}") from load_error
        transport.auth_publickey(self.user, key)

    def _connect_direct(self):
        """Connect directly (no proxy)"""
        c = self._make_client()
        kw = self._get_auth()
        try:
            c.connect(
                self.host,
                port=self.port,
                username=self.user,
                timeout=self.timeout,
                banner_timeout=self.timeout,
                auth_timeout=self.timeout,
                channel_timeout=self.timeout,
                **kw,
            )
            c.get_transport().set_keepalive(self.keepalive_interval)
            self._client = c
            self._last_used = time.time()
        except Exception:
            c.close()
            raise

    def _get_auth(self) -> dict:
        """Get authentication parameters (key or password)"""
        if self.key_path:
            kw = {"key_filename": self.key_path}
            if self.key_password:
                kw["passphrase"] = self.key_password
            return kw
        return {"password": self.password}

    def _is_alive(self) -> bool:
        try:
            transport = self._client and self._client.get_transport()
            return bool(
                transport
                and transport.is_active()
                and transport.is_authenticated()
            )
        except Exception:
            return False

    def _invalidate(self, client=None):
        """Retire a failed cached client without closing a newer replacement."""
        with self._connect_lock:
            if client is not None and self._client is not client:
                return
            failed = self._client
            self._client = None
            if failed:
                failed.close()

    def _log_proxy_error(self, proxy: dict, exc: Exception):
        """Log proxy connection errors to a log file"""
        log_path = config.SCRIPT_DIR / "proxy_error.log"
        try:
            import traceback
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {exc}\n")
                f.write(f"  Target: {self.user}@{self.host}:{self.port}\n")
                f.write(f"  Proxy: {proxy}\n")
                f.write(traceback.format_exc())
                f.write("---\n")
        except Exception:
            pass

    # ── command execution ──────────────────────────────────────────

    def _check_command(self, cmd: str) -> str:
        """Check command against whitelist/blacklist, return template if set. Raises on violation."""
        # Check blacklist (blocked substring anywhere in the command)
        for pattern in self.blacklist:
            if pattern.search(cmd):
                raise ValueError(f"Command blocked by blacklist: {pattern.pattern}")
        # Check whitelist (the WHOLE command must match one pattern; search
        # semantics would let "ls; rm -rf /" pass a "^ls" rule)
        if self.whitelist:
            if not any(p.fullmatch(cmd) for p in self.whitelist):
                raise ValueError(f"Command not in whitelist: {cmd}")
        # Apply command template
        if self.command_template:
            cmd = self.command_template.replace("<command>", cmd)
        return cmd

    def _prepare_sudo(self, cmd: str):
        """Wrap a command to run via sudo, returning (command, stdin_secret).

        The password is delivered over the channel stdin (``sudo -S``) so it
        never appears in the remote process argv (no ``ps`` exposure).
        The command always runs through ``bash -c``; on Windows servers this
        requires bash to be available (e.g., Git Bash or WSL).
        """
        if not self.sudo_password:
            raise ValueError("sudo_password not configured for this server")
        # Redirect inside the elevated shell, leaving sudo's password input
        # intact even when cached credentials make it skip reading stdin.
        payload = "exec </dev/null; " + cmd
        return f"sudo -S -p '' bash -c {shlex.quote(payload)}", self.sudo_password

    def _strip_sudo_noise(self, result: dict) -> dict:
        """Remove '[sudo]' password prompt lines from output."""
        for stream in ("stdout", "stderr"):
            result[stream] = "\n".join(
                l for l in result[stream].split("\n")
                if "Password:" not in l and "[sudo:" not in l
            ).strip("\n")
        return result

    def run(self, cmd: str, timeout: int = None, sudo: bool = False,
            stream_cb: Any = None, internal: bool = False) -> dict:
        """Execute a remote command, returns {stdout, stderr, code}.

        Commands run concurrently on independent SSH channels over the
        shared transport, so a long-running command on this server never
        blocks another thread's command. Reconnect/invalidation races are
        handled per-channel (each command owns its own channel).

        Args:
            cmd: shell command to execute
            timeout: seconds before giving up (defaults to server timeout from YAML)
            sudo: if True, run via ``sudo -S`` with the password fed over stdin
            stream_cb: optional callback(chunk: str, is_stderr: bool) for real-time output
            internal: True for code-generated helper commands (skips
                whitelist/blacklist filtering; never set from external input)
        """
        return self._run(cmd, timeout, sudo, stream_cb, internal)

    def _run(self, cmd: str, timeout: int = None, sudo: bool = False,
             stream_cb: Any = None, internal: bool = False) -> dict:
        if timeout is None or timeout <= 0:
            timeout = self.timeout
        cmd = config._repair_surrogateescaped_command(cmd)
        if not internal:
            cmd = self._check_command(cmd)
        sudo_secret = None
        if sudo:
            cmd, sudo_secret = self._prepare_sudo(cmd)
        ch = None
        client = None
        for attempt in range(2):
            self.connect()
            client = self._client
            try:
                transport = client.get_transport()
                if not transport or not transport.is_active() or not transport.is_authenticated():
                    raise paramiko.SSHException("cached SSH transport is not usable")
                ch = transport.open_session(timeout=min(timeout, self.timeout))
                ch.settimeout(timeout)
                ch.exec_command(cmd)
                if sudo_secret is not None:
                    ch.sendall((sudo_secret + "\n").encode("utf-8"))
                    ch.shutdown_write()
                break
            except (EOFError, OSError, paramiko.SSHException):
                if ch:
                    ch.close()
                    ch = None
                self._invalidate(client)
                if attempt or not self.auto_reconnect:
                    self._record_connect_failure()
                    raise

        if ch is None:
            raise paramiko.SSHException("failed to open SSH command channel")

        stdout_data, stderr_data = [], []
        deadline = time.time() + timeout
        try:
            while time.time() < deadline:
                if ch.recv_ready():
                    chunk = ch.recv(65536)
                    stdout_data.append(chunk)
                    if stream_cb:
                        stream_cb(chunk.decode(errors="replace"), False)
                if ch.recv_stderr_ready():
                    chunk = ch.recv_stderr(65536)
                    stderr_data.append(chunk)
                    if stream_cb:
                        stream_cb(chunk.decode(errors="replace"), True)
                if ch.exit_status_ready() and not ch.recv_ready() and not ch.recv_stderr_ready():
                    break
                time.sleep(0.05)
        except (EOFError, OSError, paramiko.SSHException):
            self._invalidate(client)
            raise

        # Give the channel a short grace period to flush its tail, then drain.
        if not ch.exit_status_ready():
            time.sleep(0.2)
        while ch.recv_ready():
            chunk = ch.recv(65536)
            stdout_data.append(chunk)
            if stream_cb:
                stream_cb(chunk.decode(errors="replace"), False)
        while ch.recv_stderr_ready():
            chunk = ch.recv_stderr(65536)
            stderr_data.append(chunk)
            if stream_cb:
                stream_cb(chunk.decode(errors="replace"), True)

        rc = ch.recv_exit_status() if ch.exit_status_ready() else -1
        ch.close()
        result = {
            "stdout": b"".join(stdout_data).decode(errors="replace"),
            "stderr": b"".join(stderr_data).decode(errors="replace"),
            "code": rc,
        }
        if rc == -1:
            result["stderr"] = (
                result["stderr"] +
                f"\n[ssh-ops] command timed out after {timeout}s; "
                "the channel was closed but the remote process may still be running"
            ).strip("\n")
        return self._strip_sudo_noise(result) if sudo else result

    def _cmd(self, name: str, **kwargs) -> str:
        """Format a command template, shell-quoting every placeholder value."""
        tpl = self._tpl[name]
        if not tpl:
            return ""
        if not kwargs:
            return tpl
        return tpl.format(**{k: self._quote_arg(v, k) for k, v in kwargs.items()})

    def _quote_arg(self, value: Any, key: str = "") -> str:
        """Quote one command-argument value for the server's shell."""
        if isinstance(value, int):
            return str(value)
        s = str(value)
        if config._FORBIDDEN_CHARS_RE.search(s) or "\n" in s or "\r" in s:
            raise ValueError(f"Unsafe character in command argument: {s!r}")
        if self.shell == "bash":
            return shlex.quote(s)
        if self.shell == "cmd":
            if any(c in s for c in '"&|<>^'):
                raise ValueError(f"Unsafe character in cmd argument: {s!r}")
            # '%' allows server-side env expansion; only our own staging
            # paths (built from the configured tmp_prefix, e.g. %TEMP%)
            # may contain it, so user-supplied values cannot smuggle
            # expansion-based injection.
            if "%" in s and not s.startswith(str(self._tpl["tmp_prefix"])):
                raise ValueError(f"Unsafe character in cmd argument: {s!r}")
            return f'"{s}"'
        # powershell
        if "`" in s:
            raise ValueError(f"Unsafe character in powershell argument: {s!r}")
        return "'" + s.replace("'", "''") + "'"

    # ── aliases ────────────────────────────────────────────────────

    def _scripts_base(self) -> Path:
        """Get the base directory for resolving relative script paths.
        Resolution:
          1. If scripts_local_dir is set, use {yml_dir}/{scripts_local_dir}
          2. Otherwise fall back to yml file's directory.
        """
        base = Path(self._yml_path).parent.resolve() if self._yml_path else Path.cwd()
        if self.scripts_local_dir:
            return (base / self.scripts_local_dir).resolve()
        return base

    def _is_unix(self) -> bool:
        """Check if shell is Unix-like."""
        return self.shell == "bash"

    def run_alias(self, name: str, stream_cb: Any = None) -> dict:
        """Run an alias-defined quick command"""
        target = None
        for a in self.aliases:
            if a.get("name") == name:
                target = a
                break
        if not target:
            raise ValueError(f"Alias not found: {name}")
        timeout = int(target.get("timeout", 300))
        sudo = target.get("sudo", False)

        # inline type: execute command directly on remote
        if "inline" in target:
            return self.run(target["inline"], timeout=timeout, sudo=sudo, stream_cb=stream_cb)

        # script type: upload local .sh first, then execute remotely
        local_file = (self._scripts_base() / config._safe_relpath(target["script"], "script")).resolve()
        if not local_file.is_file():
            raise FileNotFoundError(f"Script not found: {local_file}")
        base = self._scripts_base()
        if local_file.is_relative_to(base):
            rel = local_file.relative_to(base).as_posix()
            remote_path = f"{self.scripts_dir}/{config._safe_relpath(rel, 'script')}"
        else:
            remote_path = (
                f"{self.scripts_dir}/external/"
                f"{config._safe_relpath(local_file.name, 'script')}"
            )

        # Check if already uploaded (skip re-upload). Use sudo=sudo so we can stat
        # files owned by root when the alias targets a root-owned scripts_dir.
        result = self.run(self._cmd("file_exists", path=remote_path),
                         timeout=5, sudo=sudo, internal=True)
        if result["code"] != 0:
            self.upload_script(str(local_file), script_name=local_file.name,
                               timeout=30, sudo=sudo)

        return self.run(self._cmd("run_script", path=remote_path), timeout=timeout, sudo=sudo, stream_cb=stream_cb)

    def list_aliases(self) -> list:
        """List all configured aliases"""
        aliases = []
        for a in self.aliases:
            item = {
                "name": a.get("name", ""),
                "type": "script" if "script" in a else "inline",
                "desc": a.get("desc", ""),
                "timeout": a.get("timeout", 300),
                "sudo": a.get("sudo", False),
            }
            if "inline" in a:
                item["inline"] = a["inline"]
            if "script" in a:
                item["script"] = a["script"]
            aliases.append(item)
        return aliases

    def close(self):
        """Close the SSH connection"""
        with self._connect_lock:
            self._closed = True
            self._reconnect_wakeup.set()
            if self._client:
                self._client.close()
                self._client = None
