import os
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

DB_PATH = Path(os.getenv("ARK_DB_PATH", "/data/ark_stats.db"))
APP_TITLE = "ARK Stats"
SERVER_NAME = os.getenv("ARK_SERVER_NAME", "Pulpinesien - The Island")
HERO_IMAGE_URL = os.getenv(
    "ARK_HERO_IMAGE_URL",
    "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/2399830/header.jpg",
)

app = FastAPI(title=APP_TITLE)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
templates.env.globals["app_title"] = APP_TITLE
templates.env.globals["server_name"] = SERVER_NAME
templates.env.globals["hero_image_url"] = HERO_IMAGE_URL


def get_conn() -> sqlite3.Connection:
    # Open DB in read-only mode so web app never writes into bot database.
    uri = f"file:{DB_PATH}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON;")
    return conn


def fetch_all(query: str, params: tuple[Any, ...] = ()) -> tuple[list[dict], str | None]:
    try:
        with get_conn() as conn:
            return [dict(r) for r in conn.execute(query, params).fetchall()], None
    except sqlite3.Error as exc:
        return [], str(exc)


def fetch_last_db_update() -> str | None:
    query = """
    SELECT MAX(ts) AS last_update
    FROM (
      SELECT MAX(updated_at) AS ts FROM player_stats
      UNION ALL
      SELECT MAX(last_seen_at) AS ts FROM players
      UNION ALL
      SELECT MAX(last_seen_at) AS ts FROM tribes
      UNION ALL
      SELECT MAX(last_seen_at) AS ts FROM player_tribe_membership
      UNION ALL
      SELECT MAX(recorded_at) AS ts FROM dino_tame_events
      UNION ALL
      SELECT MAX(recorded_at) AS ts FROM player_kill_events
      UNION ALL
      SELECT MAX(recorded_at) AS ts FROM player_death_events
      UNION ALL
      SELECT MAX(recorded_at) AS ts FROM dino_kill_events
    )
    """
    rows, _ = fetch_all(query)
    if not rows:
        return None
    return rows[0].get("last_update")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"title": APP_TITLE, "last_db_update": fetch_last_db_update()},
    )


@app.get("/players", response_class=HTMLResponse)
def players(request: Request):
    query = """
    SELECT p.player_name,
           s.dino_kills_total,
           s.player_kills_total,
           s.dino_tames_total,
           COALESCE(d.deaths_total, 0) AS deaths_total,
           s.updated_at
    FROM player_stats s
    JOIN players p ON p.id = s.player_id
    LEFT JOIN (
        SELECT victim_player_id, COUNT(*) AS deaths_total
        FROM player_death_events
        WHERE victim_player_id IS NOT NULL
        GROUP BY victim_player_id
    ) d ON d.victim_player_id = p.id
    WHERE s.dino_kills_total > 0
       OR s.player_kills_total > 0
       OR s.dino_tames_total > 0
       OR COALESCE(d.deaths_total, 0) > 0
    ORDER BY p.player_name COLLATE NOCASE ASC
    """
    rows, db_error = fetch_all(query)

    return templates.TemplateResponse(
        request=request,
        name="players.html",
        context={
            "title": f"{APP_TITLE} - Players",
            "rows": rows,
            "db_error": db_error,
            "last_db_update": fetch_last_db_update(),
        },
    )


@app.get("/tribes", response_class=HTMLResponse)
def tribes(request: Request):
    query = """
    SELECT t.tribe_name,
           p.player_name,
           m.last_seen_at
    FROM player_tribe_membership m
    JOIN players p ON p.id = m.player_id
    JOIN tribes t ON t.id = m.tribe_id
    ORDER BY t.tribe_name COLLATE NOCASE ASC,
             p.player_name COLLATE NOCASE ASC
    """

    rows, db_error = fetch_all(query)

    return templates.TemplateResponse(
        request=request,
        name="tribes.html",
        context={
            "title": f"{APP_TITLE} - Tribes",
            "rows": rows,
            "db_error": db_error,
            "last_db_update": fetch_last_db_update(),
        },
    )


@app.get("/leaderboards", response_class=HTMLResponse)
def leaderboards(request: Request):
    dino_kills, err1 = fetch_all(
        """
        SELECT p.player_name, s.dino_kills_total AS score
        FROM player_stats s
        JOIN players p ON p.id = s.player_id
        WHERE s.dino_kills_total > 0
        ORDER BY s.dino_kills_total DESC, p.player_name COLLATE NOCASE ASC
        LIMIT 100
        """
    )
    player_kills, err2 = fetch_all(
        """
        SELECT p.player_name, s.player_kills_total AS score
        FROM player_stats s
        JOIN players p ON p.id = s.player_id
        WHERE s.player_kills_total > 0
        ORDER BY s.player_kills_total DESC, p.player_name COLLATE NOCASE ASC
        LIMIT 100
        """
    )
    dino_tames, err3 = fetch_all(
        """
        SELECT p.player_name, s.dino_tames_total AS score
        FROM player_stats s
        JOIN players p ON p.id = s.player_id
        WHERE s.dino_tames_total > 0
        ORDER BY s.dino_tames_total DESC, p.player_name COLLATE NOCASE ASC
        LIMIT 100
        """
    )
    most_deaths, err4 = fetch_all(
        """
        SELECT COALESCE(p.player_name, e.victim_name) AS player_name, COUNT(*) AS score
        FROM player_death_events e
        LEFT JOIN players p ON p.id = e.victim_player_id
        GROUP BY COALESCE(p.player_name, e.victim_name)
        HAVING COUNT(*) > 0
        ORDER BY score DESC, player_name COLLATE NOCASE ASC
        LIMIT 100
        """
    )
    db_error = err1 or err2 or err3 or err4

    return templates.TemplateResponse(
        request=request,
        name="leaderboards.html",
        context={
            "title": f"{APP_TITLE} - Leaderboards",
            "dino_kills": dino_kills,
            "player_kills": player_kills,
            "dino_tames": dino_tames,
            "most_deaths": most_deaths,
            "db_error": db_error,
            "last_db_update": fetch_last_db_update(),
        },
    )


@app.get("/deaths", response_class=HTMLResponse)
def deaths(request: Request):
    leaderboard, err1 = fetch_all(
        """
        SELECT COALESCE(p.player_name, e.victim_name) AS player_name,
               COUNT(*) AS deaths_total,
               SUM(
                   CASE
                       WHEN e.killer_text IS NOT NULL
                        AND TRIM(e.killer_text) <> ''
                        AND LOWER(e.killer_text) NOT LIKE 'a %'
                        AND LOWER(e.killer_text) NOT LIKE 'an %'
                        AND LOWER(e.killer_text) NOT LIKE 'the %'
                        AND INSTR(e.killer_text, '|') = 0
                       THEN 1
                       ELSE 0
                   END
               ) AS likely_pvp_deaths
        FROM player_death_events e
        LEFT JOIN players p ON p.id = e.victim_player_id
        GROUP BY COALESCE(p.player_name, e.victim_name)
        ORDER BY deaths_total DESC, player_name COLLATE NOCASE ASC
        LIMIT 100
        """
    )

    recent_deaths, err2 = fetch_all(
        """
        SELECT COALESCE(p.player_name, e.victim_name) AS victim_name,
               COALESCE(NULLIF(TRIM(e.killer_text), ''), 'Unbekannt / Umwelt') AS killer_text,
               COALESCE(e.event_time_text, e.recorded_at) AS event_time,
               e.source_rule
        FROM player_death_events e
        LEFT JOIN players p ON p.id = e.victim_player_id
        ORDER BY e.id DESC
        LIMIT 200
        """
    )

    db_error = err1 or err2
    return templates.TemplateResponse(
        request=request,
        name="deaths.html",
        context={
            "title": f"{APP_TITLE} - Deaths",
            "leaderboard": leaderboard,
            "recent_deaths": recent_deaths,
            "db_error": db_error,
            "last_db_update": fetch_last_db_update(),
        },
    )
