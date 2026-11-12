# 部署

[中文](README.zh-CN.md) | [English](README.md)

在本仓库 CLI 之上的脚本化部署：本地打包 → 上传 → 服务器脚本执行 → 健康检查。
全程不手敲 ssh/scp。

## 流程

```
本地                                       服务器
  │                                          │
  ├─ tar czf 项目.tar.gz ─────────────────→  │
  ├─ 上传  项目-deploy-server.sh ──────────→  │ scripts_dir/
  ├─ 上传  项目.tar.gz ───────────────────→  │
  ├─ run-script 项目-deploy-server.sh ────→  │ 解压 → 装依赖/编译 → 重启服务 → 健康检查
  ←└─ ✅ 部署完成                                │
```

1. **收集信息**：部署前先与用户确认目标服务器、部署模式、部署目录、端口、
   反向代理与访问地址、服务器所在地（决定镜像源）。
2. **生成脚本**：`{项目名}-deploy-local.sh`（本地跑）与
   `{项目名}-deploy-server.sh`（服务器跑）；项目名用小写连字符英文。
3. **执行**：智能体直接运行本地脚本，打包、上传、部署、验证一气呵成。
4. **健康检查**：服务器脚本在退出前验证服务状态。

与服务器的所有交互一律走本仓库 CLI（`python cli.py`），不直接调 ssh——
sudo、代理回退、超时、路径允许列表这些能力都在 CLI 里。

## 部署模式

| 模式 | 适用 | 模板 |
|------|------|------|
| `direct` | Python / Node / Java / .NET Core 直接运行 | `scripts/server-deploy-direct.sh` |
| `compile` | Go / Rust，在服务器上编译（保证架构匹配） | `scripts/server-deploy-compile.sh` |
| `docker` | 任意项目，容器化 | `scripts/server-deploy-docker.sh` |
| `static` | Vue/React 静态产物，Nginx 等 | direct 模式去掉运行时步骤 |

## 本地脚本约定

`{项目名}-deploy-local.sh` 依次完成：

1. 打包项目为 `{项目名}.tar.gz`（排除 `.git`、`__pycache__` 等）
2. `python cli.py <服务器> upload {项目名}-deploy-server.sh -n {项目名}-deploy-server.sh --overwrite`
3. `python cli.py <服务器> upload {项目名}.tar.gz -n {项目名}.tar.gz --overwrite`
4. `python cli.py <服务器> run-script {项目名}-deploy-server.sh [-s]`
5. `python cli.py <服务器> run "<健康检查命令>"` 并汇报结果

## 加速镜像

服务器在中国大陆时，服务器脚本内配置镜像源：pip 用清华源
（`https://pypi.tuna.tsinghua.edu.cn/simple`）、npm 用
`https://registry.npmmirror.com`、Docker 用阿里云镜像；美欧服务器用官方源。
各模式完整脚本模板见 [REFERENCE.md](REFERENCE.md)。
