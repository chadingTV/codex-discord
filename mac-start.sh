#!/bin/bash
# Codex Discord Bot - Auto-update & Start Script
# Usage:
#   ./mac-start.sh          → Start (background + menu bar)
#   ./mac-start.sh --fg     → Foreground mode (for debugging)
#   ./mac-start.sh --stop   → Stop
#   ./mac-start.sh --status → Check status

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

PLIST_NAME="com.codex-discord.plist"
PLIST_SRC="$SCRIPT_DIR/$PLIST_NAME"
PLIST_DST="$HOME/Library/LaunchAgents/$PLIST_NAME"
LABEL="com.codex-discord"
MENUBAR="$SCRIPT_DIR/menubar/CodexBotMenu"
MENUBAR_PLIST_NAME="com.codex-discord-menubar.plist"
MENUBAR_PLIST_DST="$HOME/Library/LaunchAgents/$MENUBAR_PLIST_NAME"
MENUBAR_LABEL="com.codex-discord-menubar"

# --stop: 중지
if [ "$1" = "--stop" ]; then
    if launchctl list | grep -q "$LABEL"; then
        launchctl unload "$PLIST_DST" 2>/dev/null
        echo "🔴 Bot stopped"
    else
        echo "Bot is not running"
    fi
    # Stop menu bar app too
    launchctl unload "$MENUBAR_PLIST_DST" 2>/dev/null
    pkill -f "CodexBotMenu" 2>/dev/null
    exit 0
fi

# --status: 상태 확인
if [ "$1" = "--status" ]; then
    if launchctl list | grep -q "$LABEL"; then
        PID=$(launchctl list | grep "$LABEL" | awk '{print $1}')
        echo "🟢 Bot running (PID: $PID)"
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
    exec node dist/index.js
fi

# Default: background mode (register with launchd)

if ! node -e "require('./node_modules/better-sqlite3/build/Release/better_sqlite3.node')" 2>/dev/null; then
    echo "[codex-bot] Native modules incompatible, rebuilding..."
    npm rebuild better-sqlite3
fi

# Stop existing bot if running
if launchctl list | grep -q "$LABEL"; then
    echo "🔄 Stopping existing bot..."
    launchctl unload "$PLIST_DST" 2>/dev/null
    sleep 1
fi
# Also kill any orphaned bot processes not managed by launchd
pkill -f "node dist/index.js" 2>/dev/null && sleep 1

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

# Start bot if .env is properly configured, otherwise let menu bar handle setup
is_env_configured() {
    [ -f "$ENV_FILE" ] || return 1
    local token=$(grep "^DISCORD_BOT_TOKEN=" "$ENV_FILE" 2>/dev/null | cut -d= -f2)
    local guild=$(grep "^DISCORD_GUILD_ID=" "$ENV_FILE" 2>/dev/null | cut -d= -f2)
    [ -n "$token" ] && [ "$token" != "your_bot_token_here" ] && \
    [ -n "$guild" ] && [ "$guild" != "your_server_id_here" ]
}

generate_plist() {
    # Resolve node bin directory for PATH (nvm, fnm, nodenv, homebrew, etc.)
    local NODE_BIN_DIR=""
    export NVM_DIR="$HOME/.nvm"
    if [ -s "$NVM_DIR/nvm.sh" ]; then
        . "$NVM_DIR/nvm.sh"
        NODE_BIN_DIR="$(dirname "$(which node)" 2>/dev/null)"
    fi
    if [ -z "$NODE_BIN_DIR" ]; then
        for p in /opt/homebrew/bin /usr/local/bin "$HOME/.nodenv/shims" "$HOME/.fnm/aliases/default/bin"; do
            if [ -x "$p/node" ]; then
                NODE_BIN_DIR="$p"
                break
            fi
        done
    fi
    local PLIST_PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    if [ -n "$NODE_BIN_DIR" ] && [[ ":$PLIST_PATH:" != *":$NODE_BIN_DIR:"* ]]; then
        PLIST_PATH="$NODE_BIN_DIR:$PLIST_PATH"
    fi

    cat > "$PLIST_DST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$SCRIPT_DIR/mac-start.sh</string>
        <string>--fg</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$SCRIPT_DIR</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>ThrottleInterval</key>
    <integer>10</integer>
    <key>StandardOutPath</key>
    <string>$SCRIPT_DIR/bot.log</string>
    <key>StandardErrorPath</key>
    <string>$SCRIPT_DIR/bot-error.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>$PLIST_PATH</string>
    </dict>
</dict>
</plist>
PLISTEOF
}

if is_env_configured; then
    generate_plist
    launchctl load "$PLIST_DST"
    if [ -f "$MENUBAR" ]; then
        echo "🟢 Bot started in background (menu bar active)"
    else
        echo "🟢 Bot started in background"
    fi
else
    echo "⚙️ .env not found. Please configure settings from the menu bar icon."
fi

# Register menu bar app autostart (launches menu bar on login → menu bar manages bot lifecycle)
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

echo "   Stop:   ./mac-start.sh --stop"
echo "   Status: ./mac-start.sh --status"
echo "   Log:    tail -f bot.log"
