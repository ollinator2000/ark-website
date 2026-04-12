import os
import sqlite3
from datetime import UTC, datetime, timedelta
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


def resolve_local_image_path(value: str | None, fallback: str) -> str:
    candidate = (value or "").strip()
    if not candidate:
        return fallback
    lowered = candidate.lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return fallback
    normalized = candidate if candidate.startswith("/") else f"/{candidate}"
    if not normalized.startswith("/static/"):
        return fallback
    static_file = Path("static") / normalized.removeprefix("/static/")
    if not static_file.is_file():
        return fallback
    return normalized


HERO_IMAGE_URL = resolve_local_image_path(
    os.getenv("ARK_HERO_IMAGE_URL"),
    "/static/images/ark-hero-asa.jpeg",
)
CARD_IMAGE_DINO_DANGER = resolve_local_image_path(
    os.getenv("ARK_CARD_IMAGE_DINO_DANGER"),
    "/static/images/card-dino-danger.svg",
)
CARD_IMAGE_DINO_KILLER = resolve_local_image_path(
    os.getenv("ARK_CARD_IMAGE_DINO_KILLER"),
    "/static/images/card-dino-killer.svg",
)
CARD_IMAGE_TOP_TAMER = resolve_local_image_path(
    os.getenv("ARK_CARD_IMAGE_TOP_TAMER"),
    "/static/images/card-top-tamer.svg",
)
DISPLAY_TIMEZONE = os.getenv("ARK_DISPLAY_TIMEZONE", "Europe/Berlin")
MVP_WEIGHT_DINO_KILL = float(os.getenv("ARK_MVP_WEIGHT_DINO_KILL", "1.0"))
MVP_WEIGHT_PLAYER_KILL = float(os.getenv("ARK_MVP_WEIGHT_PLAYER_KILL", "3.0"))
MVP_WEIGHT_DINO_TAME = float(os.getenv("ARK_MVP_WEIGHT_DINO_TAME", "2.0"))
MVP_PENALTY_DEATH = float(os.getenv("ARK_MVP_PENALTY_DEATH", "1.5"))

app = FastAPI(title=APP_TITLE)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
templates.env.globals["app_title"] = APP_TITLE
templates.env.globals["server_name"] = SERVER_NAME
templates.env.globals["hero_image_url"] = HERO_IMAGE_URL
templates.env.globals["card_image_dino_danger"] = CARD_IMAGE_DINO_DANGER
templates.env.globals["card_image_dino_killer"] = CARD_IMAGE_DINO_KILLER
templates.env.globals["card_image_top_tamer"] = CARD_IMAGE_TOP_TAMER
templates.env.globals["display_timezone"] = DISPLAY_TIMEZONE

try:
    LOCAL_TZ = ZoneInfo(DISPLAY_TIMEZONE)
except Exception:
    LOCAL_TZ = ZoneInfo("UTC")

HUMAN_NAME_SQL = """
TRIM({col}) <> ''
AND LOWER(TRIM({col})) <> 'unknown'
AND LOWER(TRIM({col})) <> 'world'
AND INSTR(TRIM({col}), '(') = 0
AND INSTR(TRIM({col}), ')') = 0
AND LOWER(TRIM({col})) NOT LIKE 'a %'
AND LOWER(TRIM({col})) NOT LIKE 'an %'
AND LOWER(TRIM({col})) NOT LIKE 'the %'
AND INSTR(TRIM({col}), ' - Lvl ') = 0
"""


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


def format_ts_local(value: Any, include_weekday: bool = False) -> str | None:
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
    formatted = local.strftime("%d.%m.%Y %H:%M:%S %Z")
    if not include_weekday:
        return formatted

    weekdays_de = [
        "Montag",
        "Dienstag",
        "Mittwoch",
        "Donnerstag",
        "Freitag",
        "Samstag",
        "Sonntag",
    ]
    weekday = weekdays_de[local.weekday()]
    return f"{weekday}, {formatted}"


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
    return format_ts_local(rows[0].get("last_update"), include_weekday=True)


def fetch_dino_killer_ranking(limit: int = 100) -> tuple[list[dict], str | None]:
    human_cond = HUMAN_NAME_SQL.format(col="killer_text")
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
        AND NOT ({human_cond})
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
    return fetch_all(query.format(human_cond=human_cond), (limit,))


def fetch_daily_mvp_ranking(limit: int = 5) -> tuple[list[dict], str | None]:
    human_cond = HUMAN_NAME_SQL.format(col="p.player_name")
    now_local = datetime.now(LOCAL_TZ)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(UTC).isoformat()
    end_utc = end_local.astimezone(UTC).isoformat()

    query = """
    WITH daily_events AS (
      SELECT killer_player_id AS player_id, COUNT(*) AS dino_kills, 0 AS player_kills, 0 AS dino_tames, 0 AS deaths
      FROM dino_kill_events
      WHERE recorded_at >= ? AND recorded_at < ?
      GROUP BY killer_player_id

      UNION ALL

      SELECT killer_player_id AS player_id, 0 AS dino_kills, COUNT(*) AS player_kills, 0 AS dino_tames, 0 AS deaths
      FROM player_kill_events
      WHERE recorded_at >= ? AND recorded_at < ?
      GROUP BY killer_player_id

      UNION ALL

      SELECT player_id, 0 AS dino_kills, 0 AS player_kills, COUNT(*) AS dino_tames, 0 AS deaths
      FROM dino_tame_events
      WHERE recorded_at >= ? AND recorded_at < ?
      GROUP BY player_id

      UNION ALL

      SELECT victim_player_id AS player_id, 0 AS dino_kills, 0 AS player_kills, 0 AS dino_tames, COUNT(*) AS deaths
      FROM player_death_events
      WHERE victim_player_id IS NOT NULL
        AND recorded_at >= ? AND recorded_at < ?
      GROUP BY victim_player_id
    )
    SELECT p.player_name,
           SUM(d.dino_kills) AS dino_kills,
           SUM(d.player_kills) AS player_kills,
           SUM(d.dino_tames) AS dino_tames,
           SUM(d.deaths) AS deaths,
           (
             SUM(d.dino_kills) * {w_dino}
             + SUM(d.player_kills) * {w_player}
             + SUM(d.dino_tames) * {w_tame}
             - SUM(d.deaths) * {w_death_penalty}
           ) AS mvp_score
    FROM daily_events d
    JOIN players p ON p.id = d.player_id
    WHERE ({human_cond})
    GROUP BY p.id, p.player_name
    HAVING (SUM(d.dino_kills) + SUM(d.player_kills) + SUM(d.dino_tames) + SUM(d.deaths)) > 0
    ORDER BY mvp_score DESC, player_kills DESC, dino_kills DESC, dino_tames DESC, p.player_name COLLATE NOCASE ASC
    LIMIT ?
    """.format(
        human_cond=human_cond,
        w_dino=MVP_WEIGHT_DINO_KILL,
        w_player=MVP_WEIGHT_PLAYER_KILL,
        w_tame=MVP_WEIGHT_DINO_TAME,
        w_death_penalty=MVP_PENALTY_DEATH,
    )

    rows, err = fetch_all(
        query,
        (
            start_utc,
            end_utc,
            start_utc,
            end_utc,
            start_utc,
            end_utc,
            start_utc,
            end_utc,
            limit,
        ),
    )
    if err:
        return [], err
    if not rows:
        return [], None
    weekdays_de = [
        "Montag",
        "Dienstag",
        "Mittwoch",
        "Donnerstag",
        "Freitag",
        "Samstag",
        "Sonntag",
    ]
    period_label = f"{weekdays_de[start_local.weekday()]} ({start_local.strftime('%d.%m.%Y')})"
    for row in rows:
        row["period_label"] = period_label
    return rows, None


def fetch_daily_mvp() -> tuple[dict | None, str | None]:
    ranking, err = fetch_daily_mvp_ranking(limit=1)
    if err:
        return None, err
    if not ranking:
        return None, None
    return ranking[0], None


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    human_cond = HUMAN_NAME_SQL.format(col="p.player_name")
    dino_killers, dino_error = fetch_dino_killer_ranking(limit=10)
    top_dino = dino_killers[0] if dino_killers else None
    daily_mvp, mvp_error = fetch_daily_mvp()
    mvp_candidates: list[dict] = []
    if daily_mvp is None and mvp_error is None:
        mvp_candidates, mvp_error = fetch_daily_mvp_ranking(limit=3)
    top_dino_killer_players, err_player_dino = fetch_all(
        """
        SELECT p.player_name, s.dino_kills_total AS score
        FROM player_stats s
        JOIN players p ON p.id = s.player_id
        WHERE s.dino_kills_total > 0
          AND ({human_cond})
        ORDER BY s.dino_kills_total DESC, p.player_name COLLATE NOCASE ASC
        LIMIT 1
        """.format(human_cond=human_cond)
    )
    top_tamers, err_tamer = fetch_all(
        """
        SELECT p.player_name, s.dino_tames_total AS score
        FROM player_stats s
        JOIN players p ON p.id = s.player_id
        WHERE s.dino_tames_total > 0
          AND ({human_cond})
        ORDER BY s.dino_tames_total DESC, p.player_name COLLATE NOCASE ASC
        LIMIT 1
        """.format(human_cond=human_cond)
    )
    top_player_dino_kills = top_dino_killer_players[0] if top_dino_killer_players else None
    top_player_tames = top_tamers[0] if top_tamers else None
    db_error = dino_error or err_player_dino or err_tamer or mvp_error

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "title": APP_TITLE,
            "last_db_update": fetch_last_db_update(),
            "top_dino": top_dino,
            "top_player_dino_kills": top_player_dino_kills,
            "top_player_tames": top_player_tames,
            "daily_mvp": daily_mvp,
            "mvp_candidates": mvp_candidates,
            "db_error": db_error,
        },
    )


@app.get("/players", response_class=HTMLResponse)
def players(request: Request):
    human_cond = HUMAN_NAME_SQL.format(col="p.player_name")
    death_killer_human = HUMAN_NAME_SQL.format(col="killer_text")
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
                    AND ({death_killer_human})
                 THEN 1 ELSE 0 END
               ) AS deaths_by_human,
               SUM(
                 CASE
                   WHEN killer_text IS NOT NULL
                    AND TRIM(killer_text) <> ''
                    AND NOT ({death_killer_human})
                 THEN 1 ELSE 0 END
               ) AS deaths_by_dino
        FROM player_death_events
        WHERE victim_player_id IS NOT NULL
        GROUP BY victim_player_id
    ) d ON d.victim_player_id = p.id
    WHERE ({human_cond})
      AND (
          s.dino_kills_total > 0
       OR s.player_kills_total > 0
       OR s.dino_tames_total > 0
       OR COALESCE(d.deaths_total, 0) > 0
      )
    ORDER BY p.player_name COLLATE NOCASE ASC
    """.format(human_cond=human_cond, death_killer_human=death_killer_human)
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
    human_cond = HUMAN_NAME_SQL.format(col="p.player_name")
    dino_kills, err1 = fetch_all(
        """
        SELECT p.player_name, s.dino_kills_total AS score
        FROM player_stats s
        JOIN players p ON p.id = s.player_id
        WHERE s.dino_kills_total > 0
          AND ({human_cond})
        ORDER BY s.dino_kills_total DESC, p.player_name COLLATE NOCASE ASC
        LIMIT 100
        """.format(human_cond=human_cond)
    )
    dino_tames, err2 = fetch_all(
        """
        SELECT p.player_name, s.dino_tames_total AS score
        FROM player_stats s
        JOIN players p ON p.id = s.player_id
        WHERE s.dino_tames_total > 0
          AND ({human_cond})
        ORDER BY s.dino_tames_total DESC, p.player_name COLLATE NOCASE ASC
        LIMIT 100
        """.format(human_cond=human_cond)
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
        WHERE ({human_cond})
        GROUP BY p.player_name
        HAVING COUNT(*) > 0
        ORDER BY score DESC, p.player_name COLLATE NOCASE ASC
        LIMIT 100
        """.format(human_cond=human_cond)
    )
    dino_player_kills, err5 = fetch_dino_killer_ranking(limit=100)
    companion_dino_kills, err6 = fetch_all(
        """
        SELECT p.player_name, s.dino_kills_total AS score
        FROM player_stats s
        JOIN players p ON p.id = s.player_id
        WHERE s.dino_kills_total > 0
          AND INSTR(TRIM(p.player_name), '(') > 0
          AND INSTR(TRIM(p.player_name), ')') > 0
        ORDER BY s.dino_kills_total DESC, p.player_name COLLATE NOCASE ASC
        LIMIT 100
        """
    )
    db_error = err1 or err2 or err3 or err4 or err5 or err6

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
            "companion_dino_kills": companion_dino_kills,
            "db_error": db_error,
            "last_db_update": fetch_last_db_update(),
        },
    )


@app.get("/deaths", response_class=HTMLResponse)
def deaths(request: Request):
    death_killer_human = HUMAN_NAME_SQL.format(col="e.killer_text")
    leaderboard, err1 = fetch_all(
        """
        SELECT COALESCE(p.player_name, e.victim_name) AS player_name,
               COUNT(*) AS deaths_total,
               SUM(
                   CASE
                       WHEN e.killer_text IS NOT NULL
                        AND TRIM(e.killer_text) <> ''
                        AND ({death_killer_human})
                       THEN 1
                       ELSE 0
                   END
               ) AS deaths_by_human,
               SUM(
                   CASE
                       WHEN e.killer_text IS NOT NULL
                        AND TRIM(e.killer_text) <> ''
                        AND NOT ({death_killer_human})
                       THEN 1
                       ELSE 0
                   END
               ) AS deaths_by_dino
        FROM player_death_events e
        LEFT JOIN players p ON p.id = e.victim_player_id
        GROUP BY COALESCE(p.player_name, e.victim_name)
        ORDER BY deaths_total DESC, player_name COLLATE NOCASE ASC
        LIMIT 100
        """.format(death_killer_human=death_killer_human)
    )

    recent_deaths, err2 = fetch_all(
        """
        SELECT COALESCE(p.player_name, e.victim_name) AS victim_name,
               COALESCE(NULLIF(TRIM(e.killer_text), ''), 'Unbekannt / Umwelt') AS killer_text,
               COALESCE(e.event_time_text, e.recorded_at) AS event_time,
               CASE
                   WHEN e.killer_text IS NULL OR TRIM(e.killer_text) = '' THEN 'unknown'
                   WHEN ({death_killer_human}) THEN 'human'
                   ELSE 'dino'
               END AS killer_type,
               e.source_rule
        FROM player_death_events e
        LEFT JOIN players p ON p.id = e.victim_player_id
        ORDER BY e.id DESC
        LIMIT 200
        """.format(death_killer_human=death_killer_human)
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
