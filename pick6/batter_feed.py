"""Free batter projection baseline from MLB StatsAPI season rates.

Unlocks the batter Pick6 markets (hits, total bases, home runs, RBI, runs) that
RotoWire paywalls. For each batter: season per-AB / per-PA rates x projected
plate appearances -> lambda for the market's distribution (markets.py).

    lambda_hits = (H/AB) * expected_AB ,  lambda_hr = (HR/AB) * expected_AB
    lambda_tb   = (TB/AB) * expected_AB
    lambda_rbi  = (RBI/PA) * expected_PA ,  lambda_runs = (R/PA) * expected_PA

*** BASELINE ONLY, LOWER CONFIDENCE than the strikeout model. This is
MATCHUP-NEUTRAL: it ignores the opposing pitcher, park, and platoon. Treat it as
a sanity floor / second opinion, not a sharp edge. RotoWire's free tb/runs (which
DO price the matchup) cross-check these two; hits/HR/RBI stay unconfirmed. ***
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

from feed import norm

# Typical plate appearances by batting-order slot (1-9); default for unknown slot.
PA_BY_SLOT = {1: 4.6, 2: 4.5, 3: 4.4, 4: 4.3, 5: 4.1, 6: 4.0, 7: 3.9, 8: 3.8, 9: 3.7}
DEFAULT_PA = 4.2

# our market -> how to project it: (rate stat, denom stat, denom kind)
_RECIPE = {
    "hits":        ("hits", "atBats", "ab"),
    "total_bases": ("totalBases", "atBats", "ab"),
    "home_runs":   ("homeRuns", "atBats", "ab"),
    "rbi":         ("rbi", "plateAppearances", "pa"),
    "runs":        ("runs", "plateAppearances", "pa"),
}

_id_cache: dict[str, int | None] = {}
_stat_cache: dict[tuple, dict | None] = {}


def _get(url):
    with urllib.request.urlopen(url, timeout=40) as r:
        return json.load(r)


def player_id(name: str) -> int | None:
    key = norm(name)
    if key in _id_cache:
        return _id_cache[key]
    try:
        s = _get("https://statsapi.mlb.com/api/v1/people/search?names="
                 + urllib.parse.quote(name))
        ppl = s.get("people", [])
        # prefer an exact accent-folded name match
        pid = next((p["id"] for p in ppl if norm(p.get("fullName", "")) == key),
                   ppl[0]["id"] if ppl else None)
    except Exception:
        pid = None
    _id_cache[key] = pid
    return pid


def season_hitting(pid: int, season: int) -> dict | None:
    ck = (pid, season)
    if ck in _stat_cache:
        return _stat_cache[ck]
    try:
        st = _get(f"https://statsapi.mlb.com/api/v1/people/{pid}/stats"
                  f"?stats=season&group=hitting&season={season}")
        splits = st.get("stats", [{}])[0].get("splits", [])
        stat = splits[0]["stat"] if splits else None
    except Exception:
        stat = None
    _stat_cache[ck] = stat
    return stat


def project(name: str, market: str, season: int, slot: int | None = None) -> float | None:
    """lambda for a batter market, or None if unavailable / insufficient sample."""
    recipe = _RECIPE.get(market)
    if recipe is None:
        return None
    pid = player_id(name)
    if pid is None:
        return None
    stat = season_hitting(pid, season)
    if not stat:
        return None
    num_key, den_key, kind = recipe
    ab = float(stat.get("atBats", 0) or 0)
    pa = float(stat.get("plateAppearances", 0) or 0)
    if pa < 30:  # too small to trust a rate
        return None
    exp_pa = PA_BY_SLOT.get(slot, DEFAULT_PA)
    num = float(stat.get(num_key, 0) or 0)
    if kind == "ab":
        if ab <= 0:
            return None
        exp_ab = exp_pa * (ab / pa)          # expected at-bats this game
        return (num / ab) * exp_ab
    return (num / pa) * exp_pa               # per-PA markets (rbi, runs)
