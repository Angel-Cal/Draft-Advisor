# DraftBot Decision Log

The *why* behind choices that mattered. `STATUS.md` says where the project is, git history says what changed;
this says why we chose it and what we rejected.

**Add an entry only if** the decision (1) rejected a plausible alternative, (2) changed the results, or (3) you would
probably forget the reason in three months. Keep it to 3–5 lines: decision, reason with the number that justified it,
alternative rejected, pointer to the commit or test. Newest first. Do not log routine choices.

Standing rules (apply to every entry below):
- A feature is accepted only if it beats a 10-seed baseline *and* a random-noise control of the same size; anything
  within noise is dropped. Gaps under ~0.03 top-150 Spearman are not detectable with 5 test seasons.
- Ask before making a design decision that was not specified.

---

## 2026-10-21 — OL information is not worth modeling for model gains
**Decision:** do not build an offensive-line rating (plus-minus or otherwise); no OL features are in the model.
**Why:** continuity of last year's top-5 OL (returning starters, snap continuity, incoming starters) and prior-season
adjusted line yards / sack rate were null at every position (RB −0.002 to −0.009, QB −0.015 to +0.005), and did not
predict next-season team rush EPA, sack rate or pass EPA (t < 1.1, n = 288). An oracle using the line's actual
same-season result (which leaks, so flatters) moved RB top-150 by only +0.006 and QB by +0.017: if knowing the line's
result barely helps, forecasting it cannot.
**Rejected:** market/pedigree rating (contract value, draft pick) — the user's reasoning: OL is scarce, so contracts
measure a team's desperation, not the player. Scraping ESPN's pass/run block win rates — Disney terms prohibit
scraping and compiling datasets, no download exists. **See:** `src/features/advanced.py`, `tests/test_ol_*.py`.

## 2026-10-21 — Process features, wired per position
**Decision:** each position gets only the feature groups that passed ablation (`src/features/registry.py`). RB:
week-1 depth-chart tier + expected fantasy points. WR: depth tier + share of team pass/rush plays on the field. TE:
expected fantasy points + Next Gen Stats receiving. QB: none.
**Why:** RB depth + xfp +0.056 top-150 (0.482 → 0.538, RMSE 62.3 → 59.0); TE xfp + NGS +0.052 (0.360 → 0.411); WR
depth + role gains only +0.008 in the top-150 but +0.041 over all WRs and −4.7% RMSE, with no metric worse.
Team EPA/success rate was null as expected. **Rejected:** PFF grades (paid, license-restricted, not reproducible in a
public repo); PFR advanced stats (only 2018+, halves usable training rows); participation `route` (mostly empty,
approximated by on-field share).

## 2026-10-21 — QB depth-chart tier declined
**Decision:** the QB model does not use the week-1 depth chart.
**Why:** it improves starter-vs-backup AUC (0.818 → 0.857) and RMSE (−10%), but hurts the ordering of QBs who actually
started (0.443 → 0.426), the top-12 hit rate (0.587 → 0.553) and top-150 Spearman (0.310 → 0.261, 10 of 10 seeds worse).
The advisor mostly orders starters, so ordering wins. The user deferred to this recommendation.

## 2026-10-21 — Rookies: ADP-derived fallback, no pick-based model
**Decision:** anyone the model cannot score gets a projection from an isotonic curve of rank-within-position (by ADP)
to expected PPR, fit on 2021–2025, flagged `market_estimate`. Players without a GSIS ID get a synthetic `market:<name>` ID.
**Why:** draft pick alone is a noisy single signal and cannot beat ADP, which already prices pick, landing spot and camp
news; a real rookie model needs college data and is a separate later project (user decision). Leave-one-season-out
RMSE on the top-150: RB ~63, WR ~67, TE ~62 (QB 119 on 6 players); rookie bias was small and not significant.
**Why rank-within-position:** Underdog's top 100 holds ~60 WRs vs ~43 in FantasyPros, so overall-ADP curves mis-price
positions; rank within position agrees across sources. Same RMSE as model rows is used for ceiling/floor.
**Known bias:** the curve is fit on players with ≥4 games, so deep ranks run high. **See:** `src/draft/market_fallback.py`.

## 2026-10-21 — The model is not used to out-rank ADP among draftable players; point projections average model and ADP curve
**Decision:** for the draftable pool, ADP alone ranks as well as any blend, so the model is a source of calibrated
points, uncertainty and flags there. For point projections, averaging the model with the calibrated ADP curve is
better than either alone.
**Why (rerun on the FINAL model, after the process features; the first run predated them and said "adds nothing"):**
- ADP top-150, best model weight: RB 0.0 (+0.000), WR 0.1 (+0.000), TE 0.4 (+0.011, but −0.015 at 0.3), QB 0.4
  (+0.023; at 0.3 CI [−0.09, +0.11], better in 4 of 5 seasons). Nothing beats ADP alone with confidence.
- All modeled players with an ADP (deeper pool): WR +0.009 (CI [+0.001, +0.016], 4/5 seasons), TE +0.033 at weight
  0.6 (the model alone beats ADP there, 0.705 vs 0.686), RB and QB flat. The process features bought the model a
  small edge at depth for WR and TE only.
- RMSE on the top-150, model / ADP curve / average: QB 89.9 / 83.5 / 82.7, RB 76.5 / 72.2 / 71.7, WR 71.6 / 71.0 / 69.8,
  TE 52.0 / 52.8 / 51.2. The average wins at all four (0.7–1.7% better than the best single source).
**Caveat:** the ADP curve was fit leave-one-season-out, so it saw seasons after the one it predicts; the model is
walk-forward. That slightly favors the curve. **Not yet done:** the blend is not implemented in the advisor.

## 2026-10-21 — `implied_total` leaked the target season; now the prior season
**Decision:** `implied_total` is the team's PRIOR-season average total in training and prediction.
**Why:** the old value was the season's own average closing line, which reflects in-season results. Replacing it
dropped QB top-150 from 0.61 to 0.23 at the time (WR −0.03, RB/TE ~0); a model without the feature scored the same as
prior-season, so the whole benefit was leakage. The earlier "QB beats ADP" result was an artifact.
**Rejected:** keeping it (can't be known at draft time), blending with partial-2026 lines (user's first choice; made
QB projections swing ~100 PPR on one input), dropping the feature (same scores, but prior-season total is honest context).
**Guard:** `src/features/manifest.py` + `tests/test_data_integrity.py::test_prior_season_features_are_lagged_not_leaked`.

## 2026-10-21 — Data-integrity guardrails: fail on errors, warn on soft problems
**Decision:** `src/data/validate.py` raises on hard problems (null/duplicate keys, unknown team codes, a season losing
rows in a merge, out-of-range values, prediction rows that differ from training rows, duplicate advisor players) and
warns on soft ones (feature drift, column order). Plain assertions + pytest, no pandera.
**Why:** every serious bug this phase was silent (legacy team codes dropped ~80 rows, junk "Team" rows corrupted target
share for 12 team-seasons, stale 2025 age/team in 2026 prediction rows, duplicated advisor players). "Always warn" is how
silent bugs survive; "always fail" would block runs on benign drift. Also added: run manifest, freshness checks, tracked
`models/*_params`, pre-commit hook, CI workflow. **See:** README "Data Integrity Guardrails".

## 2026-10-21 — Benchmark design
**Decision:** per-position scores only, top-150 chosen by ADP among players the model projected, mean of 5 model seeds
with the spread, always shown next to a "last year's PPR" baseline. No pooled "ALL" row.
**Why:** ADP prices positional scarcity and raw PPR does not, so a pooled row flatters or punishes arbitrarily; single-seed
scores moved by ±0.03 (TE); players the model cannot project (rookies) are excluded from both sides so the comparison is
like-for-like. Unranked players enter the overall scope as the union of the top 50 by actual and by model, tied last.

## 2026-10-21 — Re-tune only when both metrics improve; training window stays expanding from 2015
**Decision:** a re-tuned parameter set replaces the old one only if top-150 Spearman *and* RMSE both improve over 10
seeds. Training uses all seasons from 2015 (expanding window).
**Why:** with 500–1,600 rows per position the tuner mostly fits noise; QB, RB and WR re-tunes never beat the old params
(only TE and one QB re-tune were adopted). Dropping older seasons hurt QB (0.608 → 0.481 starting 2018), WR and TE;
sliding windows lost at every position, so data volume beats recency here.

## 2026-10-20 — QB uses attempt share; the old QB gap was starter identification
**Decision:** QB model gets `qb_att_share_prev` (player's share of the roster QBs' prior attempts).
**Why:** ADP's edge at QB was knowing who starts (starter-vs-backup AUC 0.87 vs 0.79 for the model). The share lifted
QB top-150 from 0.230 to 0.310; expected-starter and proven-competitor flags were redundant, rookie-competitor fired on
25 rows. A first-round rookie overrides as QB1 (72% of 39 such rookies were their team's top-attempt QB).
**Same logic at RB did not work:** carry-share features were null once vacated-volume features were in, because RBs share work.

## 2026-10-20 — Historical ADP: FantasyPros consensus via Wayback, day before the opener
**Decision:** scrape FantasyPros PPR consensus ADP from Wayback Machine snapshots closest to (not after) the day before
each opener, 2021–2025, one CSV per season (user decision).
**Why:** a snapshot after the opener can reflect Week 1. Snapshots used: Sep 7 2021, Aug 31 2022, Sep 6 2023, Sep 2 2024,
Aug 26 2025 (2022 and 2025 are 6–8 days early; user accepted). **Rejected:** Fantasy Football Calculator's public API
(user: its ADP is not good), expert consensus rankings (user chose ADP), nflverse ECR.

## 2026-10-20 — Prediction rows use prediction-season inputs
**Decision:** 2026 prediction rows take age, experience, team and team total from the 2026 roster, not the 2025 row.
**Why:** otherwise every projection saw players a year younger and on last year's team. Training rows describe the season
being predicted, so prediction rows must too. Players missing from the roster get age/experience advanced by one.

## Deferred, not decided
- **Coaching tendencies** (head-coach pass-over-expected, pace, 4th-down aggression, using the coach's prior team's
  tendency when the HC changes): the user wants to scope it carefully before any work. Only head coaches are public.
