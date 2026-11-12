"""Compatibility surface of the ssh_client package after the domain split.

The package replaced a single module; every public name the module exposed
(ADR-0001) must keep resolving on the package, and runtime-rebindable config
names must resolve LIVE (against ssh_client.config) rather than as an import
-time snapshot, exactly like the old flat module.
"""
from pathlib import Path

import pytest

import ssh_client

# Public symbols defined by the old ssh_client.py (imports excluded).
OLD_PUBLIC_NAMES = [
    "SCRIPT_DIR", "CONFIG_PATH", "KNOWN_HOSTS_PATH", "HOST_KEY_MODES",
    "SERVERS_DIR", "CMD_TEMPLATES", "global_config",
    "load_yaml", "load_global_config", "unmangle_msys_argv",
    "SSHOperationError", "SSHConnection", "ConnectionPool", "pool",
]


@pytest.mark.parametrize("name", OLD_PUBLIC_NAMES)
def test_old_module_surface_still_importable(name):
    assert getattr(ssh_client, name) is not None
    assert name in dir(ssh_client)


def test_rebindable_config_names_resolve_live(monkeypatch):
    probe = Path("/tmp/servers-probe")
    monkeypatch.setattr(ssh_client.config, "SERVERS_DIR", probe)
    assert ssh_client.SERVERS_DIR == probe
    assert getattr(ssh_client, "SERVERS_DIR") == probe


def test_star_import_covers_old_surface():
    ns = {}
    exec("from ssh_client import *", ns)
    missing = [name for name in OLD_PUBLIC_NAMES if name not in ns]
    assert not missing, f"missing from star import: {missing}"


def test_rebinding_on_old_path_updates_config_single_source():
    # Old flat-module users could rebind ssh_client.SERVERS_DIR; the
    # package must forward the write so the config module (the single
    # source of truth the pool reads) sees the new value too.
    probe = Path("/tmp/servers-probe2")
    orig = ssh_client.config.SERVERS_DIR
    try:
        ssh_client.SERVERS_DIR = probe
        assert ssh_client.config.SERVERS_DIR == probe
        assert ssh_client.SERVERS_DIR == probe
    finally:
        ssh_client.config.SERVERS_DIR = orig


def test_unknown_attribute_raises():
    with pytest.raises(AttributeError):
        ssh_client.not_a_real_symbol
