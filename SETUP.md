# Codex Discord Setup Guide

Guide for installing and running the Codex Discord controller on macOS, Linux, and Windows.

## Requirements

- Node.js 20+
- `codex` CLI installed
- Logged in with ChatGPT via `codex login`
- Discord bot token and guild ID

## Quick Start

1. Clone the project and install dependencies.

```bash
git clone <your-repo-or-local-path>
cd codex-discord
npm install
npm run build
```

2. Verify Codex is available.

```bash
codex --version
codex login
codex login status
```

3. Create `.env` from `.env.example` and fill in your Discord values.

```bash
cp .env.example .env
```

Required values:

```env
DISCORD_BOT_TOKEN=your_bot_token_here
DISCORD_GUILD_ID=your_server_id_here
ALLOWED_USER_IDS=your_user_id_here
BASE_PROJECT_DIR=/Users/you/projects
RATE_LIMIT_PER_MINUTE=10
SHOW_COST=false
```

4. Start the bot.

macOS:

```bash
./mac-start.sh
```

Linux:

```bash
./linux-start.sh
```

Windows:

```bat
win-start.bat
```

## Discord Usage

- `/register <folder>` maps the current channel to a local project.
- Send normal messages in that channel to continue or start a Codex thread.
- `/sessions` shows resumable local Codex threads, including VS Code-created threads from `~/.codex`.
- `/stop` interrupts the active turn.
- `/auto-approve on|off` controls approval behavior for that channel.
- `/queue list` and `/queue clear` inspect queued prompts.
- `/last` fetches the last assistant response for the channel session.

## Notes

- This project uses the local logged-in Codex account, not a manually pasted API key.
- Existing Codex threads are discovered from local `~/.codex` storage and the Codex app-server APIs.
- If `codex login status` does not show a logged-in ChatGPT account, Discord requests will fail until login is completed.
