#!/bin/bash
# =============================================================================
# Server Deploy Script — Compile Mode (Go/Rust)
# =============================================================================
# For projects that need compilation on server.
# Upload code.tar.gz to REMOTE_DIR, this script extracts, builds, and deploys.
#
# Customize: REMOTE_DIR, BINARY_NAME, BUILD_TYPE, SERVICE_NAME
# =============================================================================
set -eo pipefail

# ===================== Configuration =====================
REMOTE_DIR="/opt/my-app"
BINARY_NAME="my-app"
SERVICE_NAME="my-app"
# Set to: go | rust | custom
BUILD_TYPE="go"
HEALTH_ATTEMPTS=10
HEALTH_INTERVAL=2

# ===================== Deploy =====================
echo "=== Compile Deploy ==="
echo "Dir: $REMOTE_DIR | Binary: $BINARY_NAME"

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

# 3. Build
echo "[2/4] Building..."
cd "$REMOTE_DIR"
CANDIDATE=$(mktemp "$REMOTE_DIR/.deploy-candidate.XXXXXX")
trap 'rm -f -- "$CANDIDATE"' EXIT
case "$BUILD_TYPE" in
  go)
    go build -o "$CANDIDATE" .
    ;;
  rust)
    cargo build --release
    cp "target/release/$BINARY_NAME" "$CANDIDATE"
    ;;
  *)
    echo "Error: configure custom build before deployment" >&2
    exit 1
    ;;
esac

if [ ! -s "$CANDIDATE" ]; then
  echo "  Error: build failed, binary not found"
  exit 1
fi
chmod 755 "$CANDIDATE"
echo "  Built: $BINARY_NAME ($(du -h "$CANDIDATE" | cut -f1))"

# 4. Atomic swap & restart
echo "[3/4] Swapping binary..."
# Backup old binary
if [ -f "$BINARY_NAME" ]; then
  cp -p -- "$BINARY_NAME" "$BINARY_NAME.old"
fi
mv -f -- "$CANDIDATE" "$BINARY_NAME"

# Restart service
echo "[4/4] Restarting service..."
# systemd
systemctl restart "$SERVICE_NAME"

# 5. Health check
echo "  Verifying..."
healthy=false
for ((attempt=1; attempt<=HEALTH_ATTEMPTS; attempt++)); do
  if systemctl is-active --quiet "$SERVICE_NAME"; then
    healthy=true
    break
  fi
  sleep "$HEALTH_INTERVAL"
done
if ! "$healthy"; then
  echo "Error: service is not active: $SERVICE_NAME" >&2
  exit 1
fi

echo "=== Deploy Complete ==="
