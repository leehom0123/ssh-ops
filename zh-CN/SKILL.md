---
name: ssh-ops
description: >
  Operate remote SSH servers through the bundled CLI and YAML server configurations.
  Use for remote commands, service restarts, log inspection, file transfer, text edits,
  deployments, background jobs, and aliases on bash/cmd/powershell servers, even when
  the user does not explicitly mention SSH. Local-only builds and GitHub releases
  without a remote server operation are outside this skill's scope.
  Trigger keywords: deploy, release, ship, server health, SSH, run on server,
  upload script, download file, server alias, 部署, 上线, 发布, 重启, 查看日志, 服务器健康检查.
---

# ssh-ops CLI 技能入口

[English](../SKILL.md)

## 定位工具与目标

本文件是中文参考，默认英文技能入口位于仓库根目录的 [SKILL.md](../SKILL.md)。工具根目录是本文件的上一级目录，在那里定位 `cli.py`，使用已安装项目依赖的 Python 解释器。不要假设用户项目中有 `cli.py`，也不必切换用户项目的工作目录。下文的 `python cli.py` 是简写，实际调用应使用已确认的解释器和 CLI 绝对路径；本地文件路径按当前工作目录解析。

已有确认可用的解释器时直接复用；否则先检查仓库虚拟环境或已配置的解释器，不急于重新安装依赖。以下示例需替换成实际安装路径：

```bash
/absolute/path/to/python /absolute/path/ssh-ops/cli.py my-server run "uptime"
```

先用 `list-servers` 确认服务器名称，不猜名称或用列表序号代替名称。准备复用操作时，用 `list-aliases` 查看别名内容、sudo 与超时设置；同一任务中已查明的信息无需重复查询。缺少依赖或配置时，再读[安装指南](docs/install.md)。

## 选择操作

- 已有合适别名时优先复用，先确认其内容、目标和权限符合本次任务。
- 临时检查用 `run`。命令含复杂引号、`$` 或多行内容时，用 `run -` 配合带引号的 heredoc，避免本地 shell 提前展开。
- 小配置和日志片段用文本读写命令；二进制、大文件或需要完整保留的文本用上传下载，不拼接分页结果作为无损副本。
- 可能超过单次等待时间的操作用后台任务，保存返回的任务 ID 并查询状态。后台任务仅支持 bash 服务器。
- 部署先读取[部署专章](docs/deploy.md)，再生成并执行项目脚本，不临时拼接一串发布命令。

## 命令速查

下表服务器操作均以 `python cli.py <server>` 开头。完整选项和默认值只在 [CLI 参考](docs/cli.md)中维护。

| 用途 | 命令 |
|---|---|
| 发现服务器 | `python cli.py list-servers` |
| 查别名、运行别名 | `list-aliases`、`alias <name>` |
| 执行命令 | `run '<command>'`；复杂命令用 `run -` 从 stdin 读取 |
| 上传与运行脚本 | `upload <local>`、`run-script <name>`、`upload-all`、`list-scripts` |
| 普通文件 | `upload-file <local> <remote>`、`download-file <remote> <local>` |
| 目录与脚本下载 | `download <remote> <local>`、`download-script <name> <local>` |
| 文本读写 | `read-file <remote>`、`write-file <remote> < input.txt` |
| 长任务 | `job-start '<command>'` → `job-status <id>`；需终止时用 `job-kill <id>` |
| 任务列表 | `job-list` |

本地服务器配置的创建、更新、复制与删除，按 [CLI 参考](docs/cli.md)选择具体命令，不在远端操作中修改本地配置文件。

## 关键注意事项

- 选项放在位置参数之后。不要使用不存在的 `--overwrite`；默认允许覆盖，部分传输命令可用 `--no-overwrite`。
- sudo 用 CLI 的 `-s`，不在命令里拼密码。别名的权限与超时由 YAML 决定，不受 CLI `-s/-t` 覆盖。
- 修改远端配置前先读原内容，保留可恢复副本；修改后执行应用校验，通过后再重启。
- 用户已明确授权且目标、范围清楚时直接执行；目标、删除范围或所需权限不明确时再问，不重复索取已有授权。
- 实时输出用 CLI `run`、`run-script`、`alias`；MCP 不推送执行过程。
- 文本分页、sudo 暂存、命令过滤与路径限制有明确边界，见[运行参考](docs/reference.md)。不要把正则过滤当沙箱。

## 部署

按[部署专章](docs/deploy.md)先确认服务器、所在地、模式、目录、端口和检查地址，再生成项目专用的本地脚本与服务器脚本。模板位于 [deploy/scripts/](../deploy/scripts/)，不是无需修改即可运行的通用发布器。所有远端交互走此 CLI；镜像源与健康检查规则以部署专章为准。

## 验证与汇报

启动成功不等于任务完成。检查操作退出码和实际输出；后台任务需查询最终状态及任务退出码，发布或重启还需执行应用健康检查，不能只看本地 CLI 是否返回成功。

普通命令超时不保证远端进程已终止。超时或断连后先查远端任务、进程和服务状态，再决定是否重试，避免重复部署或重复执行迁移。

汇报目标服务器、实际执行的操作和验证结果；未完成或无法验证的部分明确说明。任务仍在运行时附上任务 ID，不宣称已经完成。

MCP 形态入口另见 [SKILL.mcp.md](SKILL.mcp.md)。
