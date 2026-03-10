# AGENTS.md

Codex Discord controller workspace notes.

## Overview

This project runs a Discord bot that controls local Codex threads through the Codex app-server and local `~/.codex` storage. One Discord channel maps to one local project directory.

## Commands

```bash
npm run dev
npm run build
npm start
npm test
./install.sh
./mac-start.sh
./linux-start.sh
win-start.bat
```

## Key Paths

- `src/index.ts`: entrypoint
- `src/bot/`: Discord client, commands, handlers
- `src/codex/`: Codex app-server client, session manager, thread storage helpers
- `src/db/`: SQLite persistence
- `src/security/`: auth and rate limiting
- `src/utils/`: config and i18n

## Notes

- Attachment downloads are stored under `.codex-uploads/` inside the registered project.
- Existing Codex threads are discovered from local `~/.codex` state.
- Slash commands and Discord UI are the primary control surface; do not reintroduce Claude SDK dependencies.
