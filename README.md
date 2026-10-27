# Telegram CLI

A feature-rich Telegram command-line interface built with Python and Telethon.

## Features

- **Message replies** – Reply to specific messages by ID
- **File uploads** – Send documents, images, audio, and video with optional captions
- **Attachment management** – Browse, download, and open received attachments
- **Persistent settings** – Configurable download directory, history limits, and more
- **Privacy controls** – View and update Telegram privacy settings
- **Clean architecture** – Modular, extensible codebase

## Quick Start

```bash
# Activate the virtual environment
source .venv/bin/activate

# Run the CLI
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
| `chats` | List recent conversations |
| `open INDEX` or `open @username` | Open a chat |
| `history [COUNT]` | Show recent messages with IDs |
| `send MESSAGE` | Send a message |
| `reply MSG_ID MESSAGE` | Reply to a specific message |
| `attach "/path/to/file" [--caption TEXT] [--reply MSG_ID]` | Upload a file |
| `attachments [COUNT]` | List recent media attachments |
| `download MSG_ID` | Download an attachment |
| `view MSG_ID` | Download and open an attachment |
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
| `help` | Show all commands |
| `quit` / `exit` | Exit |

## Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `download_dir` | `downloads` | Directory for downloaded attachments |
| `history_limit` | `20` | Default number of messages to show |
| `confirm_before_send` | `false` | Ask for confirmation before sending |
| `theme` | `default` | Terminal theme (default, minimal, colorful) |

## Architecture

```
telegram-cli/
├── telegram_cli.py          # Entry point
├── app/
│   ├── cli.py               # Command parsing & interactive loop
│   ├── config.py            # Persistent configuration
│   └── services/
│       ├── messaging.py     # Message history, sending, replies
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
