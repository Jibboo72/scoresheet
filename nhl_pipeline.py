
#!/usr/bin/env python3
"""
Scoresheet — NHL prop model (SOG, goals, assists).

1. Pulls every skater game log for the prior season (2024-25) and the
   test season (2025-26) from the free NHL web API.
2. Walks through 2025-26 game by game, projecting each player using ONLY
   what was known before that game (no peeking).
3. Scores the projections and writes docs/data/backtest.json for the site.

Run:  python nhl_pipeline.py            (uses cached data if present)
      python nhl_pipeline.py --refresh  (re-download everything)
"""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from scipy import stats

BASE = "https://api-web.nhle.com/v1"
PRIOR_SEASON = "20242025"
TEST_SEASON = "20252026"
TEAMS = [
    "ANA", "BOS", "BUF", "CAR", "CBJ", "CGY", "CHI", "COL", "DAL", "DET",
    "EDM", "FLA", "LAK", "MIN", "MTL", "NJD", "NSH", "NYI", "NYR", "OTT",
    "PHI", "PIT", "SEA", "SJS", "STL", "TBL", "TOR", "UTA", "VAN", "VGK",
    "WPG", "WSH",
]

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
OUT_FILE = ROOT / "docs" / "data" / "backtest.json"

# Every tunable number lives here so the backtest can be re-run with changes.
CONFIG = {
    "prior_games": 20,          # last season counts as this many games of evidence
    "recent_n": 10,             # recency window
    "recent_weight": 0.35,      # tilt toward the last 10
    "toi_recent_weight": 0.60,  # ice time follows recent usage more closely
    "team_prior_games": 10,     # shrink team/opponent rates toward league
    "opp_clamp": [0.85, 1.15],
    "sh_prior_shots": 150,      # shooting % regression (shots of league-average evidence)
    "save_prior_shots": 600,    # opponent save % regression
    "assist_prior_team_goals": 40,
    "min_history_games": 5,     # skip players with almost no history
    "min_proj_toi": 10.0,       # books rarely post lines below this
    "nb_dispersion": [None, 40, 20, 10, 6],  # None = Poisson
    "sog_lines": [1.5, 2.5, 3.5],
}

session = requests.Session()
session.headers["User-Agent"] = "scoresheet-nhl/1.0"


# --------------------------------------------------------------------------
# Fetch
# --------------------------------------------------------------------------
def get_json(url, tries=4):
    for attempt in range(tries):
        try:
            r = session.get(url, timeout=30)
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


def parse_toi(v):
    """'18:32' -> 18.53 minutes. Accepts seconds as a number too."""
    if v is None:
        return np.nan
    if isinstance(v, (int, float)):
        return v / 60.0 if v > 200 else float(v)
    parts = str(v).split(":")
    try:
        return int(parts[0]) + int(parts[1]) / 60.0 if len(parts) == 2 else float(v)
    except ValueError:
        return np.nan


def skaters_for_season(season):
    players = {}
    for team in TEAMS:
        roster = get_json(f"{BASE}/roster/{team}/{season}") or {}
        for group in ("forwards", "defensemen"):
            for p in roster.get(group, []):
                players[p["id"]] = {
                    "name": name_of(p),
                    "pos": p.get("positionCode", "D" if group == "defensemen" else "C"),
                }
        time.sleep(0.1)
    return players


def game_log_rows(pid, info, season):
    data = get_json(f"{BASE}/player/{pid}/game-log/{season}/2") or {}
    rows = []
    for g in data.get("gameLog", []):
        rows.append({
            "season": season,
            "player_id": pid,
            "name": info["name"],
            "pos": info["pos"],
            "game_id": g.get("gameId"),
            "date": g.get("gameDate"),
            "team": g.get("teamAbbrev"),
            "opp": g.get("opponentAbbrev"),
            "home": 1 if g.get("homeRoadFlag") == "H" else 0,
            "toi": parse_toi(g.get("toi")),
            "shots": g.get("shots", 0) or 0,
            "goals": g.get("goals", 0) or 0,
            "assists": g.get("assists", 0) or 0,
            "pp_points": g.get("powerPlayPoints", 0) or 0,
        })
    return rows


def fetch_season(season, refresh=False):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"games_{season}.csv"
    if path.exists() and not refresh:
        print(f"Using cached {path.name}")
        return pd.read_csv(path)

    print(f"Fetching rosters for {season}...")
    players = skaters_for_season(season)
    print(f"  {len(players)} skaters. Fetching game logs...")

    rows = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(game_log_rows, pid, info, season) for pid, info in players.items()]
        for i, f in enumerate(futures, 1):
            rows.extend(f.result())
            if i % 100 == 0:
                print(f"  {i}/{len(futures)} players")

    if not rows:
        raise RuntimeError(f"No game logs returned for {season}. The NHL API may have changed.")
    df = pd.DataFrame(rows).dropna(subset=["game_id", "team", "opp"])
    df = df.drop_duplicates(subset=["player_id", "game_id"])
    df.to_csv(path, index=False)
    print(f"  Saved {len(df):,} player-games to {path.name}")
    return df


# --------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------
def pos_group(p):
    return "D" if p == "D" else "F"


def team_games(df):
    """One row per team per game: shots/goals for and against."""
    tg = df.groupby(["game_id", "date", "team", "opp"], as_index=False).agg(
        sf=("shots", "sum"), gf=("goals", "sum"))
    against = tg[["game_id", "team", "sf", "gf"]].rename(
        columns={"team": "opp", "sf": "sa", "gf": "ga"})
    return tg.merge(against, on=["game_id", "opp"], how="left").fillna({"sa": 0, "ga": 0})


def league_baselines(prior):
    prior = prior.copy()
    prior["pg"] = prior["pos"].map(pos_group)
    tg = team_games(prior)
    prior = prior.merge(tg[["game_id", "team", "gf"]].rename(columns={"gf": "team_gf"}),
                        on=["game_id", "team"], how="left")
    base = {"team_sf_pg": tg["sf"].mean(), "team_gf_pg": tg["gf"].mean(),
            "goals_per_shot": tg["gf"].sum() / max(tg["sf"].sum(), 1), "pos": {}}
    for g, d in prior.groupby("pg"):
        base["pos"][g] = {
            "shots_per_min": d["shots"].sum() / d["toi"].sum(),
            "sh_pct": d["goals"].sum() / max(d["shots"].sum(), 1),
            "assist_share": d["assists"].sum() / max(d["team_gf"].sum(), 1),
            "toi": d["toi"].mean(),
        }
    return base, prior


def prior_player_table(prior_rows):
    return prior_rows.groupby("player_id").agg(
        p_gp=("game_id", "count"), p_toi=("toi", "sum"), p_shots=("shots", "sum"),
        p_goals=("goals", "sum"), p_assists=("assists", "sum"), p_team_gf=("team_gf", "sum"),
    ).reset_index()


def build_projections(test, prior, cfg=CONFIG):
    base, prior_rows = league_baselines(prior)
    pp = prior_player_table(prior_rows)

    df = test.copy()
    df["pg"] = df["pos"].map(pos_group)
    df = df.sort_values(["player_id", "date", "game_id"]).reset_index(drop=True)

    # Team context, strictly pre-game
    tg = team_games(df).sort_values(["team", "date", "game_id"])
    t = tg.groupby("team")
    for c in ("sf", "gf", "sa", "ga"):
        tg[f"c_{c}"] = t[c].cumsum() - tg[c]
    tg["c_gp"] = t.cumcount()
    df = df.merge(tg[["game_id", "team", "gf"]].rename(columns={"gf": "team_gf"}),
                  on=["game_id", "team"], how="left")
    team_pre = tg[["game_id", "team", "c_gf", "c_gp"]].rename(
        columns={"c_gf": "t_c_gf", "c_gp": "t_c_gp"})
    opp_pre = tg[["game_id", "team", "c_sa", "c_ga", "c_gp"]].rename(
        columns={"team": "opp", "c_sa": "o_c_sa", "c_ga": "o_c_ga", "c_gp": "o_c_gp"})
    df = df.merge(team_pre, on=["game_id", "team"], how="left")
    df = df.merge(opp_pre, on=["game_id", "opp"], how="left")

    # Player history, strictly pre-game
    g = df.groupby("player_id")
    for c in ("toi", "shots", "goals", "assists", "team_gf"):
        df[f"c_{c}"] = g[c].cumsum() - df[c]
    df["c_gp"] = g.cumcount()
    n = cfg["recent_n"]
    for c in ("toi", "shots"):
        df[f"r_{c}"] = g[c].transform(lambda s: s.shift(1).rolling(n, min_periods=1).sum()).fillna(0)
    df["r_gp"] = g["toi"].transform(lambda s: s.shift(1).rolling(n, min_periods=1).count()).fillna(0)

    df = df.merge(pp, on="player_id", how="left")
    for c in ("p_gp", "p_toi", "p_shots", "p_goals", "p_assists", "p_team_gf"):
        df[c] = df[c].fillna(0)

    lg = df["pg"].map(lambda x: base["pos"][x])
    lg_rate = lg.map(lambda d: d["shots_per_min"])
    lg_sh = lg.map(lambda d: d["sh_pct"])
    lg_share = lg.map(lambda d: d["assist_share"])
    lg_toi = lg.map(lambda d: d["toi"])

    # --- Ice time projection
    prior_toi_avg = np.where(df["p_gp"] > 0, df["p_toi"] / df["p_gp"].clip(lower=1), lg_toi)
    w_toi = 10
    season_toi = (df["c_toi"] + prior_toi_avg * w_toi) / (df["c_gp"] + w_toi)
    recent_toi = np.where(df["r_gp"] > 0, df["r_toi"] / df["r_gp"].clip(lower=1), season_toi)
    wt = cfg["toi_recent_weight"]
    df["proj_toi"] = np.where(df["r_gp"] >= 3, wt * recent_toi + (1 - wt) * season_toi, season_toi)

    # --- Shots per minute
    k = 150.0  # minutes of league-average evidence behind last season's rate
    prior_rate = (df["p_shots"] + lg_rate * k) / (df["p_toi"] + k)
    t_eq = cfg["prior_games"] * prior_toi_avg
    season_rate = (df["c_shots"] + prior_rate * t_eq) / (df["c_toi"] + t_eq)
    t_r = 3 * prior_toi_avg
    recent_rate = (df["r_shots"] + season_rate * t_r) / (df["r_toi"] + t_r)
    wr = cfg["recent_weight"]
    rate = np.where(df["r_gp"] >= 5, (1 - wr) * season_rate + wr * recent_rate, season_rate)

    # --- Opponent factors (shrunk toward league, clamped)
    lo, hi = cfg["opp_clamp"]
    tk = cfg["team_prior_games"]
    o_gp = df["o_c_gp"].fillna(0)
    opp_sa_pg = (df["o_c_sa"].fillna(0) + base["team_sf_pg"] * tk) / (o_gp + tk)
    df["opp_sog_factor"] = (opp_sa_pg / base["team_sf_pg"]).clip(lo, hi)

    sk = cfg["save_prior_shots"]
    opp_gps = (df["o_c_ga"].fillna(0) + base["goals_per_shot"] * sk) / (df["o_c_sa"].fillna(0) + sk)
    df["opp_finish_factor"] = (opp_gps / base["goals_per_shot"]).clip(lo, hi)

    # --- SOG
    df["lam_sog"] = rate * df["proj_toi"] * df["opp_sog_factor"]

    # --- Goals
    shk = cfg["sh_prior_shots"]
    sh_pct = (df["p_goals"] + df["c_goals"] + lg_sh * shk) / (df["p_shots"] + df["c_shots"] + shk)
    df["sh_pct"] = sh_pct
    df["lam_goal"] = df["lam_sog"] * sh_pct * df["opp_finish_factor"]

    # --- Assists
    t_gp = df["t_c_gp"].fillna(0)
    team_gf_pg = (df["t_c_gf"].fillna(0) + base["team_gf_pg"] * tk) / (t_gp + tk)
    opp_ga_pg = (df["o_c_ga"].fillna(0) + base["team_gf_pg"] * tk) / (o_gp + tk)
    team_proj = team_gf_pg * (opp_ga_pg / base["team_gf_pg"]).clip(lo, hi)
    ak = cfg["assist_prior_team_goals"]
    share = (df["p_assists"] + df["c_assists"] + lg_share * ak) / (df["p_team_gf"] + df["c_team_gf"] + ak)
    toi_ratio = (df["proj_toi"] / season_toi).clip(0.8, 1.2)
    df["lam_assist"] = team_proj * share * toi_ratio

    # --- Naive baseline: raw per-game average this season (last season if < 5 games)
    use_cur = df["c_gp"] >= 5
    df["naive_sog"] = np.where(use_cur, df["c_shots"] / df["c_gp"].clip(lower=1),
                               df["p_shots"] / df["p_gp"].clip(lower=1))
    df["naive_goal"] = np.where(use_cur, df["c_goals"] / df["c_gp"].clip(lower=1),
                                df["p_goals"] / df["p_gp"].clip(lower=1))
    df["naive_assist"] = np.where(use_cur, df["c_assists"] / df["c_gp"].clip(lower=1),
                                  df["p_assists"] / df["p_gp"].clip(lower=1))

    keep = ((df["c_gp"] + df["p_gp"]) >= cfg["min_history_games"]) & (df["proj_toi"] >= cfg["min_proj_toi"])
    return df[keep].copy()


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------
EPS = 1e-6


def dist_sf(k, mu, r):
    """P(X > k) for Poisson (r=None) or negative binomial with size r."""
    mu = np.maximum(mu, EPS)
    if r is None:
        return stats.poisson.sf(k, mu)
    return stats.nbinom.sf(k, r, r / (r + mu))


def dist_logpmf(x, mu, r):
    mu = np.maximum(mu, EPS)
    if r is None:
        return stats.poisson.logpmf(x, mu)
    return stats.nbinom.logpmf(x, r, r / (r + mu))


def brier(p, y):
    return float(np.mean((p - y) ** 2))


def logloss(p, y):
    p = np.clip(p, EPS, 1 - EPS)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def calibration(p, y, bins=10):
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges) - 1, 0, bins - 1)
    out, ece = [], 0.0
    for b in range(bins):
        m = idx == b
        if m.sum() == 0:
            continue
        pred, act = float(p[m].mean()), float(y[m].mean())
        ece += m.sum() / len(p) * abs(pred - act)
        out.append({"lo": round(float(edges[b]), 2), "hi": round(float(edges[b + 1]), 2),
                    "n": int(m.sum()), "pred": round(pred, 4), "actual": round(act, 4)})
    return out, float(ece)


def score_market(p, p_naive, y, early_mask):
    p, p_naive, y = np.asarray(p, float), np.asarray(p_naive, float), np.asarray(y, float)
    bm, bn = brier(p, y), brier(p_naive, y)
    cal, ece = calibration(p, y)

    def skill(mask):
        if mask.sum() < 50:
            return None
        return round(1 - brier(p[mask], y[mask]) / brier(p_naive[mask], y[mask]), 4)

    conf = p >= 0.60
    top = p >= np.quantile(p, 0.95)
    return {
        "n": int(len(y)),
        "base_rate": round(float(y.mean()), 4),
        "avg_pred": round(float(p.mean()), 4),
        "brier_model": round(bm, 5),
        "brier_naive": round(bn, 5),
        "skill": round(1 - bm / bn, 4),
        "logloss_model": round(logloss(p, y), 5),
        "logloss_naive": round(logloss(p_naive, y), 5),
        "ece": round(ece, 4),
        "early_skill": skill(early_mask),
        "late_skill": skill(~early_mask),
        "confident": {"threshold": 0.60, "n": int(conf.sum()),
                      "pred": round(float(p[conf].mean()), 4) if conf.any() else None,
                      "hit": round(float(y[conf].mean()), 4) if conf.any() else None},
        "top5": {"n": int(top.sum()), "pred": round(float(p[top].mean()), 4),
                 "hit": round(float(y[top].mean()), 4)},
        "calibration": cal,
    }


def backtest(proj, cfg=CONFIG):
    early = (proj["c_gp"] < 15).to_numpy()
    shots = proj["shots"].to_numpy()

    # Pick the SOG distribution by how well it predicts the exact shot count
    fits = []
    for r in cfg["nb_dispersion"]:
        ll = float(np.mean(dist_logpmf(shots, proj["lam_sog"].to_numpy(), r)))
        fits.append({"name": "Poisson" if r is None else f"Neg. binomial (r={r})",
                     "r": r, "loglik": round(ll, 5)})
    best = max(fits, key=lambda f: f["loglik"])
    r = best["r"]

    sog = {"label": "Shots on goal", "fits": fits, "chosen": best["name"],
           "avg_proj": round(float(proj["lam_sog"].mean()), 3),
           "avg_actual": round(float(shots.mean()), 3), "lines": {}}
    for line in cfg["sog_lines"]:
        k = int(np.floor(line))
        p = dist_sf(k, proj["lam_sog"].to_numpy(), r)
        p_n = dist_sf(k, proj["naive_sog"].to_numpy(), None)
        y = (shots > line).astype(float)
        sog["lines"][f"{line}"] = score_market(p, p_n, y, early)

    goals = score_market(1 - np.exp(-proj["lam_goal"]), 1 - np.exp(-proj["naive_goal"]),
                         (proj["goals"] >= 1).astype(float), early)
    goals.update(label="Anytime goal", avg_proj=round(float(proj["lam_goal"].mean()), 4),
                 avg_actual=round(float(proj["goals"].mean()), 4))

    assists = score_market(1 - np.exp(-proj["lam_assist"]), 1 - np.exp(-proj["naive_assist"]),
                           (proj["assists"] >= 1).astype(float), early)
    assists.update(label="1+ assist", avg_proj=round(float(proj["lam_assist"].mean()), 4),
                   avg_actual=round(float(proj["assists"].mean()), 4))

    return {"sog": sog, "goals": goals, "assists": assists}


def main():
    refresh = "--refresh" in sys.argv
    prior = fetch_season(PRIOR_SEASON, refresh)
    test = fetch_season(TEST_SEASON, refresh)
    proj = build_projections(test, prior)
    markets = backtest(proj)

    out = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "season_tested": "2025-26",
        "prior_season": "2024-25",
        "counts": {"player_games": int(len(proj)), "players": int(proj["player_id"].nunique()),
                   "games": int(proj["game_id"].nunique())},
        "config": CONFIG,
        "markets": markets,
    }
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(out, indent=1))
    print(f"Wrote {OUT_FILE}")
    for key, m in markets.items():
        if key == "sog":
            for line, s in m["lines"].items():
                print(f"  SOG o{line}: skill {s['skill']:+.1%}, calibration miss {s['ece']:.1%}")
        else:
            print(f"  {m['label']}: skill {m['skill']:+.1%}, calibration miss {m['ece']:.1%}")


if __name__ == "__main__":
    main()
