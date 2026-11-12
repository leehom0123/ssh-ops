# Scripted deployment

[中文](deploy.zh-CN.md) · [CLI](cli.md) · [Runtime reference](reference.md)

Deployment uses two project-specific scripts: `<project>-deploy-local.sh` packages and uploads; `<project>-deploy-server.sh` extracts, installs/builds, restarts, and checks health. Use lowercase hyphenated project names. All remote interaction goes through `python cli.py`, not raw ssh/scp.

## Confirm before executing

Ask for missing decisions, rather than guessing: server name and region; direct/compile/docker/static mode; runtime/build toolchain; deployment directory; service/container name; ports; reverse proxy; final URL and health endpoint; required privilege; secrets/volumes; and acceptable downtime/rollback procedure. Do not repeat questions already answered.

| Mode | Starting point | Required customization |
|---|---|---|
| `direct` | [direct template](../deploy/scripts/server-deploy-direct.sh) | Python/Node/Java/.NET or custom installation, restart command, health URL |
| `compile` | [compile template](../deploy/scripts/server-deploy-compile.sh) | Go/Rust/custom build, final binary name, existing systemd service |
| `docker` | [Docker template](../deploy/scripts/server-deploy-docker.sh) | Dockerfile or Compose, ports, secrets, volumes, health URL |
| `static` | Adapt direct mode; no separate template | Build frontend assets, publish output, validate/reload web server, check final URL |

These are bash templates, not Windows deployment support or automatic service provisioning. Inspect and customize a copy; do not run unchanged defaults on production. Builds need the target toolchain and network access. Existing service definitions and privileged directory permissions must be prepared.

## Local script contract

1. Package only the required release files as `<project>.tar.gz`. Exclude credentials, `.git`, virtual environments, dependency caches, logs and platform-specific build output. Preserve lockfiles and required vendored dependencies; do not exclude `vendor/` or `.cargo/` blindly. For prebuilt static sites, package the reviewed output directory.
2. Create the deployment directory with the required privilege.
3. Upload the customized server script using `upload`; upload the archive using `upload-file` to **`<REMOTE_DIR>/code.tar.gz`**, which all three templates expect.
4. Execute `run-script`, with sudo only when authorized. Set a suitable timeout or use a background job for a long release; inspect the resulting exit code and logs.
5. Check the externally accessible URL separately and report the deployed artifact/version and evidence. A local container/service check alone does not verify reverse-proxy routing.

Example fragments for a customized local script, run from the project root:

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

The example uses a known constant directory in the shell payload. Do not insert untrusted input into remote command strings. There is no `--overwrite`: upload overwrites by default. Full flag rules belong in [CLI reference](cli.md).

## Regional package sources

For mainland-China servers, configure pip to use `https://pypi.tuna.tsinghua.edu.cn/simple` and npm to use `https://registry.npmmirror.com` in the generated server script. For Docker use the user's verified Aliyun registry/mirror endpoint; there is no universal guaranteed `mirror.aliyun.com` accelerator. Do not rewrite daemon configuration or restart Docker without authorization. US/EU and other regions use official sources unless the user specifies otherwise. These are deployment policy choices, not automatic ssh-ops behaviour.

## Template guarantees and limits

- Direct mode requires an explicit restart command and fails if none is supplied or HTTP health checks fail.
- Compile mode builds a candidate before replacing the executable, retains the prior binary as `.old`, and requires systemd restart/status success. Candidate build failure leaves the previous executable in place. It is not a transactional release of the whole project, and does not automatically roll back a failed restart.
- Docker mode builds before stopping the existing container. Once replacement starts, runtime failure can still cause downtime; there is no automatic rollback. Both container/service state and configured HTTP health must pass. Compose support uses the `docker-compose` command; install it or adapt the script to your environment.
- Extraction overwrites files but does not remove files deleted from the new release. Use release directories and a deliberate switch strategy when clean deployment/rollback is required.
- Health checks retry for a bounded period and fail with a nonzero exit code. Tune the endpoint/retry interval for the app; an unrelated process returning 200 is not proof of a correct release.

## Troubleshooting

Use CLI `run` to check connection, `df -h`, toolchain versions and service logs; use `read-file` or download for logs. For Docker builds use `--progress=plain` when supported and retain full failure output rather than piping it to `tail`. A `tail` command streams input but shows its final lines at EOF, so it hides build progress. Check package placement and script `REMOTE_DIR` first when extraction fails. Do not interpret a local SSH timeout as proof that deployment stopped; inspect the job/process before retrying.
