# Tausendsassa Discord Bot

A flexible, modular Discord bot featuring map pinning and RSS feed cogs, plus comprehensive console, file, and webhook logging.

## Installation

```bash
git clone https://github.com/spa1teN/TausendsassaBot.git
cd TausendsassaBot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Configuration
- Set the `DISCORD_TOKEN` environment variable.
- Configure `LOG_WEBHOOK_URL` in `bot.py` or via env var.
- Download and extract the vector-file from `data/sources.txt`

## Usage
- Start the bot:
```bash
python3 bot.py
```
- run `/help`