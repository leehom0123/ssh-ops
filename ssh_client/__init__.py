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
# (and tests) may rebind them at runtime, so they are resolved lazily
# against the config module instead of snapshotted here.
_CONFIG_ATTRS = frozenset((
    "SCRIPT_DIR", "CONFIG_PATH", "KNOWN_HOSTS_PATH", "HOST_KEY_MODES",
    "SERVERS_DIR", "CMD_TEMPLATES", "global_config",
))


def __getattr__(name):
    if name in _CONFIG_ATTRS:
        return getattr(config, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(set(globals()) | _CONFIG_ATTRS)
