"""Regressions for host-key binding on the SOCKS proxy path (pytest).

The probe connection verifies a key, but the authenticating transport must
verify *its own* negotiated key before credentials are sent; otherwise a
server (or an attacker on the proxy path) could present an unverified key
type on the second connection and capture the password.
"""
import paramiko
import pytest

from ssh_client import SSHConnection
from ssh_client import connection as connmod

SERVER_KEY = paramiko.RSAKey.generate(1024)
ATTACKER_KEY = paramiko.RSAKey.generate(1024)


class FakeTransport:
    """Transport double presenting a fixed key, recording the call order."""

    instances = []

    def __init__(self, sock, key, events):
        self.key = key
        self.events = events
        self.banner_timeout = None
        self.auth_timeout = None

    def start_client(self):
        self.events.append("negotiate")

    def get_remote_server_key(self):
        self.events.append("hostkey")
        return self.key

    def auth_password(self, username, password):
        self.events.append(("password", username, password))

    def auth_publickey(self, username, key):
        self.events.append(("pubkey", username))

    def set_keepalive(self, n):
        pass

    def close(self):
        pass


def _conn(tmp_path, monkeypatch, key, **cfg):
    monkeypatch.setattr(connmod.config, "KNOWN_HOSTS_PATH",
                        tmp_path / "known_hosts")
    conn = SSHConnection({"host": "example.test", "user": "deploy", **cfg})
    conn._make_socket = lambda proxy: object()
    events = []
    monkeypatch.setattr(paramiko, "Transport",
                        lambda sock: FakeTransport(sock, key, events))
    return conn, events


def test_proxy_password_not_sent_when_auth_key_differs_from_probe(tmp_path, monkeypatch):
    # Probe records the real key; the authenticating transport then presents
    # a different rsa key -> reject and, crucially, never send the password.
    conn, events = _conn(tmp_path, monkeypatch, ATTACKER_KEY, password="pw")
    conn._check_or_record_host_key(SERVER_KEY)
    events.clear()
    with pytest.raises(paramiko.SSHException):
        conn._connect_proxy_with({"host": "p", "port": "1"})
    assert events == ["negotiate", "hostkey"]  # no ("password", ...) entry


def test_proxy_authenticates_when_key_matches_probe(tmp_path, monkeypatch):
    conn, events = _conn(tmp_path, monkeypatch, SERVER_KEY, password="pw")
    conn._check_or_record_host_key(SERVER_KEY)
    events.clear()
    conn._connect_proxy_with({"host": "p", "port": "1"})
    assert events[:2] == ["negotiate", "hostkey"]
    assert ("password", "deploy", "pw") in events


def test_proxy_tofu_records_new_key_type_before_auth(tmp_path, monkeypatch):
    # First use over proxy: no stored entry. The presented key is recorded
    # during the same verification call, before authentication proceeds.
    conn, events = _conn(tmp_path, monkeypatch, SERVER_KEY, password="pw")
    conn._connect_proxy_with({"host": "p", "port": "1"})
    assert ("password", "deploy", "pw") in events
    stored = connmod.config.KNOWN_HOSTS_PATH
    assert stored.exists() and SERVER_KEY.get_name() in stored.read_text()


def test_proxy_strict_refuses_unknown_key_without_auth(tmp_path, monkeypatch):
    conn, events = _conn(tmp_path, monkeypatch, SERVER_KEY, password="pw",
                         host_key_checking="strict")
    with pytest.raises(paramiko.SSHException):
        conn._connect_proxy_with({"host": "p", "port": "1"})
    assert not any(isinstance(e, tuple) for e in events)


def test_proxy_insecure_skips_verification_and_authenticates(tmp_path, monkeypatch):
    conn, events = _conn(tmp_path, monkeypatch, ATTACKER_KEY, password="pw",
                         host_key_checking="insecure")
    conn._connect_proxy_with({"host": "p", "port": "1"})
    assert ("password", "deploy", "pw") in events
