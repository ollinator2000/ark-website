# ARK Website

Leichtgewichtige Website, die deine bestehende ARK SQLite-Datenbank (`ark_stats.db`) read-only ausliest und veröffentlicht.

## Was die App zeigt

- `/players`: alle Spieler mit mindestens 1 Dino-Kill, Player-Kill oder Tame
- `/tribes`: Zuordnung Spieler zu Tribe
- `/leaderboards`: Rankings für Dino-Kills, Player-Kills, Dino-Tames
- `/healthz`: einfacher Healthcheck

## Architektur

- `ark-discord` schreibt Events in `ark_stats.db`.
- Diese Website liest dieselbe DB nur read-only (`mode=ro` + `PRAGMA query_only=ON`).
- Auslieferung als FastAPI-App hinter Traefik2.

## Komponenten

- App: [main.py](/Users/olveld/wrk/ark-website/app/main.py)
- Templates: `/Users/olveld/wrk/ark-website/templates`
- Styles: [style.css](/Users/olveld/wrk/ark-website/static/style.css)
- Container: [Dockerfile](/Users/olveld/wrk/ark-website/Dockerfile)
- Orchestrierung: [docker-compose.yml](/Users/olveld/wrk/ark-website/docker-compose.yml)
- Beispielvariablen: [.env.example](/Users/olveld/wrk/ark-website/.env.example)

## Voraussetzungen

- Linux Root-Server mit Docker und Docker Compose
- Traefik2 ist bereits installiert und funktionsfähig
- Zugriff auf die Bot-DB `ark_stats.db` auf dem Host

## Konfiguration

Lege `.env` an:

```bash
cd /Users/olveld/wrk/ark-website
cp .env.example .env
```

### Variablen in `.env`

- `ARK_HOST`: Bind-Adresse im Container (normal `0.0.0.0`)
- `ARK_PORT`: App-Port im Container (normal `8000`)
- `ARK_DB_SOURCE`: absoluter Host-Pfad zur SQLite-Datei
- `ARK_DB_TARGET`: Zielpfad im Container (muss nicht geändert werden, default `/data/ark_stats.db`)
- `TRAEFIK_HOST`: Domain/Subdomain, z. B. `arkstats.deinedomain.tld`
- `TRAEFIK_NETWORK`: Name des externen Docker-Netzwerks, das dein Traefik nutzt

## Installation (Docker)

1. `.env` anpassen (mindestens `ARK_DB_SOURCE`, `TRAEFIK_HOST`, optional `TRAEFIK_NETWORK`).
2. Stack bauen und starten:

```bash
docker compose up -d --build
```

3. Logs prüfen:

```bash
docker compose logs -f
```

4. Aufruf:
- `https://<TRAEFIK_HOST>/`

## Traefik-Clientkonfiguration (für diese Website)

In [docker-compose.yml](/Users/olveld/wrk/ark-website/docker-compose.yml) sind die für diese App nötigen Traefik-Labels bereits gesetzt:

- Router aktivieren: `traefik.enable=true`
- Host-Regel: `traefik.http.routers.ark-website.rule=Host(`${TRAEFIK_HOST}`)`
- EntryPoint: `websecure`
- TLS: aktiviert
- Service-Port: `8000`

Wichtig für die Website-Anbindung:

- `TRAEFIK_HOST` muss zur gewünschten Domain/Subdomain passen.
- `TRAEFIK_NETWORK` muss das bereits vorhandene externe Netzwerk deines Traefik sein.
- Der Service `ark-website` muss in genau diesem Netzwerk hängen (ist in Compose bereits so konfiguriert).

## Lokaler Dev-Start ohne Docker

```bash
cd /Users/olveld/wrk/ark-website
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export ARK_DB_PATH=/absoluter/pfad/zur/ark_stats.db
uvicorn app.main:app --reload
```

Dann öffnen: `http://127.0.0.1:8000/`

## Fehlerbehebung

- Seite zeigt `Datenbankfehler`:
  - Prüfe, ob `ARK_DB_SOURCE` auf eine existierende DB zeigt.
  - Prüfe Dateirechte (Container braucht Leserechte).
  - Prüfe, ob die DB wirklich das erwartete Schema enthält.
- Keine Daten in Tabellen:
  - Bot hat evtl. noch keine Events persistiert.
- Traefik liefert 404:
  - `TRAEFIK_HOST` stimmt nicht mit aufgerufener Domain überein.
  - Container hängt nicht im Traefik-Netzwerk.

## Sicherheitshinweis

Die Website ist öffentlich erreichbar, sobald Traefik-Router aktiv ist. Falls gewünscht, ergänze BasicAuth oder IP-Whitelist in Traefik.
