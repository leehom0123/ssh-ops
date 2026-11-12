---
name: ssh-ops
description: >
  AI-driven server operations via SSH. Run commands, deploy scripts, restart services,
  check logs, upload/download files, read/write remote text files, run background
  jobs, and manage aliases across Linux and Windows servers.
  Supports bash, cmd, and powershell shells. Use when managing servers, deploying code,
  checking logs, restarting services, uploading scripts, or running SSH commands.
  Trigger keywords: deploy, release, restart, check logs, server health, SSH, run on server,
  upload script, download file, server alias, background job, long task, 部署, 上线, 发布, 重启, 查看日志, 服务器健康检查, 后台任务.
---

# ssh-ops

## Quick Start

```bash
# Install (one-time)
pip install -r requirements.txt

# CLI usage
python cli.py list-servers
python cli.py <server> run "uptime"
python cli.py <server> alias deploy
```

## MCP Tools

| Tool | Parameters | Description |
|------|------------|-------------|
| `ssh_list_servers` | — | List all configured servers |
| `ssh_create_server` | `server`, `config` | Create a server config; refuses overwrite |
| `ssh_update_server` | `server`, `config`, `replace`(default false) | Merge a config patch or replace it |
| `ssh_copy_server` | `source_server`, `target_server` | Copy a server config to a new name |
| `ssh_delete_server` | `server` | Delete a server config |
| `ssh_list_aliases` | `server` | List quick-command aliases |
| `ssh_list_scripts` | `server`, `sudo`(default false) | List uploaded scripts on remote |
| `ssh_run` | `server`, `command`, `timeout`(default 300s), `sudo`(default false) | Execute a command |
| `ssh_run_alias` | `server`, `alias_name` | Run an alias |
| `ssh_run_script` | `server`, `script_name`, `timeout`(default 300s), `sudo`(default false) | Run an uploaded script |
| `ssh_upload_script` | `server`, `local_path`, `script_name`(opt), `run_immediately`(default false), `timeout`(default 300s), `overwrite`(default true), `sudo`(default false) | Upload a script |
| `ssh_upload_file` | `server`, `local_path`, `remote_path`, `timeout`(default 300s), `overwrite`(default true), `sudo`(default false), `executable`(default false) | Upload one file to an explicit remote path |
| `ssh_download` | `server`, `remote_path`, `local_path`, `pattern`(opt), `timeout`(default 300s), `overwrite`(default true), `sudo`(default false) | Download file or directory |
| `ssh_download_file` | `server`, `remote_path`, `local_path`, `timeout`(default 300s), `overwrite`(default true), `sudo`(default false) | Download one file from an explicit remote path |
| `ssh_download_script` | `server`, `script_name`, `local_path`, `timeout`(default 300s), `overwrite`(default true), `sudo`(default false) | Download one file from `scripts_dir` |
| `ssh_upload_all_scripts` | `server`, `sudo`(default false) | Upload all scripts from alias definitions |
| `ssh_read_file` | `server`, `remote_path`, `offset`(default 0), `max_bytes`(default 65536), `sudo`(default false) | Read a slice of a remote text file (page via returned next offset; rejects binary) |
| `ssh_write_file` | `server`, `remote_path`, `content`, `append`(default false), `sudo`(default false) | Write/append UTF-8 text to a remote file, no shell quoting |
| `ssh_job_start` | `server`, `command`, `name`(opt), `timeout`(default 0 = no limit), `workdir`(opt), `sudo`(default false) | Start a background job; returns a job id immediately (bash servers) |
| `ssh_job_status` | `server`, `job_id`, `tail_lines`(default 100) | Job state (`running`/`exited`/`killed`/`lost`), exit code, log tails |
| `ssh_job_kill` | `server`, `job_id` | Terminate a job and its whole process group |
| `ssh_job_list` | `server`, `clean_days`(default 0), `sudo`(default false) | List jobs; optionally drop finished ones older than N days |
| `ssh_alias.{server}.{name}` | — (auto-generated) | One-click alias execution |

### Notes
- **sudo** — Use `ssh_run` with `sudo: true`, never inline `sudo -S` in commands (password is sent via stdin automatically)
- **timeout** — `0` means use the server's configured default timeout
- **Concurrency** — Commands on the same server run in parallel on independent SSH channels
- **Host keys** — Verified before authentication; keys persist to `known_hosts` (see `host_key_checking` in REFERENCE.md)
- **Dynamic alias tools** — MCP exposes aliases as `ssh_alias.{server}.{name}`
- **Live stream output** — For real-time streaming, use CLI. See [CLI_USAGE.md](CLI_USAGE.md)
- **Transfer reuse** — Script upload wraps generic file upload; script download wraps generic file download.
- **Text files** — Prefer `ssh_read_file`/`ssh_write_file` for logs and configs (no local temp files, no quoting); fall back to `ssh_download_file`/`ssh_upload_file` for binary or large content.
- **Background jobs** — For commands that outlive one request timeout (`apt upgrade`, builds): `ssh_job_start` then poll `ssh_job_status`. Job state lives on the remote under `jobs_dir` (default `scripts_dir/.jobs`), so it survives MCP restarts. Bash servers only.
- **Docker build real-time output** — `docker build` uses buildkit JSON output by default. Add `--progress=plain` for real-time output. NEVER pipe to `tail` (e.g. `| tail -5`) as it buffers until command completes. Example: `docker build --progress=plain -t myimage .`

## Shell Support

Set `shell` in server YAML to auto-adapt commands:

| Shell | Use Case |
|-------|---------|
| `bash` | Linux/macOS servers (default) |
| `cmd` | Windows servers (CMD) |
| `powershell` | Windows servers (PowerShell) |

## More

- Server config, aliases, security, file transfer → [REFERENCE.md](REFERENCE.md)
- CLI commands reference → [CLI_USAGE.md](CLI_USAGE.md)
- Scripted deploy pipeline (runs via CLI) → [deploy/README.md](deploy/README.md)
- AI Agent installation guide → [INSTALL.md](INSTALL.md)
