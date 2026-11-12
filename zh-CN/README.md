# ssh-ops

[English](../README.md)

通过 CLI 或 MCP 管理 SSH 服务器，用 YAML 保存连接配置和可复用的命令别名。

## 主要能力

- 命令执行、脚本运行、SFTP 传输和远端文本编辑共用一套 Python 核心。
- CLI 面向终端和 agent；MCP 服务支持 stdio 与 HTTP 两种传输。
- YAML 别名可自动生成可调用的 MCP 工具。
- 耗时操作可交给远端后台任务，日志可按字节分页读取。
- 提供主机密钥校验、命令过滤、路径允许列表和 sudo；适用范围与限制见详细参考。

`shell` 为 `bash`、`cmd` 或 `powershell` 选择辅助命令模板，不会把任意命令翻译成另一种 shell 语法。连接只在同一进程内复用，独立的 CLI 与 MCP 进程不共享连接。

## 快速上手

```bash
git clone https://github.com/leehom0123/ssh-ops.git
cd ssh-ops
python -m pip install -r requirements.txt
python cli.py list-servers
```

按[配置参考](docs/reference.md#configuration)添加服务器后执行：

```bash
python cli.py my-server run "uptime"
```

agent 安装见[安装指南](docs/install.md)，可选择装载 CLI 技能或注册 MCP。`list-servers` 只读取本地配置，不连接服务器。

## 使用场景

- **排查故障：**先查服务器和别名，再收集服务日志与系统指标，根据证据分析。工具负责执行命令，不会自动判定故障原因。
- **修改配置：**读取原文，写入已确认的修改，执行应用自身的校验命令，再重启服务。
- **运行构建或迁移：**启动后台任务并轮询状态，不必一直占用单次 MCP 请求。
- **发布版本：**按[脚本化部署流程](docs/deploy.md)执行，为项目明确重启命令和健康检查。

## 文档导航

| 文档 | 定位 |
|---|---|
| [SKILL.md](SKILL.md) | CLI 形态的 agent 入口与命令速查 |
| [SKILL.mcp.md](SKILL.mcp.md) | MCP 注册、22 个静态工具与动态别名工具 |
| [CLI 参考](docs/cli.md) | CLI 的准确语法、选项、默认值与输出 |
| [运行参考](docs/reference.md) | YAML 字段、安全、传输与任务语义、HTTP 协议 |
| [安装](docs/install.md) | agent 安装与验证 |
| [部署](docs/deploy.md) | 流程、模板约定、镜像源与故障排查 |

实现入口为 [CLI](../cli.py)、[MCP 服务](../mcp_server.py)和 [ssh_client/](../ssh_client/) 下的领域模块。Python 导入仍保留历史名称 `ssh_client`。
