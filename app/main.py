import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

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
DISPLAY_TIMEZONE = os.getenv("ARK_DISPLAY_TIMEZONE", "Europe/Berlin")

app = FastAPI(title=APP_TITLE)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
templates.env.globals["app_title"] = APP_TITLE
templates.env.globals["server_name"] = SERVER_NAME
templates.env.globals["hero_image_url"] = HERO_IMAGE_URL
templates.env.globals["display_timezone"] = DISPLAY_TIMEZONE

try:
    LOCAL_TZ = ZoneInfo(DISPLAY_TIMEZONE)
except Exception:
    LOCAL_TZ = ZoneInfo("UTC")


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


def format_ts_local(value: Any) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None

    candidate = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    dt: datetime | None = None

    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
            try:
                dt = datetime.strptime(candidate, pattern)
                break
            except ValueError:
                continue

    if dt is None:
        return raw

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)

    local = dt.astimezone(LOCAL_TZ)
    return local.strftime("%d.%m.%Y %H:%M:%S %Z")


def format_rows_timestamps(rows: list[dict], keys: tuple[str, ...]) -> list[dict]:
    for row in rows:
        for key in keys:
            if key in row:
                row[key] = format_ts_local(row.get(key))
    return rows


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
    return format_ts_local(rows[0].get("last_update"))


def fetch_dino_killer_ranking(limit: int = 100) -> tuple[list[dict], str | None]:
    query = """
    WITH normalized AS (
      SELECT
        CASE
          WHEN LOWER(TRIM(killer_text)) LIKE 'a %' THEN SUBSTR(TRIM(killer_text), 3)
          WHEN LOWER(TRIM(killer_text)) LIKE 'an %' THEN SUBSTR(TRIM(killer_text), 4)
          WHEN LOWER(TRIM(killer_text)) LIKE 'the %' THEN SUBSTR(TRIM(killer_text), 5)
          ELSE TRIM(killer_text)
        END AS killer_no_article
      FROM player_death_events
      WHERE source_rule = 'player_death_by'
        AND killer_text IS NOT NULL
        AND TRIM(killer_text) <> ''
        AND (
          LOWER(TRIM(killer_text)) LIKE 'a %'
          OR LOWER(TRIM(killer_text)) LIKE 'an %'
          OR LOWER(TRIM(killer_text)) LIKE 'the %'
          OR INSTR(TRIM(killer_text), ' - Lvl ') > 0
        )
    ),
    typed AS (
      SELECT
        TRIM(
          CASE
            WHEN INSTR(killer_no_article, ' - Lvl ') > 0
              THEN SUBSTR(killer_no_article, 1, INSTR(killer_no_article, ' - Lvl ') - 1)
            ELSE killer_no_article
          END
        ) AS dino_name
      FROM normalized
    )
    SELECT dino_name AS player_name, dino_name, COUNT(*) AS score
    FROM typed
    WHERE dino_name <> ''
    GROUP BY dino_name
    ORDER BY score DESC, dino_name COLLATE NOCASE ASC
    LIMIT ?
    """
    return fetch_all(query, (limit,))


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    dino_killers, dino_error = fetch_dino_killer_ranking(limit=10)
    top_dino = dino_killers[0] if dino_killers else None
    top_dino_killer_players, err_player_dino = fetch_all(
        """
        SELECT p.player_name, s.dino_kills_total AS score
        FROM player_stats s
        JOIN players p ON p.id = s.player_id
        WHERE s.dino_kills_total > 0
        ORDER BY s.dino_kills_total DESC, p.player_name COLLATE NOCASE ASC
        LIMIT 1
        """
    )
    top_tamers, err_tamer = fetch_all(
        """
        SELECT p.player_name, s.dino_tames_total AS score
        FROM player_stats s
        JOIN players p ON p.id = s.player_id
        WHERE s.dino_tames_total > 0
        ORDER BY s.dino_tames_total DESC, p.player_name COLLATE NOCASE ASC
        LIMIT 1
        """
    )
    top_player_dino_kills = top_dino_killer_players[0] if top_dino_killer_players else None
    top_player_tames = top_tamers[0] if top_tamers else None
    db_error = dino_error or err_player_dino or err_tamer

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "title": APP_TITLE,
            "last_db_update": fetch_last_db_update(),
            "top_dino": top_dino,
            "top_player_dino_kills": top_player_dino_kills,
            "top_player_tames": top_player_tames,
            "db_error": db_error,
        },
    )


@app.get("/players", response_class=HTMLResponse)
def players(request: Request):
    query = """
    SELECT p.player_name,
           s.dino_kills_total,
           s.player_kills_total,
           s.dino_tames_total,
           COALESCE(d.deaths_total, 0) AS deaths_total,
           COALESCE(d.deaths_by_human, 0) AS deaths_by_human,
           COALESCE(d.deaths_by_dino, 0) AS deaths_by_dino,
           s.updated_at
    FROM player_stats s
    JOIN players p ON p.id = s.player_id
    LEFT JOIN (
        SELECT victim_player_id,
               COUNT(*) AS deaths_total,
               SUM(
                 CASE
                   WHEN killer_text IS NOT NULL
                    AND TRIM(killer_text) <> ''
                    AND NOT (
                      LOWER(TRIM(killer_text)) LIKE 'a %'
                      OR LOWER(TRIM(killer_text)) LIKE 'an %'
                      OR LOWER(TRIM(killer_text)) LIKE 'the %'
                      OR INSTR(TRIM(killer_text), ' - Lvl ') > 0
                    )
                 THEN 1 ELSE 0 END
               ) AS deaths_by_human,
               SUM(
                 CASE
                   WHEN killer_text IS NOT NULL
                    AND TRIM(killer_text) <> ''
                    AND (
                      LOWER(TRIM(killer_text)) LIKE 'a %'
                      OR LOWER(TRIM(killer_text)) LIKE 'an %'
                      OR LOWER(TRIM(killer_text)) LIKE 'the %'
                      OR INSTR(TRIM(killer_text), ' - Lvl ') > 0
                    )
                 THEN 1 ELSE 0 END
               ) AS deaths_by_dino
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
    rows = format_rows_timestamps(rows, ("updated_at",))

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
    rows = format_rows_timestamps(rows, ("last_seen_at",))

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
    dino_tames, err2 = fetch_all(
        """
        SELECT p.player_name, s.dino_tames_total AS score
        FROM player_stats s
        JOIN players p ON p.id = s.player_id
        WHERE s.dino_tames_total > 0
        ORDER BY s.dino_tames_total DESC, p.player_name COLLATE NOCASE ASC
        LIMIT 100
        """
    )
    most_deaths, err3 = fetch_all(
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
    human_player_kills, err4 = fetch_all(
        """
        SELECT p.player_name, COUNT(*) AS score
        FROM player_kill_events e
        JOIN players p ON p.id = e.killer_player_id
        GROUP BY p.player_name
        HAVING COUNT(*) > 0
        ORDER BY score DESC, p.player_name COLLATE NOCASE ASC
        LIMIT 100
        """
    )
    dino_player_kills, err5 = fetch_dino_killer_ranking(limit=100)
    db_error = err1 or err2 or err3 or err4 or err5

    return templates.TemplateResponse(
        request=request,
        name="leaderboards.html",
        context={
            "title": f"{APP_TITLE} - Leaderboards",
            "dino_kills": dino_kills,
            "human_player_kills": human_player_kills,
            "dino_tames": dino_tames,
            "most_deaths": most_deaths,
            "dino_player_kills": dino_player_kills,
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
                        AND NOT (
                          LOWER(TRIM(e.killer_text)) LIKE 'a %'
                          OR LOWER(TRIM(e.killer_text)) LIKE 'an %'
                          OR LOWER(TRIM(e.killer_text)) LIKE 'the %'
                          OR INSTR(TRIM(e.killer_text), ' - Lvl ') > 0
                        )
                       THEN 1
                       ELSE 0
                   END
               ) AS deaths_by_human,
               SUM(
                   CASE
                       WHEN e.killer_text IS NOT NULL
                        AND TRIM(e.killer_text) <> ''
                        AND (
                          LOWER(TRIM(e.killer_text)) LIKE 'a %'
                          OR LOWER(TRIM(e.killer_text)) LIKE 'an %'
                          OR LOWER(TRIM(e.killer_text)) LIKE 'the %'
                          OR INSTR(TRIM(e.killer_text), ' - Lvl ') > 0
                        )
                       THEN 1
                       ELSE 0
                   END
               ) AS deaths_by_dino
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
               CASE
                   WHEN e.killer_text IS NULL OR TRIM(e.killer_text) = '' THEN 'unknown'
                   WHEN LOWER(TRIM(e.killer_text)) LIKE 'a %'
                     OR LOWER(TRIM(e.killer_text)) LIKE 'an %'
                     OR LOWER(TRIM(e.killer_text)) LIKE 'the %'
                     OR INSTR(TRIM(e.killer_text), ' - Lvl ') > 0
                     THEN 'dino'
                   ELSE 'human'
               END AS killer_type,
               e.source_rule
        FROM player_death_events e
        LEFT JOIN players p ON p.id = e.victim_player_id
        ORDER BY e.id DESC
        LIMIT 200
        """
    )
    recent_deaths = format_rows_timestamps(recent_deaths, ("event_time",))

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
