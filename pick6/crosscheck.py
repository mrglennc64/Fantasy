"""Second-opinion annotation via RotoWire's free projections endpoint.

Each record has `betSubject` (player) and `proj` (RotoWire's projection — the
field names are RotoWire's, from their URL/API shape). We compare the side of
the line RotoWire's projection implies to the side our model leans, and attach
the agreement flag to the row. ANNOTATION ONLY: every row is still scored and
reported; the flag is displayed next to the numbers so disagreement is visible,
never used to drop output.

RotoWire exposes only k (strikeouts), tb (total bases), runs, er (earned runs)
for free; hits/HR/RBI are paywalled -> those markets get no RotoWire opinion
(annotation is None for them).
"""
from __future__ import annotations

import json
import urllib.request

from feed import norm

ENDPOINT = "https://www.rotowire.com/betting/mlb/tables/all-bets-props-plus-proj.php?prop={prop}"

# our market name -> RotoWire prop code (None = not offered free)
RW_PROP = {
    "strikeouts": "k",
    "total_bases": "tb",
    "runs": "runs",
    "earned_runs": "er",
    "hits": None,
    "home_runs": None,
    "hits_runs_rbis": None,
}

_cache: dict[str, dict[str, float]] = {}


def rotowire_projections(market: str) -> dict[str, float]:
    """norm(player) -> RotoWire proj for a market (cached per process)."""
    prop = RW_PROP.get(market)
    if not prop:
        return {}
    if prop in _cache:
        return _cache[prop]
    req = urllib.request.Request(
        ENDPOINT.format(prop=prop),
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            data = json.load(r)
    except Exception:
        _cache[prop] = {}
        return {}
    rows = data if isinstance(data, list) else data.get("data", [])
    out = {}
    for rec in rows:
        try:
            out[norm(rec["betSubject"])] = float(rec["proj"])
        except (KeyError, TypeError, ValueError):
            continue
    _cache[prop] = out
    return out


def _side(proj: float, line: float) -> str:
    return "more" if proj > line else "less"


def annotate(legs: list[dict]) -> None:
    """Attach rw_proj / rw_side / rw_agree to each leg (in place).

    rw_agree: True (RotoWire leans the same side of the line), False (leans the
    other way), or None (no free RotoWire projection for this player/market).
    Requires each leg to already carry a model 'side'.
    """
    projs_by_market: dict[str, dict[str, float]] = {}
    for l in legs:
        market = l.get("market", "strikeouts")
        projs = projs_by_market.setdefault(market, rotowire_projections(market))
        p = projs.get(norm(l["name"]))
        if p is None:
            l["rw_proj"], l["rw_side"], l["rw_agree"] = None, None, None
        else:
            rs = _side(p, l["line"])
            l["rw_proj"], l["rw_side"] = p, rs
            l["rw_agree"] = (rs == l.get("side"))
