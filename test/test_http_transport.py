#!/usr/bin/env python3
"""Tests for the Streamable HTTP transport (mcp_server.py --http).

Offline: no SSH needed; initialize, tools/list and ssh_list_servers all
work against local YAML configs.
"""
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).parent.parent.resolve()


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Client:
    def __init__(self, base, token=None):
        self.base = base
        self.token = token
        self.session = None

    def post(self, msg, expect_status=200, protocol_version=None):
        req = urllib.request.Request(
            self.base, data=json.dumps(msg).encode("utf-8"), method="POST")
        req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        if self.session:
            req.add_header("Mcp-Session-Id", self.session)
        if protocol_version:
            req.add_header("Mcp-Protocol-Version", protocol_version)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read()
                sid = resp.headers.get("Mcp-Session-Id")
                if sid:
                    self.session = sid
                assert resp.status == expect_status, resp.status
                return json.loads(body) if body and expect_status == 200 else None
        except urllib.error.HTTPError as exc:
            assert exc.code == expect_status, f"{exc.code}: {exc.read()[:200]}"
            return None

    def delete(self, expect_status=200):
        req = urllib.request.Request(self.base, method="DELETE")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        if self.session:
            req.add_header("Mcp-Session-Id", self.session)
        try:
            urllib.request.urlopen(req, timeout=10)
        except urllib.error.HTTPError as exc:
            assert exc.code == expect_status, exc.code


@pytest.fixture
def http_server():
    """Spawn one --http mcp_server per test and wait for it to answer."""
    def start(*extra):
        port = _free_port()
        proc = subprocess.Popen(
            [sys.executable, str(SKILL_DIR / "mcp_server.py"),
             "--http", "--port", str(port), *extra],
            cwd=str(SKILL_DIR), stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, text=True, encoding="utf-8")
        deadline = time.time() + 15
        while time.time() < deadline:
            if proc.poll() is not None:
                raise RuntimeError(f"server died: {proc.stderr.read()[:400]}")
            try:
                with socket.create_connection(("127.0.0.1", port), 0.5):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            proc.kill()
            raise RuntimeError("server never listened")
        yield_from = _Client(f"http://127.0.0.1:{port}/mcp")
        return proc, yield_from
    procs = []

    def _start(*extra):
        proc, client = start(*extra)
        procs.append(proc)
        return proc, client
    yield _start
    for p in procs:
        p.terminate()


INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                   "clientInfo": {"name": "pytest", "version": "1"}}}


def _handshake(client):
    resp = client.post(INIT)
    assert resp["result"]["protocolVersion"] == "2025-03-26"
    assert client.session, "initialize must return Mcp-Session-Id"
    # Notifications answer 202 with an empty body.
    client.post({"jsonrpc": "2.0", "method": "notifications/initialized"},
                expect_status=202)


def test_http_initialize_and_tools_list(http_server):
    _, client = http_server()
    _handshake(client)
    resp = client.post({"jsonrpc": "2.0", "id": 2, "method": "tools/list",
                        "params": {}})
    names = {t["name"] for t in resp["result"]["tools"]}
    assert {"ssh_run", "ssh_read_file", "ssh_job_start"} <= names


def test_http_tools_call_and_session_teardown(http_server):
    _, client = http_server()
    _handshake(client)
    resp = client.post({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                        "params": {"name": "ssh_list_servers",
                                   "arguments": {}}})
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert "servers" in payload
    client.delete()
    # The session is gone after DELETE.
    client.post({"jsonrpc": "2.0", "id": 4, "method": "tools/list",
                 "params": {}}, expect_status=404)


def test_http_rejects_requests_without_session(http_server):
    _, client = http_server()
    client.post({"jsonrpc": "2.0", "id": 9, "method": "tools/list",
                 "params": {}}, expect_status=404)


def test_http_rejects_unsupported_protocol_version(http_server):
    _, client = http_server()
    _handshake(client)
    client.post({"jsonrpc": "2.0", "id": 5, "method": "tools/list",
                 "params": {}}, expect_status=400,
                protocol_version="1999-01-01")


def test_http_batch_request(http_server):
    _, client = http_server()
    _handshake(client)
    resp = client.post([{"jsonrpc": "2.0", "id": 6, "method": "ping"},
                        {"jsonrpc": "2.0", "method": "notifications/cancelled",
                         "params": {"requestId": 6}}])
    assert resp == [{"jsonrpc": "2.0", "id": 6, "result": {}}]


def test_http_get_stream_is_optional_405(http_server):
    _, client = http_server()
    _handshake(client)
    req = urllib.request.Request(client.base)
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req, timeout=10)
    assert exc.value.code == 405


def test_http_token_required_and_enforced(http_server):
    _, client = http_server("--token", "sekrit")
    client.token = None
    client.post(INIT, expect_status=401)
    client.token = "sekrit"
    _handshake(client)


def test_http_refuses_public_bind_without_token():
    port = _free_port()
    proc = subprocess.run(
        [sys.executable, str(SKILL_DIR / "mcp_server.py"),
         "--http", "--host", "0.0.0.0", "--port", str(port)],
        cwd=str(SKILL_DIR), capture_output=True, text=True, timeout=30,
        encoding="utf-8")
    assert proc.returncode != 0
    assert "--token" in proc.stderr
