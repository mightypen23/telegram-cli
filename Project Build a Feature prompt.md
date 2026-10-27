# Project: Build a Feature-Rich Telegram CLI for Fedora Linux

You are working inside my existing Python Telegram CLI project on Fedora Linux.

## Your mission

Upgrade my working Telegram CLI into a maintainable, feature-rich terminal application using Python and Telethon. Implement the following features:

1. Reply to specific Telegram messages.
2. Upload files and send attachments with optional captions.
3. Browse, inspect, download, and open received attachments.
4. Access and manage CLI settings.
5. Maintain a clean, extensible architecture.

## CRITICAL: Inspect before modifying

Before making changes:

- Inspect the entire existing project structure and read the current source files.
- Identify the current Python environment, installed dependencies, Telethon version, session filename, authentication flow, and implemented commands.
- Preserve the existing working functionality.
- Preserve the existing Telegram session name and location. Reuse the current authenticated session; do not delete, rename, overwrite, or regenerate it.
- Never request or print my API hash, login code, two-step verification password, or session contents.
- Do not create a new session unless absolutely necessary and explicitly approved.
- Back up files before modifying them.
- Use the existing `uv` virtual environment and installed dependencies where possible. Do not install system-wide packages unnecessarily.

Do not replace the application wholesale without first understanding how it works.

## Architecture

Refactor incrementally into clearly separated modules. Use this as a target architecture, adapting it to the existing codebase where appropriate:

```text
telegram-cli/
├── telegram_cli.py
├── app/
│   ├── __init__.py
│   ├── cli.py
│   ├── config.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── messaging.py
│   │   ├── media.py
│   │   └── settings.py
├── downloads/
├── tests/
├── pyproject.toml
└── README.md
```

Responsibilities:

- `telegram_cli.py`: application entry point and lifecycle.
- `app/cli.py`: command parsing, interactive prompts, and terminal output.
- `app/config.py`: persistent local configuration and defaults.
- `app/services/messaging.py`: message history, sending, replying, and message lookup.
- `app/services/media.py`: uploads, attachment discovery, downloads, and file metadata.
- `app/services/settings.py`: local settings and supported Telegram account settings.
- `tests/`: automated tests for parsing, configuration, and service behavior.

Use dependency injection where practical. Avoid circular imports, duplicated logic, global mutable state, and oversized files. Keep Telethon API calls in the appropriate services rather than scattering them throughout the interface.

## Feature 1: Message replies

Implement:

- Display message IDs in chat history.
- Reply to a specific message by ID.
- Display reply relationships in message history.
- Validate message IDs and report missing messages.
- Allow attachments to be sent as replies.
- Ensure replies target the correct currently selected chat.

Suggested commands:

```text
chats
open 1
history 20
reply 123 Thanks for sharing this!
```

Message IDs must be interpreted within the currently selected chat. Never silently reply to a different conversation.

## Feature 2: File uploads

Implement:

- Upload documents, images, audio, and video.
- Optional captions.
- Optional reply-to-message IDs.
- Absolute and relative local file paths.
- Paths containing spaces.
- File existence and readability validation.
- Clear progress and completion messages for large uploads, using supported Telethon progress callbacks.
- Friendly handling of network failures, permissions, and Telegram upload errors.

Suggested commands:

```text
attach "/home/user/Documents/report.pdf"
attach "/home/user/Music/song.mp3" --caption "Audio sample"
attach "/home/user/Pictures/photo.jpg" --reply 123
```

Use a robust argument parser or a shell-style tokenizer. Do not parse commands using naïve string splitting.

## Feature 3: Received attachments

Implement:

- List recent messages containing media.
- Show message ID, sender, timestamp, media type, filename when available, and caption.
- Distinguish documents, photos, videos, audio, voice messages, and other media where possible.
- Download an attachment by message ID into a configurable downloads directory.
- Preserve safe filenames and prevent path traversal or accidental writes outside the configured download directory.
- Handle files without filenames and duplicate filenames safely.
- Display download progress when supported.
- Open downloaded files with Fedora's default application using `xdg-open`, without invoking a shell.
- Never automatically execute downloaded files.
- Handle unavailable media, permissions, interrupted downloads, and invalid message IDs gracefully.

Suggested commands:

```text
attachments 30
download 456
view 456
```

Do not attempt to render arbitrary binary files as terminal text. For images and other media, opening the downloaded file externally is acceptable. If terminal previews are added, make them optional and dependency-aware.

## Feature 4: Settings

Create persistent local settings stored in a JSON configuration file, with validation and safe defaults.

Support settings such as:

- Download directory.
- Default history limit.
- Send confirmation preference.
- Optional terminal theme or display preferences.

Suggested commands:

```text
settings
settings set history_limit 40
settings set download_dir ~/Downloads/telegram
settings set confirm_before_send true
```

Requirements:

- Validate values and reject invalid settings.
- Create required directories safely.
- Write configuration atomically where practical to avoid corruption.
- Keep secrets and authentication sessions out of the configuration file.
- Never print API credentials or session data.
- Clearly distinguish local CLI settings from Telegram cloud account settings.

For Telegram account settings, investigate the current Telethon API and implement only supported operations. Where feasible, add read and update commands for privacy controls and notification settings. Clearly distinguish unsupported or unavailable operations; never claim a setting changed when it did not.

Require explicit confirmation for potentially consequential account-level changes.

## Feature 5: Command-line experience

Maintain an interactive prompt with a consistent command structure.

Requirements:

- A `help` command showing available commands and usage.
- Helpful errors and recovery without terminating the application.
- Clear indication of the currently selected chat.
- Message IDs visible in history.
- Confirmation before sending messages when enabled in settings.
- Graceful shutdown on `quit`, Ctrl+C, and Ctrl+D.
- Consistent logging without exposing private information.
- No accidental sending of messages because of ambiguous command parsing.

Keep existing working commands compatible where possible.

## Engineering requirements

- Inspect the installed Python and Telethon versions before choosing APIs.
- Follow the existing Python environment; do not change Python versions unless there is a demonstrated compatibility issue.
- Add type hints to service interfaces and important functions.
- Use `pathlib` for filesystem operations.
- Use asynchronous Telethon APIs correctly.
- Avoid blocking network calls and unnecessary synchronous work in the event loop.
- Catch expected errors specifically; don't silently swallow exceptions.
- Never log API hashes, login codes, two-factor passwords, session contents, or message bodies unnecessarily.
- Never commit `.session` files, API credentials, or private configuration.
- Add a `.gitignore` covering virtual environments, session files, secrets, caches, test artifacts, and local configuration as appropriate.
- Keep dependencies minimal and document any additions.
- Use a supported argument parser rather than building a fragile custom parser.
- Add automated tests using mocks where Telegram network access is not required.

## Implementation workflow

Work in phases:

### Phase 1: Audit
Inspect the project and report the current architecture, existing commands, session location, dependencies, and potential compatibility issues. Do not expose secret values.

### Phase 2: Plan
Propose the smallest safe refactor and map each feature to its module. Identify any changes that could affect authentication or existing commands.

### Phase 3: Implement
Back up affected files, then implement the architecture and features incrementally. Preserve the existing session.

### Phase 4: Test
Run the test suite, import checks, syntax checks, and any available static checks in the existing virtual environment.

Test at least:

- Configuration defaults and invalid values.
- Settings persistence.
- Command parsing with spaces and quoted paths.
- Reply target validation.
- File existence checks.
- Attachment metadata formatting.
- Error handling.
- Graceful shutdown.

Mock Telegram API interactions where appropriate. Do not send real messages, upload files, modify account privacy settings, or perform destructive actions during tests.

### Phase 5: Verify
Review the changes for regressions, credential leaks, accidental session changes, unsafe path handling, and architectural issues.

Provide a concise summary of:

- Files created or modified.
- Features implemented.
- Commands and examples.
- Tests executed and their actual results.
- Any known limitations.
- How to launch the upgraded application.
- Any manual testing still needed.

## Important execution rules

- Operate within the existing project directory.
- Do not delete user files or the current session.
- Do not overwrite unrelated files.
- Do not ask me to paste secrets into the terminal or chat.
- Do not claim tests passed unless they were actually executed.
- Do not stop after producing a plan: after inspecting and planning, proceed with implementation and testing if the environment permits.
- If a significant issue requires my decision, explain the issue and ask before making a risky change.

The final result should be a reliable, modular Telegram CLI that works with my existing account and can be extended with additional features later.
