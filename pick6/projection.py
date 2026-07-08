"""Mean correction for the strikeout projection: shrink mu toward the line.

The shrink coefficient is CONTINUOUS and data-fitted — it is re-estimated as
frozen samples accumulate, and the probabilities it produces are always real
numbers for every row. There are no states here, only a coefficient.

Provenance (calibration/fit_mean.py, run 2026-07-08 on 164 FROZEN pre-game
projections, 6/7-6/13 mlb-edge logs + 7/5 logged rows, settled vs StatsAPI):

  mean bias (actual - mu): -0.36 K, and it grows with mu:
    low-mu  (~3.8): +0.35 K   mid-mu (~5.0): -0.45 K   high-mu (~6.3): -0.97 K
  walk-forward, model-chosen side:
    raw     stated 61.3%  realized 50.4%  gap -10.8 pts  (no information)
    affine  stated 61.3%  realized 53.7%  gap  -7.5 pts
    anchor  stated 54.2%  realized 52.9%  gap  -1.3 pts  <- winner
  high-confidence rows (p>=0.65): raw realized 55.9% vs 73.4% stated — the
  exact 7/5 (-13.5 pts) and 7/7 (-25 pts) live drift, reproduced out-of-sample.

The anchor MLE is s = 0.00: on this sample the raw projection's disagreement
with the published line carries no predictive information, so every strikeout
probability honestly sits near 50-55%. The displayed point prediction remains
the raw projection; the probability reflects what the data supports. The
coefficient rises exactly when frozen samples support it: re-run
calibration/fit_mean.py as data/slates/ archives accumulate. Never fit on
/v2/slate re-projections of past dates (outcome leakage — see
pick6/dispersion.py).
"""
from __future__ import annotations

SHRINK_TO_LINE_S = 0.00


def corrected_mu(market: str, mu: float, line: float | None) -> float:
    """Anchored mean used for probability computation. Strikeouts shrink toward
    the line by the fitted s; other markets pass through (their probability
    ceiling is markets.p_cap)."""
    if market == "strikeouts" and line is not None:
        return line + SHRINK_TO_LINE_S * (mu - line)
    return mu
