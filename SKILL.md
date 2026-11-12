---
name: ssh-ops
description: >
  SSH server management CLI. Run remote commands, deploy scripts, restart services,
  check logs, upload/download files, read/write remote text files, run background
  jobs, and manage aliases across bash/cmd/powershell servers.
  Trigger keywords: deploy, release, ship, server health, SSH, run on server,
  upload script, download file, server alias, 部署, 上线, 发布, 重启, 查看日志, 服务器健康检查.
---

# ssh-ops CLI 技能入口

先用 `list-servers` 查名称，再用 `list-aliases` 查可复用操作。所有命令在仓库目录执行；其他目录需使用 `cli.py` 的绝对路径。安装见[安装指南](docs/install.zh-CN.md)。

## 命令速查

下表服务器操作均以 `python cli.py <server>` 开头。完整选项和默认值只在 [CLI 参考](docs/cli.zh-CN.md)中维护。

| 用途 | 命令 |
|---|---|
| 发现服务器 | `python cli.py list-servers` |
| 管理本地配置 | `python cli.py create-server/update-server/copy-server/delete-server ...`，按 CLI 参考选择单个命令 |
| 查别名、运行别名 | `list-aliases`、`alias <name>` |
| 执行命令 | `run '<command>'`；复杂命令用 `run -` 从 stdin 读取 |
| 上传与运行脚本 | `upload <local>`、`run-script <name>`、`upload-all`、`list-scripts` |
| 普通文件 | `upload-file <local> <remote>`、`download-file <remote> <local>` |
| 目录与脚本下载 | `download <remote> <local>`、`download-script <name> <local>` |
| 文本读写 | `read-file <remote>`、`write-file <remote> < input.txt` |
| 长任务 | `job-start '<command>'` → `job-status <id>`；需终止时用 `job-kill <id>` |
| 任务列表 | `job-list`；清理前先确认用户授权 |

## 关键注意事项

- 选项放在位置参数之后。不要使用不存在的 `--overwrite`；默认允许覆盖，部分传输命令可用 `--no-overwrite`。
- sudo 用 CLI 的 `-s`，不在命令里拼密码。别名的权限与超时由 YAML 决定，不受 CLI `-s/-t` 覆盖。
- 先读原内容再改配置，修改后执行应用校验，再重启。删除配置、清理任务或部署前确认目标。
- 实时输出用 CLI `run`、`run-script`、`alias`；MCP 不推送执行过程。普通命令超时不保证远端进程已终止。
- 文本分页、sudo 暂存、命令过滤与路径限制有明确边界，见[运行参考](docs/reference.zh-CN.md)。不要把正则过滤当沙箱。

## 部署

按[部署专章](docs/deploy.zh-CN.md)先确认服务器、所在地、模式、目录、端口和检查地址，再生成项目专用的本地脚本与服务器脚本。模板位于 [deploy/scripts/](deploy/scripts/)，不是无需修改即可运行的通用发布器。所有远端交互走此 CLI；镜像源与健康检查规则以部署专章为准。

MCP 形态入口另见 [SKILL.mcp.md](SKILL.mcp.md)。
