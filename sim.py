#!/usr/bin/env python3
"""Scoresheet sim mode: paper-bet the board's plays and grade them from NHL boxscores.

Each run:
  1. Grades pending plays whose games are final.
  2. Logs today's qualifying plays from docs/data/board.json (games not yet started only).
  3. Logs every priced prop (bet or not) to docs/data/calib/<date>.json and grades it later,
     so the model and the book's cut can be checked on thousands of props, not just our picks.
Nothing here places real bets. Every play is a flat 1-unit paper bet.
"""
import json
from datetime import datetime, timedelta, timezone
import nhl_pipeline as m

BOARD = m.ROOT / "docs" / "data" / "board.json"
LOG = m.ROOT / "docs" / "data" / "sim_log.json"
CALIB = m.ROOT / "docs" / "data" / "calib"   # one small file per day
MIN_EV = 0.05      # same bar as "Best plays" on the board (the value strategy)
# The "most likely" strategy logs every prop board.py marks likely, even below MIN_EV (kind "likely").
FLAG_EV = 0.30     # logged, but tagged so we can see if these lose
WATCH_N = 8        # with no prices, track the model's top picks per market instead
STALE_DAYS = 3     # postponed games void after this long


def decimal(price):
    return 1 + price / 100 if price > 0 else 1 + 100 / abs(price)


def load(path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def boxscore_stats(game_id):
    """Returns (is_final, {player_id: {"goal": n, "assist": n}})."""
    data = m.get_json(f"{m.BASE}/gamecenter/{game_id}/boxscore") or {}
    final = data.get("gameState") in ("OFF", "FINAL")
    stats = {}
    teams = data.get("playerByGameStats", {})
    for side in ("awayTeam", "homeTeam"):
        for group in ("forwards", "defense"):
            for p in teams.get(side, {}).get(group, []):
                stats[int(p["playerId"])] = {"goal": p.get("goals", 0) or 0,
                                             "assist": p.get("assists", 0) or 0}
    return final, stats


def grade(log):
    now = datetime.now(timezone.utc)
    pending_games = {b["game_id"] for b in log if b["status"] == "pending"}
    for gid in pending_games:
        final, stats = boxscore_stats(gid)
        for b in (x for x in log if x["game_id"] == gid and x["status"] == "pending"):
            if final:
                if b["player_id"] not in stats:
                    b["status"] = "void"  # scratched: books refund
                else:
                    b["status"] = "win" if stats[b["player_id"]][b["market"]] >= 1 else "loss"
            elif now - datetime.fromisoformat(b["logged"]) > timedelta(days=STALE_DAYS):
                b["status"] = "void"
            if b["status"] != "pending":
                b["units"] = (round(decimal(b["price"]) - 1, 3) if b["status"] == "win" else
                              -1.0 if b["status"] == "loss" else 0.0) if b.get("price") else None
    return log


def log_today(log, board):
    now = datetime.now(timezone.utc)
    starts = {g["id"]: g.get("start") for g in board.get("games", [])}
    seen = {(b["date"], b["player_id"], b["market"]) for b in log}
    new = []
    for market in ("goal", "assist"):
        rows = [p for p in board.get("players", []) if p.get(market)]
        priced = [p for p in rows if p[market].get("ev") is not None]
        if priced:
            picks = [p for p in priced if p[market]["ev"] >= MIN_EV or p[market].get("likely")]
        else:
            picks = sorted(rows, key=lambda p: -p[market]["p"])[:WATCH_N]
        for p in picks:
            kind = "watch" if not priced else "bet" if p[market]["ev"] >= MIN_EV else "likely"
            start = starts.get(p["game_id"])
            if start and datetime.fromisoformat(start.replace("Z", "+00:00")) <= now:
                continue  # never log after puck drop
            if (board["date"], p["id"], market) in seen:
                continue  # first price logged is the one we "bet"
            mk = p[market]
            new.append({"date": board["date"], "game_id": p["game_id"], "player_id": p["id"],
                        "name": p["name"], "team": p["team"], "opp": p["opp"], "market": market,
                        "kind": kind, "p": mk["p"], "p_model": mk.get("p_model"), "p_mkt": mk.get("p_mkt"),
                        "fair": mk["fair"], "price": mk.get("price"), "book": mk.get("book"),
                        "prices": mk.get("prices"), "ev": mk.get("ev"),
                        "flag": bool(mk.get("ev") is not None and mk["ev"] >= FLAG_EV),
                        "likely": bool(mk.get("likely")),
                        "logged": now.isoformat(timespec="minutes"), "status": "pending",
                        "units": None})
    return log + new, len(new)


def calibration(board):
    """Grades old calibration files and adds tonight's priced props (first price seen is kept)."""
    CALIB.mkdir(parents=True, exist_ok=True)
    cache = {}
    for path in sorted(CALIB.glob("*.json")):
        rows = load(path, [])
        if not any(r["hit"] is None for r in rows):
            continue
        for r in rows:
            if r["hit"] is not None:
                continue
            if r["game_id"] not in cache:
                cache[r["game_id"]] = boxscore_stats(r["game_id"])
            final, stats = cache[r["game_id"]]
            if final:
                r["hit"] = -1 if r["player_id"] not in stats else int(stats[r["player_id"]][r["market"]] >= 1)
        path.write_text(json.dumps(rows, separators=(",", ":")))
    if not board.get("players"):
        return
    now = datetime.now(timezone.utc)
    starts = {g["id"]: g.get("start") for g in board.get("games", [])}
    path = CALIB / f"{board['date']}.json"
    rows = load(path, [])
    seen = {(r["player_id"], r["market"]) for r in rows}
    for p in board["players"]:
        start = starts.get(p["game_id"])
        if start and datetime.fromisoformat(start.replace("Z", "+00:00")) <= now:
            continue
        for market in ("goal", "assist"):
            mk = p.get(market) or {}
            if not mk.get("prices") or (p["id"], market) in seen:
                continue
            rows.append({"game_id": p["game_id"], "player_id": p["id"], "name": p["name"], "pos": p.get("pos"),
                         "market": market, "p_model": mk.get("p_model"), "p_mkt": mk.get("p_mkt"),
                         "prices": mk["prices"], "hit": None})  # hit: 1 yes, 0 no, -1 did not play
    path.write_text(json.dumps(rows, separators=(",", ":")))


def main():
    log = grade(load(LOG, []))
    board = load(BOARD, {})
    added = 0
    if board.get("games"):
        log, added = log_today(log, board)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text(json.dumps(log, indent=1))
    calibration(board)
    done = [b for b in log if b["status"] in ("win", "loss")]
    units = sum(b["units"] or 0 for b in done)
    print(f"Logged {added} new plays. Graded record {sum(b['status'] == 'win' for b in done)}-"
          f"{sum(b['status'] == 'loss' for b in done)}, {units:+.2f} units on priced plays.")


if __name__ == "__main__":
    main()
