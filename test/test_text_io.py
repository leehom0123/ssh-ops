#!/usr/bin/env python3
"""Unit tests for the SFTP text-file primitives (ssh_read_file/ssh_write_file).

Offline by default: paramiko's SFTPClient is mocked. The two `live`-marked
tests round-trip through a real server (SSH_TEST_SERVER gated).
"""
import io
import json
import pytest
from unittest.mock import MagicMock, patch

from ssh_client import SSHConnection


def _conn(cfg=None):
    conn = SSHConnection({"host": "example.test", "user": "tester",
                          "jobs_dir": "/opt/scripts/.jobs", **(cfg or {})})
    conn.connect = MagicMock()
    conn._client = MagicMock()
    conn.run = MagicMock(return_value={"stdout": "", "stderr": "", "code": 0})
    conn.scripts_dir = "/opt/scripts"
    return conn


def _fake_sftp(stat_size=100, read_data=b"hello", stat_raises=False):
    """A paramiko.SFTPClient stand-in wired into patch()."""
    sftp = MagicMock()
    attr = MagicMock()
    attr.st_size = stat_size
    if stat_raises:
        sftp.stat.side_effect = IOError("no such file")
    else:
        sftp.stat.return_value = attr
    fh = MagicMock()
    fh.read.return_value = read_data
    sftp.open.return_value.__enter__.return_value = fh
    return sftp


# ── read_file ─────────────────────────────────────────────────────
def test_read_file_returns_slice_and_paging_metadata():
    conn = _conn()
    sftp = _fake_sftp(stat_size=100, read_data=b"hello")
    with patch("ssh_client.paramiko.SFTPClient") as cls:
        cls.from_transport.return_value = sftp
        result = conn.read_file("/var/log/app.log", offset=10, max_bytes=5)
    sftp.open.return_value.__enter__.return_value.seek.assert_called_with(10)
    assert result["stdout"] == "hello"
    assert result["offset"] == 10 and result["next_offset"] == 15
    assert result["size"] == 100 and result["eof"] is False


def test_read_file_eof_at_end():
    conn = _conn()
    sftp = _fake_sftp(stat_size=5, read_data=b"hello")
    with patch("ssh_client.paramiko.SFTPClient") as cls:
        cls.from_transport.return_value = sftp
        result = conn.read_file("/f")
    assert result["eof"] is True and result["next_offset"] == 5


def test_read_file_rejects_binary():
    conn = _conn()
    sftp = _fake_sftp(stat_size=8, read_data=b"a\x00b")
    with patch("ssh_client.paramiko.SFTPClient") as cls:
        cls.from_transport.return_value = sftp
        with pytest.raises(ValueError, match="Binary content"):
            conn.read_file("/f")


def test_read_file_rejects_non_utf8_at_eof():
    conn = _conn()
    sftp = _fake_sftp(stat_size=2, read_data=b"\xff\xfe")
    with patch("ssh_client.paramiko.SFTPClient") as cls:
        cls.from_transport.return_value = sftp
        with pytest.raises(ValueError, match="not valid UTF-8"):
            conn.read_file("/f")


def test_read_file_ignores_ragged_tail_when_truncated():
    # Slice cut a multi-byte char in half mid-file: drop the tail instead
    # of rejecting the whole (textual) file.
    conn = _conn()
    sftp = _fake_sftp(stat_size=100, read_data="中a".encode()[:-1])
    with patch("ssh_client.paramiko.SFTPClient") as cls:
        cls.from_transport.return_value = sftp
        result = conn.read_file("/f")
    assert result["stdout"] == "中" and result["eof"] is False


def test_read_file_caps_max_bytes():
    conn = _conn()
    sftp = _fake_sftp()
    with patch("ssh_client.paramiko.SFTPClient") as cls:
        cls.from_transport.return_value = sftp
        conn.read_file("/f", max_bytes=10 ** 9)
    sftp.open.return_value.__enter__.return_value.read.assert_called_with(
        SSHConnection.READ_FILE_MAX_BYTES)


def test_read_file_respects_remote_allow_list():
    conn = _conn()
    conn._allowed_paths = {"local": [], "remote": ["/srv/app"]}
    with pytest.raises(ValueError, match="Remote path not allowed"):
        conn.read_file("/etc/shadow")


def test_read_file_sudo_stages_via_tmp():
    conn = _conn({"sudo_password": "pw"})
    sftp = _fake_sftp()
    with patch("ssh_client.paramiko.SFTPClient") as cls:
        cls.from_transport.return_value = sftp
        conn.read_file("/root/secret", sudo=True)
    cmds = [c.args[0] for c in conn.run.call_args_list]
    assert any("cp -r" in c for c in cmds), cmds      # stage
    assert any("chown" in c for c in cmds), cmds      # hand to sftp user
    assert any("rm -rf" in c for c in cmds), cmds     # cleanup
    for c in conn.run.call_args_list:
        assert c.kwargs.get("internal") is True


# ── write_file ────────────────────────────────────────────────────
def test_write_file_creates_with_open_mode_and_chmod():
    conn = _conn()
    sftp = _fake_sftp(stat_raises=True)
    with patch("ssh_client.paramiko.SFTPClient") as cls:
        cls.from_transport.return_value = sftp
        result = conn.write_file("/srv/new.conf", "cfg=1")
    sftp.open.assert_called_once_with("/srv/new.conf", "wb")
    sftp.chmod.assert_called_once_with("/srv/new.conf", 0o644)
    assert result["code"] == 0 and result["bytes"] == 5


def test_write_file_overwrite_keeps_existing_mode():
    conn = _conn()
    sftp = _fake_sftp(stat_size=1)  # stat succeeds -> file existed
    fh = sftp.open.return_value.__enter__.return_value
    with patch("ssh_client.paramiko.SFTPClient") as cls:
        cls.from_transport.return_value = sftp
        conn.write_file("/srv/old.conf", "x")
    fh.write.assert_called_once_with(b"x")
    sftp.chmod.assert_not_called()


def test_write_file_append_uses_append_mode():
    conn = _conn()
    sftp = _fake_sftp(stat_size=1)
    with patch("ssh_client.paramiko.SFTPClient") as cls:
        cls.from_transport.return_value = sftp
        conn.write_file("/srv/log", "more", append=True)
    sftp.open.assert_called_once_with("/srv/log", "ab")


def test_write_file_sudo_goes_through_staged_upload():
    conn = _conn({"sudo_password": "pw"})
    conn.upload_file = MagicMock(return_value={
        "stdout": "", "stderr": "", "code": 0})
    result = conn.write_file("/etc/motd", "hello", sudo=True)
    conn.upload_file.assert_called_once()
    args, kwargs = conn.upload_file.call_args
    local, remote = args[0], args[1]
    assert remote == "/etc/motd"
    assert kwargs["sudo"] is True
    assert result["code"] == 0
    assert "Wrote 5 bytes" in result["stdout"]


def test_write_file_sudo_append_merges_old_content():
    conn = _conn({"sudo_password": "pw"})
    conn.run = MagicMock(return_value={"stdout": "old\n", "stderr": "",
                                       "code": 0})
    captured = {}

    def fake_upload(local, remote, *args, **kwargs):
        with open(local, "rb") as fh:
            captured["data"] = fh.read()
        return {"stdout": "", "stderr": "", "code": 0}

    conn.upload_file = MagicMock(side_effect=fake_upload)
    conn.write_file("/etc/motd", "new\n", append=True, sudo=True)
    assert captured["data"] == b"old\nnew\n"


# ── CLI surface (subprocess, mocked connection via monkeypatched pool) ──
def test_cli_help_lists_new_commands(run_cli):
    out, _, code = run_cli("--help")
    assert code == 0
    for token in ("read-file", "write-file", "job-start", "job-status",
                  "job-kill", "job-list"):
        assert token in out, token


# ── Live round-trip ───────────────────────────────────────────────
@pytest.mark.live
def test_live_write_read_append_roundtrip(live_server):
    import ssh_client
    import uuid
    conn = ssh_client.pool.get(live_server)
    remote = f"{conn.scripts_dir}/.io_test_{uuid.uuid4().hex[:6]}.txt"
    try:
        r1 = conn.write_file(remote, "line1\n")
        assert r1["code"] == 0
        r2 = conn.write_file(remote, "line2\n", append=True)
        assert r2["code"] == 0
        data = conn.read_file(remote)
        assert data["stdout"] == "line1\nline2\n"
        assert data["eof"] is True and data["size"] == 12
        paged = conn.read_file(remote, offset=6, max_bytes=6)
        assert paged["stdout"] == "line2\n" and paged["eof"] is True
    finally:
        conn.run(f"rm -f {remote}", internal=True)


@pytest.mark.live
def test_live_read_file_rejects_binary(live_server):
    import ssh_client
    conn = ssh_client.pool.get(live_server)
    remote = f"{conn.scripts_dir}/.io_test_bin"
    try:
        conn.write_file(remote, "\x00\x01binary\x00")
        with pytest.raises(ValueError, match="Binary content"):
            conn.read_file(remote)
    finally:
        conn.run(f"rm -f {remote}", internal=True)
