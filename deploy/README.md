# Deploy

[中文](README.zh-CN.md) | English

Scripted deployment on top of this repo's CLI: package locally → upload → run
server script → health check. No manual SSH, no scp.

## How it works

```
Local                                   Server
  │                                        │
  ├─ tar czf project.tar.gz ────────────→  │
  ├─ upload  project-deploy-server.sh ──→  │ scripts_dir/
  ├─ upload  project.tar.gz ────────────→  │
  ├─ run-script project-deploy-server.sh → │ unpack → install/build → restart → health check
  ←└─ ✅ deployed                               │
```

1. **Collect info** — confirm server, mode, port, paths with the user first.
2. **Generate scripts** — `{project}-deploy-local.sh` (runs here) and
   `{project}-deploy-server.sh` (runs there), project name in lowercase
   hyphenated English.
3. **Execute** — run the local script; it does packaging, upload, deploy and
   verification end to end.
4. **Health check** — the server script verifies the service before exiting.

All server interaction goes through this repo's CLI (`python cli.py`), never
raw ssh/scp, so sudo, proxy fallback, timeouts and the allow-list apply.

## Deploy modes

| Mode | Use case | Template |
|------|----------|----------|
| `direct` | Python / Node / Java / .NET Core, run in place | `scripts/server-deploy-direct.sh` |
| `compile` | Go / Rust, build on the server (matches its arch) | `scripts/server-deploy-compile.sh` |
| `docker` | any project, containerized | `scripts/server-deploy-docker.sh` |
| `static` | Vue/React builds, nginx etc. | direct mode without the runtime steps |

## Local script contract

`{project}-deploy-local.sh` must:

1. package the project as `{project}.tar.gz` (exclude `.git`, `__pycache__`, …)
2. `python cli.py <server> upload {project}-deploy-server.sh -n {project}-deploy-server.sh --overwrite`
3. `python cli.py <server> upload {project}.tar.gz -n {project}.tar.gz --overwrite`
4. `python cli.py <server> run-script {project}-deploy-server.sh [-s]`
5. `python cli.py <server> run "<health check>"` and report the result

## Regional mirrors

Mainland-China servers should use mirrors inside the server script:
pip → `https://pypi.tuna.tsinghua.edu.cn/simple`, npm →
`https://registry.npmmirror.com`, Docker → Aliyun mirror. US/EU servers use
official sources. Full per-mode script templates: [REFERENCE.md](REFERENCE.md).
