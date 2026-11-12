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
    echo "  Custom: add your install commands here"
    ;;
esac

# 4. Restart service
echo "[3/4] Restarting service..."
# Choose one method:

# Method A: systemd
# systemctl restart "$SERVICE_NAME"

# Method B: pm2 (Node.js)
# pm2 restart "$SERVICE_NAME" || pm2 start index.js --name "$SERVICE_NAME"

# Method C: supervisor
# supervisorctl restart "$SERVICE_NAME"

# Method D: screen (simple)
# pkill -f "python app.py" 2>/dev/null || true
# screen -dmS "$SERVICE_NAME" bash -c "cd $REMOTE_DIR && python app.py"

echo "  Add your restart command above"

# 5. Health check
echo "[4/4] Health check..."
sleep 3

# Adjust health check URL/method as needed
if curl -sf "http://localhost:$PORT/" >/dev/null 2>&1; then
  echo "  ✅ Deploy OK"
else
  echo "  ❌ Health check failed (port $PORT)"
  exit 1
fi

echo "=== Deploy Complete ==="
