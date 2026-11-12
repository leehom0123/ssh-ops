#!/bin/bash
# =============================================================================
# Server Deploy Script — Docker Mode
# =============================================================================
# For containerized deployments.
# Upload code.tar.gz to REMOTE_DIR, this script builds Docker image and runs.
#
# ⚠️  CUSTOMIZE THESE VALUES:
#   REMOTE_DIR     - 部署目录，如 /opt/my-app
#   CONTAINER_NAME - 容器名称，如 my-app
#   IMAGE_NAME     - 镜像名称，如 my-app:latest
#   PORT           - 服务端口，如 8080
#   DOCKER_COMPOSE - 是否使用 docker-compose，true/false
# =============================================================================
set -eo pipefail

# ===================== Configuration =====================
REMOTE_DIR="/opt/my-app"
CONTAINER_NAME="my-app"
IMAGE_NAME="my-app:latest"
PORT=8080
DOCKER_COMPOSE=false  # Set true to use docker-compose

# ===================== Deploy =====================
echo "=== Docker Deploy ==="
echo "Dir: $REMOTE_DIR | Container: $CONTAINER_NAME | Port: $PORT"

# 1. Prepare directory
mkdir -p "$REMOTE_DIR"

# 2. Extract code archive
echo "[1/5] Extracting code..."
if [ -f "$REMOTE_DIR/code.tar.gz" ]; then
  cd "$REMOTE_DIR"
  tar xzf code.tar.gz -C .
  rm -f code.tar.gz
  echo "  Done"
else
  echo "  Error: code.tar.gz not found"
  exit 1
fi

# 3. Stop old container
echo "[2/5] Stopping old container..."
if "$DOCKER_COMPOSE"; then
  cd "$REMOTE_DIR"
  docker-compose down 2>/dev/null || true
else
  docker stop "$CONTAINER_NAME" 2>/dev/null || true
  docker rm "$CONTAINER_NAME" 2>/dev/null || true
fi
echo "  Done"

# 4. Build & run (--progress=plain for real-time output)
echo "[3/5] Building image..."
cd "$REMOTE_DIR"
if "$DOCKER_COMPOSE"; then
  docker-compose build --no-cache
else
  docker build --progress=plain -t "$IMAGE_NAME" .
fi

echo "[4/5] Starting container..."
if "$DOCKER_COMPOSE"; then
  docker-compose up -d
else
  docker run -d \
    --name "$CONTAINER_NAME" \
    --restart unless-stopped \
    -p "${PORT}:${PORT}" \
    "$IMAGE_NAME"
fi
echo "  Done"

# 5. Health check
echo "[5/5] Health check..."
sleep 5

if "$DOCKER_COMPOSE"; then
  # Check all containers in compose
  if docker-compose ps | grep -q "Up"; then
    echo "  ✅ Containers running"
    docker-compose ps
  else
    echo "  ❌ Container failed"
    docker-compose logs --tail=20
    exit 1
  fi
else
  if docker ps --filter "name=$CONTAINER_NAME" --filter "status=running" | grep -q "$CONTAINER_NAME"; then
    echo "  ✅ Container running"
    docker ps --filter "name=$CONTAINER_NAME"
    
    # Optional: HTTP health check
    if curl -sf "http://localhost:$PORT/" >/dev/null 2>&1; then
      echo "  ✅ HTTP check passed"
    else
      echo "  ⚠️  HTTP check failed (may need more time)"
    fi
  else
    echo "  ❌ Container failed"
    docker logs "$CONTAINER_NAME" --tail 20
    exit 1
  fi
fi

echo "=== Deploy Complete ==="
