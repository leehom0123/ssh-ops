# CONTEXT

项目领域词汇。架构评审（improve-codebase-architecture）与日常沟通使用这里的名称，
不要再引入"服务""组件"等泛称。

## 领域词

- **服务器（Server）** — 一台可通过 SSH 访问的远端机器。本地以一份 YAML
  （`servers/*.yml`）描述：host/user/认证/shell/scripts_dir/安全过滤等。
  服务器名是小写文件名去扩展名，即连接池的键。
- **别名（Alias）** — 服务器 YAML 里的一条命名快捷方式：`inline` 命令或
  `script` 脚本引用，附带 timeout/sudo。通过 `ssh_run_alias` 执行。
- **脚本目录（scripts_dir）** — 远端存放已上传脚本的目录；上传/运行/列出脚本
  都以它为根。本地相对路径由 `scripts_local_dir`（或 YAML 所在目录）解析。
- **后台任务（Job）** — 在远端脱离命令通道长期运行的进程。状态是
  `jobs_dir/<job-id>/` 下的一组标记文件（cmd、meta、wrapper.sh、pid、exit、
  killed、out.log、err.log），因此跨 MCP 重启仍可见。实现的深模块是
  `ssh_client.jobs.JobStore`，接口只有 `start / status / kill / list`。
- **连接池（Pool）** — `ssh_client.pool.ConnectionPool`：按服务器名缓存
  SSHConnection，同时是唯一改动本地服务器 YAML 的地方
  （create/update/copy/delete/list）。全局单例名 `pool`。
- **代理回退（Proxy fallback）** — 连接时先试 SOCKS5（服务器级 proxy 优先，
  否则全局 `proxy.enabled`），失败自动回退直连。
- **主机密钥模式（host_key_checking）** — `tofu`（首见即存入 known_hosts）/
  `strict`（必须在 known_hosts）/ `insecure`。认证前探测，MITM 看不到口令。
- **命令过滤（whitelist / blacklist / command_template）** — 远端命令的安全
  过滤器；白名单按整条命令 fullmatch。代码自身生成的辅助命令走
  `run(..., internal=True)` 跳过过滤。
- **路径允许列表（allowed_local_paths / allowed_remote_paths）** —
  上传/下载的路径约束，带目录边界的前缀匹配。
- **MCP 工具（Tool）** — `mcp_server.STATIC_TOOLS` 里的 ToolSpec：名称、参数
  schema、handler。22 个静态工具 + 每个别名的动态工具。

## 包结构（按域拆分，见 ADR-0001）

`ssh_client/`（包，保持 `from ssh_client import pool` 的旧 import 面）：

- `config.py` — 离线基础设施：config.yaml、路径规范化、命令行模板
  （bash/cmd/powershell）、编码修复、共享小校验器。
- `connection.py` — SSHConnection 本体：paramiko 生命周期、重连策略、
  命令执行、别名执行。
- `transfer.py` — TransferMixin：上传/下载/单文件传输/远端文本读写（SFTP）。
- `jobs.py` — JobStore 深模块 + JobsMixin（一行转发）。
- `pool.py` — ConnectionPool 与服务器 YAML 管理。

`mcp_server.py` 中多数 handler 由 `_passthrough` 工厂按注册表声明式生成；
job_*、别名、CRUD 等形状不同的保留手写。
