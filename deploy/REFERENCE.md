# SSH Deploy — Reference

## 部署信息收集

部署前必须通过 `question` 工具向用户确认以下信息：

| 信息 | 说明 | 示例 |
|------|------|------|
| 目标服务器 | SSH 别名 | `bit-run-web-1` |
| 服务器所在地 | 用于配置加速镜像 | 中国大陆 / 美国 / 欧洲 |
| 部署模式 | direct / compile / docker / static | `docker` |
| 项目类型 | Python / Node / Java / .NET Core / Go / Rust / 静态网页 | `Python` |
| 部署目录 | 远程目录路径 | `/opt/my-app` |
| 服务端口 | 端口号（1-65535） | `8080` |
| 反向代理 | CDN/Nginx 等 | `https://example.com` |
| 访问地址 | 最终 URL | `https://jg.gzbit.cn` |

---

## 加速镜像配置

根据服务器所在地，在服务器脚本中配置相应镜像源：

| 所在地 | PIP | npm | Docker |
|--------|-----|-----|--------|
| 中国大陆 | `https://pypi.tuna.tsinghua.edu.cn/simple` | `https://registry.npmmirror.com` | `https://mirror.aliyun.com` |
| 美国/欧洲 | 官方源 | 官方源 | 官方源 |
| 其他 | 官方源 | 官方源 | 官方源 |

---

## 部署模式模板

脚本命名规范：`{项目名}-deploy-server.sh`

### 1. 直接部署 (Python/Node/Java/.NET Core)

```bash
#!/bin/bash
set -eo pipefail

REMOTE_DIR="/opt/my-app"
SCRIPTS_DIR="/home/bit/scripts"
SERVICE_NAME="my-app"
PORT=8080

# 1. 准备目录
mkdir -p "$REMOTE_DIR"

# 2. 解压代码包
if [ -f "$SCRIPTS_DIR/myapp.tar.gz" ]; then
  mv "$SCRIPTS_DIR/myapp.tar.gz" "$REMOTE_DIR/code.tar.gz"
  cd "$REMOTE_DIR"
  tar xzf code.tar.gz -C .
  rm -f code.tar.gz
fi

# 3. 安装依赖
cd "$REMOTE_DIR"
pip install --no-cache-dir -r requirements.txt

# 4. 重启服务
systemctl restart "$SERVICE_NAME"

# 5. 健康检查
sleep 3
if curl -sf "http://localhost:$PORT/health" >/dev/null 2>&1; then
  echo "✅ 部署成功"
else
  echo "❌ 健康检查失败"
  exit 1
fi
```

### 2. 编译部署 (Go/Rust)

```bash
#!/bin/bash
set -eo pipefail

REMOTE_DIR="/opt/my-app"
SCRIPTS_DIR="/home/bit/scripts"
BINARY_NAME="my-app"
SERVICE_NAME="my-app"

# 1. 准备目录
mkdir -p "$REMOTE_DIR"

# 2. 解压代码包
if [ -f "$SCRIPTS_DIR/myapp.tar.gz" ]; then
  mv "$SCRIPTS_DIR/myapp.tar.gz" "$REMOTE_DIR/code.tar.gz"
  cd "$REMOTE_DIR"
  tar xzf code.tar.gz -C .
  rm -f code.tar.gz
fi

# 3. 编译
cd "$REMOTE_DIR"
go build -o "$BINARY_NAME" .

# 4. 原子替换并重启
if [ -f "$BINARY_NAME.old" ]; then
  rm -f "$BINARY_NAME.old"
fi
cp "$BINARY_NAME" "$BINARY_NAME.new"
mv -f "$BINARY_NAME.new" "$BINARY_NAME"
systemctl restart "$SERVICE_NAME"

# 5. 健康检查
sleep 3
if systemctl is-active --quiet "$SERVICE_NAME"; then
  echo "✅ 部署成功"
else
  echo "❌ 服务启动失败"
  exit 1
fi
```

### 3. Docker 部署

```bash
#!/bin/bash
set -eo pipefail

REMOTE_DIR="/opt/my-app"
SCRIPTS_DIR="/home/bit/scripts"
CONTAINER_NAME="my-app"
IMAGE_NAME="my-app:latest"
PORT=8080

# 1. 准备目录
mkdir -p "$REMOTE_DIR"

# 2. 解压代码包
if [ -f "$SCRIPTS_DIR/myapp.tar.gz" ]; then
  mv "$SCRIPTS_DIR/myapp.tar.gz" "$REMOTE_DIR/code.tar.gz"
  cd "$REMOTE_DIR"
  tar xzf code.tar.gz -C .
  rm -f code.tar.gz
fi

# 3. 停止旧容器
docker stop "$CONTAINER_NAME" 2>/dev/null || true
docker rm "$CONTAINER_NAME" 2>/dev/null || true

# 4. 构建镜像（--progress=plain 实时输出，禁止使用 tail 管道）
cd "$REMOTE_DIR"
docker build --progress=plain -t "$IMAGE_NAME" .

# 5. 启动容器
docker run -d \
  --name "$CONTAINER_NAME" \
  --restart unless-stopped \
  -p "${PORT}:${PORT}" \
  "$IMAGE_NAME"

# 6. 健康检查
sleep 5
if docker ps --filter "name=$CONTAINER_NAME" --filter "status=running" | grep -q "$CONTAINER_NAME"; then
  echo "✅ 部署成功"
  docker ps --filter "name=$CONTAINER_NAME"
else
  echo "❌ 容器启动失败"
  docker logs "$CONTAINER_NAME" --tail 20
  exit 1
fi
```

### 4. 静态网页部署 (Vue/React 等)

```bash
#!/bin/bash
set -eo pipefail

REMOTE_DIR="/opt/myapp-static"
SCRIPTS_DIR="/home/bit/scripts"

# 1. 准备目录
mkdir -p "$REMOTE_DIR"

# 2. 解压代码包（dist 目录）
if [ -f "$SCRIPTS_DIR/myapp.tar.gz" ]; then
  mv "$SCRIPTS_DIR/myapp.tar.gz" "$REMOTE_DIR/code.tar.gz"
  cd "$REMOTE_DIR"
  tar xzf code.tar.gz -C .
  rm -f code.tar.gz
fi

# 3. 配置 Nginx（如需要）
cat > /etc/nginx/sites-available/myapp <<EOF
server {
    listen 80;
    server_name _;
    root $REMOTE_DIR/dist;
    index index.html;
    location / {
        try_files \$uri \$uri/ /index.html;
    }
}
EOF
nginx -t && systemctl reload nginx

# 4. 健康检查
sleep 2
if curl -sf "http://localhost/" >/dev/null 2>&1; then
  echo "✅ 部署成功"
else
  echo "❌ 健康检查失败"
  exit 1
fi
```

---

## 常见排除模式

| 项目类型 | 排除项 |
|----------|--------|
| Python | `__pycache__`, `.pytest_cache`, `.venv/`, `*.pyc`, `tests/` |
| Node.js | `node_modules/`, `.npm/`, `.cache/` |
| .NET Core | `bin/`, `obj/`, `.vs/`, `.vscode/` |
| Go | `vendor/`, `*.exe`, `.cache/` |
| Rust | `target/`, `.cargo/` |
| 静态网页 | `node_modules/`, `.git/`, `src/`（仅保留 dist/） |
| 通用 | `.git/`, `.DS_Store`, `*.log` |

---

## 故障排查

### 上传失败
```bash
# 检查连接
python cli.py <server> run "echo test"
# 检查磁盘空间
python cli.py <server> run "df -h /"
```

### 脚本执行失败
```bash
# 检查脚本内容
python cli.py <server> run "cat /home/<user>/scripts/{项目名}-deploy-server.sh"
# 检查权限
python cli.py <server> run "ls -la /home/<user>/scripts/"
```

### Docker 构建失败
```bash
# 检查 Dockerfile
python cli.py <server> run "ls -la /opt/my-app/Dockerfile"
# 检查磁盘空间
python cli.py <server> run "df -h / && docker system df"
```

**Docker 构建实时输出**：
- `docker build` 默认使用 buildkit JSON 输出，无法实时查看构建进度
- 添加 `--progress=plain` 参数获取实时输出：`docker build --progress=plain -t myimage .`
- **切勿使用管道+tail**（如 `| tail -5`），会导致输出被缓冲直到命令完成
