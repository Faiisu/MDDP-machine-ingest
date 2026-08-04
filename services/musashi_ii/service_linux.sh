#!/usr/bin/env bash
# ============================================================
#  MUSASHI Telemetry - Linux/macOS Background Service Manager
#
#  Usage:
#    ./service_linux.sh install    # Install as systemd service (Linux)
#                                  # or launchd agent (macOS)
#    ./service_linux.sh start      # Start the service
#    ./service_linux.sh stop       # Stop the service
#    ./service_linux.sh status     # Check service status
#    ./service_linux.sh restart    # Restart the service
#    ./service_linux.sh uninstall  # Remove the service
#    ./service_linux.sh logs       # View log output
# ============================================================

set -euo pipefail

# --- Configuration ---
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT_NAME="read_musashi.py"
CONFIG_FILE="config.json"
LOG_DIR="${PROJECT_DIR}/logs"
VENV_PYTHON="${PROJECT_DIR}/.venv/bin/python"
PID_FILE="${LOG_DIR}/musashi_service.pid"
STDOUT_LOG="${LOG_DIR}/musashi_stdout.log"
STDERR_LOG="${LOG_DIR}/musashi_stderr.log"

# systemd / launchd identifiers
SYSTEMD_SERVICE="musashi-telemetry"
SYSTEMD_UNIT_FILE="/etc/systemd/system/${SYSTEMD_SERVICE}.service"
LAUNCHD_LABEL="com.musashi.telemetry"
LAUNCHD_PLIST="$HOME/Library/LaunchAgents/${LAUNCHD_LABEL}.plist"

# --- Ensure log directory ---
mkdir -p "$LOG_DIR"

# --- Detect Python ---
if [ -x "$VENV_PYTHON" ]; then
    PYTHON="$VENV_PYTHON"
elif command -v python3 &>/dev/null; then
    PYTHON="python3"
elif command -v python &>/dev/null; then
    PYTHON="python"
else
    echo "[ERR] Python not found. Install Python 3.9+ first."
    exit 1
fi

# --- Detect OS ---
OS="$(uname -s)"

# --- Color helpers ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

ok()   { echo -e "  [${GREEN}OK${NC}]   $1"; }
err()  { echo -e "  [${RED}ERR${NC}]  $1"; }
warn() { echo -e "  [${YELLOW}WARN${NC}] $1"; }
info() { echo -e "  [${CYAN}INFO${NC}] $1"; }

header() {
    echo ""
    echo -e "  ${CYAN}=============================================${NC}"
    echo -e "   MUSASHI Telemetry - Background Service"
    echo -e "  ${CYAN}=============================================${NC}"
    echo ""
}

# ============================================================
#  Linux: systemd
# ============================================================

systemd_install() {
    header
    if [ -f "$SYSTEMD_UNIT_FILE" ]; then
        warn "Service '$SYSTEMD_SERVICE' already installed."
        info "Run './service_linux.sh uninstall' first to reinstall."
        return
    fi

    local current_user
    current_user="$(whoami)"
    local current_group
    current_group="$(id -gn)"

    cat > /tmp/${SYSTEMD_SERVICE}.service <<EOF
[Unit]
Description=MUSASHI Super Sigma CMII Telemetry Ingestion Service
After=network.target

[Service]
Type=simple
User=${current_user}
Group=${current_group}
WorkingDirectory=${PROJECT_DIR}
ExecStart=${PYTHON} ${PROJECT_DIR}/${SCRIPT_NAME} --config ${CONFIG_FILE}
Restart=on-failure
RestartSec=10
StartLimitBurst=5
StartLimitIntervalSec=300

StandardOutput=append:${STDOUT_LOG}
StandardError=append:${STDERR_LOG}

# Environment
Environment="PYTHONUNBUFFERED=1"

[Install]
WantedBy=multi-user.target
EOF

    sudo mv /tmp/${SYSTEMD_SERVICE}.service "$SYSTEMD_UNIT_FILE"
    sudo chmod 644 "$SYSTEMD_UNIT_FILE"
    sudo systemctl daemon-reload
    sudo systemctl enable "$SYSTEMD_SERVICE"

    ok "systemd service '${SYSTEMD_SERVICE}' installed and enabled."
    info "Log stdout: ${STDOUT_LOG}"
    info "Log stderr: ${STDERR_LOG}"
    echo ""
    info "Run './service_linux.sh start' to start now."
}

systemd_start() {
    header
    sudo systemctl start "$SYSTEMD_SERVICE"
    ok "Service started."
    systemd_status
}

systemd_stop() {
    header
    sudo systemctl stop "$SYSTEMD_SERVICE"
    ok "Service stopped."
}

systemd_restart() {
    header
    sudo systemctl restart "$SYSTEMD_SERVICE"
    ok "Service restarted."
    systemd_status
}

systemd_status() {
    header
    if ! systemctl is-enabled "$SYSTEMD_SERVICE" &>/dev/null; then
        info "Service is NOT installed."
        return
    fi

    local state
    state="$(systemctl is-active "$SYSTEMD_SERVICE" 2>/dev/null || true)"
    
    case "$state" in
        active)   echo -e "  State:     ${GREEN}running${NC}" ;;
        inactive) echo -e "  State:     ${YELLOW}stopped${NC}" ;;
        failed)   echo -e "  State:     ${RED}failed${NC}" ;;
        *)        echo -e "  State:     $state" ;;
    esac

    # Show recent status
    systemctl status "$SYSTEMD_SERVICE" --no-pager -l 2>/dev/null | head -15 | sed 's/^/  /'
    echo ""
    info "Full logs: journalctl -u $SYSTEMD_SERVICE -f"
    info "App logs:  tail -f $STDOUT_LOG"
}

systemd_uninstall() {
    header
    if [ -f "$SYSTEMD_UNIT_FILE" ]; then
        sudo systemctl stop "$SYSTEMD_SERVICE" 2>/dev/null || true
        sudo systemctl disable "$SYSTEMD_SERVICE" 2>/dev/null || true
        sudo rm -f "$SYSTEMD_UNIT_FILE"
        sudo systemctl daemon-reload
        ok "Service '${SYSTEMD_SERVICE}' uninstalled."
    else
        info "Service was not installed."
    fi
}

systemd_logs() {
    header
    echo -e "  ${CYAN}--- Application Output (last 30 lines) ---${NC}"
    if [ -f "$STDOUT_LOG" ]; then
        tail -30 "$STDOUT_LOG" | sed 's/^/  /'
    else
        info "No stdout log yet."
    fi

    echo ""
    echo -e "  ${RED}--- Errors (last 10 lines) ---${NC}"
    if [ -f "$STDERR_LOG" ]; then
        tail -10 "$STDERR_LOG" | sed 's/^/  /'
    else
        ok "No errors."
    fi

    echo ""
    info "Live tail: journalctl -u $SYSTEMD_SERVICE -f"
    info "  or:      tail -f $STDOUT_LOG"
}

# ============================================================
#  macOS: launchd
# ============================================================

launchd_install() {
    header
    if [ -f "$LAUNCHD_PLIST" ]; then
        warn "Agent '$LAUNCHD_LABEL' already installed."
        info "Run './service_linux.sh uninstall' first to reinstall."
        return
    fi

    mkdir -p "$(dirname "$LAUNCHD_PLIST")"

    cat > "$LAUNCHD_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LAUNCHD_LABEL}</string>

    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON}</string>
        <string>${PROJECT_DIR}/${SCRIPT_NAME}</string>
        <string>--config</string>
        <string>${CONFIG_FILE}</string>
    </array>

    <key>WorkingDirectory</key>
    <string>${PROJECT_DIR}</string>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>

    <key>ThrottleInterval</key>
    <integer>10</integer>

    <key>StandardOutPath</key>
    <string>${STDOUT_LOG}</string>

    <key>StandardErrorPath</key>
    <string>${STDERR_LOG}</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONUNBUFFERED</key>
        <string>1</string>
    </dict>
</dict>
</plist>
EOF

    ok "launchd agent '${LAUNCHD_LABEL}' installed."
    info "Plist: ${LAUNCHD_PLIST}"
    info "Log stdout: ${STDOUT_LOG}"
    info "Log stderr: ${STDERR_LOG}"
    echo ""
    info "Run './service_linux.sh start' to start now."
}

launchd_start() {
    header
    launchctl load "$LAUNCHD_PLIST" 2>/dev/null || true
    # For newer macOS
    launchctl kickstart -k "gui/$(id -u)/${LAUNCHD_LABEL}" 2>/dev/null || true
    ok "Service started."
    sleep 1
    launchd_status
}

launchd_stop() {
    header
    launchctl unload "$LAUNCHD_PLIST" 2>/dev/null || true
    ok "Service stopped."
}

launchd_restart() {
    header
    launchctl unload "$LAUNCHD_PLIST" 2>/dev/null || true
    sleep 1
    launchctl load "$LAUNCHD_PLIST" 2>/dev/null || true
    ok "Service restarted."
    sleep 1
    launchd_status
}

launchd_status() {
    header
    if [ ! -f "$LAUNCHD_PLIST" ]; then
        info "Service is NOT installed."
        return
    fi

    local status_line
    status_line="$(launchctl list 2>/dev/null | grep "$LAUNCHD_LABEL" || true)"

    if [ -n "$status_line" ]; then
        local pid exit_code
        pid="$(echo "$status_line" | awk '{print $1}')"
        exit_code="$(echo "$status_line" | awk '{print $2}')"

        if [ "$pid" != "-" ] && [ -n "$pid" ]; then
            echo -e "  State:       ${GREEN}running${NC}"
            echo "  PID:         $pid"
        else
            echo -e "  State:       ${YELLOW}stopped${NC}"
        fi
        echo "  Last Exit:   $exit_code"
    else
        echo -e "  State:       ${YELLOW}not loaded${NC}"
    fi

    echo "  Plist:       $LAUNCHD_PLIST"
    echo "  Stdout Log:  $STDOUT_LOG"
    echo "  Stderr Log:  $STDERR_LOG"
    echo ""
    info "Live tail: tail -f $STDOUT_LOG"
}

launchd_uninstall() {
    header
    if [ -f "$LAUNCHD_PLIST" ]; then
        launchctl unload "$LAUNCHD_PLIST" 2>/dev/null || true
        rm -f "$LAUNCHD_PLIST"
        ok "Agent '${LAUNCHD_LABEL}' uninstalled."
    else
        info "Agent was not installed."
    fi
}

launchd_logs() {
    header
    echo -e "  ${CYAN}--- Application Output (last 30 lines) ---${NC}"
    if [ -f "$STDOUT_LOG" ]; then
        tail -30 "$STDOUT_LOG" | sed 's/^/  /'
    else
        info "No stdout log yet."
    fi

    echo ""
    echo -e "  ${RED}--- Errors (last 10 lines) ---${NC}"
    if [ -f "$STDERR_LOG" ]; then
        tail -10 "$STDERR_LOG" | sed 's/^/  /'
    else
        ok "No errors."
    fi

    echo ""
    info "Live tail: tail -f $STDOUT_LOG"
}

# ============================================================
#  DISPATCH
# ============================================================

ACTION="${1:-status}"

case "$OS" in
    Linux)
        case "$ACTION" in
            install)   systemd_install ;;
            start)     systemd_start ;;
            stop)      systemd_stop ;;
            restart)   systemd_restart ;;
            status)    systemd_status ;;
            uninstall) systemd_uninstall ;;
            logs)      systemd_logs ;;
            *) echo "Usage: $0 {install|start|stop|restart|status|uninstall|logs}"; exit 1 ;;
        esac
        ;;
    Darwin)
        case "$ACTION" in
            install)   launchd_install ;;
            start)     launchd_start ;;
            stop)      launchd_stop ;;
            restart)   launchd_restart ;;
            status)    launchd_status ;;
            uninstall) launchd_uninstall ;;
            logs)      launchd_logs ;;
            *) echo "Usage: $0 {install|start|stop|restart|status|uninstall|logs}"; exit 1 ;;
        esac
        ;;
    *)
        err "Unsupported OS: $OS"
        exit 1
        ;;
esac
