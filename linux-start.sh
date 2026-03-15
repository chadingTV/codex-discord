#!/bin/bash
# Codex Discord Bot - Linux Auto-update & Start Script
# Usage:
#   ./linux-start.sh          → Start (background + system tray)
#   ./linux-start.sh --fg     → Foreground mode (for debugging)
#   ./linux-start.sh --stop   → Stop
#   ./linux-start.sh --status → Check status

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"
SERVICE_NAME="codex-discord"
SERVICE_FILE="$HOME/.config/systemd/user/$SERVICE_NAME.service"

# Detect distro package manager and install system packages
# Usage: install_sys_packages appindicator tkinter
install_sys_packages() {
    local need_pkgs=("$@")
    [ "${#need_pkgs[@]}" -eq 0 ] && return 0

    if command -v pacman &>/dev/null; then
        # Arch / SteamOS — map logical names to arch package names
        local arch_pkgs=()
        for pkg in "${need_pkgs[@]}"; do
            case "$pkg" in
                appindicator) arch_pkgs+=("libayatana-appindicator") ;;
                tkinter)      arch_pkgs+=("tk") ;;
                *)            arch_pkgs+=("$pkg") ;;
            esac
        done
        # SteamOS has a read-only root by default; try to install but don't fail
        if ! sudo pacman -S --noconfirm --needed "${arch_pkgs[@]}" 2>/dev/null; then
            echo "⚠ Could not install ${arch_pkgs[*]} (read-only FS on SteamOS?). Tray may fall back to basic mode."
        fi
    elif command -v apt-get &>/dev/null; then
        # Ubuntu / Debian — map logical names to apt package names
        local apt_pkgs=()
        for pkg in "${need_pkgs[@]}"; do
            case "$pkg" in
                appindicator) apt_pkgs+=("gir1.2-ayatanaappindicator3-0.1") ;;
                tkinter)      apt_pkgs+=("python3-tk") ;;
                *)            apt_pkgs+=("$pkg") ;;
            esac
        done
        sudo apt install -y "${apt_pkgs[@]}" 2>/dev/null || true
    else
        echo "⚠ Unknown package manager, skipping system package install: ${need_pkgs[*]}"
    fi
}

# node 경로 찾기
find_node() {
    # nvm
    if [ -s "$HOME/.nvm/nvm.sh" ]; then
        . "$HOME/.nvm/nvm.sh"
        which node 2>/dev/null && return
    fi
    # fnm
    if command -v fnm &>/dev/null; then
        eval "$(fnm env)" 2>/dev/null
        which node 2>/dev/null && return
    fi
    # system
    which node 2>/dev/null
}

NODE_BIN=$(find_node)
if [ -z "$NODE_BIN" ]; then
    echo "❌ Node.js not found"
    exit 1
fi

check_native_modules() {
    local sqlite_node="$SCRIPT_DIR/node_modules/better-sqlite3/build/Release/better_sqlite3.node"
    if [ -f "$sqlite_node" ]; then
        if ! "$NODE_BIN" -e "require('$sqlite_node')" 2>/dev/null; then
            echo "🔧 Native modules incompatible with this machine, rebuilding..."
            cd "$SCRIPT_DIR" && npm rebuild better-sqlite3 2>/dev/null
        fi
    fi
}

# --stop: 중지
if [ "$1" = "--stop" ]; then
    systemctl --user stop "$SERVICE_NAME" 2>/dev/null
    echo "🔴 Bot stopped"
    # Stop tray app too
    pkill -f "codex_tray.py" 2>/dev/null
    exit 0
fi

# --regen-service: systemd service 파일만 재생성
if [ "$1" = "--regen-service" ]; then
    mkdir -p "$HOME/.config/systemd/user"
    cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Codex Discord Bot

[Service]
Type=simple
WorkingDirectory=$SCRIPT_DIR
Environment=HOME=$HOME
Environment=PATH=$(dirname "$NODE_BIN"):$PATH
Environment=NODE_PATH=$(dirname "$NODE_BIN")
ExecStartPre=/bin/bash -c 'touch $SCRIPT_DIR/.bot.lock'
ExecStart=$NODE_BIN $SCRIPT_DIR/dist/index.js
ExecStopPost=/bin/bash -c 'rm -f $SCRIPT_DIR/.bot.lock'
Restart=on-failure
RestartSec=10
StartLimitIntervalSec=0
StandardOutput=append:$SCRIPT_DIR/bot.log
StandardError=append:$SCRIPT_DIR/bot-error.log

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload
    exit 0
fi

# --status: 상태 확인
if [ "$1" = "--status" ]; then
    if systemctl --user is-active "$SERVICE_NAME" &>/dev/null; then
        echo "🟢 Bot running"
        systemctl --user status "$SERVICE_NAME" --no-pager -l 2>/dev/null | head -5
    else
        echo "🔴 Bot stopped"
    fi
    exit 0
fi

# --fg: Foreground mode
if [ "$1" = "--fg" ]; then
    # nvm 환경 로드 (systemd에서 실행 시 필요)
    if [ -s "$HOME/.nvm/nvm.sh" ]; then
        export NVM_DIR="$HOME/.nvm"
        . "$NVM_DIR/nvm.sh"
    fi
    if command -v fnm &>/dev/null; then
        eval "$(fnm env)" 2>/dev/null
    fi
    # Re-find node after loading nvm/fnm
    NODE_BIN=$(which node 2>/dev/null)
    if [ -z "$NODE_BIN" ]; then
        echo "[codex-bot] ❌ Node.js not found in foreground mode"
        exit 1
    fi
    cd "$SCRIPT_DIR"

    VERSION=$(git describe --tags --always 2>/dev/null || echo "unknown")
    echo "[codex-bot] Current version: $VERSION"
    echo "[codex-bot] Checking for updates..."
    git fetch origin main 2>/dev/null
    LOCAL=$(git rev-parse HEAD 2>/dev/null)
    REMOTE=$(git rev-parse origin/main 2>/dev/null)

    if [ -n "$LOCAL" ] && [ -n "$REMOTE" ] && [ "$LOCAL" != "$REMOTE" ]; then
        echo "[codex-bot] Update available (update from tray)"
    else
        echo "[codex-bot] Up to date"
    fi

    if [ ! -d "dist" ]; then
        echo "[codex-bot] No build files found, building..."
        npm run build
    elif find src -name "*.ts" -newer dist/index.js 2>/dev/null | grep -q .; then
        echo "[codex-bot] Source changed, rebuilding..."
        npm run build
    fi

    check_native_modules

    echo "[codex-bot] Starting bot (foreground)..."
    touch "$SCRIPT_DIR/.bot.lock"
    trap 'rm -f "$SCRIPT_DIR/.bot.lock"' EXIT
    exec "$NODE_BIN" dist/index.js
fi

# Default: background mode (register with systemd)

check_native_modules

# Create systemd user directory
mkdir -p "$HOME/.config/systemd/user"

# Stop existing bot if running
if systemctl --user is-active "$SERVICE_NAME" &>/dev/null; then
    echo "🔄 Stopping existing bot..."
    systemctl --user stop "$SERVICE_NAME"
    sleep 1
fi

# Create systemd service file
cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Codex Discord Bot

[Service]
Type=simple
WorkingDirectory=$SCRIPT_DIR
Environment=HOME=$HOME
Environment=PATH=$(dirname "$NODE_BIN"):$PATH
Environment=NODE_PATH=$(dirname "$NODE_BIN")
ExecStartPre=/bin/bash -c 'touch $SCRIPT_DIR/.bot.lock'
ExecStart=$NODE_BIN $SCRIPT_DIR/dist/index.js
ExecStopPost=/bin/bash -c 'rm -f $SCRIPT_DIR/.bot.lock'
Restart=on-failure
RestartSec=10
StartLimitIntervalSec=0
StandardOutput=append:$SCRIPT_DIR/bot.log
StandardError=append:$SCRIPT_DIR/bot-error.log

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload

is_env_configured() {
    [ -f "$ENV_FILE" ] || return 1
    local token=$(grep "^DISCORD_BOT_TOKEN=" "$ENV_FILE" 2>/dev/null | cut -d= -f2)
    local guild=$(grep "^DISCORD_GUILD_ID=" "$ENV_FILE" 2>/dev/null | cut -d= -f2)
    [ -n "$token" ] && [ "$token" != "your_bot_token_here" ] && \
    [ -n "$guild" ] && [ "$guild" != "your_server_id_here" ]
}

# GUI mode: tray manages bot lifecycle / Headless: start bot directly
TRAY_SCRIPT="$SCRIPT_DIR/tray/codex_tray.py"
HAS_GUI=false
if [ -n "$DISPLAY" ] || [ -n "$WAYLAND_DISPLAY" ]; then
    if [ -f "$TRAY_SCRIPT" ] && command -v python3 &>/dev/null; then
        # pystray + Pillow 설치 확인 및 자동 설치
        if ! python3 -c "import pystray; from PIL import Image" 2>/dev/null; then
            echo "📦 Installing tray app dependencies..."
            pip3 install --user pystray Pillow 2>/dev/null || \
            pip3 install pystray Pillow 2>/dev/null || \
            pip install --user pystray Pillow 2>/dev/null
        fi
        # AppIndicator + tkinter system packages (distro-aware)
        NEED_SYS_PKGS=()
        if ! python3 -c "import gi; gi.require_version('AyatanaAppIndicator3', '0.1')" 2>/dev/null && \
           ! python3 -c "import gi; gi.require_version('AppIndicator3', '0.1')" 2>/dev/null; then
            NEED_SYS_PKGS+=("appindicator")
        fi
        if ! python3 -c "import tkinter" 2>/dev/null; then
            NEED_SYS_PKGS+=("tkinter")
        fi
        if [ "${#NEED_SYS_PKGS[@]}" -gt 0 ]; then
            echo "📦 Installing system tray libraries..."
            install_sys_packages "${NEED_SYS_PKGS[@]}"
        fi
        if python3 -c "import pystray; from PIL import Image" 2>/dev/null; then
            pkill -f "codex_tray.py" 2>/dev/null
            nohup python3 "$TRAY_SCRIPT" > /dev/null 2>&1 &
            HAS_GUI=true
            echo "🔔 Tray started (manages bot lifecycle)"
        fi
    fi
fi

if [ "$HAS_GUI" = false ]; then
    # Headless: no tray available, start bot directly
    if is_env_configured; then
        systemctl --user enable "$SERVICE_NAME" 2>/dev/null
        loginctl enable-linger 2>/dev/null
        systemctl --user start "$SERVICE_NAME"
        echo "🟢 Bot started in background (headless mode)"
    else
        echo "⚙️ .env not configured. Edit .env manually and run again."
    fi
fi

# Create desktop shortcut
DESKTOP_FILE="$HOME/Desktop/Codex Discord Bot.desktop"
if [ ! -f "$DESKTOP_FILE" ]; then
    # Try to find an icon, fallback to no icon
    ICON_PATH="$SCRIPT_DIR/docs/icon-rounded.png"
    cat > "$DESKTOP_FILE" << DEOF
[Desktop Entry]
Type=Application
Name=Codex Discord Bot
Comment=Codex Discord Bot Tray Manager
Exec=/bin/bash $SCRIPT_DIR/linux-start.sh
Icon=$ICON_PATH
Terminal=false
Categories=Utility;
StartupNotify=false
DEOF
    chmod +x "$DESKTOP_FILE"
    # Mark as trusted (GNOME only; harmless no-op on KDE/SteamOS)
    if command -v gio &>/dev/null; then
        gio set "$DESKTOP_FILE" metadata::trusted true 2>/dev/null || true
    fi
    echo "🖥️ Desktop shortcut created"
fi

# Register tray app autostart (launches tray on login → tray manages bot lifecycle)
AUTOSTART_DIR="$HOME/.config/autostart"
AUTOSTART_FILE="$AUTOSTART_DIR/codex-discord-tray.desktop"
TRAY_ICON="$SCRIPT_DIR/docs/icon-rounded.png"
if [ -f "$TRAY_SCRIPT" ]; then
    mkdir -p "$AUTOSTART_DIR"
    cat > "$AUTOSTART_FILE" << AEOF
[Desktop Entry]
Type=Application
Name=Codex Discord Bot Tray
Comment=Codex Discord Bot system tray manager
Exec=/bin/bash -c 'sleep 3 && python3 $SCRIPT_DIR/tray/codex_tray.py'
Icon=$TRAY_ICON
Terminal=false
X-GNOME-Autostart-enabled=true
StartupNotify=false
AEOF
    echo "🔔 Tray autostart registered"
fi

echo "   Stop:   ./linux-start.sh --stop"
echo "   Status: ./linux-start.sh --status"
echo "   Log:    tail -f bot.log"
