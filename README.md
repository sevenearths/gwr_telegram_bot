# Train Fares Telegram Bot

Sends GWR train fare updates to subscribers on Wednesdays and Saturdays at 3pm.

## Usage

Run the bot for interactive commands (`/start`, `/stop`, `/check`):

```bash
TELEGRAM_BOT_TOKEN="your-token" python train_fares_bot.py
```

Send scheduled fares to all subscribers (for cron):

```bash
TELEGRAM_BOT_TOKEN="your-token" python train_fares_bot.py scheduled
```

## Cron Setup

Add to crontab (`crontab -e`) for Wednesdays and Saturdays at 3pm:

```
# m h  dom mon dow   command
0 15 * * 3,6 TELEGRAM_BOT_TOKEN="your-token" /path/to/.venv/bin/python /path/to/train_fares_bot.py scheduled >> /path/to/cron.log 2>&1
```

## Commands

- `/start` - Subscribe to fare updates
- `/stop` - Unsubscribe
- `/check` - Get fares now
