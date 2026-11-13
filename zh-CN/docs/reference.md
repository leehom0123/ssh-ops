# 运行与配置参考

[English](../../docs/reference.md) · [CLI 语法](cli.md) · [MCP 工具](../SKILL.mcp.md)

本文统一说明配置和运行行为。部署专用约定见[部署专章](deploy.md)。

## 实现结构

[cli.py](../../cli.py) 与 [mcp_server.py](../../mcp_server.py) 均调用 [ssh_client/](../../ssh_client/) 包：

- [config.py](../../ssh_client/config.py)：本地路径、YAML、shell 模板、编码辅助。
- [connection.py](../../ssh_client/connection.py)：SSH 生命周期、主机密钥、命令执行、别名。
- [transfer.py](../../ssh_client/transfer.py)：SFTP、脚本封装、文本读写。
- [jobs.py](../../ssh_client/jobs.py)：`JobStore` 与远端标记文件协议。
- [pool.py](../../ssh_client/pool.py)：进程内连接缓存与服务器 YAML 增删改查。

<a id="configuration"></a>
## 配置

### 全局文件

`config.yaml`、`known_hosts` 位于仓库根目录，不随当前工作目录变化。以下仅演示字段，并非当前安装配置的副本：

```yaml
servers_dir: servers
proxy:
  enabled: false
  host: 127.0.0.1
  port: 1080
server:
  timeout: 30
  auto_reconnect: true
  reconnect_interval: 5
  keepalive_interval: 15
  host_key_checking: tofu
security:
  blacklist: []
  whitelist: []
  command_template: ""
```

- `servers_dir`：绝对路径，或相对于 `config.yaml` 的路径；省略时为 `servers`。Linux/WSL 下转换 Windows 盘符路径，Windows 下转换 `/mnt/<drive>/...` 路径。
- `proxy`：全局 SOCKS5 开关、主机和端口。没有独立生效的 `proxy.timeout`，套接字使用服务器超时。
- `server`：上例五个连接策略字段的默认值。
- `security`：全局命令过滤和模板默认值，见[安全](#security)。

全局默认值和服务器目录在导入时读取，连接对象也会缓存。直接修改文件后，建议重启持久运行的 MCP 进程，确保重新加载。连接路径会重读全局代理配置，但缓存连接上已经解析出的代理可能保留旧值，不应依赖实时切换代理。

### 服务器 YAML 字段

在 `servers_dir` 下，每台服务器保存一个小写 `<name>.yml` 文件。发现机制只扫描顶层 `*.yml`，不扫描子目录或 `*.yaml`。接收名称的操作会去掉可选的 `.yml`/`.yaml` 后缀并转小写；首字符必须是 ASCII 字母或数字，其后可用 ASCII 字母、数字、`.`、`_`、`-`。

顶层键为 `server`、`aliases` 和可选的 `extends`。以下连接和安全字段均应放在 **`server` 内部**。

```yaml
server:
  host: example.invalid
  user: deploy
  key: /absolute/path/to/private_key
  scripts_dir: /home/deploy/scripts
  scripts_local_dir: scripts
aliases:
  - name: health
    inline: "df -h /"
    desc: Check disk usage
  - name: deploy
    script: deploy.sh
    timeout: 300
    sudo: false
```

| `server` 字段 | 默认值与含义 |
|---|---|
| `host` | 继承合并后必填，主机名或 IP |
| `user` | 继承合并后必填，SSH 登录用户 |
| `port` | 22 |
| `password` | 可选的登录密码 |
| `key` | 运行 ssh-ops 的机器上的私钥路径；优先于密码 |
| `key_password` | 可选的私钥口令 |
| `sudo_password` | 缺省或为空时回退到 `password` |
| `timeout` | 全局 `server.timeout`，否则 30 秒；用于连接超时及默认命令超时 |
| `auto_reconnect` | 全局设置，否则 true |
| `reconnect_interval` | 全局设置，否则 5 秒；最小为 0 |
| `keepalive_interval` | 全局设置，否则 15 秒；0 关闭保活 |
| `host_key_checking` | 全局设置，否则 `tofu`；也接受 `strict`、`insecure` |
| `shell` | `bash`；另可选 `cmd`、`powershell` |
| `scripts_dir` | `/home/<user>/scripts`；Windows 或其他主目录布局需明确配置 |
| `scripts_local_dir` | 未设置时用服务器 YAML 所在目录；设置后相对于该目录解析 |
| `jobs_dir` | 缺省或为空时为 `<scripts_dir>/.jobs` |
| `proxy` | 非空 `{host: ..., port: ...}` 覆盖全局代理；`{}` 会回退到全局，不能作为单服务器关闭开关 |
| `whitelist` | 缺省/null 时用全局列表；显式 `[]` 可关闭继承的白名单 |
| `blacklist` | 缺省/null 时用全局列表；显式 `[]` 可关闭继承的黑名单 |
| `command_template` | 缺省或为空时用全局模板；替换标记为 `<command>` |
| `allowed_local_paths` | `[]`，不限制；约束本地传输路径 |
| `allowed_remote_paths` | `[]`，不限制；约束远端传输和文本读写路径 |
| `name` | 显示名称；列表回退到 YAML 文件名（不含后缀） |
| `desc` | 显示描述，默认空 |
| `system` | 显示系统信息，默认空 |
| `group` | 列表排序分组，默认服务器名称 |

显示字段不改变连接行为。列表按分组、名称排序，附带从 1 开始的 `index`；该序号不是服务器标识。

### 继承与更新

```yaml
extends:
  - _shared/base.yml
  - _shared/commands.yml
server:
  host: example.invalid
aliases:
  - name: health
    inline: "df -h /"
```

`extends` 应为文件路径列表，相对于服务器 YAML 所在目录。加载**只有一层，不递归**。本地 `server` 字段优先于继承字段；已经继承的字段按列表先出现者优先。`server` 为浅合并。别名按名称精确比较，本地优先，较早继承的别名也优先于后续同名项。缺失文件会警告并跳过。继承脚本的路径仍相对于使用它的服务器 YAML，而不是共享文件。

继承加载器会复制旧式顶层安全、代理和路径键，但连接构造器从 `server` 读取这些设置。共享配置也应把它们放在 `server` 映射内；顶层副本不会配置连接。

CRUD 更新与继承不同：映射递归合并，数组和标量整项替换；`replace` 替换整个对象。新建和复制拒绝覆盖，删除仅移除本地 YAML。新配置请求 0600 权限，更新保留原权限位，复制保留源内容和权限位。写入使用临时文件与原子替换；实际权限保障取决于本地文件系统。CRUD 丢弃受影响的缓存连接，MCP CRUD 还会使别名工具发现缓存失效。

## 别名与 shell 选择

别名包含 `name`、可选 `desc`、`timeout`（默认 300 秒）、`sudo`（默认 false），以及 `inline`、`script` 二选一。两者都有时执行优先选 `inline`，不要同时配置。`list-aliases` 只读取本地配置。

- `inline` 经命令过滤和模板处理后交给远端 shell。
- `script` 指本地脚本，不是已上传的远端文件。按需执行时，`deploy.sh` 这类简单相对文件名最可靠。即使远端副本存在，本地文件仍须存在。远端文件存在就跳过上传，不比较内容，也不自动刷新。
- 按需脚本别名拒绝绝对路径、反斜杠、空路径段、`.`、`..`。它会计算相对远端路径，但缺失的嵌套脚本目前按文件名上传。嵌套脚本应先按准确的相对远端名称上传，或改用显式上传和执行操作。
- 批量别名上传另有路径处理：`scripts_local_dir` 内的相对路径保留目录层级；解析后在目录外的文件上传到 `<scripts_dir>/external/<basename>`。这不意味着按需 `alias` 执行也接受绝对路径。

`shell` 选择生成的辅助命令语法和参数引号，不会切换 SSH 账号的登录 shell，也不会翻译用户命令。bash 用 `bash` 执行脚本，cmd 用 `call`，PowerShell 用 `&`。远端 SSH shell 需配套设置。sudo 要求远端有 `sudo` 和 `bash`，不是 Windows 提权机制。部署模板面向 bash。

<a id="security"></a>
## 安全与连接策略

### 过滤与路径

非内部 `run` 调用按以下顺序处理：黑名单 `re.search`、非空白名单 `re.fullmatch`、替换 `command_template` 中的 `<command>`。`ls.*` 这类宽泛正则仍允许 shell 操作符；两种列表都不是沙箱，应另用凭据与操作系统权限限制能力。

内联别名和后台任务命令也经过这些检查。程序生成的辅助命令通过 `internal=True` 同时绕过过滤**和命令模板**。`run-script` 也走内部路径，因此白名单不能限制上传脚本的内容。脚本别名和上传后执行则把生成的调用交给普通 `run`，过滤的是调用语句，而不是脚本正文。

路径允许列表按目录边界比较，不是任意字符串前缀匹配。本地路径在客户端解析，远端路径只做 POSIX 词法归一化。远端大小写折叠取决于客户端操作系统，也不会解析远端符号链接。因此它不是文件系统沙箱，也不约束任意 `run` 命令或任务目录。下载检查本地根路径及每个远端文件；sudo 递归下载检查的是暂存路径，可能与原目录的允许列表冲突。限制路径时，需先验证 sudo 递归下载是否适合当前配置。

生成的辅助命令参数按目标 shell 加引号。脚本名校验会拒绝目录穿越和绝对名称，但不是每个任意远端路径都经过这项校验。YAML 凭据需设置本地权限，且不要纳入版本控制。MCP 错误中的参数摘要会按已知密钥名隐藏秘密值，但异常消息和工具输出不会统一脱敏，也不会隐藏嵌在 command/content 字符串中的秘密。

### 主机密钥

| 模式 | 当前行为 |
|---|---|
| `tofu` | 认证前探测并检查仓库内 `known_hosts`；未知密钥类型会登记，同类型已存密钥变化时拒绝连接 |
| `strict` | 认证前探测要求仓库内 `known_hosts` 已有匹配密钥；只有系统 known_hosts 条目还不够 |
| `insecure` | 跳过探测，使用宽松的缺失密钥策略；直连路径上，Paramiko 仍可能拒绝已加载的密钥不匹配 |

直连 SSH 客户端还会加载系统主机密钥和仓库内文件。非默认端口使用 `[host]:port`。首次信任前应通过独立渠道确认指纹。合法轮换也应先验证新密钥，再改本地条目，不要直接删除后盲目信任。TOFU 保存失败会打印警告，因此连接成功不代表登记已持久保存。

在 `tofu`/`strict` 模式下，代理认证连接也会在发送凭据前校验自身协商的主机密钥，规则与独立探测相同。直连认证连接由 Paramiko 根据已加载的主机密钥策略校验。

### 代理、重连与并发

非空服务器 SOCKS5 代理优先于已启用的全局代理。代理认证连接尝试失败时记录 `proxy_error.log` 并尝试直连。但**主机密钥探测发生在回退代码块之前**，代理探测失败会终止本轮连接，不会转直连。没有实现代理认证字段或独立代理超时。

代理 SSH 认证使用指定的 `key` 和可选的 `key_password`，未设置私钥时使用登录密码；不自动查找 agent 或默认私钥，也不在本地交互询问凭据。私钥加载错误和认证未完成都会进入上述直连回退流程，直连时 Paramiko 还可能尝试 agent 或默认私钥。

连接周期失败后可启动守护重连线程。连续失败少于五次时等待 `reconnect_interval`，从第五次起改为等待 60 秒。显式请求即使在冷却期也会立即尝试。`auto_reconnect: false` 关闭后台重试，也关闭通道打开失败后的自动重试。线程随进程结束，短命 CLI 不是常驻重连服务。

连接池在每个进程内按归一化服务器名称缓存一个连接。已建立连接支持独立命令通道，但同一连接的建立过程会串行，因此重连可能让该服务器的其他请求等待。stdio MCP 使用八个请求线程；HTTP 使用线程化服务器。

### 超时与 sudo

CLI 选项默认值见 [CLI 参考](cli.md)，MCP 参数默认值见 [SKILL.mcp.md](../SKILL.mcp.md)。对具有正数 `timeout` 参数 `t` 的 MCP 直通工具，实际转发值为：

```text
max(1, t - min(5, t * 0.1))
```

例如 300 变成 295，30 变成 27。这是为响应留余量，不是测得的客户端截止时间，也不保证整个请求时长。`None`/0 原样传递，命令执行再使用服务器超时。SFTP 超时作用于通道，不是整次传输的截止时间；SFTP 辅助方法不会把 0 转成服务器超时。多步骤传输另有固定的辅助命令超时。别名超时、任务时限和文本读写不使用该 MCP 调整。

普通命令超时后关闭通道并返回 `-1`，远端进程可能仍在运行。sudo 命令使用 `sudo -S -p '' bash -c ...`，密码从通道 stdin 传递，不放在 argv 中。提权后的 shell 通过 `exec </dev/null` 将命令输入与 sudo 密码输入隔离，即使 sudo 跳过密码提示也不会把残留密码传给命令。后台 sudo 任务使用下文的临时密码文件协议。

<a id="transfers"></a>
## 传输与文本语义

### 文件、脚本、覆盖与去重

- 上传接受单个本地文件，不支持递归上传目录。脚本上传目标为 `<scripts_dir>/<script_name>`，请求执行权限，也可上传后执行。脚本名可使用安全的相对子路径。
- 下载支持文件和目录。`download-file` 委托同一实现，不会单独拒绝目录。递归下载保留目录结构，以正则搜索匹配单个文件名；深度超过 48 时停止递归，根深度为 0。文件被拒绝或超过深度会产生汇总的非零结果。
- 默认允许覆盖。禁止覆盖时，上传检查远端文件是否存在；下载拒绝已有本地目标，也包括已有目录根。这不是原子性的“仅新建”保证。批量上传遇到已有文件会计为失败，不是成功跳过。
- 批量别名上传在本次调用内用 MD5 对本地内容去重；后续重复文件计为失败。这既不是远端同步，也不是安全哈希校验。
- 非 sudo 上传可在 bash 服务器上把可执行文件设为 0755，否则按 SFTP/服务器创建规则处理。sudo bash 上传先暂存到 `/tmp` 再移动：覆盖时恢复目标原属主和权限；新建时采用父目录的属主、属组，权限为 0755。`executable=false` 不会改变 sudo 新文件的这一权限。
- sudo 下载先复制到唯一的 `/tmp` 暂存路径，将暂存副本交给登录用户，再下载并尝试清理。不会修改源文件的属主和权限。

bash 暂存路径含随机后缀，但没有独占预留，也不保证私密权限。sudo 上传安装成功时会把暂存文件移动到目标；上传或安装失败可能留下文件。下载和读取会尝试删除暂存文件，但进入清理流程前的暂存失败仍可能留下文件。

### 文本读写

读取按字节偏移进行，默认 65536 字节，正数请求上限为 **1 MiB（1048576 字节）**。`max_bytes=0` 使用默认值。结果包含 `size`、`offset`、`next_offset`、`eof` 和文本 stdout；MCP 在文本摘要中显示分页字段，CLI 在 stderr 提示继续位置。MCP 显式 null 的偏移和大小使用默认值。

包含 NUL 字节时拒绝读取。到 EOF 时，无效 UTF-8 会报错；未到 EOF 的分页会忽略无效序列。**当前限制：**`next_offset` 按实际读取的原始字节前进，也包含已丢弃的半个 UTF-8 字符。因此跨多字节字符分页可能丢字。需要完整保留文本时应下载文件，不应拼接分页结果；二进制内容也应下载。

写入将内容编码为 UTF-8。非 sudo 覆盖保留原属主和权限；新文件在支持 chmod 时请求 0644，追加使用 SFTP 追加模式。sudo 写入会使用**本地临时文件**，再走前述 sudo 上传安装路径。sudo 追加先读完整旧文本再重写，不是原子操作，不适合正在并发写入的日志。写入没有对应的 1 MiB 上限，大内容应使用文件传输。MCP `content` 必填且拒绝空字符串，CLI 标准输入可以为空。

<a id="jobs"></a>
## 后台任务协议

bash 服务器需有 `setsid`、`nohup` 和包装脚本使用的辅助命令；任务时限非零时还需 `timeout`。任务 ID 形如 `job-YYYYMMDD-HHMMSS-<六位十六进制字符>`。

`JobStore.start` 先过滤用户命令，写入 `cmd`、JSON `meta`，为 `wrapper.sh` 请求 0700 权限，再用 `setsid nohup bash` 启动。返回前探测 PID 或退出标记；启动响应只确认包装脚本已启动，不代表任务成功完成。状态保存在 `<jobs_dir>/<id>/`，独立于 MCP 进程。

| 文件或状态 | 含义 |
|---|---|
| `cmd`、`meta`、`wrapper.sh` | 命令、标签/时间/权限/目录/时限元数据、包装脚本 |
| `pid`、`out.log`、`err.log` | 包装脚本 PID 与输出流 |
| `exit` | 从 `exit.tmp` 原子改名而来，优先判定为 `exited` 并附退出码 |
| `killed` | 终止标记；没有退出标记且未进入存活 PID 分支时，判定为 `killed` |
| `running` | PID 存活，且命令行包含任务 ID |
| `lost` | 未识别到完成标记或匹配的存活包装脚本 |

状态查询读取元数据、判断状态并读取每份日志尾部，默认 100 行，范围限制为 1–1000，0 使用默认值。任务超时非零时限制命令存活时长，0 不限。远端状态可跨客户端断连和重启保留，但不保证跨服务器重启，也不能在任务目录删除后恢复。

终止时先查状态、写入 `killed`，向包装脚本进程组发送 TERM，最多等待五次一秒，再在 PID 仍存活时升级为 KILL。即使是 sudo 任务，信号仍以登录用户发送，不能保证终止 root 子进程。涉及提权任务时应检查最终状态和远端进程。

`clean_days > 0` 用 `find ... -name exit -mtime +N` 删除所在任务目录，遵循 `find` 按整天计算的语义。只清理有退出标记的任务，不是所有 `killed`/`lost` 任务。清理具有破坏性，尽管 `ssh_job_list` 当前仍带只读工具注解。列表包含 ID、状态、退出码、命令预览，不含人工标签。

sudo 启动通过 SFTP 写入 `pass`，新建文件请求 0600 权限，已有文件保留原权限；包装脚本在执行命令前读取并尝试删除它。权限设置在写入之后才执行，共享写入方法容忍 chmod 错误；启动失败也可能留下密码文件。因此不能保证秘密从未短暂可读，应给远端目录设置严格权限和 umask。密码经 `printf '%s\n' "$SP" | sudo -S` 管道传递，提权后的 shell 在执行任务前将标准输入重定向到 `/dev/null`。即使 sudo 因凭据缓存或 NOPASSWD 不读取密码，残留密码也不会进入任务输入。非 sudo 任务同样从 `/dev/null` 读取标准输入；两种分支均不等待客户端交互输入。状态查询按已存 sudo 标记读取状态和日志。日志由登录用户的包装脚本打开，并非天然归 root 所有。

<a id="http"></a>
## MCP HTTP 语义

启动选项和注册见 [SKILL.mcp.md](../SKILL.mcp.md)。本实现支持 JSON POST 响应，不支持服务端主动 SSE 推送或可恢复事件流。

- 默认端点为 `http://127.0.0.1:8802/mcp`。`--path` 与 URL 路径精确匹配，忽略查询字符串；配置时需带开头的 `/`。
- 先发送一条带 ID 的独立 `initialize` 请求。成功响应通过头部返回 `Mcp-Session-Id`；后续 POST（包括通知）都带上它。批量请求中的初始化不走同一会话头创建路径，因此应独立初始化。
- 会话保存在内存，无过期机制，重启后丢失。缺失或未知会话返回 HTTP 404。对端点发送 DELETE 并带会话头，可删除会话：存在返回 200，否则 404。删除不会取消 SSH 命令或任务。
- 需要响应的 POST 返回 HTTP 200 JSON，也包括 JSON-RPC/工具错误。无需响应的通知返回空 202。非法 JSON 返回 400，未知路径返回 404，GET 返回 405，没有 SSE 流。
- 如果提供 `Mcp-Protocol-Version`，必须是 `2025-11-25`、`2025-06-18`、`2025-03-26`、`2024-11-05` 之一，否则返回 400。初始化接受支持的版本，否则选择最新版本。
- 设置 `--token` 后，POST、DELETE 必须带准确的 `Authorization: Bearer <token>`，否则返回 401。绑定非回环地址必须有非空 token；启动检查只把 `127.0.0.1`、`localhost`、`::1` 认作回环。该检查不保证支持 IPv6 绑定。
- HTTP 为明文，应使用可信本地网络或 HTTPS 反向代理。token 授予服务工具访问权，不提供按服务器授权。没有实现用户级权限、Origin 校验、TLS 或自动 token 管理。token 位于启动参数，可能出现在本地进程列表中。

stdio 每行承载一条 JSON-RPC 消息，并发请求可能乱序完成。MCP 返回文本内容块，不是统一的结构化 JSON 结果；部分工具把 JSON 序列化后放在文本中。操作失败使用 `isError`，非法参数和未知工具返回 JSON-RPC 错误。工具注解只是提示，不是强制访问控制。
