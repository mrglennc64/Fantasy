"""Day-level correlation between legs: the shared "K environment" factor.

Settled data shows a real slate-wide factor: a whole day's strikeouts run high
or low together (7/2/2026 came in at 0.69x expected). After removing sampling
noise, the latent day factor has sd tau ~= 0.08 (calibration/correlation.py).
Model it as a shared multiplier D on every leg's projection:

    actual_i ~ NB(lambda_i * D),   D ~ Normal(mean 1, sd tau), floored > 0

D has mean 1 so each leg's MARGINAL probability stays the fitted NB value; only
the dependence between legs changes. Consequences for a set of leans considered
jointly:
  - all-same-side (e.g. all Less): POSITIVELY correlated — they land together
    on a low-K day, so the true joint probability is HIGHER than the
    independent product, with more all-or-nothing spread.
  - mixed More/Less: the shared factor works against joint agreement — the
    true joint probability is LOWER than the independent product.
This module gives the corrected joint probability; the independent product is
wrong in both directions.
"""
from __future__ import annotations

import math

from markets import p_over

# Latent day-factor sd, estimated on live_settled.csv (variance decomposition
# removing per-start NB sampling noise). Re-estimate as the sample grows.
DAY_FACTOR_SD = 0.081


def _grid(n=15):
    """Normal(mean=1, sd=tau) quadrature nodes/weights, floored positive."""
    tau = DAY_FACTOR_SD
    lo, hi = max(1e-3, 1 - 4 * tau), 1 + 4 * tau
    step = (hi - lo) / (n - 1)
    nodes, wts = [], []
    for i in range(n):
        d = lo + i * step
        w = math.exp(-0.5 * ((d - 1) / tau) ** 2)
        nodes.append(d); wts.append(w)
    s = sum(wts)
    return list(zip(nodes, [w / s for w in wts]))


_GRID = _grid()


def p_leg_given_D(leg: dict, D: float) -> float:
    """P(leg's leaned side lands | day factor D)."""
    market = leg.get("market", "strikeouts")
    pm = p_over(market, leg["lam"] * D, leg["line"])
    return pm if leg["side"] == "more" else 1.0 - pm


def joint_p_all(legs: list[dict]) -> float:
    """Correlation-adjusted P(all leans land) = E_D[ prod_i P(leg_i | D) ]."""
    total = 0.0
    for D, w in _GRID:
        prod = 1.0
        for l in legs:
            prod *= p_leg_given_D(l, D)
        total += w * prod
    return total


def same_side(legs: list[dict]) -> bool:
    return len({l["side"] for l in legs}) == 1
