"""Transfer domain: file upload/download and remote text I/O over SFTP.

Mixed into ``SSHConnection`` (see connection.py). The methods reach the
connection through ``self.connect() / self.run() / self._cmd() /
self._client`` only — sudo staging and the allow-list checks are the
transfer module's own business, so every path-transfer bug lives in this
one file.
"""
import hashlib
import os
import posixpath
import re
import shlex
import socket
import tempfile
import uuid
from pathlib import Path
from typing import Any

import paramiko

from . import config


class TransferMixin:

    _MAX_RECURSE_DEPTH = 48
    READ_FILE_MAX_BYTES = 1 << 20  # cap one read at 1 MiB (protects MCP channel)

    def download(self, remote_path: str, local_path: str, timeout: int = 300,
                 pattern: str = None, overwrite: bool = True, sudo: bool = False) -> dict:
        """Download a file or directory from remote to local via SFTP.

        If remote_path is a directory, recursively downloads all files.
        Optionally filter by regex pattern on filenames.

        Args:
            sudo: if True, read root-owned files by staging through /tmp:
                  `sudo cp -r <src> /tmp/<uuid>` -> `sudo chown <user>` -> SFTP get -> remove tmp.
        """
        self.connect()

        if self._path_blocked(local_path, "local"):
            raise ValueError(f"Local path not allowed: {local_path}")

        # When sudo, stage entire source tree to a user-readable temp location first
        actual_remote = remote_path
        tmp_stage = None
        if sudo:
            tmp_prefix = self._cmd("tmp_prefix")
            tmp_stage = f"{tmp_prefix}/.dl_stage_{uuid.uuid4().hex[:8]}"
            stage = self.run(
                self._cmd("cp_r", src=remote_path, dst=tmp_stage),
                timeout=timeout, sudo=True, internal=True,
            )
            if stage["code"] != 0:
                raise RuntimeError(f"sudo stage failed: {stage['stderr'].strip()[:200]}")
            if self._is_unix():
                self.run(self._cmd("chown_r", user=self.user, path=tmp_stage),
                          timeout=10, sudo=True, internal=True)
            actual_remote = tmp_stage

        try:
            # Check if (staged) remote is a directory
            sftp = self._sftp(timeout=timeout)
            remote_attr = sftp.stat(actual_remote)
            is_dir = (remote_attr.st_mode & 0o170000) == 0o040000

            if not is_dir:
                if self._path_blocked(remote_path, "remote"):
                    raise ValueError(f"Remote path not allowed: {remote_path}")
                local_path_obj = Path(local_path)
                if not overwrite and local_path_obj.exists():
                    raise FileExistsError(f"Local path already exists: {local_path}")
                local_dir = local_path_obj.parent
                if not local_dir.exists():
                    local_dir.mkdir(parents=True, exist_ok=True)
                sftp.get(actual_remote, str(local_path))
                sftp.close()
                return {
                    "stdout": f"Downloaded {remote_path} -> {local_path}\n",
                    "stderr": "",
                    "code": 0,
                    "remote_path": remote_path,
                    "local_path": local_path,
                }

            # Directory download
            if not overwrite and Path(local_path).exists():
                raise FileExistsError(f"Local path already exists: {local_path}")
            return self._download_dir(sftp, actual_remote, local_path, pattern, timeout,
                                      display_remote=remote_path)
        except (TimeoutError, socket.timeout) as exc:
            raise config._operation_failure(
                "SFTP download", f"{remote_path} from {self.user}@{self.host}:{self.port}",
                timeout, exc,
            ) from exc
        finally:
            if tmp_stage:
                self.run(self._cmd("rm_dir", path=tmp_stage), timeout=15,
                         sudo=True, internal=True)

    def _download_dir(self, sftp, remote_dir: str, local_dir: str,
                      pattern: str = None, timeout: int = 300,
                      display_remote: str = None) -> dict:
        """Recursively download a remote directory."""
        if pattern:
            pat = re.compile(pattern)
        display = display_remote or remote_dir

        total = 0
        errors = []

        def recurse(remote, local, depth=0):
            nonlocal total
            if depth > self._MAX_RECURSE_DEPTH:
                errors.append(f"  x {remote}: max recursion depth exceeded")
                return
            if not local.exists():
                local.mkdir(parents=True, exist_ok=True)
            entries = sftp.listdir_attr(remote)
            for entry in entries:
                name = entry.filename
                if name in (".", ".."):
                    continue
                rpath = f"{remote}/{name}"
                lpath = local / name
                is_dir = (entry.st_mode & 0o170000) == 0o040000
                if is_dir:
                    recurse(rpath, lpath, depth + 1)
                else:
                    if pattern and not pat.search(name):
                        continue
                    if self._path_blocked(rpath, "remote"):
                        errors.append(f"  x {rpath}: path not allowed")
                        continue
                    lpath.parent.mkdir(parents=True, exist_ok=True)
                    sftp.get(rpath, str(lpath))
                    total += 1

        local_path = Path(local_dir)
        if not local_path.exists():
            local_path.mkdir(parents=True, exist_ok=True)
        recurse(remote_dir, local_path)
        sftp.close()

        lines = [f"Downloaded {total} files from {display} -> {local_dir}\n"]
        if errors:
            lines.append("Errors:\n" + "\n".join(errors))
        return {
            "stdout": "".join(lines),
            "stderr": "",
            "code": 1 if errors else 0,
            "remote_path": display,
            "local_path": str(local_dir),
            "count": total,
        }

    def _path_blocked(self, path: str, kind: str) -> bool:
        """Return True when path falls OUTSIDE the configured allow-list.

        Remote paths are compared lexically with posixpath.normpath (they
        live on the server; resolving them locally would be wrong, e.g.
        '/var/log' -> 'C:\\var\\log' on Windows). Prefix matching is done
        with a directory boundary so '/allowed/dir' does not also permit
        '/allowed/dir-evil'.
        """
        allowed = self._allowed_paths.get(kind, [])
        if not allowed:
            return False
        if kind == "remote":
            resolved = posixpath.normpath(str(path).replace("\\", "/"))
            bases = [posixpath.normpath(str(p).replace("\\", "/")) for p in allowed]
        else:
            resolved = str(Path(path).resolve())
            bases = [str(Path(p).resolve()) for p in allowed]
        fold = str.casefold if os.sep == "\\" else (lambda s: s)
        for base in bases:
            r, b = fold(resolved), fold(base)
            if r == b:
                return False
            b = b.rstrip("/")
            if b and (r + "/").startswith(b + "/"):
                return False
        return True

    def upload_file(self, local_path: str, remote_path: str, timeout: int = 300,
                    overwrite: bool = True, sudo: bool = False,
                    executable: bool = False) -> dict:
        """Upload one local file to an explicit remote path via SFTP."""
        self.connect()
        if self._path_blocked(local_path, "local"):
            raise ValueError(f"Local path not allowed: {local_path}")
        if self._path_blocked(remote_path, "remote"):
            raise ValueError(f"Remote path not allowed: {remote_path}")
        source = Path(local_path)
        if not source.is_file():
            raise FileNotFoundError(f"Local file not found: {local_path}")
        if not overwrite:
            check = self.run(self._cmd("file_exists", path=remote_path), timeout=5,
                             sudo=sudo, internal=True)
            if check["code"] == 0:
                raise FileExistsError(f"Remote file already exists: {remote_path}")
        remote_parent = str(Path(remote_path).parent)
        self.run(self._cmd("mkdir", path=remote_parent), timeout=10, sudo=sudo,
                 internal=True)
        try:
            sftp = self._sftp(timeout=timeout)
            if sudo:
                tmp_prefix = self._cmd("tmp_prefix")
                tmp_path = f"{tmp_prefix}/.staging_{uuid.uuid4().hex[:8]}_{source.name}"
                sftp.put(str(source), tmp_path)
                sftp.close()
                installed = self.run(
                    self._cmd("install", tmp=tmp_path, target=remote_path),
                    timeout=15, sudo=True, internal=True,
                )
                if installed["code"] != 0:
                    return installed
                # The ``install`` template already applies the ownership/mode
                # semantics (preserve on overwrite, parent-owner + 755 on
                # create); a follow-up chmod would clobber the preserved mode.
            else:
                sftp.put(str(source), remote_path)
                if executable and self._is_unix():
                    sftp.chmod(remote_path, 0o755)
                sftp.close()
        except (TimeoutError, socket.timeout) as exc:
            raise config._operation_failure(
                "SFTP upload", f"{local_path} -> {remote_path}", timeout, exc,
            ) from exc
        return {
            "stdout": f"Uploaded {local_path} -> {remote_path}\n",
            "stderr": "", "code": 0, "remote_path": remote_path,
        }

    def upload_script(self, local_path: str, script_name: str = None,
                      run_immediately: bool = False, timeout: int = 300,
                      overwrite: bool = True, sudo: bool = False) -> dict:
        """Upload a local script to the remote scripts_dir, optionally run immediately.

        Args:
            sudo: if True, write the script as root via stage-via-/tmp
                  (SFTP -> tmp -> sudo install, which sets owner/mode).
                  When run_immediately=True, also execute the script as root.
        """
        if not script_name:
            script_name = Path(local_path).name
        script_name = config._safe_relpath(script_name, "script_name")
        remote_path = f"{self.scripts_dir}/{script_name}"
        result = self.upload_file(local_path, remote_path, timeout, overwrite, sudo, executable=True)
        result["stdout"] = f"Script uploaded to {remote_path}\n" if result["code"] == 0 else result["stdout"]

        if run_immediately:
            run_cmd = self._cmd("run_script", path=remote_path)
            run_result = self.run(run_cmd, timeout=timeout, sudo=sudo)
            result["run_stdout"] = run_result["stdout"]
            result["run_stderr"] = run_result["stderr"]
            result["run_code"] = run_result["code"]
            result["code"] = run_result["code"]

        return result

    def download_file(self, remote_path: str, local_path: str, timeout: int = 300,
                      overwrite: bool = True, sudo: bool = False) -> dict:
        """Download one remote file to an explicit local path via SFTP.

        Counterpart of upload_file: same allow-list checks, sudo staging
        and timeout diagnostics, all provided by the download() primitive.
        """
        return self.download(
            remote_path, local_path, timeout=timeout,
            overwrite=overwrite, sudo=sudo,
        )

    def download_script(self, script_name: str, local_path: str, timeout: int = 300,
                        overwrite: bool = True, sudo: bool = False) -> dict:
        """Download a script from scripts_dir, reusing the single-file downloader."""
        script_name = config._safe_relpath(script_name, "script_name")
        return self.download_file(
            f"{self.scripts_dir}/{script_name}", local_path, timeout=timeout,
            overwrite=overwrite, sudo=sudo,
        )

    def upload_all_scripts(self, sudo: bool = False, overwrite: bool = True) -> dict:
        """Upload all scripts referenced by alias 'script' fields.

        Args:
            sudo: if True, uploads via stage-via-/tmp + sudo mv (for root-owned dirs).
            overwrite: if False, skip files that already exist on remote (default True).
        """
        script_aliases = [a for a in self.aliases if a.get("script")]
        if not script_aliases:
            return {"stdout": "No alias with 'script' field found.\n", "stderr": "", "code": 0}

        msg, fail = [], []
        seen_hashes = {}
        base = self._scripts_base()
        for a in script_aliases:
            src = (base / a["script"]).resolve()
            if not src.is_file():
                fail.append(f"  x {a['script']}: file not found at {src}")
                continue
            content_hash = hashlib.md5(src.read_bytes()).hexdigest()
            if content_hash in seen_hashes:
                prev_alias = seen_hashes[content_hash]
                fail.append(f"  x {a['script']}: duplicate content of {prev_alias}")
                continue
            seen_hashes[content_hash] = a["name"]
            remote_name = src.name
            if src.is_relative_to(base):
                rel = src.relative_to(base).as_posix()
                remote = f"{self.scripts_dir}/{config._safe_relpath(rel, 'script')}"
            else:
                remote = f"{self.scripts_dir}/external/{config._safe_relpath(remote_name, 'script')}"
            try:
                result = self.upload_file(
                    str(src), remote, timeout=300, overwrite=overwrite,
                    sudo=sudo, executable=True,
                )
                if result["code"] == 0:
                    msg.append(f"  + {remote}")
                else:
                    fail.append(
                        f"  x {a['script']}: upload failed: "
                        f"{result.get('stderr', result.get('stdout', 'unknown error'))[:80]}"
                    )
            except Exception as exc:
                fail.append(f"  x {a['script']}: {exc}")

        out = f"Upload done ({len(msg)}/{len(script_aliases)})\n"
        out += "\n".join(msg + fail) + "\n"
        return {"stdout": out, "stderr": "", "code": 0 if not fail else 1}

    def list_scripts(self, sudo: bool = False) -> dict:
        """List uploaded scripts on the remote server"""
        self.connect()
        return self.run(self._cmd("list_dir", path=self.scripts_dir),
                        timeout=30, sudo=sudo, internal=True)

    def run_script(self, script_name: str, timeout: int = 300, sudo: bool = False, stream_cb: Any = None) -> dict:
        """Run an already-uploaded script.

        Args:
            script_name: file name under scripts_dir
            timeout: command timeout in seconds
            sudo: if True, execute as root (requires sudo_password configured)
            stream_cb: optional callback(chunk: str, is_stderr: bool) for real-time output
        """
        self.connect()
        script_name = config._safe_relpath(script_name, "script_name")
        remote_path = f"{self.scripts_dir}/{script_name}"
        return self.run(self._cmd("run_script", path=remote_path),
                        timeout=timeout, sudo=sudo, stream_cb=stream_cb,
                        internal=True)

    # ── Text file I/O (SFTP, no shell quoting) ────────────────────

    def _sftp(self, timeout: int = 30):
        sftp = paramiko.SFTPClient.from_transport(self._client.get_transport())
        sftp.get_channel().settimeout(timeout)
        return sftp

    def _remote_put_bytes(self, remote_path: str, data: bytes,
                          mode: int = None, append: bool = False):
        """Create, overwrite, or append a small remote file over SFTP.

        ``mode`` applies only to newly created files; existing files keep
        their current owner and mode.
        """
        self.run(self._cmd("mkdir", path=posixpath.dirname(remote_path)),
                 timeout=10, internal=True)
        sftp = self._sftp(timeout=self.timeout)
        try:
            try:
                sftp.stat(remote_path)
                existed = True
            except IOError:
                existed = False
            with sftp.open(remote_path, "ab" if append else "wb") as fh:
                fh.write(data)
            if mode is not None and not existed:
                try:
                    sftp.chmod(remote_path, mode)
                except IOError:
                    pass  # e.g. Windows SFTP servers without chmod
        finally:
            sftp.close()

    def read_file(self, remote_path: str, offset: int = 0,
                  max_bytes: int = 65536, sudo: bool = False) -> dict:
        """Read a slice of a remote TEXT file over SFTP.

        Byte-offset paging lets a caller walk a large log without
        downloading it; binary content is rejected so the caller is routed
        to ``download_file`` instead of receiving replacement characters.

        Args:
            offset: byte offset to start at (default 0)
            max_bytes: maximum bytes to return (default 65536, cap 1 MiB)
            sudo: read root-owned files by staging through /tmp
        """
        self.connect()
        if self._path_blocked(remote_path, "remote"):
            raise ValueError(f"Remote path not allowed: {remote_path}")
        offset = max(0, int(offset))
        max_bytes = int(max_bytes) or 65536
        if max_bytes > self.READ_FILE_MAX_BYTES:
            max_bytes = self.READ_FILE_MAX_BYTES

        actual = remote_path
        tmp_stage = None
        if sudo:
            tmp_prefix = self._cmd("tmp_prefix")
            tmp_stage = f"{tmp_prefix}/.rf_stage_{uuid.uuid4().hex[:8]}"
            stage = self.run(self._cmd("cp_r", src=remote_path, dst=tmp_stage),
                             timeout=30, sudo=True, internal=True)
            if stage["code"] != 0:
                raise RuntimeError(
                    f"sudo stage failed: {stage['stderr'].strip()[:200]}")
            if self._is_unix():
                self.run(self._cmd("chown", user=self.user, path=tmp_stage),
                         timeout=10, sudo=True, internal=True)
            actual = tmp_stage
        try:
            sftp = self._sftp(timeout=self.timeout)
            try:
                size = sftp.stat(actual).st_size
                with sftp.open(actual, "rb") as fh:
                    fh.seek(offset)
                    data = fh.read(max_bytes)
            finally:
                sftp.close()
        except (TimeoutError, socket.timeout) as exc:
            raise config._operation_failure(
                "SFTP read", f"{remote_path} from {self.user}@{self.host}:{self.port}",
                self.timeout, exc,
            ) from exc
        finally:
            if tmp_stage:
                self.run(self._cmd("rm_dir", path=tmp_stage), timeout=15,
                         sudo=True, internal=True)

        if b"\x00" in data:
            raise ValueError(
                f"Binary content (NUL byte) in {remote_path}; "
                "use ssh_download_file instead of ssh_read_file")
        end = offset + len(data)
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            if end < size:
                # Slice cut a multi-byte character in half; dropping the
                # ragged tail is safe, the next page re-reads it whole.
                text = data.decode("utf-8", errors="ignore")
            else:
                raise ValueError(
                    f"{remote_path} is not valid UTF-8 text; "
                    "use ssh_download_file instead of ssh_read_file")
        return {
            "stdout": text, "stderr": "", "code": 0,
            "size": size, "offset": offset, "next_offset": end,
            "eof": end >= size,
        }

    def write_file(self, remote_path: str, content: str,
                   append: bool = False, sudo: bool = False) -> dict:
        """Write or append TEXT content to a remote file over SFTP.

        Unlike ``upload_file`` this takes the content itself (UTF-8), so a
        caller can create small files without staging a local temp file and
        without shell-quoting hazards. Overwriting keeps the existing
        file's mode/owner; a new file gets 0644 (sudo writes go through the
        stage-via-/tmp install path instead).
        """
        self.connect()
        if self._path_blocked(remote_path, "remote"):
            raise ValueError(f"Remote path not allowed: {remote_path}")
        data = content.encode("utf-8")

        if not sudo:
            self._remote_put_bytes(remote_path, data, mode=0o644,
                                   append=append)
            return {
                "stdout": f"Wrote {len(data)} bytes -> {remote_path}\n",
                "stderr": "", "code": 0,
                "remote_path": remote_path, "bytes": len(data),
            }

        # sudo: append needs the old content; read it as root first.
        if append:
            existing = self.run(
                f"cat -- {shlex.quote(remote_path)} 2>/dev/null || true",
                timeout=60, sudo=True, internal=True)
            if existing["code"] == 0 and existing["stdout"]:
                data = existing["stdout"].encode("utf-8") + data
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name
            tmp.write(data)
        try:
            result = self.upload_file(tmp_path, remote_path, timeout=120,
                                      overwrite=True, sudo=True)
        finally:
            os.unlink(tmp_path)
        if result["code"] == 0:
            result["stdout"] = f"Wrote {len(data)} bytes -> {remote_path}\n"
            result["bytes"] = len(data)
        return result
