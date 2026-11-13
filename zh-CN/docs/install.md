# agent 安装指南

[English](../../docs/install.md) · [首页](../README.md)

## 1. 准备仓库与解释器

使用 Python 3.9 或更高版本，并准备可用的 SSH/SFTP 服务器。某些依赖版本可能要求更新的 Python，建议选择仍在维护支持范围内的版本。

```bash
git clone https://github.com/leehom0123/ssh-ops.git
cd ssh-ops
python -m venv .venv
```

POSIX 使用 `.venv/bin/python`，Windows 使用 `.venv/Scripts/python.exe`，执行 `-m pip install -r requirements.txt`。运行依赖为 Paramiko、PyYAML、PySocks；开发测试另需 pytest。注册 MCP 时保留所选解释器的绝对路径。

## 2. 选择 agent 入口

- **Codex 插件：**manifest 将 `skills/ssh-ops/` 注册为下述指南的唯一技能入口，通过 `.mcp.json` 注册本地 stdio 服务。启用前，客户端 PATH 中的 `python` 需已安装运行依赖；从已激活的虚拟环境启动客户端并继承其 PATH 即可。MCP 工作目录解析为已安装插件的根目录，不是用户项目目录。安装插件不会创建环境、安装依赖或配置服务器。若需固定解释器，可改用下述手动 MCP 注册方式，避免重复注册。根目录 `SKILL.md` 和语言副本只作参考，不作为额外插件技能装载。插件安装与直接安装技能二选一，同时使用可能出现重复技能。
- **CLI 技能：**将完整仓库放入 agent 支持的技能目录，或在 agent 中配置该目录。默认装载根目录的英文 [SKILL.md](../../SKILL.md)；`zh-CN/` 只提供同名中文参考，不作为独立技能安装。保留完整目录结构，不能只复制技能文件。技能目录规则取决于客户端及版本，本项目不安装全局 `ssh-ops` 命令。
- **MCP：**仓库可放在合适的位置，注册 [mcp_server.py](../../mcp_server.py)，以根目录英文 [SKILL.mcp.md](../../SKILL.mcp.md) 作为操作指南，需要时查阅[中文参考](../SKILL.mcp.md)。CLI 与 MCP 技能以及语言副本的 `name` 相同，不要作为多个技能同时装载。

MCP 入口文档提供 stdio 和 HTTP 注册命令。如果客户端使用常见的 `mcpServers` JSON 格式，stdio 配置等价于：

```json
{
  "mcpServers": {
    "ssh-ops": {
      "command": "/absolute/path/to/python",
      "args": ["/absolute/path/ssh-ops/mcp_server.py"]
    }
  }
}
```

这只是格式示例，不是所有 agent 通用的配置文件。应使用客户端规定的位置与结构；例如 OpenCode 有自己的配置格式。不要直接粘贴到任意 `mcp.json` 或 settings 文件中。客户端工作目录不必是仓库目录。

## 3. 配置服务器

先检查已安装的 `config.yaml` 中 `servers_dir` 指向哪里，不要假设它一定是仓库内的 `servers/`。按[配置参考](reference.md#configuration)创建服务器 YAML。凭据不要纳入版本控制，首次连接的主机指纹需通过独立渠道核实。

## 4. 验证安装

```bash
python cli.py --help
python cli.py list-servers
```

使用前面安装依赖的解释器。空服务器列表是正常结果，这两条命令都不连接远端。重启或重新加载 agent 后，检查 MCP `initialize` 和 `tools/list`：应出现 [SKILL.mcp.md](../SKILL.mcp.md) 中的 22 个静态工具，以及发现的别名。只安装 CLI 技能不会注册 MCP 工具。

选择已配置服务器后，可用 `whoami` 等无修改命令验证 SSH。这会连接远端，也可能登记 TOFU 主机密钥，应先获得授权。HTTP 需按[协议参考](reference.md#http)完成会话初始化。

开发验证需另装 pytest，再运行 `python -m pytest test/ -m 'not live' -q`。live 测试需要明确的服务器配置和授权。
