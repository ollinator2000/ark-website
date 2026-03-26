# ARK Website

Leichtgewichtige FastAPI-Website, die deine bestehende ARK SQLite-Datenbank (`ark_stats.db`) read-only ausliest und veröffentlicht.

## Features

- `/players`: Spieler mit mindestens einem Dino-Kill, Player-Kill oder Tame
- `/tribes`: Spieler-zu-Tribe Übersicht
- `/leaderboards`: Top Dino-Kills, Player-Kills, Dino-Tames
- `/deaths`: Death-Log mit Most-Deaths und letzten Todesereignissen
- `/healthz`: Healthcheck
- ARK-Theme mit konfigurierbarem Servernamen und Hero-Bild

## Architektur

- `ark-discord` schreibt in `ark_stats.db`
- diese Website liest dieselbe DB read-only (`mode=ro`, `PRAGMA query_only=ON`)
- Deployment als Container hinter bestehendem Traefik

## Wichtige Dateien

- App: [main.py](/Users/olveld/wrk/ark-website/app/main.py)
- Styling: [style.css](/Users/olveld/wrk/ark-website/static/style.css)
- Templates: `/Users/olveld/wrk/ark-website/templates`
- Compose: [docker-compose.yml](/Users/olveld/wrk/ark-website/docker-compose.yml)
- Env-Vorlage: [.env.example](/Users/olveld/wrk/ark-website/.env.example)

## Voraussetzungen

- Docker + Docker Compose
- laufender Traefik2-Stack
- lesbarer Host-Pfad zur `ark_stats.db`

## Konfiguration

```bash
cd /Users/olveld/wrk/ark-website
cp .env.example .env
```

### Variablen in `.env`

- `ARK_HOST`: Bind-Adresse im Container (Standard: `0.0.0.0`)
- `ARK_PORT`: App-Port im Container (Standard: `8000`)
- `ARK_SERVER_NAME`: Anzeigename im Hero-Bereich
- `ARK_HERO_IMAGE_URL`: Hero-Hintergrundbild (URL)
- `ARK_DB_SOURCE`: absoluter Host-Pfad zur SQLite-Datei
- `ARK_DB_TARGET`: Zielpfad im Container (Standard: `/data/ark_stats.db`)
- `TRAEFIK_HOST`: Domain/Subdomain für die Website
- `TRAEFIK_NETWORK`: externes Docker-Netzwerk deines Traefik

## Start

```bash
docker compose up -d --build
docker compose logs -f
```

Aufruf:
- `https://<TRAEFIK_HOST>/`

## Traefik-Clientsettings dieser App

Im Compose sind diese Labels gesetzt:

- `traefik.enable=true`
- `traefik.docker.network=${TRAEFIK_NETWORK}`
- `traefik.http.routers.ark-secure.rule=Host(`${TRAEFIK_HOST}`)`
- `traefik.http.routers.ark-secure.entrypoints=https`
- `traefik.http.routers.ark-secure.tls=true`
- `traefik.http.routers.ark-secure.service=ark`
- `traefik.http.services.ark.loadbalancer.server.port=8000`

## Funktionstest im Terminal

Container/App prüfen:

```bash
docker compose ps
docker compose logs --tail=100 ark-website
```

Healthcheck intern (ohne `curl` im Container):

```bash
docker compose exec ark-website sh -lc 'python -c "import urllib.request; print(urllib.request.urlopen(\"http://127.0.0.1:8000/healthz\").read().decode())"'
```

DB-Mount prüfen:

```bash
docker compose exec ark-website sh -lc 'python -c "import sqlite3,os; p=os.environ[\"ARK_DB_PATH\"]; c=sqlite3.connect(f\"file:{p}?mode=ro\", uri=True); print(c.execute(\"PRAGMA database_list;\").fetchall())"'
```

## Lokaler Start ohne Docker

```bash
cd /Users/olveld/wrk/ark-website
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export ARK_DB_PATH=/absoluter/pfad/zur/ark_stats.db
uvicorn app.main:app --reload
```

Dann öffnen: `http://127.0.0.1:8000/`

## Troubleshooting

- `502 Bad Gateway` über Traefik:
  - Service-Port-Label muss `8000` sein
  - `TRAEFIK_NETWORK` muss korrekt sein
  - `TRAEFIK_HOST` muss exakt zur Domain passen
- `Datenbankfehler` auf Seiten:
  - `ARK_DB_SOURCE` zeigt auf falschen Pfad
  - fehlende Leserechte auf der DB-Datei
- leere Tabellen:
  - Bot hat noch keine Events persistiert

## Hinweis

Die Seite lädt Google Fonts und das Hero-Bild per externer URL. Wenn dein Server ausgehende Verbindungen stark beschränkt, kann das Theme reduziert dargestellt werden.
