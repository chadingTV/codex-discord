#!/bin/bash
# Codex Discord Bot - Auto-update & Start Script
# Usage:
#   ./mac-start.sh          → Start menu bar panel only
#   ./mac-start.sh --fg     → Foreground mode (for debugging)
#   ./mac-start.sh --stop   → Stop bot and menu bar panel
#   ./mac-start.sh --status → Check bot status

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

PLIST_NAME="com.codex-discord.plist"
PLIST_DST="$HOME/Library/LaunchAgents/$PLIST_NAME"
LABEL="com.codex-discord"
MENUBAR="$SCRIPT_DIR/menubar/CodexBotMenu"
MENUBAR_PLIST_NAME="com.codex-discord-menubar.plist"
MENUBAR_PLIST_DST="$HOME/Library/LaunchAgents/$MENUBAR_PLIST_NAME"
MENUBAR_LABEL="com.codex-discord-menubar"
LAUNCHD_DOMAIN="gui/$(id -u)"

launchd_stop() {
    local label="$1"
    local plist="$2"
    launchctl bootout "$LAUNCHD_DOMAIN/$label" 2>/dev/null || launchctl unload "$plist" 2>/dev/null
}

# --stop: bot과 패널 모두 중지
if [ "$1" = "--stop" ]; then
    if launchctl list | grep -q "$LABEL"; then
        launchd_stop "$LABEL" "$PLIST_DST"
        echo "🔴 Bot stopped"
    else
        echo "Bot is not running"
    fi
    pkill -f "$SCRIPT_DIR/.*/dist/index.js|$SCRIPT_DIR/dist/index.js|$SCRIPT_DIR/mac-start.sh --fg|node dist/index.js" 2>/dev/null
    rm -f "$SCRIPT_DIR/.bot.lock" 2>/dev/null
    launchd_stop "$MENUBAR_LABEL" "$MENUBAR_PLIST_DST"
    pkill -f "CodexBotMenu" 2>/dev/null
    echo "🔴 Menu bar panel stopped"
    exit 0
fi

# --status: 상태 확인
if [ "$1" = "--status" ]; then
    if launchctl list | grep -q "$LABEL"; then
        PID=$(launchctl list | grep "$LABEL" | awk '{print $1}')
        if [ -n "$PID" ] && [ "$PID" != "-" ] && [ "$PID" != "0" ]; then
            echo "🟢 Bot running (PID: $PID)"
        else
            echo "🔴 Bot stopped"
        fi
    else
        echo "🔴 Bot stopped"
    fi
    exit 0
fi

# --fg: 포그라운드 실행 (launchd 없이 직접 실행)
if [ "$1" = "--fg" ]; then
    # Try to find node: nvm → homebrew → common paths
    export NVM_DIR="$HOME/.nvm"
    [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"

    if ! command -v node &>/dev/null; then
        # Try Homebrew paths (Apple Silicon + Intel)
        for p in /opt/homebrew/bin /usr/local/bin "$HOME/.nodenv/shims" "$HOME/.fnm/aliases/default/bin"; do
            if [ -x "$p/node" ]; then
                export PATH="$p:$PATH"
                break
            fi
        done
    fi

    if ! command -v node &>/dev/null; then
        echo "[codex-bot] ERROR: node not found. Please install Node.js (nvm, homebrew, or nodejs.org)"
        echo "[codex-bot] Install with: brew install node  OR  curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash"
        exit 1
    fi

    echo "[codex-bot] Using node: $(which node) ($(node --version))"
    cd "$SCRIPT_DIR"

    VERSION=$(git describe --tags --always 2>/dev/null || echo "unknown")
    echo "[codex-bot] Current version: $VERSION"
    echo "[codex-bot] Checking for updates..."
    git fetch origin main --tags 2>/dev/null
    LOCAL=$(git rev-parse HEAD 2>/dev/null)
    REMOTE=$(git rev-parse origin/main 2>/dev/null)

    if [ -n "$LOCAL" ] && [ -n "$REMOTE" ] && [ "$LOCAL" != "$REMOTE" ]; then
        echo "[codex-bot] Update available (update from menu bar)"
    else
        echo "[codex-bot] Up to date"
    fi

    if [ ! -d "node_modules" ]; then
        echo "[codex-bot] Installing dependencies..."
        npm install
    fi

    if [ ! -d "dist" ]; then
        echo "[codex-bot] No build files found, building..."
        npm run build
    elif find src -name "*.ts" -newer dist/index.js 2>/dev/null | grep -q .; then
        echo "[codex-bot] Source changed, rebuilding..."
        npm run build
    fi

    if ! node -e "require('./node_modules/better-sqlite3/build/Release/better_sqlite3.node')" 2>/dev/null; then
        echo "[codex-bot] Native modules incompatible, rebuilding..."
        npm rebuild better-sqlite3
    fi

    echo "[codex-bot] Starting bot (foreground)..."
    touch "$SCRIPT_DIR/.bot.lock"
    trap 'rm -f "$SCRIPT_DIR/.bot.lock"' EXIT
    node dist/index.js
    exit $?
fi

# Default: panel mode. The panel controls bot start/stop.

# Compile menu bar app (rebuild if source is newer than binary)
if [ -f "$SCRIPT_DIR/menubar/CodexBotMenu.swift" ]; then
    if [ ! -f "$MENUBAR" ] || [ "$SCRIPT_DIR/menubar/CodexBotMenu.swift" -nt "$MENUBAR" ]; then
        # Check Xcode Command Line Tools and license
        if ! xcode-select -p &>/dev/null; then
            echo "⚠ Xcode Command Line Tools required. Installing..."
            xcode-select --install
            echo "  Complete the installation dialog, then re-run this script."
            exit 0
        fi
        if ! xcrun --find swiftc &>/dev/null; then
            echo "⚠ Xcode license not accepted. Accepting..."
            sudo xcodebuild -license accept 2>/dev/null || {
                echo "  Failed. Please run manually: sudo xcodebuild -license accept"
                exit 1
            }
        fi
        echo "🔨 Building menu bar app..."
        swiftc -o "$MENUBAR" "$SCRIPT_DIR/menubar/CodexBotMenu.swift" -framework Cocoa
    fi
fi

# Start menu bar app (shows settings dialog if .env not configured)
if [ -f "$MENUBAR" ]; then
    pkill -f "CodexBotMenu" 2>/dev/null
    nohup "$MENUBAR" > /dev/null 2>&1 &
fi

if [ ! -f "$ENV_FILE" ]; then
    echo "⚙️ .env not found. Please configure settings from the menu bar icon."
fi

# Register menu bar app autostart (launches panel on login; panel controls bot lifecycle)
# Only write plist file — do NOT launchctl load here (nohup already started it above)
# The plist with RunAtLoad=true will auto-start on next login/reboot
if [ -f "$MENUBAR" ]; then
    mkdir -p "$HOME/Library/LaunchAgents"
    cat > "$MENUBAR_PLIST_DST" <<MBEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$MENUBAR_LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$MENUBAR</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$SCRIPT_DIR</string>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/dev/null</string>
    <key>StandardErrorPath</key>
    <string>/dev/null</string>
</dict>
</plist>
MBEOF
    echo "🔔 Menu bar autostart registered"
fi

echo "🟢 Menu bar panel started"
echo "   Bot controls: use the menu bar panel"
echo "   Bot status:   ./mac-start.sh --status"
