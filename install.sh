#!/bin/bash
set -e

echo "==================================="
echo " Codex Discord Controller Installer"
echo "==================================="
echo ""

NEED_RESTART=false

# --- 0. Xcode Command Line Tools (macOS only, needed for Swift menu bar app) ---
if [[ "$OSTYPE" == "darwin"* ]]; then
  echo "[0/5] Checking Xcode Command Line Tools..."
  if ! xcode-select -p &>/dev/null; then
    echo "  Not found. Installing (this may take a few minutes)..."
    xcode-select --install 2>/dev/null || true
    echo "  ⚠ A dialog should appear. Complete the installation, then re-run this script."
    exit 0
  fi
  # Accept Xcode license if needed (required for swiftc)
  if ! xcrun --find swiftc &>/dev/null; then
    echo "  Accepting Xcode license..."
    sudo xcodebuild -license accept 2>/dev/null || true
  fi
  echo "  ✅ OK"
  echo ""
fi

# --- 1. Node.js ---
echo "[1/5] Checking Node.js..."
if command -v node &>/dev/null; then
  NODE_VER=$(node -v | sed 's/v//' | cut -d. -f1)
  echo "  Found Node.js $(node -v)"
  if [ "$NODE_VER" -lt 20 ]; then
    echo "  ⚠ Node.js 20+ required (current: v$NODE_VER)"
    echo "  Upgrading..."
    if [[ "$OSTYPE" == "darwin"* ]]; then
      if command -v brew &>/dev/null; then
        brew install node
      else
        echo "  ❌ Homebrew not found. Install from https://nodejs.org"
        exit 1
      fi
    else
      curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
      sudo apt-get install -y nodejs
    fi
    echo "  ✅ Node.js $(node -v) installed"
  else
    echo "  ✅ OK"
  fi
else
  echo "  Node.js not found. Installing..."
  if [[ "$OSTYPE" == "darwin"* ]]; then
    if command -v brew &>/dev/null; then
      brew install node
    else
      echo "  ❌ Homebrew not found."
      echo "  Install Homebrew: /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
      echo "  Or download Node.js from https://nodejs.org"
      exit 1
    fi
  else
    curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
    sudo apt-get install -y nodejs
  fi
  echo "  ✅ Node.js $(node -v) installed"
fi
echo ""

# --- 2. Codex CLI ---
echo "[2/5] Checking Codex CLI..."
if command -v codex &>/dev/null; then
  echo "  Found Codex $(codex --version 2>/dev/null || echo '(version unknown)')"
  echo "  ✅ OK"
else
  echo "  Codex not found. Installing..."
  npm install -g @openai/codex
  echo "  ✅ Codex installed"
  echo ""
  echo "  ⚠ Codex login required!"
  echo "  Run 'codex login' once to complete ChatGPT login."
  NEED_RESTART=true
fi
echo ""

# --- 3. npm install ---
echo "[3/5] Installing project dependencies..."
npm install
echo "  ✅ Done"
echo ""

# --- 4. .env ---
echo "[4/5] Checking .env file..."
if [ -f .env ]; then
  echo "  .env already exists"
  echo "  ✅ OK"
else
  echo "  .env not found (will be configured via GUI settings)"
  echo "  ✅ OK"
fi
echo ""

# --- 5. Build ---
echo "[5/5] Building project..."
npm run build
echo "  ✅ Done"
echo ""

# --- Detect OS-specific start script ---
if [[ "$OSTYPE" == "darwin"* ]]; then
  START_SCRIPT="./mac-start.sh"
else
  START_SCRIPT="./linux-start.sh"
fi

# --- Done ---
echo "==================================="
echo " Installation complete!"
echo "==================================="
echo ""
if [ "$NEED_RESTART" = true ]; then
  echo "⚠ Next steps:"
  echo "  1. Run 'codex login' to log in to Codex"
  echo "  2. Run '$START_SCRIPT' to start the bot"
else
  echo "Starting bot..."
  echo ""
  exec $START_SCRIPT
fi
echo ""
echo "See SETUP.md for detailed instructions."
