"""Fitted strikeout dispersion for the Negative-Binomial side model.

Provenance: MLE fit (calibration/nb.py fit_dispersion) on 147 settled starts in
live_settled.csv (6/28-7/3, 2026). Head-to-head reliability (calibration/
compare.py): NegBinom cut the weighted mean |gap| from 3.2 -> 1.6 pts and fixed
the 60-65% band (Poisson -6.9 pts overconfident -> NB +0.4 pts) that Pick6 legs
live in. Re-fit as the settled sample grows (target n>=400).
"""
# NB size/dispersion. Var(Y) = mu * (1 + mu/r); r -> inf recovers Poisson.
DISPERSION_R = 16.6
