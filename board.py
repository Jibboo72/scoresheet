#!/usr/bin/env python3
"""Scoresheet tonight's board: model odds for goals + assists vs. sportsbook prices."""
import json, math, os, sys, unicodedata
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import pandas as pd
import requests
import goalies
import market
import nhl_pipeline as m

TUNED = m.ROOT / "data" / "tuned_config.json"
if TUNED.exists():  # settings chosen by tune.py
    m.CONFIG.update(json.loads(TUNED.read_text()))

SEASON, PRIOR = "20262027", "20252026"
OUT = m.ROOT / "docs" / "data" / "board.json"
ODDS_KEY = os.environ.get("ODDS_API_KEY", "").strip()
ODDS_BASE = "https://api.the-odds-api.com/v4/sports/icehockey_nhl"
MARKETS = {"goal": "player_goal_scorer_anytime", "assist": "player_assists"}
# Only books you can bet (up to 10 costs the same). Fanatics (fanatics) needs the paid odds plan.
BOOKS = "draftkings,fanduel,betmgm,hardrockbet,espnbet,betrivers,betparx"
TEAM_WORDS = {"ANA": "ducks", "BOS": "bruins", "BUF": "sabres", "CAR": "hurricanes", "CBJ": "jackets",
    "CGY": "flames", "CHI": "blackhawks", "COL": "avalanche", "DAL": "stars", "DET": "wings",
    "EDM": "oilers", "FLA": "panthers", "LAK": "kings", "MIN": "wild", "MTL": "canadiens",
    "NJD": "devils", "NSH": "predators", "NYI": "islanders", "NYR": "rangers", "OTT": "senators",
    "PHI": "flyers", "PIT": "penguins", "SEA": "kraken", "SJS": "sharks", "STL": "blues",
    "TBL": "lightning", "TOR": "leafs", "UTA": "utah", "VAN": "canucks", "VGK": "knights",
    "WPG": "jets", "WSH": "capitals"}


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return "".join(c for c in s if c.isalnum() or c == " ").strip()


def decimal(price):
    return 1 + price / 100 if price > 0 else 1 + 100 / abs(price)


def fair_american(p):
    p = min(max(p, 0.01), 0.99)
    return -round(100 * p / (1 - p)) if p >= 0.5 else round(100 * (1 - p) / p)


def tonight_games(date):
    data = m.get_json(f"{m.BASE}/schedule/{date}") or {}
    for day in data.get("gameWeek", []):
        if day.get("date") == date:
            return [{"id": g["id"], "start": g.get("startTimeUTC"),
                     "away": g["awayTeam"]["abbrev"], "home": g["homeTeam"]["abbrev"]}
                    for g in day.get("games", []) if g.get("gameType") in (2, 3)]
    return []


def current_players():
    players = {}
    for team in m.TEAMS:
        roster = m.get_json(f"{m.BASE}/roster/{team}/current") or {}
        for group in ("forwards", "defensemen"):
            for p in roster.get(group, []):
                players[p["id"]] = {"name": m.name_of(p), "team": team,
                                    "pos": p.get("positionCode", "D" if group == "defensemen" else "C")}
    return players


def season_rows(date):
    """Every skater-game this season before today (all players, including traded and called-up)."""
    df = m.fetch_season(SEASON, refresh=True)
    return df[df["date"] < date]


def fetch_odds(date):
    """Every book's price per player for each market. Returns (odds, status)."""
    if not ODDS_KEY:
        return {}, "No odds key set. Showing fair odds only."
    try:
        events = requests.get(f"{ODDS_BASE}/events", params={"apiKey": ODDS_KEY}, timeout=30).json()
        et = ZoneInfo("America/New_York")
        todays = [e for e in events if datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00"))
                  .astimezone(et).strftime("%Y-%m-%d") == date]
        odds, left = {}, None
        for e in todays:
            r = requests.get(f"{ODDS_BASE}/events/{e['id']}/odds", timeout=30, params={
                "apiKey": ODDS_KEY, "bookmakers": BOOKS, "markets": ",".join(MARKETS.values()),
                "oddsFormat": "american"})
            left = r.headers.get("x-requests-remaining", left)
            teams = norm(e["home_team"]) + " " + norm(e["away_team"])
            for book in r.json().get("bookmakers", []):
                for mk in book.get("markets", []):
                    kind = next((k for k, v in MARKETS.items() if v == mk["key"]), None)
                    for o in mk.get("outcomes", []) if kind else []:
                        if kind == "assist" and o.get("point") != 0.5:
                            continue
                        side = kind if o.get("name") in ("Yes", "Over") else kind + "_other"  # No / Under
                        key = (side, norm(o.get("description")), teams)
                        odds.setdefault(key, {})[book.get("title", book.get("key"))] = o["price"]
        n = len(todays)
        return odds, f"Odds from {n} game{'' if n == 1 else 's'}. {left} odds credits left this month."
    except Exception as exc:  # the board still works without odds
        return {}, f"Odds pull failed ({exc.__class__.__name__}). Showing fair odds only."


def main():
    date = sys.argv[1] if len(sys.argv) > 1 else datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    games = tonight_games(date)
    out = {"date": date, "generated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
           "games": games, "players": [], "odds_status": ""}
    if not games:
        out["odds_status"] = "No NHL games on this date."
        OUT.write_text(json.dumps(out, indent=1)); print(out["odds_status"]); return

    players = current_players()
    played = season_rows(date)
    matchup = {g["away"]: (g["home"], 0, g["id"]) for g in games}
    matchup.update({g["home"]: (g["away"], 1, g["id"]) for g in games})
    tonight = [{"season": SEASON, "player_id": pid, "name": p["name"], "pos": p["pos"],
                "game_id": matchup[p["team"]][2], "date": date, "team": p["team"],
                "opp": matchup[p["team"]][0], "home": matchup[p["team"]][1], "toi": 0.0,
                "shots": 0, "goals": 0, "assists": 0, "pp_points": 0}
               for pid, p in players.items() if p["team"] in matchup]
    prior = m.fetch_season(PRIOR)
    gg_now = m.fetch_goalies(SEASON, refresh=True)
    gg = (m.fetch_goalies(PRIOR), gg_now[gg_now["date"] < date])
    proj = m.build_projections(pd.concat([played, pd.DataFrame(tonight)], ignore_index=True), prior, goalies=gg)
    proj = proj[proj["date"] == date]
    tg = pd.DataFrame([{"game_id": g["id"], "date": date, "team": t} for g in games for t in (g["away"], g["home"])])
    starters = goalies.predict_starters(pd.concat(gg), tg)
    names = dict(zip(pd.concat(gg)["player_id"], pd.concat(gg)["name"]))
    out["goalies"] = {t: names.get(g, "Unknown") for t, g in zip(starters["team"], starters["goalie_id"])}

    odds, out["odds_status"] = fetch_odds(date)
    try:  # the market's expected goals for each team, from moneylines and totals
        lines = market.game_lines(ODDS_KEY, ODDS_BASE, BOOKS, date, TEAM_WORDS, ZoneInfo("America/New_York")) if ODDS_KEY else {}
    except Exception:
        lines = {}
    out["odds_status"] += f" Game lines for {len(lines) // 2} games."
    for _, r in proj.iterrows():
        env = market.env_factor(lines.get(r["team"]), r["team_proj"])
        row = {"id": int(r["player_id"]), "name": r["name"], "team": r["team"], "opp": r["opp"],
               "pos": r["pos"], "game_id": int(r["game_id"]), "toi": round(r["proj_toi"], 1),
               "sog": round(r["lam_sog"], 2), "env": round(env, 3)}
        word = TEAM_WORDS.get(r["team"], "~")
        find = lambda side: next((v for (k, n, t), v in odds.items()
                                  if k == side and n == norm(r["name"]) and word in t), None)
        for kind, lam in (("goal", r["lam_goal"]), ("assist", r["lam_assist"])):
            row[kind] = {"p_model": round(1 - math.exp(-float(lam) * env), 4)}
            if find(kind):
                row[kind].update(prices=find(kind), other=find(kind + "_other") or {})
        out["players"].append(row)
    market.market_view(out["players"])
    for row in out["players"]:  # final chance = model blended with the market, then EV at the best price
        for kind in ("goal", "assist"):
            mk = row[kind]
            p = mk["p_model"] if mk.get("p_mkt") is None else (
                market.MODEL_WEIGHT[kind] * mk["p_model"] + (1 - market.MODEL_WEIGHT[kind]) * mk["p_mkt"])
            mk.update(p=round(p, 4), fair=fair_american(p))
            if mk.get("prices"):
                book = max(mk["prices"], key=mk["prices"].get)
                mk.update(price=mk["prices"][book], book=book, ev=round(p * decimal(mk["prices"][book]) - 1, 4))
            mk.pop("other", None)
    out["max_price"] = market.MAX_PRICE
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1))
    print(f"{date}: {len(games)} games, {len(out['players'])} players. {out['odds_status']}")


if __name__ == "__main__":
    main()
