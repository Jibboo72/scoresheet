#!/usr/bin/env python3
"""
Scoresheet — NHL prop model (SOG, goals, assists).

The data pull lives in nhl_data.py and the model in nhl_model.py. This file scores
the model: it projects every 2025-26 game using only earlier games and writes
docs/data/backtest.json. board.py, sim.py and tune.py import everything through here.

Run:  python nhl_pipeline.py            (uses cached data if present)
      python nhl_pipeline.py --refresh  (re-download everything)
"""
import json
import sys
from datetime import datetime, timezone

import numpy as np
from scipy import stats

from nhl_data import BASE, DATA_DIR, ROOT, TEAMS, fetch_games, fetch_goalies, fetch_season, get_json, name_of  # noqa: F401
from nhl_model import CONFIG, build_projections, team_games  # noqa: F401

PRIOR_SEASON = "20242025"
TEST_SEASON = "20252026"
OUT_FILE = ROOT / "docs" / "data" / "backtest.json"

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
