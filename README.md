# Telegram CLI

A feature-rich Telegram command-line interface built with Python and Telethon.

## Features

- **Real-Time Chatting** – Live incoming messages in open chats without needing to manually run `history`
- **Chat Folders & Filtering** – View Telegram chat folders, open chats by folder, or view all chats
- **Mass Archiving & Unarchiving** – Archive and unarchive single or multiple chats in one go
- **Broadcast Channels Only** – Filter and list only subscribed broadcast channels
- **Folder Management** – Mass add or remove chats from Telegram chat folders
- **Message replies** – Reply to specific messages by ID
- **File uploads** – Send documents, images, audio, and video with optional captions
- **Attachment management** – Browse, download, and open received attachments
- **Persistent settings** – Configurable download directory, history limits, and more
- **Privacy controls** – View and update Telegram privacy settings
- **Local AI Assistant (Ollama)** – Search chats by context, locate discussions, and draft messages locally
- **Telegram Bot Remote Control** – Manage your Telegram account from Telegram Desktop or mobile via your private bot (@mightypen_bot)
- **Draft-First Safety** – AI messages are always previewed and require confirmation before sending
- **Group & Channel Integration** – Mention the bot in group chats or discussion channels to answer questions or summarize
- **Clean architecture** – Modular, extensible codebase

## Quick Start

You can run the application from anywhere using the `mightygram` command (no virtual environment activation needed):

```bash
# Run the interactive CLI & AI assistant from any terminal
mightygram

# Or run in standalone bot daemon mode (for background use from Desktop/Mobile)
mightygram --bot
```

Alternatively, you can run directly with python:
```bash
python telegram_cli.py
```

You can authenticate in any of the following convenient ways:

1. **Interactive Prompt (Recommended)**: On first run, enter your API ID and hash. The app will prompt to save them securely in `~/.config/telegram-cli/.credentials` with `0600` permissions (readable only by you). Future launches will connect automatically!
2. **Environment Variables**:
   ```bash
   export TELEGRAM_API_ID="123456"
   export TELEGRAM_API_HASH="your_api_hash_here"
   ```
3. **Local `.env` file**: Create a `.env` in the project root:
   ```env
   TELEGRAM_API_ID=123456
   TELEGRAM_API_HASH=your_api_hash_here
   ```
To clear saved credentials at any time, run the `logout` command inside the CLI.

## Commands

| Command | Description |
|---------|-------------|
| `chats` | List chat folders (default, custom, archived) |
| `all chats` / `all` | Open and list all conversations directly |
| `open FOLDER` or `open INDEX` | Open chats inside a folder or open a conversation |
| `channels [COUNT]` | List broadcast channels only |
| `archived [COUNT]` | List archived conversations |
| `archive TARGETS...` | Mass archive chats (e.g. `archive 1 2 3`, `archive 1-4`, `archive all`) |
| `unarchive TARGETS...` | Mass unarchive chats (e.g. `unarchive 1 2`, `unarchive all`) |
| `folder` / `folder list` | List chat folders |
| `folder add FOLDER TARGETS...` | Mass add chats to a folder (e.g. `folder add Work 1 2 3`) |
| `folder remove FOLDER TARGETS...` | Mass remove chats from a folder (e.g. `folder remove Work 1 2`) |
| `open INDEX` or `open @username` | Open a chat conversation for live messaging |
| `open saved` / `saved` | Open Saved Messages to see saved messages |
| `close` | Close the currently open chat |
| `history [COUNT]` | Show recent messages with IDs |
| `send MESSAGE` | Send a message |
| `reply MSG_ID MESSAGE` | Reply to a specific message |
| `attach "/path/to/file" [--caption TEXT] [--reply MSG_ID]` | Upload a file |
| `attachments [COUNT]` | List recent media attachments |
| `download INDEX | MSG_ID` | Download an attachment by 1-based index or message ID |
| `view INDEX | MSG_ID` | Download and open an attachment with xdg-open by 1-based index or message ID |
| `settings` | Show current settings |
| `settings set KEY VALUE` | Change a setting |
| `settings reset KEY` | Reset a setting to default |
| `account` | Show Telegram account info |
| `privacy` | Show privacy settings |
| `privacy set KEY VALUE` | Update a privacy setting |
| `notifications` | Show notification settings |
| `notifications mute TYPE [HOURS]` | Mute notifications (`users`, `chats`, `channels`) |
| `notifications unmute TYPE` | Unmute notifications (`users`, `chats`, `channels`) |
| `me` | Show your account summary |
| `ai PROMPT...` | Query local AI assistant to search chats, draft messages, or summarize |
| `ai clear` / `ai reset` | Clear conversation memory in CLI session |
| `bot [status\|start\|stop]` | Manage personal AI Telegram bot service |
| `help` | Show all commands |
| `quit` / `exit` | Exit |

## Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `download_dir` | `downloads` | Directory for downloaded attachments |
| `history_limit` | `20` | Default number of messages to show |
| `confirm_before_send` | `false` | Ask for confirmation before sending |
| `theme` | `default` | Terminal theme (default, minimal, colorful) |
| `ollama_url` | `http://localhost:11434` | Local Ollama API endpoint |
| `ai_model` | `qwen2.5:3b` | Local Ollama model name |
| `ai_draft_first` | `true` | Always show a draft before sending AI messages |

## Architecture

```
telegram-cli/
├── telegram_cli.py          # Entry point (interactive CLI & bot daemon)
├── app/
│   ├── cli.py               # Command parsing & interactive loop
│   ├── config.py            # Persistent configuration
│   ├── credentials.py       # Secure credential & bot token storage
│   └── services/
│       ├── ai.py            # Local Ollama AI assistant & tool dispatch
│       ├── bot.py           # Telegram bot bridge for Desktop/Mobile
│       ├── messaging.py     # Message history, sending, replies, search
│       ├── media.py         # Uploads, downloads, attachments
│       └── settings.py      # CLI & Telegram account settings
├── tests/                   # Automated tests
├── downloads/               # Default download directory
├── pyproject.toml
└── README.md
```

## Running Tests

```bash
source .venv/bin/activate
python -m pytest tests/ -v
```
