#!/bin/bash
# =============================================================================
# Server Deploy Script — Docker Mode
# =============================================================================
# For containerized deployments.
# Upload code.tar.gz to REMOTE_DIR, this script builds Docker image and runs.
#
# ⚠️  CUSTOMIZE THESE VALUES:
#   REMOTE_DIR     - deployment directory, e.g. /opt/my-app
#   CONTAINER_NAME - container name, e.g. my-app
#   IMAGE_NAME     - image name, e.g. my-app:latest
#   PORT           - service port, e.g. 8080
#   DOCKER_COMPOSE - use docker-compose instead of plain docker, true/false
# =============================================================================
set -eo pipefail

# ===================== Configuration =====================
REMOTE_DIR="/opt/my-app"
CONTAINER_NAME="my-app"
IMAGE_NAME="my-app:latest"
PORT=8080
DOCKER_COMPOSE=false  # Set true to use docker-compose
HEALTH_URL="http://localhost:$PORT/"
HEALTH_ATTEMPTS=10
HEALTH_INTERVAL=3

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

# 3. Build before stopping the running release.
echo "[2/5] Building image..."
cd "$REMOTE_DIR"
if "$DOCKER_COMPOSE"; then
  docker-compose build --no-cache
else
  docker build --progress=plain -t "$IMAGE_NAME" .
fi

# 4. Replace only after a successful build. No automatic rollback.
echo "[3/5] Stopping old container..."
if "$DOCKER_COMPOSE"; then
  docker-compose down
else
  if docker container inspect "$CONTAINER_NAME" >/dev/null 2>&1; then
    docker stop "$CONTAINER_NAME"
    docker rm "$CONTAINER_NAME"
  fi
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
healthy=false
for ((attempt=1; attempt<=HEALTH_ATTEMPTS; attempt++)); do
  running=true
  if "$DOCKER_COMPOSE"; then
    containers=$(docker-compose ps -q)
    if [ -z "$containers" ]; then
      running=false
    else
      for id in $containers; do
        if [ "$(docker inspect --format '{{.State.Running}}' "$id")" != true ]; then
          running=false
        fi
      done
    fi
  elif [ "$(docker inspect --format '{{.State.Running}}' "$CONTAINER_NAME")" != true ]; then
    running=false
  fi
  if "$running" && curl --connect-timeout 3 --max-time 5 -fsS "$HEALTH_URL" >/dev/null 2>&1; then
    healthy=true
    break
  fi
  sleep "$HEALTH_INTERVAL"
done
if ! "$healthy"; then
  echo "Error: container/service or HTTP health check failed: $HEALTH_URL" >&2
  if "$DOCKER_COMPOSE"; then
    docker-compose logs --tail=20 || true
  else
    docker logs "$CONTAINER_NAME" --tail 20 || true
  fi
  exit 1
fi

echo "=== Deploy Complete ==="
