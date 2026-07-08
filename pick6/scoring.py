"""Leg scoring: numeric predictions for every board row.

For each (player, market, line) the scorer emits real numbers, always:
  predicted   the raw model projection (mean of the market's distribution)
  p_more      P(stat > line) under the market's distribution
  p_less      1 - p_more
  side        which side of the line the model leans ("more"/"less")
  p           the leaned side's probability (confidence)

Strikeout probabilities use a Negative-Binomial with the dispersion fitted on
settled data (pick6/dispersion.py) and the mean anchored per pick6/projection.py
(a continuous, data-fitted shrink coefficient — see that module's provenance).
Other markets use the distribution declared in markets.py, with a probability
ceiling (markets.p_cap) where no dispersion has been fitted yet.

There is no qualification threshold here: every row gets scored and reported.
Rankings order by confidence (distance from 50%); they never suppress output.
"""
from __future__ import annotations

import math

from dispersion import DISPERSION_R
from markets import p_cap, p_over
from projection import corrected_mu

_EPS = 1e-9


def nb_pmf(k: int, mu: float, r: float = DISPERSION_R) -> float:
    mu = max(mu, _EPS)
    logp = (math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1)
            + r * math.log(r / (r + mu)) + k * math.log(mu / (r + mu)))
    return math.exp(logp)


def p_more(lam: float, line: float, r: float = DISPERSION_R) -> float:
    """P(strikeouts > line) for a half-integer line under NB(mean=lam, size=r).

    More wins on K >= ceil(line); e.g. line 5.5 -> More needs K >= 6.
    """
    need = math.ceil(line)
    return max(0.0, 1.0 - sum(nb_pmf(i, lam, r) for i in range(need)))


def score_leg(leg: dict) -> dict:
    """leg in: name, game, line, lam, market. Out: leg + predicted / p_more /
    p_less / side / p — real numbers for every row, no exceptions."""
    market = leg.get("market", "strikeouts")
    # Probabilities come from the anchored mean (pick6/projection.py); the
    # displayed point prediction stays the raw projection — both are real
    # numbers, serving different jobs (estimate vs uncertainty).
    mu = corrected_mu(market, leg["lam"], leg["line"])
    pm = p_over(market, mu, leg["line"])
    side, p = ("more", pm) if pm >= 0.5 else ("less", 1.0 - pm)
    cap = p_cap(market)
    if cap is not None and p > cap:
        p = cap                      # un-fitted dispersion: cap the confidence
        pm = cap if side == "more" else 1.0 - cap
    return {**leg, "predicted": leg["lam"], "p_more": pm, "p_less": 1.0 - pm,
            "side": side, "p": p}


def rank_by_confidence(legs: list[dict]) -> list[dict]:
    """All legs scored, ordered by confidence. Nothing is dropped."""
    return sorted((score_leg(l) for l in legs), key=lambda l: l["p"], reverse=True)
