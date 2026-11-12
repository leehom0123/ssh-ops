"""ssh-alias-mcp core, split by domain.

The package keeps the old single-module surface: ``from ssh_client import
pool`` (and the helpers the CLI imports) work exactly as before.

Modules:
    config      global config.yaml, paths, command templates, encoding fixes
    connection  SSHConnection lifecycle and command execution
    transfer    file upload/download and remote text I/O (TransferMixin)
    jobs        background-job state machine (JobStore, JobsMixin)
    pool        ConnectionPool and local server YAML management
"""
import sys as _sys
from types import ModuleType as _ModuleType

from . import config
from .config import (
    SSHOperationError,
    _normalize_path,
    _operation_failure,
    _repair_surrogateescaped_command,
    _safe_relpath,
    load_global_config,
    load_yaml,
    unmangle_msys_argv,
)
from .connection import SSHConnection
from .jobs import JobStore
from .pool import ConnectionPool, pool

# The old single module exposed these as plain attributes, and callers
# may rebind them at runtime; reads AND writes on the package are
# forwarded to the config module so there is one source of truth (the
# old flat module had exactly one binding per name).
_CONFIG_ATTRS = frozenset((
    "SCRIPT_DIR", "CONFIG_PATH", "KNOWN_HOSTS_PATH", "HOST_KEY_MODES",
    "SERVERS_DIR", "CMD_TEMPLATES", "global_config",
))

__all__ = [
    "SSHConnection", "ConnectionPool", "pool", "JobStore", "config",
    "SSHOperationError", "load_yaml", "load_global_config",
    "unmangle_msys_argv",
] + sorted(_CONFIG_ATTRS)


class _CompatModule(_ModuleType):
    def __getattr__(self, name):
        if name in _CONFIG_ATTRS:
            return getattr(config, name)
        raise AttributeError(
            f"module {self.__name__!r} has no attribute {name!r}")

    def __setattr__(self, name, value):
        if name in _CONFIG_ATTRS:
            setattr(config, name, value)
        else:
            super().__setattr__(name, value)

    def __delattr__(self, name):
        # patch.object() on the package restores by deleting when the
        # package dict had no binding; the real binding lives in config.
        if name in _CONFIG_ATTRS:
            delattr(config, name)
        else:
            super().__delattr__(name)

    def __dir__(self):
        return sorted(set(self.__dict__) | _CONFIG_ATTRS)


_sys.modules[__name__].__class__ = _CompatModule
