# ADR-0001: ssh_client 按域拆包，用同名包保持 import 稳定

日期：2026-11-13
状态：已接受

## 背景

`ssh_client.py` 单文件 1985 行，混住了五个域：本地配置与路径、SSH 连接生命
周期、文件传输、后台任务、连接池与服务器 YAML 管理。改动任何一域都要在两千
行里定位，测试 patch 也只能打在同一模块的全局名上。架构评审提出按域拆分。

曾考虑的替代方案：拆成多个不同名模块（如 `ssh_config.py`、`ssh_jobs.py`），
调用方需要全部改 import。

## 决策

拆成**与旧模块同名的包** `ssh_client/`，Python 的包解析规则使
`from ssh_client import pool`、`import ssh_client` 等所有旧 import 原样可用，
对外入口（`mcp_server.py`、`cli.py`）零改动。包内按域分五个模块：
`config` / `connection` / `transfer` / `jobs` / `pool`。

后台任务域单独做成深模块 `JobStore`（接口 `start/status/kill/list`），
`SSHConnection` 上的 `job_*` 方法只是 JobsMixin 的一行转发，不把状态机逻辑
搅进连接类。

代价：测试里凡是对旧单模块全局名的 patch（`ssh_client.SERVERS_DIR`、
`ssh_client.paramiko.SFTPClient` 等）必须移到真实读取处
（`ssh_client.config.SERVERS_DIR`、`paramiko.SFTPClient`、
`ssh_client.pool.SSHConnection`）。这同时暴露了原先"patch 快照名"与"实现
内部读取全局字典"两种风格混用的问题，统一到了前者。

## 后果

- 每域一个文件，改动局部性明确；包对外面不变。
- 测试必须 patch 定义处而非 import 处，这是包结构带来的长期约束，写进了
  CONTEXT.md。
- 后续复审不要再提"按不同名模块拆分"或"合并回单文件"。
