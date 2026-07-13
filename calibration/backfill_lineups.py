"""Backfill starter rows + CONFIRMED-LINEUP K% from historical boxscores.

    python backfill_lineups.py 2026-06-13 2026-07-12

Compresses the "wait weeks for a forward archive" problem: for PAST games the
confirmed lineup is simply the boxscore batting order, and each batter's K%
can be queried AS OF the day before the game (StatsAPI byDateRange) — so the
lineup feature is available historically, leakage-free, today.

For every final game in the range, per starting pitcher:
  date, pitcher, pitcher_id, team, opponent, is_home, K, BF, pitches
    (extends the training gamelog past its 6/12 cutoff)
  lineup_k_pct  PA-weighted season-to-date K% of the 9 batters who actually
                started against him, each shrunk (K + 50*0.22)/(PA + 50) so
                a call-up's 20-PA rate can't dominate
  lineup_n      batters found (rows with < 7 are flagged, kept)

Batter K% lookups are cached per (batter, week) — rates move slowly — and
persisted to the output dir, so reruns are cheap.

Output: data/lineups_backfill.csv (append-safe: skips dates already present).
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
import urllib.request
from datetime import date as _date, timedelta

OUT = os.path.join(os.path.dirname(__file__), "..", "data", "lineups_backfill.csv")
CACHE = os.path.join(os.path.dirname(__file__), "..", "data", ".batter_k_cache.json")
FIELDS = ["date", "pitcher", "pitcher_id", "team", "opponent", "is_home",
          "K", "BF", "pitches", "lineup_k_pct", "lineup_n"]
LG_K = 0.22        # league K per PA, shrink prior
PRIOR_PA = 50.0


def _get(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=45) as r:
                return json.load(r)
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2.0 * (i + 1))


_cache: dict[str, float] = {}


def _load_cache():
    global _cache
    if os.path.exists(CACHE):
        _cache = json.load(open(CACHE, encoding="utf-8"))


def _save_cache():
    json.dump(_cache, open(CACHE, "w", encoding="utf-8"))


def batter_k(pid: int, day: str) -> float | None:
    """Shrunk season-to-date K/PA for a batter, as of the day BEFORE `day`.
    Cached per (pid, iso-week) — weekly granularity is plenty."""
    d = _date.fromisoformat(day)
    key = f"{pid}:{d.isocalendar()[0]}-{d.isocalendar()[1]}"
    if key in _cache:
        return _cache[key]
    end = (d - timedelta(days=1)).isoformat()
    try:
        st = _get(f"https://statsapi.mlb.com/api/v1/people/{pid}/stats"
                  f"?stats=byDateRange&group=hitting&season={d.year}"
                  f"&startDate={d.year}-03-01&endDate={end}")
        splits = st.get("stats", [{}])[0].get("splits", [])
        s = splits[0]["stat"] if splits else {}
        k = float(s.get("strikeOuts", 0) or 0)
        pa = float(s.get("plateAppearances", 0) or 0)
        v = (k + PRIOR_PA * LG_K) / (pa + PRIOR_PA)
    except Exception:
        v = None
    _cache[key] = v
    return v


def day_rows(ds: str) -> list[dict]:
    rows = []
    sched = _get(f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={ds}")
    for d in sched.get("dates", []):
        for g in d.get("games", []):
            if g.get("status", {}).get("abstractGameState") != "Final":
                continue
            try:
                box = _get("https://statsapi.mlb.com/api/v1/game/"
                           f"{g['gamePk']}/boxscore")
            except Exception:
                continue
            names = {s: box["teams"][s]["team"].get("abbreviation")
                     or box["teams"][s]["team"]["name"] for s in ("home", "away")}
            for side, opp in (("home", "away"), ("away", "home")):
                tb = box["teams"][side]
                # starting pitcher: first id in the team's `pitchers` list
                pids = tb.get("pitchers") or []
                if not pids:
                    continue
                sp = tb["players"].get(f"ID{pids[0]}")
                if not sp:
                    continue
                pst = sp.get("stats", {}).get("pitching", {})
                if not pst:
                    continue
                # opposing lineup = the OTHER side's batting order
                order = (box["teams"][opp].get("battingOrder") or [])[:9]
                ks = [batter_k(b, ds) for b in order]
                ks = [k for k in ks if k is not None]
                rows.append({
                    "date": ds, "pitcher": sp["person"]["fullName"],
                    "pitcher_id": pids[0], "team": names[side],
                    "opponent": names[opp], "is_home": side == "home",
                    "K": int(pst.get("strikeOuts", 0) or 0),
                    "BF": int(pst.get("battersFaced", 0) or 0),
                    "pitches": int(pst.get("pitchesThrown",
                                           pst.get("numberOfPitches", 0)) or 0),
                    "lineup_k_pct": (f"{sum(ks)/len(ks):.4f}" if ks else ""),
                    "lineup_n": len(ks),
                })
    return rows


def main() -> None:
    if len(sys.argv) < 3:
        print("usage: backfill_lineups.py <start> <end>")
        return
    start, end = sys.argv[1], sys.argv[2]
    _load_cache()
    done = set()
    if os.path.exists(OUT):
        done = {r["date"] for r in csv.DictReader(open(OUT, encoding="utf-8"))}
    new = not os.path.exists(OUT)
    d = _date.fromisoformat(start)
    with open(OUT, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        while d <= _date.fromisoformat(end):
            ds = d.isoformat()
            if ds in done:
                print(f"{ds}: already backfilled — skip", flush=True)
            else:
                rows = day_rows(ds)
                w.writerows(rows)
                f.flush()
                _save_cache()
                print(f"{ds}: {len(rows)} starters "
                      f"(lineup found for "
                      f"{sum(1 for r in rows if r['lineup_k_pct'])})", flush=True)
            d += timedelta(days=1)
    _save_cache()
    print(f"done -> {OUT}")


if __name__ == "__main__":
    main()
