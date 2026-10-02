"""Scoresheet model: projects shots, goals and assists for each skater-game using only earlier games."""
import numpy as np
import pandas as pd

# Every tunable number lives here. tune.py picks the best values and saves them to data/tuned_config.json.
CONFIG = {
    "prior_games": 20,          # last season counts as this many games of evidence
    "recent_n": 10,             # recency window
    "recent_weight": 0.35,      # tilt toward the last 10
    "toi_recent_weight": 0.60,  # ice time follows recent usage more closely
    "pp_weight": 1.0,           # a power-play minute counts this many even-strength minutes
    "sh_weight": 1.0,           # a penalty-kill minute counts this many even-strength minutes
    "home_edge": 0.0,           # home +x, away -x on every projection
    "b2b_drop": 0.0,            # second night of a back-to-back
    "team_prior_games": 10, "opp_clamp": [0.85, 1.15],  # shrink team/opponent rates toward league
    "sh_prior_shots": 150,      # shooting % regression (shots of evidence)
    "save_prior_shots": 600,    # opponent save % regression
    "assist_prior_team_goals": 40,
    "role_prior_goals": False, "role_prior_assists": False,  # regress toward similar-ice-time players
    "min_history_games": 5,     # skip players with almost no history
    "min_proj_toi": 10.0,       # books rarely post lines below this
    "nb_dispersion": [None, 40, 20, 10, 6], "sog_lines": [1.5, 2.5, 3.5],  # None = Poisson
}
ROLE_BINS = [0, 13, 15, 17, 19, 40]  # minutes per game


def pos_group(p):
    return "D" if p == "D" else "F"


def prep(df, cfg):
    df = df.copy()
    for c in ("pp_toi", "sh_toi"):
        df[c] = df[c].fillna(0.0) if c in df else 0.0
    df["eff"] = df["toi"] + (cfg["pp_weight"] - 1) * df["pp_toi"] + (cfg["sh_weight"] - 1) * df["sh_toi"]
    df["pg"] = df["pos"].map(pos_group)
    return df


def team_games(df):
    """One row per team per game: shots/goals for and against."""
    tg = df.groupby(["game_id", "date", "team", "opp"], as_index=False).agg(
        sf=("shots", "sum"), gf=("goals", "sum"))
    against = tg[["game_id", "team", "sf", "gf"]].rename(columns={"team": "opp", "sf": "sa", "gf": "ga"})
    return tg.merge(against, on=["game_id", "opp"], how="left").fillna({"sa": 0, "ga": 0})


def league_baselines(prior, cfg):
    prior = prep(prior, cfg)
    tg = team_games(prior)
    prior = prior.merge(tg[["game_id", "team", "gf"]].rename(columns={"gf": "team_gf"}),
                        on=["game_id", "team"], how="left")
    base = {"team_sf_pg": tg["sf"].mean(), "team_gf_pg": tg["gf"].mean(), "pos": {}}
    for g, d in prior.groupby("pg"):
        base["pos"][g] = {"shots_per_min": d["shots"].sum() / d["eff"].sum(),
                          "sh_pct": d["goals"].sum() / max(d["shots"].sum(), 1),
                          "assist_share": d["assists"].sum() / max(d["team_gf"].sum(), 1),
                          "toi": d["toi"].mean(), "eff": d["eff"].mean()}
    pt = prior.groupby("player_id").agg(pg=("pg", "first"), toi=("toi", "mean"), g=("goals", "sum"),
                                        s=("shots", "sum"), a=("assists", "sum"), tgf=("team_gf", "sum"))
    pt["tier"] = pd.cut(pt["toi"], ROLE_BINS, labels=False)
    rt = pt.groupby(["pg", "tier"])[["g", "s", "a", "tgf"]].sum()
    base["role_sh"] = (rt["g"] / rt["s"].clip(lower=1)).to_dict()
    base["role_share"] = (rt["a"] / rt["tgf"].clip(lower=1)).to_dict()
    return base, prior


def prior_player_table(prior_rows):
    return prior_rows.groupby("player_id").agg(
        p_gp=("game_id", "count"), p_toi=("toi", "sum"), p_eff=("eff", "sum"), p_shots=("shots", "sum"),
        p_goals=("goals", "sum"), p_assists=("assists", "sum"), p_team_gf=("team_gf", "sum")).reset_index()


def build_projections(test, prior, cfg=CONFIG):
    base, prior_rows = league_baselines(prior, cfg)
    df = prep(test, cfg).sort_values(["player_id", "date", "game_id"]).reset_index(drop=True)

    # Team context, strictly pre-game
    tg = team_games(df).sort_values(["team", "date", "game_id"])
    t = tg.groupby("team")
    for c in ("sf", "gf", "sa", "ga"):
        tg[f"c_{c}"] = t[c].cumsum() - tg[c]
    tg["c_gp"] = t.cumcount()
    tg["rest"] = pd.to_datetime(tg["date"]).groupby(tg["team"]).diff().dt.days
    # League averages from this season to date, leaning on last season early on
    daily = tg.groupby("date").agg(sf=("sf", "sum"), gf=("gf", "sum"), n=("sf", "size")).sort_index()
    cum, K = daily.cumsum().shift(1).fillna(0), 64
    cum["lg_sf"] = (cum["sf"] + base["team_sf_pg"] * K) / (cum["n"] + K)
    cum["lg_gf"] = (cum["gf"] + base["team_gf_pg"] * K) / (cum["n"] + K)
    df = df.merge(cum[["lg_sf", "lg_gf"]], left_on="date", right_index=True, how="left")
    df = df.merge(tg[["game_id", "team", "gf", "c_gf", "c_gp", "rest"]].rename(
        columns={"gf": "team_gf", "c_gf": "t_c_gf", "c_gp": "t_c_gp"}), on=["game_id", "team"], how="left")
    df = df.merge(tg[["game_id", "team", "c_sa", "c_ga", "c_gp"]].rename(
        columns={"team": "opp", "c_sa": "o_c_sa", "c_ga": "o_c_ga", "c_gp": "o_c_gp"}), on=["game_id", "opp"], how="left")
    # Player history, strictly pre-game
    g = df.groupby("player_id")
    for c in ("toi", "eff", "shots", "goals", "assists", "team_gf"):
        df[f"c_{c}"] = g[c].cumsum() - df[c]
    df["c_gp"] = g.cumcount()
    n = cfg["recent_n"]
    for c in ("toi", "eff", "shots"):
        df[f"r_{c}"] = g[c].transform(lambda s: s.shift(1).rolling(n, min_periods=1).sum()).fillna(0)
    df["r_gp"] = g["toi"].transform(lambda s: s.shift(1).rolling(n, min_periods=1).count()).fillna(0)
    df = df.merge(prior_player_table(prior_rows), on="player_id", how="left")
    for c in ("p_gp", "p_toi", "p_eff", "p_shots", "p_goals", "p_assists", "p_team_gf"):
        df[c] = df[c].fillna(0)
    lg = df["pg"].map(lambda x: base["pos"][x])
    # Ice time (minutes, for display and filters) and effective minutes (power play weighted, for rates)
    wt = cfg["toi_recent_weight"]

    def usage(col, lg_val):
        prior_avg = np.where(df["p_gp"] > 0, df[f"p_{col}"] / df["p_gp"].clip(lower=1), lg_val)
        season = (df[f"c_{col}"] + prior_avg * 10) / (df["c_gp"] + 10)
        recent = np.where(df["r_gp"] > 0, df[f"r_{col}"] / df["r_gp"].clip(lower=1), season)
        return prior_avg, season, np.where(df["r_gp"] >= 3, wt * recent + (1 - wt) * season, season)
    prior_toi_avg, _, df["proj_toi"] = usage("toi", lg.map(lambda d: d["toi"]))
    prior_eff_avg, season_eff, df["proj_eff"] = usage("eff", lg.map(lambda d: d["eff"]))

    # Shots per effective minute
    k = 150.0
    prior_rate = (df["p_shots"] + lg.map(lambda d: d["shots_per_min"]) * k) / (df["p_eff"] + k)
    t_eq = cfg["prior_games"] * prior_eff_avg
    season_rate = (df["c_shots"] + prior_rate * t_eq) / (df["c_eff"] + t_eq)
    t_r = 3 * prior_eff_avg
    recent_rate = (df["r_shots"] + season_rate * t_r) / (df["r_eff"] + t_r)
    wr = cfg["recent_weight"]
    rate = np.where(df["r_gp"] >= 5, (1 - wr) * season_rate + wr * recent_rate, season_rate)
    # Opponents, compared with this season's league average
    lo, hi = cfg["opp_clamp"]
    tk, o_gp = cfg["team_prior_games"], df["o_c_gp"].fillna(0)
    opp_sa_pg = (df["o_c_sa"].fillna(0) + df["lg_sf"] * tk) / (o_gp + tk)
    df["opp_sog_factor"] = (opp_sa_pg / df["lg_sf"]).clip(lo, hi)
    sk, lg_gps = cfg["save_prior_shots"], df["lg_gf"] / df["lg_sf"]
    opp_gps = (df["o_c_ga"].fillna(0) + lg_gps * sk) / (df["o_c_sa"].fillna(0) + sk)
    df["opp_finish_factor"] = (opp_gps / lg_gps).clip(lo, hi)
    # Home ice and the second night of a back-to-back
    h, b = cfg["home_edge"], cfg["b2b_drop"]
    df["ctx"] = np.where(df["home"] == 1, 1 + h, 1 - h) * np.where(df["rest"] == 1, 1 - b, 1.0)
    df["lam_sog"] = rate * df["proj_eff"] * df["opp_sog_factor"] * df["ctx"]
    # Goals: regressed shooting %, optionally toward players with similar ice time
    role_toi = np.where(df["p_gp"] > 0, prior_toi_avg, df["proj_toi"])  # rookies: use current ice time
    tier = pd.cut(pd.Series(role_toi, index=df.index), ROLE_BINS, labels=False).fillna(2).astype(int)

    def role(table, key):
        pos_val = lg.map(lambda d: d[key])
        vals = pd.Series([table.get((p, t), np.nan) for p, t in zip(df["pg"], tier)], index=df.index)
        return vals.fillna(pos_val)
    lg_sh = role(base["role_sh"], "sh_pct") if cfg["role_prior_goals"] else lg.map(lambda d: d["sh_pct"])
    shk = cfg["sh_prior_shots"]
    df["sh_pct"] = (df["p_goals"] + df["c_goals"] + lg_sh * shk) / (df["p_shots"] + df["c_shots"] + shk)
    df["lam_goal"] = df["lam_sog"] * df["sh_pct"] * df["opp_finish_factor"]
    # Assists: projected team goals x the player's share of them
    t_gp = df["t_c_gp"].fillna(0)
    team_gf_pg = (df["t_c_gf"].fillna(0) + df["lg_gf"] * tk) / (t_gp + tk)
    opp_ga_pg = (df["o_c_ga"].fillna(0) + df["lg_gf"] * tk) / (o_gp + tk)
    team_proj = team_gf_pg * (opp_ga_pg / df["lg_gf"]).clip(lo, hi) * df["ctx"]
        df["team_proj"] = team_proj  # the model's expected goals for the player's team

    lg_share = role(base["role_share"], "assist_share") if cfg["role_prior_assists"] else lg.map(lambda d: d["assist_share"])
    ak = cfg["assist_prior_team_goals"]
    share = (df["p_assists"] + df["c_assists"] + lg_share * ak) / (df["p_team_gf"] + df["c_team_gf"] + ak)
    df["lam_assist"] = team_proj * share * (df["proj_eff"] / season_eff).clip(0.8, 1.2)
    # Naive baseline: raw per-game average this season (last season if < 5 games)
    use_cur = df["c_gp"] >= 5
    for stat, col in (("sog", "shots"), ("goal", "goals"), ("assist", "assists")):
        df[f"naive_{stat}"] = np.where(use_cur, df[f"c_{col}"] / df["c_gp"].clip(lower=1),
                                       df[f"p_{col}"] / df["p_gp"].clip(lower=1))
    keep = ((df["c_gp"] + df["p_gp"]) >= cfg["min_history_games"]) & (df["proj_toi"] >= cfg["min_proj_toi"])
    return df[keep].copy()
