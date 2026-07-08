"""Platform reference tables: published pick-count multipliers per app.

Each pick'em platform publishes ONE projection line per player and a fixed
multiplier per set size. These tables are kept as REFERENCE CONTEXT for
accuracy analyses: the implied per-selection probability p = (1/M)**(1/n) is
the natural yardstick a stated model probability gets compared against when
judging whether a probability estimate is meaningfully far from 50%.

Nothing in the prediction pipeline reads these values to decide what to
output — every board row is always scored and reported (scoring.py).

*** The published multipliers change and vary by promo; refresh against each
platform's current tables before quoting them in any analysis. Approximate as
of 2026-07. ***
"""
from __future__ import annotations

# Per-platform multiplier by pick count (all selections must land).
PLATFORMS = {
    "prizepicks": {2: 3.0, 3: 5.0, 4: 10.0, 5: 20.0, 6: 37.5},
    "underdog":   {2: 3.0, 3: 6.0, 4: 10.0, 5: 20.0, 6: 35.0},
    "dk_pick6":   {2: 3.0, 3: 6.0, 4: 10.0, 5: 20.0, 6: 35.0},
    "sleeper":    {2: 3.0, 3: 6.0, 4: 10.0, 5: 20.0, 6: 25.0},
    "betr":       {2: 3.0, 3: 6.0, 4: 10.0, 5: 20.0, 6: 35.0},
    "parlayplay": {2: 3.0, 3: 6.0, 4: 10.0, 5: 25.0, 6: 50.0},
}
DEFAULT_PLATFORM = "dk_pick6"


def reference_multiplier(n_picks: int, platform: str = DEFAULT_PLATFORM) -> float:
    """The platform's published multiplier for an n-pick set."""
    table = PLATFORMS.get(platform)
    if table is None:
        raise ValueError(f"unknown platform {platform!r} (have {list(PLATFORMS)})")
    if n_picks not in table:
        raise ValueError(f"{platform}: unsupported pick count {n_picks}")
    return table[n_picks]


def implied_leg_probability(n_picks: int, platform: str = DEFAULT_PLATFORM) -> float:
    """Per-selection probability implied by the multiplier: p = (1/M)**(1/n).

    Reference yardstick only — a model probability near this value is a claim
    of information; a model probability near 50% is a statement of none.
    """
    return (1.0 / reference_multiplier(n_picks, platform)) ** (1.0 / n_picks)


if __name__ == "__main__":  # reference table across platforms
    print(f"  {'picks':>5}", *(f"{p:>12}" for p in PLATFORMS))
    for n in (2, 3, 4, 5):
        cells = []
        for p in PLATFORMS:
            m = PLATFORMS[p][n]
            cells.append(f"{m:.0f}x/{implied_leg_probability(n, platform=p)*100:.1f}%")
        print(f"  {n:>5}", *(f"{c:>12}" for c in cells))
