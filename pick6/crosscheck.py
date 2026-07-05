"""Phase 3 second-opinion cross-check via RotoWire's free projections endpoint.

    GET rotowire.com/betting/mlb/tables/all-bets-props-plus-proj.php?prop={k|tb|runs|er}

Each record has `betSubject` (player) and `proj` (RotoWire's projection). We
compare the side RotoWire's proj implies (vs the DK line) to the side our model
implies, and gate a leg unless they AGREE. This is the cheap guard against a
single over-projected leg sinking a whole power play (see the 7/4 Imanaga miss).

RotoWire exposes only k (strikeouts), tb (total bases), runs, er (earned runs)
for free; hits/HR/RBI are paywalled -> those markets get no RotoWire opinion
(cross-check returns None; wire a free baseline in crosscheck_baseline later).
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

    rw_agree: True (RotoWire agrees with the leg's model side), False (disagrees),
    or None (RotoWire has no free projection for this player/market).
    Requires each leg to already carry a model-chosen 'side'.
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


def gate(legs: list[dict], require_agree: bool = True) -> list[dict]:
    """Drop legs RotoWire explicitly disagrees with. Legs with no RotoWire
    opinion (rw_agree is None) pass through (flagged 'unconfirmed')."""
    if not require_agree:
        return legs
    return [l for l in legs if l.get("rw_agree") is not False]
