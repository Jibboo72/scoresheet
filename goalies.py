"""Scoresheet goalies: who probably starts each game, and how good he is.

Uses only games before the one being projected, so the backtest is honest:
  - starter = the team's main goalie (most starts in its last 10 games), except on the
    second night of a back-to-back, when it's whoever didn't start the night before
  - quality = save % from last season and this season to date, pulled hard toward the
    league average because save % is mostly noise over short stretches
"""
from bisect import bisect_left
from collections import Counter
import numpy as np
import pandas as pd


def predict_starters(gg, games):
    """games: one row per team-game (game_id, date, team). Returns the same rows plus goalie_id."""
    starts = gg[gg["started"] == 1].sort_values(["date", "game_id"])
    by_team = {t: (list(d["date"]), list(d["player_id"])) for t, d in starts.groupby("team")}
    picks = []
    for gid, date, team in games[["game_id", "date", "team"]].itertuples(index=False):
        dates, ids = by_team.get(team, ([], []))
        i = bisect_left(dates, date)  # starts strictly before this date
        if i == 0:
            picks.append(None)
            continue
        pick = Counter(ids[max(0, i - 10):i]).most_common(1)[0][0]
        if (pd.Timestamp(date) - pd.Timestamp(dates[i - 1])).days == 1:  # played last night
            rested = [g for g in ids[max(0, i - 20):i] if g != ids[i - 1]]
            if rested:
                pick = Counter(rested).most_common(1)[0][0]
        picks.append(pick)
    return games.assign(goalie_id=picks)


def goalie_factors(gg_prior, gg, games, prior_shots):
    """Goal multiplier for shooters facing each team's projected starter (1.0 = league average)."""
    lg_sv = gg_prior["saves"].sum() / max(gg_prior["shots_against"].sum(), 1)
    base = gg_prior.groupby("player_id")[["saves", "shots_against"]].sum()
    cur = gg.sort_values(["date", "game_id"])
    hist = {g: (list(d["date"]), np.cumsum(d["saves"].to_numpy()), np.cumsum(d["shots_against"].to_numpy()))
            for g, d in cur.groupby("player_id")}
    out = predict_starters(pd.concat([gg_prior, gg]), games)  # last season covers the first games
    factors = []
    for g, date in out[["goalie_id", "date"]].itertuples(index=False):
        if g is None or pd.isna(g):
            factors.append(1.0)
            continue
        sv, sa = (base.loc[g, "saves"], base.loc[g, "shots_against"]) if g in base.index else (0.0, 0.0)
        if g in hist:
            dates, csv, csa = hist[g]
            i = bisect_left(dates, date)
            if i:
                sv, sa = sv + csv[i - 1], sa + csa[i - 1]
        rate = (sv + lg_sv * prior_shots) / (sa + prior_shots)
        factors.append(float(np.clip((1 - rate) / (1 - lg_sv), 0.8, 1.25)))
    return out.assign(g_factor=factors)


def starter_accuracy(gg, games):
    """Share of team-games where the projected starter actually started."""
    pred = predict_starters(gg, games)
    actual = gg[gg["started"] == 1][["game_id", "team", "player_id"]]
    x = pred.merge(actual, on=["game_id", "team"])
    return float((x["goalie_id"] == x["player_id"]).mean()) if len(x) else None
