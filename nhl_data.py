"""Scoresheet data: every skater and goalie in every game from the NHL stats feed, including power-play ice time."""
import json
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

BASE = "https://api-web.nhle.com/v1"           # schedule, rosters, boxscores
STATS = "https://api.nhle.com/stats/rest/en"   # per-game stats for every skater
TEAMS = [
    "ANA", "BOS", "BUF", "CAR", "CBJ", "CGY", "CHI", "COL", "DAL", "DET",
    "EDM", "FLA", "LAK", "MIN", "MTL", "NJD", "NSH", "NYI", "NYR", "OTT",
    "PHI", "PIT", "SEA", "SJS", "STL", "TBL", "TOR", "UTA", "VAN", "VGK",
    "WPG", "WSH",
]
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
COLS = ["season", "player_id", "name", "pos", "game_id", "date", "team", "opp", "home",
        "toi", "pp_toi", "sh_toi", "shots", "goals", "assists", "pp_points"]
GCOLS = ["season", "player_id", "name", "game_id", "date", "team", "opp", "started", "shots_against", "saves"]
NUMERIC = ["player_id", "game_id", "home", "toi", "pp_toi", "sh_toi", "shots", "goals", "assists", "pp_points"]

session = requests.Session()
session.headers["User-Agent"] = "scoresheet-nhl/2.0"


def get_json(url, params=None, tries=4):
    for attempt in range(tries):
        try:
            r = session.get(url, params=params, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:
                return None
        except requests.RequestException:
            pass
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Request failed after {tries} tries: {url}")


def name_of(p):
    def pick(v):
        return v.get("default", "") if isinstance(v, dict) else (v or "")
    return f"{pick(p.get('firstName'))} {pick(p.get('lastName'))}".strip()


def stats_report(report, start, end):
    """All per-game rows of one stats report (e.g. skater/summary) between two dates, regular season."""
    rows, offset = [], 0
    while True:
        data = get_json(f"{STATS}/{report}", {
            "isAggregate": "false", "isGame": "true", "limit": 1000, "start": offset,
            "sort": json.dumps([{"property": "gameId", "direction": "ASC"},
                                {"property": "playerId", "direction": "ASC"}]),
            "cayenneExp": f'gameTypeId=2 and gameDate>="{start}" and gameDate<="{end}"'}) or {}
        batch = data.get("data", [])
        rows += batch
        offset += len(batch)
        if not batch or offset >= data.get("total", 0):
            return rows


def fetch_games(season, through=None):
    """Every skater-game of a season, three days at a time."""
    year = int(str(season)[:4])
    day, last = date(year, 9, 20), min(date(year + 1, 6, 30), through or date.today())
    out = []
    while day <= last:
        end = min(day + timedelta(days=2), last)
        toi = {(r["playerId"], r["gameId"]): r for r in stats_report("skater/timeonice", day, end)}
        for r in stats_report("skater/summary", day, end):
            t = toi.get((r["playerId"], r["gameId"]), {})
            out.append({
                "season": str(season), "player_id": r["playerId"], "name": r.get("skaterFullName", ""),
                "pos": r.get("positionCode", "C"), "game_id": r["gameId"], "date": r["gameDate"][:10],
                "team": r.get("teamAbbrev"), "opp": r.get("opponentTeamAbbrev"),
                "home": 1 if r.get("homeRoad") == "H" else 0,
                "toi": (r.get("timeOnIcePerGame") or 0) / 60.0,
                "pp_toi": (t.get("ppTimeOnIce") or 0) / 60.0, "sh_toi": (t.get("shTimeOnIce") or 0) / 60.0,
                "shots": r.get("shots") or 0, "goals": r.get("goals") or 0,
                "assists": r.get("assists") or 0, "pp_points": r.get("ppPoints") or 0})
        day = end + timedelta(days=1)
        time.sleep(0.2)
    df = pd.DataFrame(out, columns=COLS).dropna(subset=["team", "opp"])
    df = df[df["toi"] > 0].drop_duplicates(subset=["player_id", "game_id"])
    return df.astype({c: float for c in NUMERIC}).astype({"player_id": int, "game_id": int, "home": int})


def fetch_season(season, refresh=False):
    """Cached per season in data/. refresh=True always re-downloads (use for the current season)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"games_v2_{season}.csv"
    if path.exists() and not refresh:
        print(f"Using cached {path.name}")
        return pd.read_csv(path)
    print(f"Fetching every skater-game for {season}...")
    df = fetch_games(season)
    tg = df.groupby(["game_id", "team"]).size()
    print(f"  {len(df):,} skater-games, {df['game_id'].nunique()} games, "
          f"{tg.mean() if len(tg) else 0:.1f} skaters per team-game")
    df.to_csv(path, index=False)
    return df


def fetch_goalies(season, refresh=False):
    """Every goalie-game of a season: who started, shots faced, saves. Cached like skaters."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"goalies_v2_{season}.csv"
    if path.exists() and not refresh:
        return pd.read_csv(path)
    year = int(str(season)[:4])
    day, last = date(year, 9, 20), min(date(year + 1, 6, 30), date.today())
    out = []
    while day <= last:
        end = min(day + timedelta(days=2), last)
        for r in stats_report("goalie/summary", day, end):
            out.append({"season": str(season), "player_id": r["playerId"], "name": r.get("goalieFullName", ""),
                        "game_id": r["gameId"], "date": r["gameDate"][:10], "team": r.get("teamAbbrev"),
                        "opp": r.get("opponentTeamAbbrev"), "started": r.get("gamesStarted") or 0,
                        "shots_against": r.get("shotsAgainst") or 0, "saves": r.get("saves") or 0})
        day = end + timedelta(days=1)
        time.sleep(0.2)
    df = pd.DataFrame(out, columns=GCOLS).drop_duplicates(subset=["player_id", "game_id"])
    print(f"  {len(df):,} goalie-games, {int(df['started'].sum()) if len(df) else 0} starts for {season}")
    df.to_csv(path, index=False)
    return df
