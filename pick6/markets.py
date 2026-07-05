"""Market registry: per-prop distribution + dispersion so the same machinery
scores strikeouts, hits, total bases, home runs, etc. — not just Ks.

Each market maps a projection (mean mu) to P(Over line). Strikeouts use the
Negative-Binomial with the dispersion fitted in Phase 2. Other markets are
scaffolded with a documented distribution; their dispersion still needs fitting
on real data (calibration/fit_market.py, TODO) and — crucially — a PROJECTION
SOURCE, since strike/mlb-edge only projects strikeouts. Until a market has both
a fitted dispersion and a mu source, it is declared but not production-ready.
"""
from __future__ import annotations

import math

from dispersion import DISPERSION_R

_EPS = 1e-9


def _nb_pmf(k, mu, r):
    mu = max(mu, _EPS)
    return math.exp(math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1)
                    + r * math.log(r / (r + mu)) + k * math.log(mu / (r + mu)))


def _pois_pmf(k, mu):
    mu = max(mu, _EPS)
    return math.exp(-mu) * mu ** k / math.factorial(k)


# dist: "nb" needs r; "poisson" for rare counts. ready=True once dispersion is
# fitted AND a mu (projection) source is wired.
MARKETS = {
    "strikeouts":      {"dist": "nb", "r": DISPERSION_R, "ready": True,
                        "mu_source": "mlb-edge /v2/slate expected_ks"},
    "hits":            {"dist": "nb", "r": 12.0, "ready": False, "mu_source": None},
    "total_bases":     {"dist": "nb", "r": 6.0,  "ready": False, "mu_source": None},
    "hits_runs_rbis":  {"dist": "nb", "r": 8.0,  "ready": False, "mu_source": None},
    "home_runs":       {"dist": "poisson",       "ready": False, "mu_source": None},
    "walks":           {"dist": "poisson",       "ready": False, "mu_source": None},
}


def is_ready(market: str) -> bool:
    return MARKETS.get(market, {}).get("ready", False)


def p_over(market: str, mu: float, line: float) -> float:
    """P(stat > line) for a half-integer line, per the market's distribution.

    Over wins on stat >= ceil(line); e.g. line 5.5 -> Over needs >= 6.
    """
    spec = MARKETS.get(market)
    if spec is None:
        raise ValueError(f"unknown market {market!r}")
    need = math.ceil(line)
    if spec["dist"] == "nb":
        cdf = sum(_nb_pmf(i, mu, spec["r"]) for i in range(need))
    else:
        cdf = sum(_pois_pmf(i, mu) for i in range(need))
    return max(0.0, 1.0 - cdf)
