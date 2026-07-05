"""Estimate the latent day-level "K environment" factor for Phase 4.

A whole slate's strikeouts run high/low together. Model actual_i ~ NB(lambda_i*D)
with a shared daily D. The per-day MLE of D (Poisson) is sum(actual)/sum(exp).
The raw spread of D across days overstates the true factor because each day has
only ~25 starts (sampling noise), so we subtract the expected per-day sampling
variance (NB: Var = lambda*(1+lambda/r)) to recover the latent tau.

    python correlation.py [live_settled.csv]

Feeds pick6/correlation.py DAY_FACTOR_SD. Re-run as the sample grows.
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict

from nb import fit_dispersion

DEFAULT = r"C:\strike-data\features\live_settled.csv"


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    rows = [(r["date"], float(r["expected_ks"]), float(r["actual_ks"]))
            for r in csv.DictReader(open(path)) if r.get("expected_ks")]
    r = fit_dispersion([(l, y) for _, l, y in rows])

    byday = defaultdict(list)
    for d, l, y in rows:
        byday[d].append((l, y))

    Ds, samp, W = [], [], 0
    print("date        starts  sumExp  sumAct    D")
    for d in sorted(byday):
        starts = byday[d]
        sumL = sum(l for l, _ in starts); sumY = sum(y for _, y in starts)
        D = sumY / sumL; n = len(starts); W += n
        Ds.append((D, n))
        samp.append(sum(l * (1 + l / r) for l, _ in starts) / sumL ** 2)
        print(f"{d}   {n:5}   {sumL:6.1f}  {sumY:6.0f}   {D:.3f}")

    mean = sum(D * n for D, n in Ds) / W
    obs = sum(n * (D - mean) ** 2 for D, n in Ds) / W
    msamp = sum(samp) / len(samp)
    latent = max(0.0, obs - msamp)
    print(f"\nNB r={r:.1f}   weighted mean D={mean:.3f}")
    print(f"observed Var(D)={obs:.5f} (sd {obs**0.5:.3f})   "
          f"sampling Var={msamp:.5f} (sd {msamp**0.5:.3f})")
    print(f"LATENT day-factor tau = {latent**0.5:.3f}  "
          f"-> set pick6/correlation.py DAY_FACTOR_SD accordingly")


if __name__ == "__main__":
    main()
