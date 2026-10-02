"""Scoresheet market view: what the betting market says about each game and each prop.

1. Game lines (moneyline + total) -> each team's expected goals. Books' game lines are sharp,
   so the model's team scoring is pulled toward them.
2. Prop prices with the book's cut removed -> the market's fair chance for each prop.
   The final chance is a blend of the model and the market, so one stat quirk can't
   manufacture a huge edge by itself.
"""
import statistics
import numpy as np
import requests
from scipy import stats
from scipy.optimize import brentq

ENV_WEIGHT = 0.7     # how far team scoring moves toward the market's game lines
MODEL_WEIGHT = 0.5   # final chance = this much model + the rest market (the sim tracks both to tune it)
ENV_CLAMP = (0.75, 1.33)


def implied(price):
    return 1 / (1 + price / 100) if price > 0 else abs(price) / (abs(price) + 100)


def two_way(a, b):
    """Fair chance of side a once the cut is removed."""
    pa, pb = implied(a), implied(b)
    return pa / (pa + pb)


def team_goals(point, p_over, p_home):
    """Expected goals for home and away from the total and the moneyline (overtime included)."""
    k = int(np.floor(point))

    def over(t):  # chance the total goes over, pushes removed
        push = stats.poisson.pmf(point, t) if point == k else 0.0
        return stats.poisson.sf(k, t) / (1 - push)
    total = brentq(lambda t: over(t) - p_over, 2.0, 12.0)

    def home_win(s):
        h, a = s * total, (1 - s) * total
        return stats.skellam.sf(0, h, a) + 0.5 * stats.skellam.pmf(0, h, a)
    s = brentq(lambda s: home_win(s) - p_home, 0.2, 0.8)
    return s * total, (1 - s) * total


def game_lines(key, base, books, date, team_words, tz):
    """{team abbrev: market expected goals} for tonight. Costs 2 odds credits per run (all games)."""
    from datetime import datetime
    r = requests.get(f"{base}/odds", timeout=30, params={
        "apiKey": key, "bookmakers": books, "markets": "h2h,totals", "oddsFormat": "american"})
    abbrev = lambda name: next((a for a, w in team_words.items() if w in name.lower()), None)
    out = {}
    for e in r.json():
        if datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00")).astimezone(tz).strftime("%Y-%m-%d") != date:
            continue
        home, away = e["home_team"], e["away_team"]
        wins, totals = [], {}
        for bk in e.get("bookmakers", []):
            for mk in bk.get("markets", []):
                o = {x["name"]: x for x in mk.get("outcomes", [])}
                if mk["key"] == "h2h" and home in o and away in o:
                    wins.append(two_way(o[home]["price"], o[away]["price"]))
                if mk["key"] == "totals" and "Over" in o and "Under" in o:
                    totals.setdefault(o["Over"]["point"], []).append(two_way(o["Over"]["price"], o["Under"]["price"]))
        if not wins or not totals:
            continue
        point = max(totals, key=lambda p: len(totals[p]))  # the line most books agree on
        try:
            h, a = team_goals(point, statistics.median(totals[point]), statistics.median(wins))
        except ValueError:
            continue
        if abbrev(home) and abbrev(away):
            out[abbrev(home)], out[abbrev(away)] = h, a
    return out


def env_factor(market_goals, model_goals):
    """Multiplier that moves the model's team scoring toward the market's."""
    if not market_goals or not model_goals:
        return 1.0
    target = ENV_WEIGHT * market_goals + (1 - ENV_WEIGHT) * model_goals
    return float(np.clip(target / model_goals, *ENV_CLAMP))


def market_view(rows):
    """Adds the market's fair chance and the blended final chance to every priced prop.

    Fair chance comes from books posting both sides (Yes/No, Over/Under). Anytime-goal props
    with only a Yes price are scaled so each team's chances add up to the goals the model
    expects that team to score, which removes the book's cut across the roster.
    """
    teams = {}
    for r in rows:
        teams.setdefault(r["team"], []).append(r)
    for kind in ("goal", "assist"):
        for team_rows in teams.values():
            yes_only = []
            for r in team_rows:
                m = r[kind]
                fair = [two_way(m["prices"][b], m["other"][b]) for b in m.get("prices", {}) if b in m.get("other", {})]
                if fair:
                    m["p_mkt"] = round(statistics.median(fair), 4)
                elif m.get("prices"):
                    yes_only.append(r)
            if kind == "goal" and len(yes_only) >= 6:
                raw = [statistics.median(implied(p) for p in r[kind]["prices"].values()) for r in yes_only]
                expected = sum(r[kind]["p_model"] for r in yes_only)
                scale = expected / sum(raw)
                for r, p in zip(yes_only, raw):
                    r[kind]["p_mkt"] = round(min(p * scale, 0.95), 4)
    return rows
