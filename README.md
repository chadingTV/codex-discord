# Codex Discord Controller

Discord bot for controlling local Codex sessions from mobile or desktop Discord.

## What it does

- Maps one Discord channel to one local project directory
- Uses the local `codex` login session, not a manually pasted API key
- Lets you continue existing Codex threads, including VS Code-created threads stored under `~/.codex`
- Streams assistant output into Discord
- Supports command/file-change approval, queued prompts, stop, and last-response lookup

## Requirements

- Node.js 20+
- `codex` CLI installed and logged in with ChatGPT
- Discord bot token and guild ID

## Commands

- `/register <folder>`
- `/unregister`
- `/status`
- `/stop`
- `/auto-approve on|off`
- `/sessions`
- `/last`
- `/queue list`
- `/queue clear`
- `/clear-sessions`

## Notes

Uses Codex app-server and local `~/.codex` thread storage for thread discovery and resume.
