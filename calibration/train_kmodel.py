"""Train an OWNED strikeout projection from per-start gamelogs — Phase B.

    python train_kmodel.py

Trains on the 2024-2026 starter gamelogs (per-start K, BF, pitches, opponent
K%), predicting each start's strikeouts from information available BEFORE
that start:

  roll_kbf_3 / roll_kbf_10  K per batter faced over the last 3 / 10 starts,
                            shrunk toward league K/BF by a pseudo-BF prior
  prior_kbf                 career-to-date K/BF (same shrink)
  roll_bf_3                 batters faced over the last 3 starts (the leash)
  opp_k_pct                 opposing team strikeout rate
  is_home, rest_days        schedule context

Model: Poisson GLM (log link) — deliberately simple and portable: the fitted
coefficients can be served in pick6/ with no ML dependency. A gradient-boosted
alternative is only worth adding if it beats the GLM on the same time split.

Evaluation is time-ordered (train strictly before the validation window) and
the bar is explicit: does the new projection carry information BEYOND the
published line? That is measured exactly like production — fit the anchor
coefficient s for model mu on starts with real logged lines (mlb-edge
June log + our frozen boards). s > 0 with a better log-loss = skill; s ~ 0 =
back to feature work. The line is the benchmark, never an input.
"""
from __future__ import annotations

import csv
import math
import os
import sys
from collections import defaultdict
from datetime import date as _date

import numpy as np
from sklearn.linear_model import PoissonRegressor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pick6"))
from feed import norm                                        # noqa: E402
from nb import fit_dispersion                                # noqa: E402
from fit_mean import fit_anchor, anchor_ci, nb_logpmf        # noqa: E402

MLB = r"C:\Users\carin\OneDrive\Dokument\stike\mlb-edge\data"
LOGS = os.path.join(MLB, "all_starters_gamelogs_2024_2026.csv")
PRED = os.path.join(MLB, "exports", "vps", "predictions.csv")

VAL_FROM = "2026-05-01"     # train strictly before, validate from here
PRIOR_BF = 150.0            # shrink pseudo-BF for rolling K/BF rates
FEATURES = ["roll_kbf_3", "roll_kbf_10", "prior_kbf", "roll_bf_3",
            "opp_k_pct", "is_home", "rest_days"]


def load_starts() -> list[dict]:
    rows = []
    for r in csv.DictReader(open(LOGS, encoding="utf-8")):
        try:
            rows.append({
                "date": r["date"], "pitcher": r["pitcher"],
                "pid": r["pitcher_id"], "K": int(float(r["K"])),
                "BF": float(r["BF"]), "pitches": float(r["pitches"] or 0),
                "opp_k_pct": float(r["opp_k_pct"]),
                "is_home": 1.0 if r["is_home"] == "True" else 0.0,
            })
        except (KeyError, ValueError):
            continue
    rows.sort(key=lambda r: r["date"])
    return rows


def build_features(rows: list[dict]) -> list[dict]:
    """Attach strictly-prior features to each start (per pitcher, in order)."""
    lg_kbf = 0.22  # placeholder; replaced by running league rate below
    tot_k = tot_bf = 0.0
    hist: dict[str, list[dict]] = defaultdict(list)
    out = []
    for r in rows:
        h = hist[r["pid"]]

        def _kbf(last: int | None) -> float:
            hh = h if last is None else h[-last:]
            k = sum(x["K"] for x in hh)
            bf = sum(x["BF"] for x in hh)
            base = tot_k / tot_bf if tot_bf > 500 else lg_kbf
            return (k + PRIOR_BF * base) / (bf + PRIOR_BF)

        if len(h) >= 2:  # need some history to be a real projection
            prev = h[-1]
            rest = (_date.fromisoformat(r["date"])
                    - _date.fromisoformat(prev["date"])).days
            out.append({**r,
                        "roll_kbf_3": _kbf(3), "roll_kbf_10": _kbf(10),
                        "prior_kbf": _kbf(None),
                        "roll_bf_3": sum(x["BF"] for x in h[-3:]) / min(len(h), 3),
                        "rest_days": float(min(max(rest, 3), 12))})
        h.append(r)
        tot_k += r["K"]
        tot_bf += r["BF"]
    return out


def matrix(rows: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    X = np.array([[r[f] for f in FEATURES] for r in rows])
    y = np.array([r["K"] for r in rows], dtype=float)
    return X, y


def load_lines() -> dict[tuple[str, str], dict]:
    """(date, norm(pitcher)) -> {line, mu_edge} from the June pre-game
    mlb-edge log (real published lines, frozen before the games)."""
    out = {}
    if not os.path.exists(PRED):
        return out
    for r in csv.DictReader(open(PRED, encoding="utf-8")):
        if not r.get("expected_ks") or not r.get("line"):
            continue
        key = (r["date"], norm(r["pitcher"]))
        if key not in out or r.get("bookmaker") == "draftkings":
            out[key] = {"line": float(r["line"]), "mu_edge": float(r["expected_ks"])}
    return out


def main() -> None:
    rows = build_features(load_starts())
    train = [r for r in rows if r["date"] < VAL_FROM]
    val = [r for r in rows if r["date"] >= VAL_FROM]
    print(f"K-MODEL TRAINING  {len(rows)} usable starts "
          f"({len(train)} train < {VAL_FROM} <= {len(val)} validate)")

    Xt, yt = matrix(train)
    mean, sd = Xt.mean(0), Xt.std(0) + 1e-9
    model = PoissonRegressor(alpha=1e-4, max_iter=2000)
    model.fit((Xt - mean) / sd, yt)

    Xv, yv = matrix(val)
    mu_v = model.predict((Xv - mean) / sd)
    mae = float(np.abs(mu_v - yv).mean())
    bias = float((yv - mu_v).mean())
    print(f"\nheld-out point accuracy: MAE {mae:.2f} K   bias {bias:+.2f} K")
    for f, c in sorted(zip(FEATURES, model.coef_), key=lambda t: -abs(t[1])):
        print(f"  {f:12} {c:+.3f}")

    # dispersion of the new model's residuals (for probability statements)
    r_new = fit_dispersion([(float(m), int(a)) for m, a in zip(mu_v, yv)])
    print(f"residual NB dispersion on validation: r = {r_new:.1f}")

    # ---- the bar: information beyond the published line ---------------------
    lines = load_lines()
    joined = []
    for r, mu in zip(val, mu_v):
        rec = lines.get((r["date"], norm(r["pitcher"])))
        if rec:
            joined.append({"date": r["date"], "mu": float(mu),
                           "line": rec["line"], "mu_edge": rec["mu_edge"],
                           "actual": r["K"]})
    if len(joined) < 40:
        print(f"\nonly {len(joined)} validation starts have real logged lines — "
              "not enough for the anchor test; extend the line archive first.")
        return

    print(f"\nANCHOR TEST vs real lines (n={len(joined)}, frozen June log)")
    for tag, key in (("new model", "mu"), ("expected_ks", "mu_edge")):
        pairs = [{"mu": j[key], "line": j["line"], "actual": j["actual"],
                  "date": j["date"]} for j in joined]
        s = fit_anchor(pairs)
        lo, hi = anchor_ci(pairs)
        # side accuracy at the line under NB(mu shrunk by fitted s)
        hit = tot = 0
        for p in pairs:
            mu_s = p["line"] + s * (p["mu"] - p["line"])
            pm = 1.0 - sum(math.exp(nb_logpmf(i, mu_s, r_new))
                           for i in range(math.ceil(p["line"])))
            side_more = pm >= 0.5
            if p["actual"] == p["line"]:
                continue
            tot += 1
            hit += int(side_more == (p["actual"] > p["line"]))
        print(f"  {tag:12} fitted s = {s:.2f}  CI [{lo:.2f}, {hi:.2f}]"
              f"   side accuracy at fitted s: {hit}/{tot} ({hit/max(tot,1)*100:.1f}%)")
    print("\n=> ship only if the new model's s CI clears zero and side accuracy"
          "\n   beats expected_ks. Otherwise: more features, not more hope.")


if __name__ == "__main__":
    main()
