#!/bin/bash
# =============================================================================
# Server Deploy Script — Compile Mode (Go/Rust)
# =============================================================================
# For projects that need compilation on server.
# Upload code.tar.gz to REMOTE_DIR, this script extracts, builds, and deploys.
#
# Customize: REMOTE_DIR, BINARY_NAME, BUILD_CMD, SERVICE_NAME
# =============================================================================
set -eo pipefail

# ===================== Configuration =====================
REMOTE_DIR="/opt/my-app"
BINARY_NAME="my-app"
SERVICE_NAME="my-app"
# Set to: go | rust | custom
BUILD_TYPE="go"

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
case "$BUILD_TYPE" in
  go)
    go build -o "$BINARY_NAME" .
    ;;
  rust)
    cargo build --release
    cp "target/release/$BINARY_NAME" .
    ;;
  *)
    echo "  Custom: add your build commands here"
    ;;
esac

if [ ! -f "$BINARY_NAME" ]; then
  echo "  Error: build failed, binary not found"
  exit 1
fi
echo "  Built: $BINARY_NAME ($(du -h "$BINARY_NAME" | cut -f1))"

# 4. Atomic swap & restart
echo "[3/4] Swapping binary..."
# Backup old binary
if [ -f "$BINARY_NAME.old" ]; then
  rm -f "$BINARY_NAME.old"
fi
cp "$BINARY_NAME" "$BINARY_NAME.new"
mv -f "$BINARY_NAME.new" "$BINARY_NAME"

# Restart service
echo "[4/4] Restarting service..."
# systemd
systemctl restart "$SERVICE_NAME" 2>/dev/null || {
  echo "  systemd not available, use custom restart"
  # pkill "$SERVICE_NAME" 2>/dev/null || true
  # nohup ./"$BINARY_NAME" &
}

# 5. Health check
echo "  Verifying..."
sleep 2
if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
  echo "  ✅ Deploy OK"
else
  echo "  ⚠️  Service status unknown (check manually)"
fi

echo "=== Deploy Complete ==="
