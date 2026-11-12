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
    CONFIG_PATH,
    SCRIPT_DIR,
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
