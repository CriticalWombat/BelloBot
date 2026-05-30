# BelloBot

A Discord bot for [Carabello Coffee](https://www.carabellocoffee.com/) that serves menu information, community voting, drink notes, upcoming events, reservations, and location-based notifications via Home Assistant. Runs in Docker behind a Cloudflare Tunnel.

---

## Features

### Menu
- `/analog` — Displays the current Analog Bar menu image
- `/events` — Scrapes and displays upcoming coffee class events with ticket links
- `/reserve` — Posts a reservation link for the Analog Bar via Resurva

### Voting
- `/vote` — Assign your 🥇 Gold (3 pts), 🥈 Silver (2 pts), or 🥉 Bronze (1 pt) vote to a drink. You can change any tier at any time; each tier can only be held by one drink at a time.
- `/results` — Leaderboard for the current menu, sorted by weighted score. Shows who assigned each tier to each drink.
- `/votehistory` — Browse vote results from past menus (archived when the menu changes).

### Notes
- `/add_note` — Leave a text note on a specific drink, signed automatically with your display name and date.
- `/notes` — View all notes left on the current menu's drinks.

### Debug
- `/debug` — Shows the raw OCR output and parsed drink names from the current menu image. Useful for diagnosing autocomplete issues.

### Webhook
- **Webhook listener** — Receives authenticated POST requests from Home Assistant to post location-based notifications in Discord.

---

## Architecture

```
Home Assistant (Zone Trigger)
        │
        ▼
REST Command → POST https://bellobot.yourdomain.com/webhook
        │
        ▼
Cloudflare Tunnel
        │
        ▼
Docker Network (bellonet)
        │
        ▼
Bot Container (aiohttp on :8080)
        │
        ▼
Discord Channel
```

Vote and note data is persisted to `votes.json` on a named Docker volume (`votes_data`) mounted at `/data`. Each time the Analog Bar menu changes (detected by hashing the OCR-parsed drink list), the active session is archived and a new one begins. Archived sessions remain readable via `/votehistory`.

---

## Requirements

- Docker + Docker Compose
- A Discord bot token ([Discord Developer Portal](https://discord.com/developers/applications))
- A Cloudflare account with a managed domain and tunnel configured
- Python 3.12+ (for local development only)
- Tesseract OCR (`tesseract-ocr` package, included in the Docker image)

---

## Environment Variables

Create a `.env` file in the project root:

```
TOKEN=               # Discord bot token
SERVERID=            # Discord server ID
CHANNEL_ID=          # Discord channel ID for webhook notifications
WEBHOOK_SECRET=      # Secret key for authenticating webhook requests
CF_TUNNEL_TOKEN=     # Cloudflare tunnel token
```

`VOTES_PATH` is set automatically by `docker-compose.yaml` to `/data/votes.json`. Override it for local development if needed.

> ⚠️ Never commit `.env` to version control. It is excluded via `.gitignore`.

---

## Running with Docker

```bash
docker compose up -d --build
docker compose logs -f
```

Both the bot and Cloudflare Tunnel container will start on the shared `bellonet` Docker network. The tunnel routes `https://bellobot.yourdomain.com/webhook` to `http://bot:8080`. Vote data is stored in the `votes_data` named volume and survives container restarts and rebuilds.

---

## Webhook

The bot exposes a single POST endpoint at `/webhook`.

**Required header:**
```
X-Webhook-Secret: your_secret_here
```

**Expected payload:**
```json
{
  "source": "home_assistant",
  "event": "loc-ping",
  "person": "your_name"
}
```

**Response:**
- `200 OK` — payload accepted, message posted to Discord
- `401 Unauthorized` — invalid or missing secret
- `400 Unrecognized payload` — payload does not match expected shape

**Test with curl:**
```bash
curl -X POST https://bellobot.yourdomain.com/webhook \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: your_secret_here" \
  -d '{"source": "home_assistant", "event": "loc-ping", "person": "your_name"}'
```

---

## Home Assistant Integration

Add the following to `configuration.yaml`:

```yaml
rest_command:
  notify_bellobot:
    url: "https://bellobot.yourdomain.com/webhook"
    method: POST
    headers:
      Content-Type: "application/json"
      X-Webhook-Secret: !secret bellobot_webhook_secret
    payload: '{"source": "home_assistant", "event": "loc-ping", "person": "your_name"}'
    content_type: "application/json"
```

Add the secret to `secrets.yaml`:

```yaml
bellobot_webhook_secret: your_secret_here
```

Example zone automation:

```yaml
alias: "Notify Discord - Arrived at Carabello"
trigger:
  - platform: zone
    entity_id: person.your_name
    zone: zone.carabello_coffee
    event: enter
action:
  - service: rest_command.notify_bellobot
```

---

## Discord Bot Permissions

**OAuth2 Scopes:**
- `bot`
- `applications.commands`

**Bot Permissions:**
- `Send Messages`
- `Embed Links`
- `Mention Everyone`

---

## Local Development

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

> The `venv/` directory is excluded from Docker builds via `.dockerignore`.
