"""Backtest the Pick6 pitcher-strikeout strategy over a date range and write a CSV.

For each day: pull the strike/mlb-edge slate (projected K = lambda, and the book
line as a Pick6-line proxy), pull real strikeout actuals from MLB StatsAPI, run
the SAME pipeline as the live picker (calibrated NB scoring -> breakeven gate ->
step-down power-play build -> correlation-adjusted sizing), grade each entry, and
record it. Flat 1-unit stake per entry so ROI is stake-agnostic.

    python backtest_pick6.py 2026-06-05 2026-07-04

CAVEATS (read these):
  * Book line is a PROXY for the DK Pick6 line (real Pick6 boards weren't stored
    historically). Pick6 lines are usually softer, so real edge could differ.
  * No RotoWire gate (no historical projections) -> this is the UN-gated strategy.
  * The NB dispersion was fit on 6/28-7/3, so those days are IN-SAMPLE.
  * Only days with usable book lines + final games are covered; gaps are reported.
"""
from __future__ import annotations

import csv
import json
import os
import sys
import urllib.request
from datetime import date as _date, timedelta

import math

from config import MIN_PICKS, entry_multiplier
from feed import norm
from grade import final_stats, leg_won
from pick6_line import sim_pick6_line
from sim import rank_legs

N_PICKS, MAX_ENTRIES, MARGIN, STAKE = 3, 4, 0.05, 1.0
OUT = os.path.join(os.path.dirname(__file__), "..", "data")


def _make_entry(legs):
    boosts = [l["boost"] for l in legs]
    mult = entry_multiplier(len(legs), boosts)
    p = math.prod(l["p"] for l in legs)
    return {"legs": legs, "n": len(legs), "p": p, "mult": mult, "ev": p * mult - 1}


def build_disjoint(legs, n, max_entries, margin=MARGIN, platform="dk_pick6"):
    """Entries that never REUSE a leg (no double-counted, correlated overlap).
    Since each pitcher starts once/day, this also caps each pitcher to <=1
    entry/day — the per-day pitcher-cluster cap."""
    ranked = rank_legs(legs, n, margin, platform)
    used, entries = set(), []
    while len(entries) < max_entries:
        chosen, games = [], set()
        for l in ranked:
            if id(l) in used or l["game"] in games:
                continue
            chosen.append(l); games.add(l["game"])
            if len(chosen) == n:
                break
        if len(chosen) < n:
            break
        for l in chosen:
            used.add(id(l))
        entries.append(_make_entry(chosen))
    return entries


def _get(u):
    with urllib.request.urlopen(u, timeout=90) as r:
        return json.load(r)


def slate_legs(d: str) -> list[dict]:
    try:
        s = _get(f"https://strike.perfecthold.online/api/v2/slate?date={d}")
    except Exception:
        return []
    legs = []
    for r in s.get("rows", []) or []:
        if r.get("expected_ks") is None or r.get("line") is None:
            continue
        legs.append({"name": r["pitcher"], "market": "strikeouts",
                     "game": r.get("game_pk") or r.get("opponent") or r["pitcher"],
                     "line": float(r["line"]), "lam": float(r["expected_ks"])})
    return legs


def daterange(a: str, b: str):
    d0 = _date.fromisoformat(a); d1 = _date.fromisoformat(b)
    while d0 <= d1:
        yield d0.isoformat()
        d0 += timedelta(days=1)


# Line sources for the sensitivity sweep. Each maps a book line -> the line the
# strategy actually bets against. "sportsbook" = use the book line as-is (the
# proxy); "sim" = simulate a pick'em line with the measured jitter + a softness
# shift (negative = pick'em posts lines BELOW sportsbook, making Overs easier).
def line_sources():
    src = [("sportsbook (proxy)", lambda bl, nm, d: bl)]
    for s in (-0.5, 0.0, 0.5):
        tag = f"pick'em sim {s:+.1f}" + (" soft" if s < 0 else " tight" if s > 0 else "")
        src.append((tag, (lambda s: lambda bl, nm, d: sim_pick6_line(bl, nm, d, softness=s))(s)))
    return src


def run(day_legs, line_fn, margin):
    """Disjoint (per-day cluster-capped) strategy under a line source + gate."""
    rows, legsamp = [], []
    for d, legs in day_legs.items():
        legs2 = [dict(l) for l in legs]
        for l in legs2:
            l["line"] = line_fn(l["line"], l["name"], d)   # book line -> bet line
        n, entries = 3, []
        while n >= MIN_PICKS:
            entries = build_disjoint(legs2, n, 4, margin)
            if entries:
                break
            n -= 1
        for e in entries:
            won = all(leg_won(l["side"], l["line"], l["actual"]) for l in e["legs"])
            rows.append({"date": d, "n": e["n"], "won": int(won),
                         "pnl": (e["mult"] - 1) if won else -1,
                         "legs": " + ".join(
                             f"{l['name'].split()[-1]} {l['side'][0].upper()}{l['line']}"
                             f"={l['actual']}{'W' if leg_won(l['side'],l['line'],l['actual']) else 'L'}"
                             for l in e["legs"])})
            for l in e["legs"]:
                legsamp.append((l["p"], leg_won(l["side"], l["line"], l["actual"])))
    return rows, legsamp


def main():
    end = sys.argv[2] if len(sys.argv) > 2 else (_date.today() - timedelta(days=1)).isoformat()
    start = sys.argv[1] if len(sys.argv) > 1 else (_date.fromisoformat(end) - timedelta(days=29)).isoformat()
    GATE = 0.08   # gated margin (proxy for the live RotoWire quality gate — no
    #             historical RotoWire projections exist, so we gate on a stiffer
    #             edge requirement instead).

    day_legs, skipped = {}, 0
    for d in daterange(start, end):
        legs = slate_legs(d)
        actuals = final_stats(d) if legs else {}
        for l in legs:
            l["actual"] = actuals.get(norm(l["name"]), {}).get("strikeouts")
        legs = [l for l in legs if l["actual"] is not None]
        if len(legs) < MIN_PICKS:
            skipped += 1
        else:
            day_legs[d] = legs

    out_path = os.path.join(OUT, f"backtest_pick6_{start}_{end}.csv")
    fields = ["line_source", "date", "n", "won", "pnl", "legs"]
    all_rows = []
    print(f"ENHANCED BACKTEST {start} -> {end}   days usable {len(day_legs)}/{len(day_legs)+skipped}")
    print("  disjoint entries (per-day pitcher-cluster cap) · gate margin 0.08 · flat 1u")
    print(f"\n  {'line source':22}{'entries':>8}{'won':>5}{'win%':>7}{'ROI':>8}   leg-calib pred->real")
    for tag, fn in line_sources():
        rows, ls = run(day_legs, fn, GATE)
        for r in rows:
            all_rows.append({"line_source": tag, **r})
        if not rows:
            print(f"  {tag:22}{0:>8}"); continue
        won = sum(r["won"] for r in rows); pnl = sum(r["pnl"] for r in rows)
        pred = sum(p for p, _ in ls) / len(ls); real = sum(1 for _, w in ls if w) / len(ls)
        print(f"  {tag:22}{len(rows):>8}{won:>5}{won/len(rows)*100:>6.0f}%"
              f"{pnl/len(rows)*100:>+7.0f}%   {pred*100:.1f}% -> {real*100:.1f}% (n={len(ls)})")

    # reference: ungated sportsbook, to show the gate's effect
    rows, ls = run(day_legs, lambda bl, nm, d: bl, 0.05)
    if rows:
        won = sum(r["won"] for r in rows); pnl = sum(r["pnl"] for r in rows)
        print(f"  {'[ref] sportsbook ungated':22}{len(rows):>8}{won:>5}"
              f"{won/len(rows)*100:>6.0f}%{pnl/len(rows)*100:>+7.0f}%")

    os.makedirs(OUT, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); w.writerows(all_rows)
    print("\n  Read the sweep, not one number: if the edge only survives at 'soft',")
    print("  it depends on pick'em lines being softer than sportsbook — capture real")
    print("  boards to confirm. leg-calib is the model check; ROI is small-sample.")
    print(f"  CSV -> {out_path}")


if __name__ == "__main__":
    main()
