#!/bin/bash
# =============================================================================
# Server Deploy Script — Direct Mode (Python/Node/Java)
# =============================================================================
# For projects that run directly on server without compilation.
# Upload code.tar.gz to REMOTE_DIR, this script extracts and deploys.
#
# Usage:
#   1. Upload code.tar.gz to $REMOTE_DIR via CLI
#   2. Run this script on server via CLI
#
# Customize: REMOTE_DIR, PORT, SERVICE_NAME, install commands
# =============================================================================
set -eo pipefail

# ===================== Configuration =====================
REMOTE_DIR="/opt/my-app"
PORT=8080
SERVICE_NAME="my-app"
# Set to: pip | npm | mvn | custom
INSTALL_CMD="pip"
# Required: customize this command; it is executed by bash.
RESTART_CMD=""
HEALTH_URL="http://localhost:$PORT/"
HEALTH_ATTEMPTS=10
HEALTH_INTERVAL=3

if [ -z "$RESTART_CMD" ]; then
  echo "Error: configure RESTART_CMD before deployment" >&2
  exit 1
fi

# ===================== Deploy =====================
echo "=== Direct Deploy ==="
echo "Dir: $REMOTE_DIR | Port: $PORT | Service: $SERVICE_NAME"

# 1. Prepare directory
mkdir -p "$REMOTE_DIR"

# 2. Extract code archive
echo "[1/4] Extracting code..."
if [ -f "$REMOTE_DIR/code.tar.gz" ]; then
  cd "$REMOTE_DIR"
  tar xzf code.tar.gz -C .
  rm -f code.tar.gz
  echo "  Done"
else
  echo "  Error: code.tar.gz not found"
  exit 1
fi

# 3. Install dependencies
echo "[2/4] Installing dependencies..."
cd "$REMOTE_DIR"
case "$INSTALL_CMD" in
  pip)
    if [ -f requirements.txt ]; then
      pip install --no-cache-dir -r requirements.txt
    fi
    ;;
  npm)
    if [ -f package.json ]; then
      npm install --production
    fi
    ;;
  mvn)
    mvn clean package -DskipTests
    ;;
  *)
    echo "Error: configure custom installation before deployment" >&2
    exit 1
    ;;
esac

# 4. Restart service
echo "[3/4] Restarting service..."
# Examples: systemctl restart my-app; pm2 restart my-app;
# supervisorctl restart my-app. Use a project-specific command.
bash -c "$RESTART_CMD"

# 5. Health check
echo "[4/4] Health check..."
healthy=false
for ((attempt=1; attempt<=HEALTH_ATTEMPTS; attempt++)); do
  if curl --connect-timeout 3 --max-time 5 -fsS "$HEALTH_URL" >/dev/null 2>&1; then
    healthy=true
    break
  fi
  sleep "$HEALTH_INTERVAL"
done
if ! "$healthy"; then
  echo "Error: health check failed: $HEALTH_URL" >&2
  exit 1
fi

echo "=== Deploy Complete ==="
