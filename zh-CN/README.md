# ssh-ops

[English](../README.md)

用 CLI 或 MCP 操作远端 SSH 服务器：两个入口共用一套 Python 核心，服务器配置写在 YAML 里，常用命令登记成可复用的别名。

## 特色

- **一个核心，两个入口。** 命令执行、脚本上传运行、SFTP 传输、远端文本编辑和后台任务都由同一套 Python 代码实现，CLI 与 MCP 服务（支持 stdio 和 HTTP 两种传输）只是入口不同。终端里验证过的操作，可以直接交给 agent 通过 MCP 调用。
- **按名字管一组服务器。** 每台服务器是一份 YAML 条目，host、认证、shell、脚本目录、别名和安全过滤各自独立。agent 用 `list-servers` 摸清机器清单，按名字指定目标，Linux 和 Windows 机器走同一个界面。连接可走 SOCKS5 代理，失败自动回退直连；连接只在单进程内复用，CLI 和 MCP 各自建立自己的连接。
- **别名即工具。** 常用命令登记在服务器 YAML 里成为别名：一条命名命令或脚本，带自己的 timeout 和 sudo 设置。MCP 服务为每个别名生成一个零参数工具（如 `ssh_alias.my-server.health`），agent 直接调用，不用重新拼命令、判断权限：

  ```yaml
  # servers/my-server.yml
  aliases:
    - name: health
      inline: "df -h /"
      desc: 查看磁盘占用
  ```

- **后台任务与分页读取。** 构建、迁移这类耗时操作以背景任务启动，拿任务 ID 轮询，不必占住一次 MCP 请求；任务状态记在远端的标记文件里，本地进程或 MCP 重启后依然可查。日志和文本按字节分页读取，大文件不会整段进入 agent 上下文。背景任务要求 bash 服务器。
- **安全限制。** 主机密钥在认证前探测，默认首次信任（`tofu`），中间人拿不到登录口令；命令按黑白名单过滤，上传下载核对本地和远端路径允许列表，sudo 密码配在 YAML 里，不嵌在命令行中。正则过滤是护栏不是沙箱，各项边界见[运行参考](docs/reference.md)。
- **客户机不限系统，服务器不限 shell。** ssh-ops 内置 paramiko（纯 Python 的 SSH 实现），运行时不需要系统 ssh 客户端，Windows、Linux、macOS 均可。服务器端 `shell` 覆盖 bash（Linux、macOS 服务器）和 cmd、powershell（装了 OpenSSH 服务的 Windows 服务器），该设置只决定辅助命令用哪套模板，不翻译用户命令。

## 快速上手

```bash
git clone https://github.com/leehom0123/ssh-ops.git
cd ssh-ops
python -m pip install -r requirements.txt
python cli.py list-servers
```

新建服务器：按[配置参考](docs/reference.md#configuration)把连接字段写成 YAML，用 `python cli.py create-server my-server my-server.yml` 或 MCP 的 `ssh_create_server` 提交。之后执行：

```bash
python cli.py my-server run "uptime"
```

agent 安装见[安装指南](docs/install.md)，可选择装载 CLI 技能或注册 MCP。服务器条目的增删改走 CLI 命令或 MCP 工具，不直接读写配置文件本身；用户说的服务器不在 `list-servers` 结果里时，先列出相近名称供选择，或请用户补齐 host、用户和认证信息再新建。`list-servers` 只读取本地配置，不连接服务器。

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

实现入口为 [CLI](../cli.py)、[MCP 服务](../mcp_server.py)和 [ssh_client/](../ssh_client/) 下的领域模块。Python 导入仍沿用旧名称 `ssh_client`。
