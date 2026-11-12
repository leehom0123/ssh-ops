---
name: ssh-ops
description: >
  SSH operations through MCP: commands, scripts, files, remote text, background
  jobs, and aliases across bash/cmd/powershell servers.
  Trigger keywords: deploy, release, restart, check logs, server health, SSH, run on server,
  upload script, download file, server alias, background job, long task, 部署, 上线, 发布, 重启, 查看日志, 服务器健康检查, 后台任务.
---

# ssh-ops MCP skill

[中文参考](zh-CN/SKILL.mcp.md)

Call `ssh_list_servers` first, then use `ssh_list_aliases` to confirm aliases. Configuration and runtime semantics are maintained in the [runtime reference](docs/reference.md). For CLI use, see [SKILL.md](SKILL.md).

## 22 static tools

Each row corresponds to [STATIC_TOOLS](mcp_server.py). Parameters without `?` or `=` are required; `?` means optional with a null default, and `=value` gives an optional parameter's default. Paths, names, commands, and content are strings; `config` is an object; timeout/offset/max_bytes/tail_lines/clean_days are nonnegative numbers; other switches are booleans.

| Tool | Parameters | Purpose |
|---|---|---|
| `ssh_create_server` | `server, config` | Create local YAML; refuse overwrite |
| `ssh_update_server` | `server, config, replace=false` | Recursively merge or replace the configuration |
| `ssh_copy_server` | `source_server, target_server` | Copy local configuration; refuse overwrite |
| `ssh_delete_server` | `server` | Delete local configuration |
| `ssh_run` | `server, command, timeout=300, sudo=false` | Execute a remote command |
| `ssh_upload_script` | `server, local_path, script_name?, run_immediately=false, timeout=300, overwrite=true, sudo=false` | Upload into the script directory; optionally execute |
| `ssh_upload_file` | `server, local_path, remote_path, timeout=300, overwrite=true, sudo=false, executable=false` | Upload one file to an explicit path |
| `ssh_run_script` | `server, script_name, timeout=300, sudo=false` | Execute a script from the script directory |
| `ssh_list_scripts` | `server, sudo=false` | List remote scripts |
| `ssh_read_file` | `server, remote_path, offset=0, max_bytes=65536, sudo=false` | Read a UTF-8 byte slice; paging fields appear in the result summary |
| `ssh_write_file` | `server, remote_path, content, append=false, sudo=false` | Write or append UTF-8 text |
| `ssh_job_start` | `server, command, name?, timeout=0, workdir?, sudo=false` | Start a bash background job and return its ID |
| `ssh_job_status` | `server, job_id, tail_lines=100` | Return state, exit code, and log tails |
| `ssh_job_kill` | `server, job_id` | Send termination signals to the job's process group |
| `ssh_job_list` | `server, clean_days=0, sudo=false` | List jobs; a nonzero cleanup threshold can delete job directories |
| `ssh_list_servers` | None | List local server configurations |
| `ssh_download` | `server, remote_path, local_path, pattern?, timeout=300, overwrite=true, sudo=false` | Download a file or directory, with an optional filename regex |
| `ssh_download_file` | `server, remote_path, local_path, timeout=300, overwrite=true, sudo=false` | Download from an explicit path using the shared downloader |
| `ssh_download_script` | `server, script_name, local_path, timeout=300, overwrite=true, sudo=false` | Download from the script directory |
| `ssh_upload_all_scripts` | `server, sudo=false` | Upload alias scripts in bulk |
| `ssh_run_alias` | `server, alias_name` | Execute an alias using YAML privilege and timeout settings |
| `ssh_list_aliases` | `server` | List local alias definitions |

Required strings cannot be empty; unknown arguments are rejected. Explicit null offset/max_bytes values for `ssh_read_file` use defaults. Do not pass null indiscriminately for other optional parameters. Ordinary timeouts and job lifetimes differ; the exact adjustment formula is in the [timeout rules](docs/reference.md#security). Tool annotations are not access controls: listing jobs with cleanup enabled deletes remote content.

## Dynamic alias tools

Each alias can generate a zero-argument tool named `ssh_alias.<server>.<name>`. Unsupported characters are replaced, names are limited to 128 characters, and collisions receive a digest and, if necessary, a counter. Use the actual `tools/list` result rather than constructing names yourself.

Discovery is cached for 10 seconds. MCP configuration CRUD invalidates it, but external file edits do not guarantee cached connections reload. Tool-list changes are not pushed to clients. Alias configuration and path restrictions are described in the [runtime reference](docs/reference.md).

## Transports and registration

The default transport is stdio: one JSON-RPC message per line, with stdout reserved for the protocol. For example, register absolute paths with Claude Code:

```bash
claude mcp add --transport stdio ssh-ops -- python /absolute/path/ssh-ops/mcp_server.py
```

HTTP service:

```bash
python mcp_server.py --http --host 127.0.0.1 --port 8802 --path /mcp
```

Launch options are `--http`, `--host` (default `127.0.0.1`), `--port` (default `8802`), `--path` (default `/mcp`), and `--token` (unset by default). Binding beyond loopback requires a nonempty token. Obtain it from trusted secret storage; do not commit it to a configuration repository.

Example registration for a loopback endpoint without a token:

```bash
claude mcp add --transport http ssh-ops http://127.0.0.1:8802/mcp
```

With a token enabled, configure the client's `Authorization: Bearer <token>` header. Session initialization, DELETE, notifications, status codes, and the lack of SSE support are documented in the [HTTP protocol reference](docs/reference.md#http). Installation and the common configuration format are covered in the [installation guide](docs/install.md).
