"""Score TODAY's DraftKings Pick6 pitcher-strikeout board with the mlb-edge model.

Joins the live strike/mlb-edge slate (its projected strikeouts = lambda per
pitcher) to the captured DK Pick6 board (data/pick6_board_<date>.csv), scores
More/Less against DK's OWN line (not the sportsbook line — DK's soft number is
the edge), and builds paper power-play entries.

    python pick6_today.py 2026-07-05

*** PAPER ONLY — model is uncalibrated / over-projects. Run the calibration
backtest (calibration/backtest.py) before trusting any breakeven. ***
"""
from __future__ import annotations

import csv
import os
import sys

from config import MIN_PICKS, breakeven_per_leg
from correlation import corr_outcome_matrix, joint_p_all, same_side
from crosscheck import annotate, gate
from feed import lambdas_for
from sim import allocate, build_entries, outcome_matrix, rank_legs, score_leg

BANKROLL, N_PICKS, MAX_ENTRIES = 1000.0, 3, 4
DAILY_FRAC, KELLY_FRAC, PER_CAP, MARGIN = 0.05, 0.25, 0.02, 0.05
REQUIRE_AGREE = True  # Phase 3: drop legs RotoWire disagrees with


DATA = os.path.join(os.path.dirname(__file__), "..", "data")


def load_board(date: str) -> list[dict]:
    path = os.path.join(DATA, f"pick6_board_{date}.csv")
    rows = []
    for r in csv.DictReader(open(path, encoding="utf-8")):
        rows.append({
            "pitcher": r["pitcher"], "game": r["game"], "line": float(r["line"]),
            "market": r.get("market", "strikeouts"),
            "more_boost": float(r["more_boost"]),
            "more_available": r["more_available"] == "True",
            "less_available": r["less_available"] == "True",
        })
    return rows


def compute_entries(date: str) -> dict:
    """Build the day's paper entries. Returns a dict consumed by both the CLI
    display and the entry logger (log_entries.py). No printing here.
    """
    board = load_board(date)
    lam = lambdas_for(board, date)  # full-slate feed + per-pitcher fallback

    legs, unmatched = [], []
    for b in board:
        L = lam.get(b["pitcher"])
        if L is None:
            unmatched.append(b["pitcher"])
            continue
        legs.append({"name": b["pitcher"], "game": b["game"], "line": b["line"],
                     "market": b["market"], "lam": L, "more_boost": b["more_boost"],
                     "more_available": b["more_available"],
                     "less_available": b["less_available"]})

    # Phase 3: attach a model side, then RotoWire second-opinion agreement, and
    # gate out legs RotoWire explicitly disagrees with.
    for l in legs:
        l["side"] = score_leg(l)["side"]
    annotate(legs)
    gated = gate(legs, REQUIRE_AGREE)

    # Step down from N_PICKS to MIN_PICKS until a valid entry set exists.
    n, entries = N_PICKS, []
    while n >= MIN_PICKS:
        cand = rank_legs(gated, n, MARGIN)
        entries = build_entries(cand, n, MAX_ENTRIES) if len(cand) >= n else []
        if entries:
            break
        n -= 1
    # Phase 4: correlation-adjust each entry (shared day-factor), re-rank by the
    # corrected EV, and size stakes off the corrected win probability.
    for e in entries:
        e["corr_p"] = joint_p_all(e["legs"])
        e["corr_ev"] = e["corr_p"] * e["mult"] - 1.0
        e["same_side"] = same_side(e["legs"])
        b = e["mult"] - 1.0
        e["kelly"] = max(0.0, (e["corr_p"] * b - (1 - e["corr_p"])) / b)
    entries.sort(key=lambda e: e["corr_ev"], reverse=True)

    daily_cap = scale = None
    if entries:
        entries, daily_cap, scale = allocate(
            entries, BANKROLL, DAILY_FRAC, KELLY_FRAC, PER_CAP)
    return {"date": date, "board": board, "legs": legs, "unmatched": unmatched,
            "entries": entries, "n_picks": n, "daily_cap": daily_cap, "scale": scale}


def main() -> None:
    date = sys.argv[1] if len(sys.argv) > 1 else "2026-07-05"
    res = compute_entries(date)
    legs, entries, n = res["legs"], res["entries"], res["n_picks"]
    board, unmatched = res["board"], res["unmatched"]

    print(f"DK Pick6 strikeouts  {date}   board {len(board)} legs, "
          f"model matched {len(legs)}"
          + (f"  (unmatched: {', '.join(unmatched)})" if unmatched else ""))
    if not legs:
        print("No model<->board matches (is the slate live / names aligned?).")
        return

    kept_names = {x["name"] for e in entries for x in e["legs"]}
    be = breakeven_per_leg(N_PICKS)
    print(f"\nLEG SCORES (need P >= breakeven {be*100:.1f}% + {MARGIN*100:.0f}%margin; "
          f"RotoWire must agree)")
    print(f"  {'pitcher':16}{'DKline':>7}{'lambda':>8}{'pick':>7}{'modelP':>8}"
          f"{'RW proj':>8}{'RW':>5}{'play':>6}")
    for l in sorted(legs, key=lambda x: -score_leg(x)["p"]):
        s = score_leg(l)
        rw = l.get("rw_proj")
        rwp = f"{rw:.1f}" if rw is not None else "  -"
        agree = {True: "ok", False: "DIFF", None: "?"}[l.get("rw_agree")]
        play = "yes" if l["name"] in kept_names else ""
        print(f"  {l['name']:16}{l['line']:7.1f}{l['lam']:8.2f}"
              f"{s['side'].upper():>7}{s['p']*100:7.1f}%{rwp:>8}{agree:>5}{play:>6}")

    if not entries:
        print(f"\nNo playable entry: fewer than {MIN_PICKS} independent legs clear "
              "breakeven+margin across distinct games today. Stop.")
        return
    if n < N_PICKS:
        print(f"\n(Only enough edge for a {n}-pick — stepped down from {N_PICKS}.)")

    daily_cap, scale = res["daily_cap"], res["scale"]
    print(f"\nPOWER-PLAY ENTRIES  ({n}-pick, <= {MAX_ENTRIES}/day, "
          f"daily cap ${daily_cap:.0f}{', scaled '+format(scale,'.2f')+'x' if scale<1 else ''})")
    print("  (P_ind = independent; P_cor = day-correlation-adjusted, used for sizing)")
    print(f"  {'#':>2} {'legs':38}{'P_ind':>7}{'P_cor':>7}{'mult':>6}{'EV_cor':>8}{'stake':>8}")
    for i, e in enumerate(entries, 1):
        names = " + ".join(f"{l['name'].split()[-1]} {l['side'][0].upper()}{l['line']}"
                           for l in e["legs"])
        conc = " *same-side" if e["same_side"] else ""
        print(f"  {i:>2} {names:38}{e['p']*100:6.1f}%{e['corr_p']*100:6.1f}%"
              f"{e['mult']:5.1f}x{e['corr_ev']*100:+7.0f}%{e['stake']:8.2f}{conc}")

    om_i = outcome_matrix(entries)
    om = corr_outcome_matrix(entries)
    print(f"\nOUTCOME MATRIX  (staked ${om['staked']:.2f})   [independent -> correlated]")
    print(f"  expected P&L ${om_i['ev']:+.2f} -> ${om['ev']:+.2f}   "
          f"st.dev ${om_i['sd']:.2f} -> ${om['sd']:.2f}   "
          f"P(profit) {om_i['p_profit']*100:.1f}% -> {om['p_profit']*100:.1f}%")
    print(f"  best ${om['best'][1]:+.2f}  worst ${om['worst'][1]:+.2f}")
    if any(e["same_side"] for e in entries):
        print("  * same-side entries sweep together on an extreme K day — higher "
              "win prob, fatter tail (that's the correlation at work).")
    print("\nPAPER ONLY — validate calibration before staking real money.")


if __name__ == "__main__":
    main()
