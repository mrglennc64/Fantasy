"""Phase 4: day-level correlation between legs.

Settled data shows a real "K environment" factor: a whole slate's strikeouts run
high or low together (7/2/2026 came in at 0.69x expected). After removing
sampling noise, the latent day factor has sd tau ~= 0.08 (calibration/
correlation.py). Model it as a shared multiplier D on every leg's projection:

    actual_i ~ NB(lambda_i * D),   D ~ Normal(mean 1, sd tau), floored > 0

D has mean 1 so each leg's MARGINAL stays the calibrated NB value; only the
dependence changes. Consequences for a power play (ALL legs must hit):
  - all-same-side (e.g. all Unders): POSITIVELY correlated -> they sweep together
    on a low-K day, so true P(all hit) is HIGHER than the independent product,
    but with a fatter losing tail.
  - mixed Over/Under: the factor works against you -> true P(all hit) is LOWER.
The independent product (sim.build_entries) is wrong in both directions; this
module gives the corrected joint probability and P&L distribution.
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
    """P(leg's chosen side wins | day factor D)."""
    market = leg.get("market", "strikeouts")
    pm = p_over(market, leg["lam"] * D, leg["line"])
    return pm if leg["side"] == "more" else 1.0 - pm


def joint_p_all(legs: list[dict]) -> float:
    """Correlation-adjusted P(all legs hit) = E_D[ prod_i P(leg_i | D) ]."""
    total = 0.0
    for D, w in _GRID:
        prod = 1.0
        for l in legs:
            prod *= p_leg_given_D(l, D)
        total += w * prod
    return total


def same_side(legs: list[dict]) -> bool:
    return len({l["side"] for l in legs}) == 1


def corr_outcome_matrix(entries: list[dict]) -> dict:
    """Exact P&L distribution integrating over the shared day factor D (legs are
    conditionally independent given D). Mirrors sim.outcome_matrix but correlated.
    """
    leg_ids = sorted({id(l) for e in entries for l in e["legs"]}, key=lambda x: x)
    idx = {lid: i for i, lid in enumerate(leg_ids)}
    legs_by_i = {}
    for e in entries:
        for l in e["legs"]:
            legs_by_i[idx[id(l)]] = l
    L = len(leg_ids)

    agg = {}  # pnl -> prob   (and running moments)
    ev = 0.0
    by_n = {}
    for D, wD in _GRID:
        cond_p = {i: p_leg_given_D(legs_by_i[i], D) for i in range(L)}
        for mask in range(1 << L):
            prob = wD
            won = [False] * L
            for i in range(L):
                hit = (mask >> i) & 1
                won[i] = bool(hit)
                prob *= cond_p[i] if hit else (1 - cond_p[i])
            pnl, nwon = 0.0, 0
            for e in entries:
                if all(won[idx[id(l)]] for l in e["legs"]):
                    pnl += e["stake"] * (e["mult"] - 1); nwon += 1
                else:
                    pnl -= e["stake"]
            agg[round(pnl, 4)] = agg.get(round(pnl, 4), 0.0) + prob
            ev += prob * pnl
            a = by_n.setdefault(nwon, [0.0, 0.0]); a[0] += prob; a[1] += prob * pnl
    var = sum(p * (pnl - ev) ** 2 for pnl, p in agg.items())
    p_profit = sum(p for pnl, p in agg.items() if pnl > 0)
    staked = sum(e["stake"] for e in entries)
    best = max(agg.items(), key=lambda t: t[0])
    worst = min(agg.items(), key=lambda t: t[0])
    return {"ev": ev, "sd": var ** 0.5, "p_profit": p_profit, "staked": staked,
            "best": (best[1], best[0]), "worst": (worst[1], worst[0]), "by_n": by_n}
