#!/bin/bash
# Install and enable MDDP Docker systemd service for Linux autostart on system boot

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SERVICE_NAME="mddp-docker.service"
TARGET_SERVICE_PATH="/etc/systemd/system/$SERVICE_NAME"
CURRENT_USER="$(whoami)"

echo "=========================================================="
echo "   MDDP Docker Systemd Service Autostart Installer (Linux)"
echo "=========================================================="
echo "[SYSTEM] Project Root : $PROJECT_ROOT"
echo "[SYSTEM] Service User : $CURRENT_USER"

if [ "$EUID" -ne 0 ]; then
    echo "[WARNING] Systemd service installation requires root permissions."
    echo "[SYSTEM] Re-executing with sudo..."
    exec sudo "$0" "$@"
fi

# Ensure Docker daemon auto-starts on system boot
echo "[SYSTEM] Enabling Docker daemon auto-start via systemctl..."
systemctl enable docker

# Generate temporary systemd unit file with resolved paths
TMP_SERVICE="/tmp/$SERVICE_NAME"
sed -e "s|__SERVICE_USER__|$CURRENT_USER|g" \
    -e "s|__PROJECT_ROOT__|$PROJECT_ROOT|g" \
    "$SCRIPT_DIR/mddp-docker.service" > "$TMP_SERVICE"

# Copy service unit file to systemd directory
cp "$TMP_SERVICE" "$TARGET_SERVICE_PATH"
chmod 644 "$TARGET_SERVICE_PATH"
rm -f "$TMP_SERVICE"

# Make execution scripts executable
chmod +x "$PROJECT_ROOT/deploy/linux/docker-run.sh"
chmod +x "$PROJECT_ROOT/deploy/linux/docker-stop.sh"

# Reload systemd manager configuration
systemctl daemon-reload

# Enable service to start automatically on system boot
systemctl enable "$SERVICE_NAME"

echo "=========================================================="
echo "[SUCCESS] MDDP Docker systemd service installed & enabled!"
echo "[SYSTEM] Service Unit File: $TARGET_SERVICE_PATH"
echo "[SYSTEM] To start service now, run  : sudo systemctl start mddp-docker"
echo "[SYSTEM] To check service status, run: sudo systemctl status mddp-docker"
echo "[SYSTEM] To stop service, run        : sudo systemctl stop mddp-docker"
echo "=========================================================="
