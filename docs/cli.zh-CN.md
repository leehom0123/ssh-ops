# CLI 使用参考

[English](cli.md) · [CLI 技能入口](../SKILL.md) · [运行语义](reference.zh-CN.md)

在仓库目录执行命令，或把 `cli.py` 换成绝对路径。`python cli.py`、`-h`、`--help` 显示帮助。CLI 使用自定义的尾部选项解析器，不使用 argparse。

## 解析规则与选项

```text
python cli.py <global-command> ...
python cli.py <server> <command> <positional-arguments> [options]
```

选项必须放在所有位置参数之后。解析器只消费末尾连续出现的已知选项。远端命令应整体加引号；本地 shell 仍会处理引号、`$`、管道和重定向。复杂命令可用 `run -` 配合带引号的 heredoc。`-` 必须是唯一的命令参数，标准输入不能是空白。

| 选项 | 含义与适用命令 |
|---|---|
| `-s`, `--sudo` | 对 `run`、`run-script`、`upload`、`upload-file`、`download`、`download-file`、`download-script`、`read-file`、`write-file`、`job-start`、`job-list`、`upload-all`、`list-scripts` 使用 sudo |
| `-t`, `--timeout SECS` | `run`、`run-script`、`upload`、`upload-file`、`download`、`download-file`、`download-script` 的整数秒超时；省略时用服务器超时。对 `job-start` 则是任务时限，省略或 0 表示不限 |
| `-n`, `--name VALUE` | `upload` 的远端脚本名；`job-start` 的标签；`job-status` 每份日志的尾部行数（默认 100） |
| `-r`, `--run` | `upload`：上传后执行 |
| `-p`, `--pattern REGEX` | `download`：按文件名正则过滤 |
| `-x`, `--executable` | `upload-file`：请求设置 Unix 执行权限 |
| `-o`, `--offset BYTES` | `read-file`：起始字节偏移，默认 0 |
| `-l`, `--length BYTES` | `read-file`：最多读取字节数，默认 65536；0 也使用默认值 |
| `-a`, `--append` | `write-file`：追加而非覆盖 |
| `-w`, `--workdir DIR` | `job-start`：工作目录，默认远端主目录 |
| `--clean-days N` | `job-list`：清理阈值，默认 0，即全部保留 |
| `--no-overwrite` | `upload-file`、`download`、`download-file`、`download-script`：目标已存在时报错 |
| `--replace` | `update-server`：替换整个 YAML 对象 |

能被解析不等于会生效：即使某命令不使用这些选项，解析器仍会消费它们。尤其是 `alias` 忽略 CLI 的 sudo/timeout，使用 YAML 设置；`upload-all`、`list-scripts` 忽略 CLI timeout。文本读写与任务控制使用内部操作超时。CLI 没有 `--overwrite`、`--tail-lines` 或 `--max-bytes` 选项。

## 本地配置命令

| 命令 | 行为 |
|---|---|
| `python cli.py list-servers` | 输出含 `count`、`servers` 的 JSON，不连接 SSH |
| `python cli.py create-server <name> <config.yml>` | 从 YAML 文件新建配置；目标已存在时报错 |
| `python cli.py update-server <name> <patch.yml> [--replace]` | 递归合并映射，替换数组和标量；也可整份替换 |
| `python cli.py copy-server <source> <new-name>` | 复制 YAML 原始内容与权限位；目标已存在时报错 |
| `python cli.py delete-server <name>` | 删除本地 YAML，不删除远端内容 |

修改命令输出 JSON。名称规则、存储、继承和缓存失效机制见[配置参考](reference.zh-CN.md#configuration)。

## 命令执行与脚本

下表命令均以 `python cli.py <server>` 开头。

| 命令后缀 | 行为 |
|---|---|
| `run <command> [-s] [-t SECS]` | 执行远端命令，流式输出 stdout/stderr |
| `run - [-s] [-t SECS]` | 从标准输入读取整条命令，流式输出 stdout/stderr |
| `run-script <name> [-s] [-t SECS]` | 执行 `scripts_dir` 中的脚本，流式输出 stdout/stderr |
| `alias <name>` | 执行配置中的别名，流式输出 stdout/stderr |
| `upload <local> [-n NAME] [-r] [-s] [-t SECS]` | 上传到 `scripts_dir`，默认使用本地文件名；始终允许覆盖 |
| `upload-all [-s]` | 上传别名脚本，汇总成功与失败项 |
| `list-scripts [-s]` | 列出远端脚本，内部超时为 30 秒 |
| `list-aliases` | 输出含 `count`、`aliases` 的 JSON，不连接 SSH |

```bash
python cli.py my-server run - -t 30 <<'EOF'
printf '%s\n' "$HOME"
EOF
```

## 文件与文本

| 命令后缀 | 行为 |
|---|---|
| `upload-file <local> <remote> [-s] [-x] [-t SECS] [--no-overwrite]` | 上传单个文件到指定路径 |
| `download <remote> <local> [-s] [-p REGEX] [-t SECS] [--no-overwrite]` | 下载文件或目录 |
| `download-file <remote> <local> [-s] [-t SECS] [--no-overwrite]` | 指定路径下载，委托同一下载实现 |
| `download-script <name> <local> [-s] [-t SECS] [--no-overwrite]` | 从 `scripts_dir` 下载 |
| `read-file <remote> [-o BYTES] [-l BYTES] [-s]` | stdout 输出文本；未读完时 stderr 提示下一个字节偏移 |
| `write-file <remote> [-a] [-s]` | 从标准输入读取 UTF-8 文本，输出操作结果 |

传输默认覆盖。读取上限、UTF-8 边界限制、文件权限、sudo 暂存和去重语义统一见[运行参考](reference.zh-CN.md#transfers)。

```bash
python cli.py my-server read-file /var/log/app.log -o 0 -l 4096
python cli.py my-server write-file /etc/motd -s < note.txt
```

## 后台任务

| 命令后缀 | 输出与行为 |
|---|---|
| `job-start <command> [-n NAME] [-w DIR] [-t SECS] [-s]` | 输出 JSON `job_id`、`pid`；命令换成 `-` 时读取标准输入 |
| `job-status <id> [-n LINES]` | JSON 状态、退出码、元数据及 stdout/stderr 尾部 |
| `job-kill <id>` | JSON 终止结果，读取已保存的任务元数据 |
| `job-list [--clean-days N] [-s]` | JSON `count`、`jobs`；清理会删除远端任务目录 |

这些命令要求 bash 服务器。见[任务协议与限制](reference.zh-CN.md#jobs)。

## 输出、错误与本地路径

- 执行和传输命令通常返回操作的退出码。已知操作错误在 stderr 输出 `Error: ...` 并以 1 退出；非法 timeout 值和不合法的标准输入命令以 2 退出。
- 列表、文本读取和正常返回的任务处理逻辑，不会把远端命令退出码直接变成 CLI 退出码。应检查任务 JSON 和健康检查结果，不能只看本地退出状态。
- 本地上传、下载和配置文件路径使用项目的 Windows/WSL 路径转换。在 Windows Git Bash 下，CLI 会尝试用 `cygpath` 撤销 MSYS 路径重写；真实 Windows 目标路径若以 Git 或临时目录前缀开头，可改用 PowerShell/cmd 避免歧义。
- 部署请按[部署专章](deploy.zh-CN.md)执行，不要从本参考中临时拼凑流程。
