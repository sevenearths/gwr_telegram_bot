# Train Fares Telegram Bot

A Telegram bot that sends personalized GWR train fare alerts based on your commute schedule. Set up your journey preferences once, and receive regular updates with the cheapest fares—highlighted when they fall below your target price.

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Begin the setup wizard to configure your journey preferences |
| `/check` | Manually fetch current fares (4-hour cooldown between checks) |
| `/settings` | View your current preferences |
| `/change` | Modify individual settings without full reconfiguration |
| `/stop` | Unsubscribe from fare updates |
| `/cancel` | Cancel the current setup or change conversation |

## Features

- **Personalized Setup** — Configure departure/return stations, travel days & times, fare thresholds, and notification schedule
- **Fuzzy Station Search** — Find stations by name with typo tolerance using rapidfuzz
- **Price Alerts** — Fares below your threshold are marked with 🔥
- **Flexible Scheduling** — Choose two days per week and any 15-minute time slot for notifications
- **Configurable Search Period** — Look 1–3 months ahead for fares
- **Manual Checks** — Get fares on-demand with `/check`

---

## Development Notes

### Running the Bot

**Interactive mode** (handles user commands):
```bash
TELEGRAM_BOT_TOKEN="your-token" python train_fares_bot.py
```

**Scheduled mode** (sends fares to users at their preferred times):
```bash
TELEGRAM_BOT_TOKEN="your-token" python train_fares_bot.py scheduled
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | *required* | Bot token from [@BotFather](https://t.me/BotFather) |
| `CHECK_COOLDOWN_HOURS` | `4` | Hours between manual `/check` commands |
| `FUZZY_SEARCH_THRESHOLD` | `90` | Score threshold for auto-selecting station matches |

### Cron Setup

Run scheduled mode frequently (e.g., every 5 minutes) to catch all user-configured notification times:

```cron
*/5 * * * * TELEGRAM_BOT_TOKEN="your-token" /path/to/.venv/bin/python /path/to/train_fares_bot.py scheduled >> /path/to/cron.log 2>&1
```

### Data Storage

- `chat_ids..json` — User preferences (stations, schedule, thresholds)
- `locations.json` — Station database for fuzzy search

### Recent Changes

- **Per-user preferences** — Each user has fully independent settings stored as JSON
- **Conversation-based setup** — Guided wizard collects all preferences step-by-step
- **Station fuzzy search** — Type station names with typos; bot suggests closest matches
- **Change settings menu** — `/change` command to update individual preferences without re-running full setup
- **Configurable fare thresholds** — Separate outbound/return price alerts (fares below shown with 🔥)
- **Flexible message scheduling** — Users pick 2 days + time for automatic fare updates
- **Search period selection** — Choose 1, 2, or 3 months ahead
- **Check cooldown** — Prevents API abuse; configurable via environment variable
