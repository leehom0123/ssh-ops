"""Server-config domain: the connection pool and local YAML management.

One YAML file per server under ``config.SERVERS_DIR``; the pool caches one
SSHConnection per server name. create/update/copy/delete here are the
only functions that mutate local config files.
"""
import os
import re
import sys
import threading
import uuid
from pathlib import Path
from typing import Dict

import yaml

from . import config as conf
from .connection import SSHConnection


class ConnectionPool:
    """SSH connection pool — manages connection reuse by server name"""

    def __init__(self):
        self._pool: Dict[str, SSHConnection] = {}
        self._lock = threading.Lock()

    def get(self, server_name: str) -> SSHConnection:
        """Get or create an SSHConnection (lazy — call conn.connect() on first use).

        The whole build is serialised so concurrent callers for the same
        server can never create two SSHConnection objects (each would hold
        its own transport). The returned connection supports concurrent
        commands on independent channels.
        """
        key, _ = self._config_target(server_name)
        with self._lock:
            if key in self._pool:
                return self._pool[key]
            yml_path = self._resolve_config_path(key)
            data = self._load_config(key)
            conn = SSHConnection(data["server"], data.get("aliases", []), yml_path)
            self._pool[key] = conn
            return conn

    def create_server(self, server_name: str, config: dict) -> dict:
        """Create a server YAML file without overwriting an existing config."""
        key, config_path = self._config_target(server_name)
        if config_path.exists():
            raise FileExistsError(f"Server config already exists: {config_path}")
        self._validate_server_config(config)
        self._write_config(config_path, config)
        self._discard(key)
        return {"name": key, "path": str(config_path), "created": True}

    def update_server(self, server_name: str, config: dict, replace: bool = False) -> dict:
        """Recursively merge a server config patch, or replace the whole config."""
        key, config_path = self._config_target(server_name)
        if not config_path.exists():
            raise FileNotFoundError(f"Server config not found: {config_path}")
        current = conf.load_yaml(str(config_path))
        updated = config if replace else self._deep_merge(current, config)
        self._validate_server_config(updated)
        self._write_config(config_path, updated)
        self._discard(key)
        return {
            "name": key,
            "path": str(config_path),
            "updated": True,
            "replace": replace,
        }

    def copy_server(self, source_server: str, target_server: str) -> dict:
        """Copy a server YAML file to a new name without overwriting."""
        source_key, source_path = self._config_target(source_server)
        target_key, target_path = self._config_target(target_server)
        if not source_path.exists():
            raise FileNotFoundError(f"Server config not found: {source_path}")
        if target_path.exists():
            raise FileExistsError(f"Server config already exists: {target_path}")
        config = conf.load_yaml(str(source_path))
        self._validate_server_config(config)
        self._copy_config_file(source_path, target_path)
        self._discard(target_key)
        return {
            "source": source_key,
            "name": target_key,
            "path": str(target_path),
            "copied": True,
        }

    def delete_server(self, server_name: str) -> dict:
        """Delete one server YAML file."""
        key, config_path = self._config_target(server_name)
        if not config_path.exists():
            raise FileNotFoundError(f"Server config not found: {config_path}")
        config_path.unlink()
        self._discard(key)
        return {"name": key, "path": str(config_path), "deleted": True}

    @staticmethod
    def _config_target(server_name: str):
        if not isinstance(server_name, str):
            raise ValueError("Server name must be a string")
        name = server_name.strip()
        if name.lower().endswith((".yml", ".yaml")):
            name = name.rsplit(".", 1)[0]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
            raise ValueError(
                "Invalid server name; use letters, numbers, dot, underscore, or hyphen"
            )
        key = name.lower()
        return key, conf.SERVERS_DIR / f"{key}.yml"

    @staticmethod
    def _validate_server_config(config: dict):
        if not isinstance(config, dict):
            raise ValueError("Server config must be an object")
        server = config.get("server")
        if not isinstance(server, dict):
            raise ValueError("Server config must contain a 'server' object")
        if not config.get("extends"):
            for field in ("host", "user"):
                if not isinstance(server.get(field), str) or not server[field].strip():
                    raise ValueError(
                        f"Server config must contain a non-empty server.{field}"
                    )
        aliases = config.get("aliases")
        if aliases is not None and not isinstance(aliases, list):
            raise ValueError("Server config 'aliases' must be an array")
        if aliases is not None:
            for index, alias in enumerate(aliases):
                if not isinstance(alias, dict):
                    raise ValueError(f"Alias at index {index} must be an object")
                if not isinstance(alias.get("name"), str) or not alias["name"].strip():
                    raise ValueError(f"Alias at index {index} must have a non-empty name")

    @staticmethod
    def _deep_merge(current: dict, patch: dict) -> dict:
        if not isinstance(patch, dict):
            raise ValueError("Server config patch must be an object")
        merged = dict(current)
        for key, value in patch.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = ConnectionPool._deep_merge(merged[key], value)
            else:
                merged[key] = value
        return merged

    @staticmethod
    def _atomic_write(target_path: Path, write_fn, mode: int):
        """Write through a temp file and atomically replace ``target_path``."""
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = target_path.with_name(f".{target_path.name}.{uuid.uuid4().hex}.tmp")
        try:
            write_fn(temp_path)
            temp_path.chmod(mode)
            os.replace(temp_path, target_path)
        finally:
            if temp_path.exists():
                temp_path.unlink()

    @classmethod
    def _write_config(cls, config_path: Path, config: dict, mode: int = None):
        text = yaml.safe_dump(
            config,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )
        file_mode = mode
        if file_mode is None:
            file_mode = (
                config_path.stat().st_mode & 0o777
                if config_path.exists()
                else 0o600
            )
        cls._atomic_write(
            config_path,
            lambda temp: temp.write_text(text, encoding="utf-8"),
            file_mode,
        )

    @classmethod
    def _copy_config_file(cls, source_path: Path, target_path: Path):
        data = source_path.read_bytes()
        cls._atomic_write(
            target_path,
            lambda temp: temp.write_bytes(data),
            source_path.stat().st_mode & 0o777,
        )

    def _discard(self, key: str):
        with self._lock:
            conn = self._pool.pop(key, None)
        if conn is not None:
            conn.close()

    def close_all(self):
        """Close and remove all cached connections."""
        with self._lock:
            connections = list(self._pool.values())
            self._pool.clear()
        for conn in connections:
            conn.close()

    def _resolve_config_path(self, name: str) -> str:
        _, config_path = self._config_target(name)
        if not config_path.exists():
            raise FileNotFoundError(f"Server config not found: {config_path}")
        return str(config_path)

    def _load_config(self, name: str) -> dict:
        config_path = conf.SERVERS_DIR / f"{name}.yml"
        if not config_path.exists():
            raise FileNotFoundError(f"Server config not found: {config_path}")
        cfg = conf.load_yaml(str(config_path))

        # Handle 'extends' inheritance
        extends = cfg.pop("extends", [])
        if extends:
            base_cfg = dict(cfg)
            for ext_file in extends:
                ext_path = config_path.parent / ext_file
                if not ext_path.exists():
                    print(f"Warning: extends file not found: {ext_path}", file=sys.stderr)
                    continue
                ext_cfg = conf.load_yaml(str(ext_path))
                # Merge server fields: base + local overrides
                ext_server = ext_cfg.get("server", {})
                if ext_server:
                    merged_server = {**ext_server, **base_cfg.get("server", {})}
                    base_cfg["server"] = merged_server
                # Merge aliases: local takes priority
                ext_aliases = ext_cfg.get("aliases", [])
                if ext_aliases:
                    existing_names = {a["name"] for a in base_cfg.get("aliases", [])}
                    base_cfg["aliases"] = [
                        a for a in ext_aliases if a.get("name") not in existing_names
                    ] + base_cfg.get("aliases", [])
                # Merge security fields
                for key in ["whitelist", "blacklist", "command_template",
                            "allowed_local_paths", "allowed_remote_paths", "scripts_dir"]:
                    if key not in base_cfg and key in ext_cfg:
                        base_cfg[key] = ext_cfg[key]
                # Merge proxy config
                if "proxy" in ext_cfg and "proxy" not in base_cfg:
                    base_cfg["proxy"] = ext_cfg["proxy"]
            cfg = base_cfg

        return cfg

    def list_servers(self) -> list:
        """List all configured servers"""
        if not conf.SERVERS_DIR.exists():
            return []
        servers = []
        for f in sorted(conf.SERVERS_DIR.glob("*.yml")):
            try:
                name = f.stem
                cfg = self._load_config(name)
                srv = cfg["server"]
                info = {
                    "name": name,
                    "host": srv["host"],
                    "port": srv.get("port", 22),
                    "user": srv["user"],
                    "display": srv.get("name", name),
                    "desc": srv.get("desc", ""),
                    "system": srv.get("system", ""),
                    "group": srv.get("group", name),
                    "shell": srv.get("shell", "bash"),
                }
                aliases = cfg.get("aliases", [])
                if aliases:
                    info["aliases"] = len(aliases)
                servers.append(info)
            except Exception as e:
                servers.append({"name": f.stem, "error": str(e)})
        servers.sort(key=lambda s: (s.get("group", ""), s.get("name", "")))
        for i, srv in enumerate(servers, start=1):
            srv["index"] = i
        return servers

    @classmethod
    def _to_key(cls, name: str) -> str:
        """Normalise a server name to its pool key (see ``_config_target``)."""
        return cls._config_target(name)[0]


# Global connection pool instance
pool = ConnectionPool()
