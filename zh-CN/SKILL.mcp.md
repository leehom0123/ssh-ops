---
name: ssh-ops
description: >
  SSH operations through MCP: commands, scripts, files, remote text, background
  jobs, and aliases across bash/cmd/powershell servers.
  Trigger keywords: deploy, release, restart, check logs, server health, SSH, run on server,
  upload script, download file, server alias, background job, long task, 部署, 上线, 发布, 重启, 查看日志, 服务器健康检查, 后台任务.
---

# ssh-ops MCP 技能入口

[English](../SKILL.mcp.md)

本文件是中文参考，默认英文入口位于根目录的 [SKILL.mcp.md](../SKILL.mcp.md)。先调用 `ssh_list_servers`，再用 `ssh_list_aliases` 确认别名。配置与运行语义统一见[运行参考](docs/reference.md)，CLI 使用见 [SKILL.md](SKILL.md)。下文命令在仓库根目录执行，不是在 `zh-CN/` 中执行。

## 22 个静态工具

逐项对应 [STATIC_TOOLS](../mcp_server.py)。参数不带 `?` 或 `=` 时必填；`?` 表示可省略且默认 null，`=值` 表示可省略及其默认值。路径、名称、命令、内容均为字符串；`config` 为对象；timeout/offset/max_bytes/tail_lines/clean_days 为非负数；其余开关为布尔值。

| 工具 | 参数 | 用途 |
|---|---|---|
| `ssh_create_server` | `server, config` | 新建本地 YAML，拒绝覆盖 |
| `ssh_update_server` | `server, config, replace=false` | 递归合并或整份替换配置 |
| `ssh_copy_server` | `source_server, target_server` | 复制本地配置，拒绝覆盖 |
| `ssh_delete_server` | `server` | 删除本地配置 |
| `ssh_run` | `server, command, timeout=300, sudo=false` | 执行远端命令 |
| `ssh_upload_script` | `server, local_path, script_name?, run_immediately=false, timeout=300, overwrite=true, sudo=false` | 上传到脚本目录，可立即执行 |
| `ssh_upload_file` | `server, local_path, remote_path, timeout=300, overwrite=true, sudo=false, executable=false` | 上传单文件到指定路径 |
| `ssh_run_script` | `server, script_name, timeout=300, sudo=false` | 执行脚本目录中的脚本 |
| `ssh_list_scripts` | `server, sudo=false` | 列出远端脚本 |
| `ssh_read_file` | `server, remote_path, offset=0, max_bytes=65536, sudo=false` | 读取 UTF-8 文本字节片段，分页字段见结果摘要 |
| `ssh_write_file` | `server, remote_path, content, append=false, sudo=false` | 写入或追加 UTF-8 文本 |
| `ssh_job_start` | `server, command, name?, timeout=0, workdir?, sudo=false` | 启动 bash 后台任务，返回任务 ID |
| `ssh_job_status` | `server, job_id, tail_lines=100` | 状态、退出码及日志尾部 |
| `ssh_job_kill` | `server, job_id` | 向任务进程组发送终止信号 |
| `ssh_job_list` | `server, clean_days=0, sudo=false` | 列出任务；非零清理阈值可能删除任务目录 |
| `ssh_list_servers` | 无 | 列出本地服务器配置 |
| `ssh_download` | `server, remote_path, local_path, pattern?, timeout=300, overwrite=true, sudo=false` | 下载文件或目录，可按文件名正则过滤 |
| `ssh_download_file` | `server, remote_path, local_path, timeout=300, overwrite=true, sudo=false` | 指定路径下载，复用下载实现 |
| `ssh_download_script` | `server, script_name, local_path, timeout=300, overwrite=true, sudo=false` | 从脚本目录下载 |
| `ssh_upload_all_scripts` | `server, sudo=false` | 批量上传别名脚本 |
| `ssh_run_alias` | `server, alias_name` | 使用 YAML 权限与超时执行别名 |
| `ssh_list_aliases` | `server` | 列出本地别名定义 |

必填字符串不能为空；未知参数会被拒绝。`ssh_read_file` 的 offset/max_bytes 显式 null 使用默认值，其他可选参数不应随意传 null。普通 timeout 和任务 timeout 含义不同，精确调整公式见[超时规则](docs/reference.md#security)。不要把工具注解当权限控制；尤其任务列表带清理参数时会删除远端内容。

## 动态别名工具

每个别名可生成无参数工具 `ssh_alias.<server>.<name>`。名称中的不支持字符会替换，最长 128 字符，冲突时附加摘要和必要的序号，因此应以 `tools/list` 实际结果为准，不自行拼接名称。

发现结果缓存 10 秒；MCP 配置 CRUD 会使缓存失效，但外部编辑文件不保证缓存连接重新加载。工具列表不发送主动变更通知。别名配置与路径限制见[运行参考](docs/reference.md)。

## 传输与注册

默认 stdio：每行一条 JSON-RPC 消息，stdout 仅用于协议。以 Claude Code 为例，使用绝对路径注册：

```bash
claude mcp add --transport stdio ssh-ops -- python /absolute/path/ssh-ops/mcp_server.py
```

HTTP 服务：

```bash
python mcp_server.py --http --host 127.0.0.1 --port 8802 --path /mcp
```

启动选项为 `--http`、`--host`（默认 `127.0.0.1`）、`--port`（默认 `8802`）、`--path`（默认 `/mcp`）、`--token`（默认无）。非回环绑定必须设置非空 token；部署时从可信秘密存储获取，勿提交到配置仓库。

回环无 token 的注册示例：

```bash
claude mcp add --transport http ssh-ops http://127.0.0.1:8802/mcp
```

启用 token 时，客户端另需设置 `Authorization: Bearer <token>` 请求头。会话初始化、DELETE、通知、状态码和不支持 SSE 的限制统一见 [HTTP 协议](docs/reference.md#http)。安装与通用配置格式见[安装指南](docs/install.md)。
