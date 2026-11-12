# 脚本化部署

[English](../../docs/deploy.md) · [CLI](cli.md) · [运行参考](reference.md)

部署使用两个项目专用脚本：`<project>-deploy-local.sh` 负责打包和上传，`<project>-deploy-server.sh` 负责解压、安装或编译、重启和健康检查。项目名用小写英文，以连字符分词。所有远端交互均通过 `python cli.py`，不直接调用 ssh/scp。

## 执行前确认

只对缺失的决策向用户提问，不自行猜测：服务器名称与所在地，direct/compile/docker/static 模式，运行时或构建工具链，部署目录，服务或容器名称，端口，反向代理，最终 URL 与健康检查地址，所需权限，秘密与挂载卷，以及可接受的停机时间和回滚方式。已确认的信息不要重复询问。

| 模式 | 起点 | 必须按项目调整 |
|---|---|---|
| `direct` | [直接部署模板](../../deploy/scripts/server-deploy-direct.sh) | Python/Node/Java/.NET 或自定义安装、重启命令、健康检查 URL |
| `compile` | [编译部署模板](../../deploy/scripts/server-deploy-compile.sh) | Go/Rust/自定义构建、最终二进制名称、已有 systemd 服务 |
| `docker` | [Docker 模板](../../deploy/scripts/server-deploy-docker.sh) | Dockerfile 或 Compose、端口、秘密、挂载卷、健康检查 URL |
| `static` | 改编 direct 模式，没有独立模板 | 构建前端产物、发布、校验并重载 Web 服务、检查最终 URL |

这些是 bash 模板，不支持 Windows 部署，也不会自动创建服务。应先复制、阅读并修改，不要把默认值直接用于生产。构建需要目标工具链与网络，服务定义和部署目录权限也需提前准备。

## 本地脚本约定

1. 只把发布所需文件打包为 `<project>.tar.gz`。排除凭据、`.git`、虚拟环境、依赖缓存、日志和不适用的本地构建产物。保留锁文件和必需的 vendored 依赖，不要一律排除 `vendor/`、`.cargo/`。预构建静态站点应打包已确认的产物目录。
2. 使用所需权限创建部署目录。
3. 用 `upload` 上传定制的服务器脚本，用 `upload-file` 把压缩包上传到 **`<REMOTE_DIR>/code.tar.gz`**，三个模板均从这里读取。
4. 执行 `run-script`，仅在已授权时使用 sudo。设置合适的超时；耗时发布可交给后台任务，并检查退出码和日志。
5. 单独检查外部访问 URL，汇报实际发布的产物或版本及验证证据。容器或服务本地检查不能证明反向代理路由正确。

以下片段供项目本地脚本改编，在项目根目录执行：

```bash
set -euo pipefail
CLI=/absolute/path/ssh-ops/cli.py
SERVER=my-server
REMOTE_DIR=/opt/my-app
python "$CLI" "$SERVER" run "mkdir -p /opt/my-app" -s
python "$CLI" "$SERVER" upload ./my-app-deploy-server.sh -n my-app-deploy-server.sh
python "$CLI" "$SERVER" upload-file ./my-app.tar.gz "$REMOTE_DIR/code.tar.gz" -s
python "$CLI" "$SERVER" run-script my-app-deploy-server.sh -s -t 900
```

例中 shell 命令使用已知常量目录，不要把不可信输入直接插入远端命令。没有 `--overwrite` 选项，上传默认覆盖。完整选项规则见 [CLI 参考](cli.md)。

## 按所在地选择镜像源

中国大陆服务器在生成的服务器脚本中为 pip 配置 `https://pypi.tuna.tsinghua.edu.cn/simple`，为 npm 配置 `https://registry.npmmirror.com`。Docker 使用用户已验证的阿里云仓库或镜像加速地址，不存在保证通用可用的 `mirror.aliyun.com` 加速器。未经授权，不改 Docker daemon 配置，也不重启 Docker。美欧及其他地区默认使用官方源，除非用户另有要求。这些是部署约定，不是 ssh-ops 自动行为。

## 模板保障与边界

- direct 必须配置实际重启命令；未配置或 HTTP 健康检查失败时返回非零。
- compile 先构建候选文件，再替换可执行文件，旧文件保留为 `.old`；要求 systemd 重启与状态检查成功。构建失败不会替换原可执行文件。但这不是整个项目的事务式发布，重启失败也不会自动回滚。
- Docker 先构建，再停止旧容器；进入替换阶段后，启动失败仍可能停机，且没有自动回滚。容器或服务状态与已配置的 HTTP 检查都必须通过。Compose 路径使用 `docker-compose` 命令，需预装或按环境修改。
- 解压覆盖同名文件，但不会删除新版本已移除的旧文件。需要干净发布或可靠回滚时，应采用版本目录与明确的切换方案。
- 健康检查在有限时间内重试，最终失败会返回非零。应按应用设置检查地址和间隔；无关进程返回 200 不能证明发布正确。

## 故障排查

用 CLI `run` 检查连接、`df -h`、工具链版本和服务日志，日志也可用 `read-file` 或下载。Docker 构建在支持时使用 `--progress=plain`，保留完整失败输出，不要接 `tail` 隐藏过程。`tail` 会读取输入，但最后若干行通常要到 EOF 才显示，因而看不到构建进度。解压失败时，先查压缩包位置和脚本中的 `REMOTE_DIR` 是否一致。SSH 本地超时不代表部署停止，重试前先查任务或进程。
