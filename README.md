# Fantasy — MLB prop projection system

Daily numeric projections for MLB player props (pitcher strikeouts + batter
hits / total bases / home runs / RBI / runs), scored against the prop lines
published by pick'em platforms (PrizePicks, DK Pick6, Underdog, …), with an
automatically graded accuracy record. Live at
**https://fantasy.perfecthold.online** (rebuilt hourly).

The system always outputs real numbers for every matched board row:

| output | meaning |
|---|---|
| `predicted` | raw model projection (e.g. 6.83 strikeouts) |
| `P(more)` / `P(less)` | probability the actual lands above/below the published line |
| `lean` | the side of the line with the higher probability |
| `P` | that side's probability — the model's stated confidence |

Nothing is filtered, suppressed, or toggled. Rows are ordered by confidence;
low-information probabilities near 50% are shown as exactly that.

## How the numbers are made

1. **Board capture** — `pick6/scrape_firecrawl.py` pulls the day's published
   lines (PrizePicks JSON:API via Firecrawl) into `data/boards/<date>.csv`,
   with a freshness guard against yesterday's board.
2. **Projections** —
   - *Pitcher strikeouts*: `expected_ks` from the strike/mlb-edge slate
     (`pick6/feed.py`).
   - *Batter markets*: StatsAPI season rates × projected plate appearances,
     adjusted for opposing starter and platoon split (`pick6/batter_feed.py`).
   - *Consensus (candidate source)*: FantasyPros daily projections are frozen
     every day (`pick6/consensus.py`) so their predictive value can be
     measured before they feed anything.
3. **Probabilities** (`pick6/scoring.py`) —
   - Strikeouts: Negative-Binomial with dispersion fitted on settled starts
     (`pick6/dispersion.py`, r = 16.6, PIT-validated on frozen data).
   - The strikeout **mean is anchored to the published line** by a
     continuous shrink coefficient (`pick6/projection.py`). Fitted 2026-07-08
     on 164 frozen pre-game projections: s = 0.00 — the raw projection's
     disagreement with the line showed no walk-forward information, so stated
     probabilities honestly sit near 50% until data earns the coefficient up.
   - Markets without a fitted dispersion carry a 70% probability ceiling
     (`pick6/markets.py`).
   - RotoWire's free projection is attached to each row as an independent
     second opinion (`pick6/crosscheck.py`) — displayed, never a filter.
4. **Record & grading** — every scored row is logged once per day
   (`pick6/log_predictions.py` → `data/predictions_log.csv`, plus a frozen
   `_scored.json` snapshot so the dashboard's numbers never drift after
   logging). `pick6/grade.py` fills actuals from MLB StatsAPI final boxscores
   and prints hit rate + calibration (stated vs realized, pitcher/batter
   split, probability buckets).

## Calibration workflow (all fits on FROZEN data only)

- `pick6/archive_slate.py` — freezes each day's slate projections at
  generation time. **Never fit on `/v2/slate` re-projections of past dates**:
  the API recomputes with current season stats, leaking outcomes into the fit
  (it once drove the dispersion to r≈500, i.e. fake-Poisson).
- `calibration/fit_mean.py` — fits/validates the mean corrections
  (affine and line-anchor) walk-forward; source of the shrink coefficient.
- `calibration/refit_dispersion.py` + `walk_forward.py` — re-fit/validate the
  NB dispersion with held-out PIT coverage.
- `calibration/backtest.py`, `compare.py`, `correlation.py`, `nb.py` —
  reliability references (NB vs Poisson, day-factor estimation).
- `pick6/correlation.py` — shared day-factor model (τ ≈ 0.08): joint
  probability of several leans landing together, correlation-corrected.
- `pick6/config.py` — platform reference tables (published multipliers and
  the per-selection probability they imply); context for analyses only,
  never an input to scoring.

## Ops

- VPS cron (`deploy/cron_daily.sh`) runs hourly: grade → freeze slate +
  consensus → capture board → log predictions → rebuild + publish the
  dashboard (`web/build_site.py`). All steps are poll-safe no-ops once done.
- Runtime state (`data/predictions_log.csv`, boards, slates) is gitignored
  and owned by the host that runs the cron; `data/pick6_entries.csv` is the
  frozen legacy per-row history, migrated into the log by `grade.py`.
- A pre-commit hook (`.githooks/pre-commit`, enable with
  `git config core.hooksPath .githooks`) blocks reintroduction of the
  legacy terminology this repo removed on 2026-07-08 (see History).

## History

Until 2026-07-08 the repo also contained a hypothetical multi-pick
set-builder and a $-denominated tracking loop. That machinery was removed:
the projection quality is the product, and it is measured in hit rate and
calibration, not currency. See git history for the removed modules.
