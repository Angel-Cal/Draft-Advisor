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

## 2026-10-28 — Waiting bonus with only reachable alternatives tested and rejected: ties the adopted bonus, or ruins it when the reach cost is applied
**Question (raised by the user from an explainer sentence that named K.Allen, ADP 78, as the alternative at pick 19):** the waiting bonus counts every likely survivor at his position as my alternative at full value, even a player far past his ADP at that pick whom the reach cap would never let the recommender take. Does restricting alternatives to players recommendable at the later pick (`WaitSettings.Reachable`, `tune-reachable`) improve the picks?
**Result (60 seeds = 3,600 drafts per arm, noise x1, `need+wait` weights 2 / 4 / 8):** inside the 4-sigma cap at that pick ("cap"): points -3 +/- 1 / -1 +/- 1 / -1 +/- 2 and title odds -0.5 / -0.1 / -0.4 pp against the adopted bonus (all within noise; best weight still 4); leave-one-season-out -9 +/- 8 points, -0.6 +/- 0.9 pp. Also cutting each alternative's value by the reach cost it would carry at that pick ("cap+cost"): -107 / -124 / -162 points and -9.9 / -11.6 / -13.0 pp, worse than plain ADP.
**Reading:** the distant high-model player does not distort the picks, so the adopted bonus stays. "cap+cost" fails by construction, not by bug: with lambda 1000 the reach cost is a wall (a player 3 picks past his ADP already costs ~360 points), so almost no survivor has any value left, the shortfall becomes the candidate's whole value, and the bonus turns into a flat tax on the best player at every position. Noise x0.5 and x2 were not run since the main result is a tie. The option stays in the code, off by default (`AlternativeReach.Any`). The explainer still names the reachable alternative, since that is the honest sentence for a reader, whatever the bonus does internally.

## 2026-10-28 — Reasoning strings: `Explainer` describes the score's terms in words and never quotes score units
**Decision:** a Core class (`Explainer`, `Explanation`, `ReasonLabel`) turns the top candidates into a headline plus up to 4 reasons with badge labels (starter / backup / thin position / bargain / early pick / injury history / estimated projection); the `draft` CLI prints it under the table (full reasons for #1, one line for #2-5). It is in Core so the Phase 5 app reuses it.
**Why in words:** the waiting bonus has weight 4 and is not in points (LOG 2026-10-25/27), so quoting it would let a beginner add up numbers that do not add up. Numbers in the text are real projected season points (his projection, lineup gain over a replacement-level player) or pick numbers. The headline names the score term that adds the most (lineup gain, bench value or waiting bonus); "thin position" is told by naming the best same-position player the recommender could take at the next pick (at least a 50% chance to last, inside the reach cap at that pick, best after the reach cost) and how many projected points worse he is (10 or more). First version picked the survivor by raw projection and named K.Allen (ADP 78 at pick 19, never recommendable there); fixed 2026-10-28 after the user caught it.
**Not done:** a "why not the ADP pick" line (asked about, not chosen), and risk is a label only (the player-level risk signal does not exist, LOG 2026-10-25). The wording is untested on real beginners; the Phase 6 friends beta is where to check it.

## 2026-10-28 — Rollout policy improvement tested: +15 points over the adopted advisor, not consistent across seasons, not adopted
**Idea:** instead of scoring a pick by a formula, try the best few candidates: take him, play the draft forward with the other drafters sampled from `OpponentModel` and my own later picks made by the base recommender, and keep the candidate whose finished rosters (best lineup plus structural bench value) are best on average, with the same sampled opponents for every candidate (`Rollout`, `RolloutStrategy`, `tune-rollout`; 4 candidates x 10 rollouts).
**Result (`tune-rollout --seeds 20 --metric points`, 1,200 drafts per arm, noise x1, points / vs adopted `need+wait`):** rollout `need+wait` 2217, +60 +/- 6 over ADP and +15 +/- 6 over the adopted advisor (2202, +45); rollout on plain `need` 2202 (+0 +/- 6: no gain without the waiting bonus); `need` 2193. By season against the adopted advisor: +38, +24, -55 (2023), +48, +19. Leave-one-season-out gain +15 +/- 18. A 300-draft run gave +20 +/- 12; a 60-draft probe's +45 was noise.
**Decision:** not adopted. The gain is under 1% of the score, not consistent across seasons, and an upper bound: the rollouts assume the simulator's own opponent model (noise x1, its caps), which a real league only approximates. It also costs minutes of CPU per draft against milliseconds for the adopted advisor. The title-odds and noise x0.5 / x2 checks of the protocol were not run (about 6 more hours) since the points result already fell short. Code stays in the repo as an opt-in strategy (`Rollout`, `RolloutStrategy`); `DraftState.Clone` and `Roster.Clone` are reusable.
**Run notes:** the 1,200-draft sweep took 2 h 5 min, a 300-draft sweep 11 min; a first 20-seed run was killed after about 4 h with an empty output file (cause not found, it did not recur). `Experiment.Run` now prints `n/total drafts done` to stderr, and the rollout loop throws if it makes no progress.

## 2026-10-27 — Roster-aware simulated survival: much better calibrated, no better picks, and the weight of 4 stays
**Idea:** the waiting bonus estimates survival from ADP alone (normal model); the opponents actually follow caps and forced fills and have known rosters. Estimate survival by playing out the other drafters' picks to my next turn many times (`SurvivalSampler`, `OpponentModel`, `WaitSettings.Opponents`; 40 samples, noise and rules as the simulator's, no knowledge of its seeds).
**Calibration (`calibrate-survival --simulated true`, 1.8M predictions at 1,200 drafts' turns):** Brier 0.0387 and log-loss 0.1454 for simulated survival, against 0.0468 / 0.1534 for the best normal model (spread x0.7) and 0.0470 / 0.1564 for the adopted spread; without caps and forced fills 0.0419 / 0.1624. Better in every round block (rounds 9-16: 0.1816 vs 0.1990). Roster awareness is worth about 17% of Brier, mostly from the caps.
**Simulator (`tune-survival`, 100 seeds, `need+wait` edge relative to the adopted bonus, points / title odds):** simulated w=4 0 +/- 1 / 0.0 at x1, +1 / +2 at x0.5 and x2; no-rules w=4 +1 / +0.1; w=1 -5 / -0.6; w=2 -5 / -0.6; w=8 -3 / -0.6. Held out +1 +/- 1 and +0.1 +/- 0.2.
**Reading:** a better probability does not give better picks, and the best weight is still 4, not 1 (the weight an expected shortfall in points should have): so the 4 is not covering for survival error (a third suspect ruled out, after the spread and the horizon). It is more likely absorbing what the score leaves out (the value of owning a scarce player beyond the next pick, correlated runs, the lineup effect of a starter at a thin position). Not adopted; the sampler stays in the code, off by default, and is reused by any rollout work.

## 2026-10-27 — Edge by draft slot: large differences between slots, but a slot-dependent waiting weight does not generalize
**Question:** the waiting bonus is one global weight (4), yet the gap between a team's picks depends on its slot (22 picks at slot 1, 2 at slot 12). Does the best weight, or the edge, depend on the slot?
**Edge by slot (`backtest` now prints it; `need+wait` vs ADP, noise x1, 500 drafts per slot):** validated files +66 / +62 / +62 / +21 / +43 / +44 / +61 / +41 / +18 / +60 / +91 / +67 points for slots 1-12 (title odds +0.4 to +9.0 pp; slots 1-4 are the weakest in title odds); the refit files give the same shape (slot 4 +20, slot 9 +18, slot 11 +86; correlation across the two file sets 0.78, but they share the opponent draws).
The differences are far beyond noise (heterogeneity Q 71 and 75 on 11 degrees of freedom) but not smooth: they are unrelated to how long the slot waits between picks (correlation -0.15 and 0.01), so they look like where the five specific player pools break at particular pick numbers, not a mechanism.
**Weight by slot (`tune-slot`, weights 1 / 2 / 8 against 4, 100 seeds):** over all slots every other weight is worse, in points -5.3 +/- 1.4 / -3.9 +/- 1.1 / -1.8 +/- 1.3 and in title odds -0.6 pp each, so 4 stays. By slot, w=8 helps slots 11-12 (+13.5 / +18.9 points, +1.6 / +2.6 pp) and hurts slots 8-9 (-27.9 / -25.4); w=1 helps slot 9 (+22.6, +2.0 pp).
**Leave-one-season-out choice of the best weight per slot:** -1.9 +/- 1.8 points and 0.0 +/- 0.3 pp title odds against the global 4 (by season +1.7, -0.5, -2.4, +0.4, -8.6). **Decision:** rejected; the weight stays global. The late-slot preference for a larger weight (the most plausible reading: with picks 11/14 and 12/13 back to back, a scarce position is lost for a long stretch unless taken now) is the only pattern worth a second look and would need more seasons than we have.

## 2026-10-27 — Bye-week-aware roster building tested and rejected: no measurable effect
**Idea:** the recommender knows byes only as an average inside the bench weight (q 0.23 = 3.1/17 missed games + one bye in 18). Bye weeks are public, so a bench player whose bye differs from the starters he covers should be worth more than one who shares it.
**Built (`ByeSchedule`, `LineupValue.ByeCover`, `NeedSettings.Byes`, `tune-bye`; off by default, 5 xUnit tests):** the term is the change in `ByeCover` when the player joins: the sum over 18 weeks of the best lineup among players not on bye (projection / 17 per week, open slots at replacement level) minus the season-total lineup. It is in points, so it has no weight to tune, and it is exact for the model's own numbers.
Byes are read off the weekly points in the backtest files (the week with the fewest scorers per team, 32 of 32 teams in every season; live files need the schedule). Because q already contains an average bye, the cover term was also run with q rebuilt from missed games only (3.1/17), and that q change alone as a control.
**Result, 100 seeds, 2021-2025, `need+wait` baseline (paired difference, points / title odds):** noise x1: cover -1 +/- 1 / 0.0; cover with q misses only +1 +/- 1 / 0.0; q misses only without cover +2 +/- 1 / +0.1. x0.5: +1 / +1 / +1. x2: -3 / 0 / +2 (all +/- 1). Leave-one-season-out gain +2 +/- 2, +0 and -1 +/- 1. Nothing clears the adoption bar (both metrics, held out, at half and double noise).
**Reading:** the bye hole is a small, nearly constant cost spread over every roster, so it rarely separates two candidates that the existing score already separates; the weak positive of the q control (+1 to +2 points, no title-odds gain) is within what the protocol treats as noise. **Decision:** not adopted, code stays off by default. Do not retry bye cover with these projections; it would need a much larger hole (a league with fewer bench spots or a harsher scoring of byes) to matter.

## 2026-10-27 — Shrinking the model's disagreements by player type tested and rejected: better held-out accuracy, much worse recommender
**Question (`src/evaluation/gap_reliability.py`):** the uniform 50/50 model + ADP-curve blend ruined the recommender, but perhaps only some disagreements are unreliable (injury-distorted, veteran, fades), so shrink those alone.
**Slopes** (`actual - curve` on `model - curve`, 600 draftable player-seasons 2022-2025, player bootstrap): all 0.42 (0.28-0.55), TE 0.72, QB 0.48, WR 0.45, RB 0.17 (-0.18 to 0.51). Cells with the largest departures are small and overlap: RBs who missed 5+ games or have 7+ years of experience about -0.77 (n 25-36); RB fades (model below the curve) -0.04 vs RB risers 0.82; the same split at WR runs the other way (0.58 vs 0.27), which argues for noise. About 55 cells were looked at, so none of this counts as a finding on its own.
**Held-out accuracy (leave one season out, slopes fit on the other seasons, clipped to 0-1):** every shrink helps ranking (top-150 Spearman RB 0.551 model, 0.587 blend, 0.584 by position, 0.596 position x sign, 0.594 RB-fades-only; QB 0.241 -> 0.30; TE 0.333 -> 0.366; WR 0.531 -> 0.57) and RMSE (RB 64.2 -> 60.9, QB 86.1 -> 84.2).
**Simulator, `need+wait` edge over ADP at x1 / title odds, seasons 2022-2025, 100 seeds:** unshrunk +52.2 / 16.3%; RB fades only +51.3 / 15.8%; position x gap sign +29.5 / 12.4%; by position +12.1 / 12.3%; uniform blend +7.2 / 11.9%. At x2 the order is the same (+25.8, +15.8, +18.2, -40.7, -28.4).
**Reading:** the edge falls with how much of the gap is removed, even when accuracy rises, and the one targeted cell (RB fades) gains nothing out of sample in the simulator despite the best RB Spearman. So the disagreements are worth keeping at full size for the recommender whatever their average calibration; do not shrink by player type. The group slopes are not usable as a signal either (too few rows per cell for 4 seasons).

## 2026-10-27 — The validated-vs-refit simulator gap is real but small, about half QB, and not an accuracy difference
**Question:** why does `need+wait` earn +52.9 points over ADP (x1) with the validated files but +42.6 with the refit files, at equal RMSE? **Tests (`src/evaluation/seed_spread.py`, 100 draft seeds, same opponents):**
1. *Projection-draw luck:* rebuilt both recipes from seed sets 5-9 and 10-14 (0-4 reproduces the existing files exactly). x1 edge over ADP, points: validated 52.9 / 47.3 / 45.3 (mean 48.5), refit 42.7 / 38.5 / 38.7 (mean 40.0); x2: validated 30.6 / 27.0 / 30.6, refit 19.5 / 6.7 / 13.8. The sets do not overlap, so the gap is the recipe, not the seeds, but the original +52.9 was the top of the validated range: **honest numbers are about +48 validated, +40 refit** (about 8.5 points at x1, about 16 at x2).
2. *Header RMSE rescaling* (my refit files rescaled the position RMSE by 0.99-1.01): unscaled header gives +42.7 vs +42.6. Irrelevant.
3. *Contrarianism:* mean within-position rank gap to ADP over the top 150 is 5.26 validated, 5.15 refit (live-style 5.78); same spread and ADP correlation. The refit is not more or less contrarian.
4. *Where it sits:* the validated recipe equals the refit recipe without the newest training season (refit on the early-stopping fit's own data gives the same predictions), so the only difference is that the refit trains on season s-1. Per-season gains (x1) are lower for refit in 2021 and especially 2025 (+23 / +14 validated, -30 / -22 refit) and higher in 2024. The biggest projection differences are a few QBs (Murray 2025 +27 and he was injured, Jackson 2021 +68, Hurts 2024 +45).
   Hybrid files (one recipe everywhere, the other's QBs swapped in): validated + refit QBs 43.7 / 42.9 (from 47.3 / 45.3), refit + validated QBs 43.6 / 43.1 (from 38.5 / 38.7). QBs explain about 3-5 points, the non-QB positions the other 4-5.
**Reading:** accuracy on the top 100 by ADP is the same in every season (RMSE 85.6 vs 86.2, 81.0 vs 82.5, 79.2 vs 78.8), title odds at x1 are equal within noise (validated +4.8 / +4.0 / +4.4 pp, refit +4.1 / +4.2 / +4.2), so the points gap does not show up in the league-finish metric. What adding season s-1 changes in the model-vs-ADP disagreements that costs about 8 points is not identified, and with five test seasons I do not think it can be. **Decision:** keep the refit for the live file; stop investigating unless new seasons give a sixth test year.

## 2026-10-27 — Live training fixed (refit at the best iteration, 5 seeds, no tree scaling): accuracy recovered, simulator edge only partly
**Decision:** `Model.refit_predict` (`train.py`) is now what `predict.py` uses for QB/RB/WR/TE: per seed 0-4, early-stop (patience 50) on the newest season with the older seasons as training, refit on all seasons at `best_iteration_`, average the seeds. `projections_2026_v1.json` was regenerated (predict -> vor -> export).
**Tree scaling (user: try both, then pick):** refit at `best_iteration_` exactly vs times the data-size ratio (`scale_trees`) gave the same RMSE (within 0.1) and top-150 Spearman within 0.006 (unscaled equal or better at RB/QB/TE), so no scaling; the argument is kept for the Phase 3 retrain.
**Validation (`src/evaluation/refit_oos.py`, walk-forward 2021-2025, refit uses every season before the test season):** RMSE QB/RB/WR/TE 84.4 / 61.4 / 54.7 / 40.5 (validated 84.5 / 61.7 / 55.0 / 40.1, live-style 87.1 / 63.5 / 56.2 / 42.5); top-150 Spearman 0.233 / 0.538 / 0.509 / 0.413 (validated 0.310 / 0.537 / 0.512 / 0.383).
The QB gap is noise (about 22 QBs a season, per-season rho SD about 0.2): over all QBs the per-season rho is 0.666 refit vs 0.677 validated vs 0.662 live-style.
**Simulator (`backtest --data data/processed/refit`, 100 seeds, same opponents as the other worlds), `need+wait` edge over plain ADP at noise x0.5 / x1 / x2:** +41.2 / +42.6 / +19.5 points, title odds +2.6 / +4.1 / +2.1 pp (15.5% title at x1). Validated: +50.2 / +52.9 / +30.6 points, +3.4 / +4.8 / +3.2 pp; live-style: +35.4 / +40.7 / +11.1, +2.4 / +4.2 / +1.6.
**Reading, against the expectation that the gap would close:** the fix helps at double noise (+11 -> +20) but at the calibrated noise the refit edge (+42.6) is no better than live-style (+40.7), still about 10 points under the validated file. Per season at x1 (gain over ADP, 2021-2025): validated +56 / +66 / +78 / +43 / +21; refit +19 / +55 / +84 / +60 / -6; live-style +21 / +52 / +96 / +43 / -13.
The shortfall sits in 2021 and 2025. Not explained, and not tested: the draft-level SE (+/- 2.4) does not include the variance of the projection file itself, which is large in single seasons (a different set of model-vs-ADP disagreements), so the validated +53 may be partly a favorable draw of one model-fitting recipe, or the validated models, which never see season s-1 in training, may differ from refit ones in a way that matters here.
I shipped the refit anyway: it is at least as accurate as the validated recipe on every position by RMSE, it is a recipe that can be built for 2026 (the validated one cannot, it early-stops on a season it does not train on), and it is not worse than the old one anywhere. Do not expect +53 from the live file; the honest planning number is about +40 to +43 points / 4 pp title odds.

## 2026-10-27 — Decision: fix the live training recipe with "refit at the best iteration" plus 5-seed averaging (option 2); to be done in a new session
**Decision (user):** replace `train_final_model` in `predict.py` with: per seed, early-stop on the newest season (fit on all earlier seasons) to find the best iteration, refit on all seasons through the newest season at that tree count, average seeds 0-4 (as the validated files do).
Full step list, targets and reference numbers are in STATUS.md ("NEXT TASK").
**Why this option:** it adapts the tree count to each position and seed, keeps the freshest season's labels in training, and matches the validated recipe's 5-seed averaging. **Alternatives considered:** a fixed tree count per position (median best iteration of the other folds: QB ~251, RB ~253, WR ~342, TE ~209) trained on all data (likely similar);
early-stopping on the newest season only (mirrors the backtest exactly but never trains on it). **Open for the next session:** whether to scale the refit tree count by the data-size ratio (about 1.1); the stakes (about 13 starter points and 0.6 pp title odds for `need+wait` at calibrated noise) are in the entry below.

## 2026-10-27 — Stakes of the live-training gap measured: the shipped recipe would cost the recommender about a quarter of its edge (fix not yet made)
**Question:** how much does training the live way (1000-tree cap, no early stopping, one seed; `predict.py`) cost the recommender, compared with the validated way (early-stopped on the previous season, 5 seeds; `oos_predictions.py`)?
**Method (`src/evaluation/live_style_oos.py`):** for each test season 2021-2025 train every position on all earlier seasons exactly as `predict.py` does, write copies of the backtest files with only `projected_ppr` replaced (position RMSE scaled by the live-style/validated RMSE ratio, 1.02-1.06),
and run the identical backtest (100 seeds, same opponents; plain ADP moves by under 1 point between the two worlds, so the comparison is clean).
**Accuracy (reproduces the bug-sweep finding):** RMSE validated -> live-style QB 84.5 -> 87.1, RB 61.7 -> 63.5, WR 55.0 -> 56.2, TE 40.1 -> 42.5; top-150 Spearman QB 0.310 -> 0.251, RB 0.537 -> 0.496, WR 0.512 -> 0.489, TE 0.383 -> 0.395 (TE slightly better on this measure).
**Simulator, live-style minus validated, paired (cluster SE), noise x0.5 / x1 / x2:** `need+wait` points -14.2 +/- 2.1 / -12.9 +/- 2.3 / -19.0 +/- 3.8; title odds -0.9 +/- 0.3 / -0.6 +/- 0.3 / -1.4 +/- 0.6 pp; playoff odds -1.6 / -1.4 / -1.1 pp.
Plain `need` -8 to -9 points at every noise level; `value` -6.5 / -7.9 / -14.6. **Edge over plain ADP for `need+wait`:** x0.5 +50.2 -> +35.4 points (title +3.4 -> +2.4 pp), x1 +52.9 -> +40.7 (+4.8 -> +4.2 pp), x2 +30.6 -> +11.1 (+3.2 -> +1.6 pp).
**Reading:** the edge survives the shipped recipe at every noise level but loses about a quarter of its points at the calibrated noise and almost two thirds at double noise, so fixing it is worth doing and is cheap. **Anomaly, not understood:** the old position-first `windowed` recommender gains +62 points
(+8.6 pp playoff odds) at x1 with the live-style projections, even though they are less accurate; it is a high-variance strategy whose result depends on the projections in ways I have not explained, so I would not read anything into it.
**Next:** fix `predict.py` (options in STATUS: fixed tree count, or refit at the best iteration, plus 5-seed averaging) after the user picks; then re-run predict -> vor -> export_projections and the comparison above should close.

## 2026-10-27 — Spread-normalized waiting bonus tested: no better than the raw weight of 4; the 4 is mostly a unit ratio
**Decision:** `WaitSettings.Standardize` / `StandardizePool` (value and shortfall as z-scores over the best 15 candidates, `score = mean + sd x (z_value + w x z_shortfall) / (1 + w) - reach cost`, so the weight is a unit-free mix; `tune-standardized`)
stays in the code, off by default, not adopted. The adopted bonus is unchanged (raw, weight 4). User's idea (scale by the spread of values so a weight means the same thing in every round).
**Design correction on the way:** the first version standardized the one-step score; the diagnostic (`diagnose-scales`) showed that spread in the thousands because most of the best 15 candidates by one-step score carry huge reach penalties. The final version standardizes the value before the reach cost
and keeps the reach cost a separate wall in points (dead-pick offset preserved).
**Explanation of the 4 (`diagnose-scales`, 28,800 picks, best 15 candidates by one-step score, spread in points):** SD of value vs SD of shortfall: rounds 1-2 26.1 vs 9.2 (ratio 2.8), 3-4 20.0 vs 6.6 (3.0), 5-9 13.0 vs 4.2 (3.1), 10-16 2.6 vs 1.1 (2.4), all 11.0 vs 3.7 (2.9); value and shortfall correlate 0.5-0.7.
In standardized units `value + 4 x shortfall` is about `z_value + 1.4 x z_shortfall`: the shortfall varies about a third as much as value, so a raw 4 is roughly equal importance for the two. The ratio is nearly constant across rounds, which predicted that normalizing by spread would not matter much.
**Result (100 seeds; adopted raw w = 4 vs best z-mix):** noise x1: title 16.3% vs 15.7% (w = 0.5; -0.6 +/- 0.2), points 2210 vs 2206 (w = 1; -4 +/- 1), held-out -1.1 +/- 0.5 pp and -11 +/- 3 points; half noise 12.2% vs 11.9% (w = 0.25); double noise 24.4% vs 24.1% (w = 4).
The best standardized weight is not stable (0.25 at x0.5, 0.5-1 at x1, 4 at x2) while the raw 4 was good at all three, so the "unit-free" version is less robust, probably because a z-score over 15 candidates, many of them infeasible, is a noisy normalization.
**Net:** the weight of 4 is a mixing weight, about equal importance after putting value and shortfall on the same scale, concentrated at RB (and TE) in the early rounds. It is still empirical (a first-principles value is not derived), but no longer an unexplained constant.

## 2026-10-27 — Where the waiting bonus earns its gain: rounds 1-4 and RB; the global weight of 4 partly hides this (adopted setting unchanged)
**Question (user):** why does a weight of 4 work, and is it just an arbitrary constant? First reading: the reach cost (lambda 1000) is effectively a hard wall (2 picks past the pick costs 117 points at pick 24), so the recommender only chooses among
players the market says are due to go; within that set raw values are close and the cliff to the next survivor separates the options. Score = value + 4 x VONA is 20% value / 80% value-over-next-available, a mixing weight between two ranking criteria.
**Switching the adopted bonus (weight 4) on only in a block, and off only there** (`tune-where`, 100 seeds, noise x1; title odds % / starter points; adopted 16.3 / 2210, plain `need` 14.4 / 2199):
rounds 1-4 only 15.7 / 2208, all but rounds 1-4 15.2 / 2203; rounds 5-9 only 14.7 / 2202, all but 16.1 / 2209; rounds 10-16 only 14.9 / 2200, all but 15.8 / 2209;
RB only 15.3 / 2212, all but RB 14.9 / 2197; TE only 15.2 / 2201, all but TE 15.7 / 2208; WR only 14.5 / 2200, all but WR 16.3 / 2212; QB only 14.4 / 2195, all but QB 15.9 / 2213.
**Reading:** about 80% of the points gain and two thirds of the title gain come from rounds 1-4. By position the points gain is all RB (RB alone matches the adopted result, dropping RB loses 13); TE adds title odds (TE alone +0.8 pp),
WR adds nothing (dropping it changes nothing), QB alone hurts points (-4). So the bonus is mostly positional scarcity at RB (and TE) early, and one global constant gets that by also adding noise at WR and QB.
**Not adopted:** choosing the best arm on four seasons and scoring it on the fifth does not beat the adopted setting (-8 +/- 6 points, -0.9 +/- 0.7 pp title), so the position and round filters are not an improvement as selected here. The filters stay in
`WaitSettings` (`ActiveRounds`, `ActivePositions`), off by default. **RB+TE-only test (`tune-scarce`, 100 seeds, weights 2 / 4 / 6 / 8):** it ties the global bonus and is not adopted. At weight 4 vs the adopted global bonus: title odds 16.0% vs 16.3% (-0.3 +/- 0.2; held out -0.3 +/- 1.2),
points 2215 vs 2210 (+5 +/- 1; held out +5 +/- 8), half noise 12.2% vs 12.2%, double noise 24.3% vs 24.4%. Weight 4 is again the best RB+TE weight (2: 15.6%, 6: 15.5%, 8: 15.1%). The season profile differs (RB+TE is better in 2025, worse in 2022 and
2024), so the two are different but equivalent drafters, and the filter was chosen from the same seeds. Rule set beforehand (match or beat on both metrics, held out and at other noise levels): title is level to slightly lower, so not met cleanly; the global bonus
is also the simpler one (no position list chosen from the data). **What it does establish:** the weight of 4 is a scarcity bonus at RB and TE; leaving WR and QB in changes nothing measurable.

## 2026-10-27 — Handcuff logic: the absorber cannot be identified from preseason information, so no handcuff term is built
**Decision:** no handcuff bonus. `src/evaluation/handcuff_study.py` (writes `data/processed/handcuff_events.csv`) is the study; the user's pushback shaped it: a depth-chart RB2 is a guess about who inherits the work, not a fact,
so identification had to pass its own test first (go/no-go gate) before any value logic.
**Method:** 306 team-seasons 2015-2024 with a week-1 chart RB1; his absent weeks come from the weekly stats (no touches, and he did not play for another team); every other RB on the team is scored by PPR points gained in those weeks
over his own average while the starter played; the top gainer is the "absorber". 165 events (starter missed >= 2 games, played >= 2). Preseason predictors pick one chart RB: depth tier, last year's carry share, target share,
points per game, draft capital (known for only 40% of rostered players, since the roster file starts in 2020).
**Result:** the starter missed >= 2 games in 56% of team-seasons and >= 4 in 33%. In 30% of events the absorber was not on the week-1 chart at all (signings, later chart slots). Over the 115 events where he was on the chart, hit rates are
depth tier 55.7%, carry share 52.2%, target share 48.7%, ppg 51.3%, draft capital 56.5% against 48.1% for a random chart RB (SE about 4.7%): none is distinguishable from chance. A random chart RB is worth 8.2 PPR points per team-season over his own
baseline, the best predictor 8.9, the hindsight absorber 23.7, so what prediction could add is under one point per season. The share the depth-chart RB2 absorbed does not persist for a team across seasons (Spearman +0.04, 126 pairs), so
team-level (or coach-level) absorption cannot be carried forward either.
**Why this closes it:** the gate failed (identification is near chance), the whole average prize is about 8 points a season, and the bench option value already prices the average backup (23% miss rate). Consistent with the user's expectation of "next to no change".
**Caveats:** the starter is the week-1 chart RB1, absence is "no touches" (inactive healthy scratches count), gains are over the player's own baseline and not over a waiver pickup, draft capital coverage is low, and the first run had a baseline bug
(random baseline ignored events whose absorber was off the chart; it made every predictor look worse than chance), fixed before the numbers above. Still open as an explanation label only: "backup to your RB1" is worth telling beginners (reasoning strings).

## 2026-10-27 — Multi-pick horizon in the waiting bonus tested and rejected; the weight of 4 is an empirical scale, not explained by later picks
**Decision:** `WaitSettings.Horizon` / `HorizonDecay` (the bonus summed over my next H picks, optionally with each later pick scaled by the decay; `DraftState.UpcomingPicks`; `tune-horizon`) stay in the code, off by
default (horizon 1 is exactly the adopted bonus). The adopted setting is unchanged: weight 4, horizon 1.
**Result (60 seeds, noise x1, title odds / points, vs adopted `need+wait`):** h=1 w=4 16.2% / 2207; h=1 w=2 15.8% / 2204; h=2 w=2 15.6% / 2205; h=2 w=1 15.5% / 2202; h=3 w=1 15.6% / 2202; h=3 w=2 15.0% / 2203;
h=3 decay 0.5 w=2 15.8% / 2206 (-0.3 pp, -1 point); `need` 14.6% / 2199. Held-out (arm chosen on four seasons): -1.0 +/- 0.6 pp title, -1 +/- 1 points; the choice is h=1 w=4 in 3 of 5 seasons.
**Reading:** a longer horizon behaves like a rescaled weight (h=2 w=1 is close to h=1 w=2, h=2 w=2 to h=1 w=4, h=3 w=2 overshoots just as w=8 does). If later picks were the reason the best weight is 4, h=3
at a weight near 1 would match h=1 at 4; it does not (15.6% vs 16.2%). So the bonus needs an effective multiplier of about 4 on the one-pick shortfall however it is built; the reason is still unexplained.
Ruled out so far: survival spread, reach cost, a two-step lookahead, a multi-pick horizon. Untested: that the shortfall in points over replacement understates how much a scarce top player is worth to title odds.
The sweep took 223 s (title) and 214 s (points).

## 2026-10-25 — Two-step lookahead tested and rejected; the adopted waiting bonus stays
**Decision:** `LookaheadSettings` (score = value + beta x E[best pick at my next turn given my roster with him on it, from the likely survivors at all positions]; top 15 candidates, 12 survivors per
position; cannot be combined with the waiting bonus) stays in the code, off by default, and is not adopted. User chose two steps and top-15 pruning. `tune-lookahead` runs it.
**Result (60 seeds, noise x1, beta 0.5 / 1 / 2 x reach cost 0 / 100 / 300 / 1000):** no arm beats `need+wait`. Best lookahead arms equal or trail plain `need`: title odds 14.6% (beta 1, lambda 1000) vs `need` 14.6% vs
`need+wait` 16.2%; points -9 / -10 vs `need+wait` at lambda 1000. Held-out (arm chosen on four seasons): title -5.9 +/- 2.6 pp, points -43 +/- 25 vs `need+wait`. Lower reach costs are worse and erratic:
lambda 0 swings from 3.0% title odds (2023) to 28.8% (2022) and costs 17-31 points; lambda 100 -3.3 pp vs `need+wait`. Larger beta is no better (beta 2 is the worst at every lambda), so it does not
reproduce the weight-4 behavior of the waiting bonus either.
**Why (untested):** the waiting bonus compares a player with the alternatives at his own position, a targeted signal; the lookahead adds a next-turn term across all positions that is mostly the same for every
candidate, so it adds noise as much as signal, and without the reach cost it drifts away from ADP. **Still unexplained:** why the waiting weight is 4. The one-pick-ahead explanation is not supported by a two-step
version doing worse; a multi-pick horizon inside the waiting bonus itself would be the direct test.
**Cost note:** the title sweep took 10,402 s and the same sweep scored by points 1,494 s; I do not know why the first was so much slower (machine load or throttling is likely) and did not add progress output.

## 2026-10-25 — Survival model checked against real data and the simulator; why the waiting weight is 4 stays unexplained (two suspects ruled out)
**Question:** the adoption evidence is partly circular (simulator opponents are ADP + Gaussian noise, the same assumption as the survival model), and if the model were right weight 1 would be best.
**Real data (Fantasy Football Calculator mocks, 2021-2025, about 1,000 player-seasons):** real pick spread is about 0.11 x ADP (6.5 -> 1.6, 36 -> 4.5, 60 -> 6.4, 108 -> 10, 160 -> 18); the survival model's
2 + 0.16 x ADP (taken from the reach cost, where it means disagreement between ADP sources) is 1.5-2.0x that in every bucket. Robust to the "drafted in most mocks" filter.
**Simulator reliability** (`calibrate-survival`, 2.7M predictions at 1,800 drafts' turns by `need+wait`): log-loss best at spread scale 0.85 (0.1518 vs 0.1567 at 1; 0.55 -> 0.1693; 0.4 -> 0.2158). At
scale 1 the model over-predicts survival of players likely to be gone (23% predicted, 10% observed) and under-predicts for likely survivors (90.9% vs 94.7%); the effect is in rounds 1-8, none in 9-16.
So the real-data spread is not the right spread for predicting survival at my next turn (fat tails, caps and forced picks widen it).
**Spread x weight sweep** (`tune-spread`, 60 seeds): scales 0.5 / 0.7 / 1.0 give the same result at each weight (title 16.0 / 16.1 / 16.2% at w = 4; points 2206-2207); best weight stays 4. Good for the
adoption: the gain does not depend on the spread being right to within a factor of two, so the real-data mismatch does not threaten transfer.
**Reach cost x weight sweep** (`tune-reach-wait`): the reach cost is not why the weight is 4. Best weight stays 4 at lambda = 100, 300 and 1000; lambda = 1000 stays best (title 16.2%, points 2207); lambda = 100
is unstable (title 24.8% in 2022, 10.9% in 2023). Without the bonus lambda = 1000 is also best (14.6%), so the old tuning holds.
**Still unexplained:** the weight above 1. Not a miscalibrated spread and not the reach cost. Most plausible (untested): the bonus looks one pick ahead, and the cost of missing a scarce player recurs over later picks.
That is what a two-step lookahead would capture, so it is the next step. **Rejected:** testing the alternative valued after the candidate joins the roster (see the correction in the 2026-10-22 entry).

## 2026-10-25 — OPEN, not decided: the live projections come from a different model than the one we validated (trees, seeds)
**Finding:** a separate bug-sweep session found that `predict.py` trains the live models with `n_estimators` 1000 and no early stopping, while `oos_predictions.py` early-stops on the prior
season (best iteration about 200-360 trees). On the five walk-forward folds (3 seeds) the live-style model is worse: RMSE QB 86.4 vs 84.2, RB 60.5 vs 59.1, WR 54.2 vs 53.2, TE 40.7 vs 38.7;
Spearman TE 0.734 vs 0.767, QB 0.666 vs 0.680, RB 0.780 vs 0.796. I verified the code and then found a second gap: the live path uses one seed (`random_state` 42), the validated
files average 5 (seed spread moves top-150 Spearman by 0.01-0.03).
**Impact:** none on any backtest, simulator or league-metric result (they use the early-stopped 5-seed files); `projections_2026_v1.json` is affected, and it is what the product would ship.
Plausible but unmeasured: larger model-vs-ADP disagreements than validated, which the recommender's edge depends on.
**Proposed fix (awaiting the user's choice):** fixed tree count per position (median best iteration of the other folds: QB ~251, RB ~253, WR ~342, TE ~209) trained on all data, averaged over several
seeds. **Alternative considered:** early-stopping the live model on 2025, which mirrors the backtest exactly but never trains on 2025's results. Do it in the Phase 3 retrain, before Phase 5.
Pointers: `STATUS.md` (Known issue), memory note `project_live_model_tree_count`.

## 2026-10-25 — Cost of waiting adopted (weight 4) as the default advisor; `need` stays as the reference arm
**Decision:** `ValueRecommender.DefaultWait = WaitSettings(4)`; `draft --recommender need` uses roster need + the waiting bonus, `need-only` is the old advisor, the `backtest` shows both
(`need` and `need+wait`). User set the gate: robustness checks first, adopt only if the gain holds and rosters look sane.
**Checks (60 seeds, w = 4 vs `need`; title / points):** noise x0.5 +0.9 pp / +5, held-out +0.4 +/- 0.5 / -2 +/- 1; x2 +3.0 pp / +13, held-out +2.6 +/- 2.5 / +6 +/- 13;
rules lifted +1.5 pp / +8, held-out +0.6 +/- 0.6 / 0 +/- 4; x1 (100 seeds) +1.9 pp / +11, held-out +1.2 +/- 0.6 / +9 +/- 8. Positive on both metrics in every
condition at the draft level, never significantly negative; the benefit grows with opponent noise. Roster composition identical to `need` (QB 2.0, RB 5.0, WR 7.0, TE 2.0 in 2024 and 2025);
2024 +32 points (finish 5.49 vs 6.12), 2025 +7. Weight 8 is worse than `need` at x0.5 (-0.4 pp title), so 4 rather than the top of the range.
**Final 100-seed backtest (x1):** `need+wait` 2211 (+53 +/- 2 over ADP), playoffs 65.2%, title 16.3% (ADP 11.4%, `need` 14.4%); x0.5 +50 / 12.2% title, x2 +31 / 24.4% title (ADP 21.3%).
**Caveats:** the weight was picked on the same 100 seeds (so the x1 line is in-sample); the season-level evidence is about 2 SE on title odds at x1 and weaker elsewhere; the gain is
small at low noise. **Rejected for now:** the variance-aware starter value (see the entry below).

## 2026-10-25 — Re-test under the league metric: starter option rejected; cost-of-waiting bonus looks positive at weight 4, not yet adopted
**Decision:** sweeps take `--metric points|wins|playoffs|title` (`SweepMetric`, `ArmSweep`; reports also show a paired difference against the headline arm). The variance-aware
starter value (`NeedSettings.StarterOption`, `OptionPremium`: a starter who busts is cut and replaced from the waiver level, so he is worth E[max(X, waiver)]; `tune-starter`) is
off by default and rejected. The waiting bonus (`WaitSettings`) is still off by default; adoption is the user's call.
**Starter option (60 seeds):** points w = 0.5 / 1 / 2 / 4 = +3 / +3 / -2 / 0 vs `need`; title odds +0.1 / -0.4 / -0.8 / -0.8 pp; combined with the waiting bonus no better than the bonus alone
(title 15.7% vs 15.8%). Likely cause: one position-wide spread for everyone pushes picks toward high-spread positions; the player-level risk study found nothing better to use.
**Waiting bonus (100 seeds, noise x1, weights 0.1 .. 8):** dose-response rises to w = 4 and plateaus at 8. w = 4 vs `need`: title 16.3% vs 14.4% (+1.9 +/- 0.3 pp, draft-level SE), playoffs +1.7 +/- 0.3,
points +11 +/- 2. Leave-one-season-out gain over `need` (chosen on four seasons, scored on the fifth): title +1.2 +/- 0.6 pp, points +9 +/- 8, playoffs 0.0 +/- 1.3. Season by season
the title gain is positive in 2021-2024 and -0.6 in 2025; the points gain is driven by 2022 and 2024 (+15, +37) with 2023 at -4. So: consistent direction on three metrics, but the season-level
evidence is about 2 SE on title and weaker on the others, and w = 4 was picked from seven arms. Draft-level SEs ignore that drafts in a season share opponents.
**Fixed on the way:** the new `Signed` helper printed a literal "+F1" (a custom format string), so the first title and playoff runs had no paired columns; reran.

## 2026-10-25 — League-finish metric: 13-week head-to-head season, 6-team playoff, odds averaged over 200 random schedules
**Decision:** every simulated draft is also replayed as a league season (`LeagueSeason`, `SeasonFormat`, `SimSettings.Season` / `ScheduleSamples`): 13 regular-season
weeks of random round-robin, top 6 by wins then points for, seeds 1-2 byes, single elimination in weeks 14-16 (best remaining seed plays the worst; a tie goes to the
better seed). Reported as win %, playoff odds and title odds. User chose the format (13 weeks, 6 teams) and the averaging over schedules.
**Why:** points are an expected-value objective; a risk preference (or anything about variance) can only matter for winning, and "finish" until now was only the rank of total
points. Weekly scores are fixed by the real season, so schedule luck is the only randomness left; averaging 200 schedules removes it (cheaper than 200x more drafts), and
schedule s depends only on the seed, so strategies are compared on the same schedules. **Rejected:** one fixed schedule per draft (title odds near 8% would need many times more drafts).
**Result (100 seeds, noise x1):** same ranking as points. `need` playoffs 63.5% / title 14.4% vs ADP 57.8% / 11.4% (+5.7 +/- 0.5 and +3.0 +/- 0.3 pp), `value` +1.5 pp title,
`windowed` level with ADP although 28 points behind (the metric saturates), VOR -3.7, old recommender -10.9. At x2 noise `need` is level with ADP (+0.3 +/- 0.5 pp).
**Not modeled:** waiver wire, start/sit mistakes (lineups are hindsight-optimal), trades; weeks 17-18 count for points but not for the season.

## 2026-10-25 — The 50/50 model + ADP-curve blend is more accurate but makes the recommender worse; the recommender keeps the pure model
**Decision:** `projected_ppr` for the recommender stays the pure model. The blend (`src/evaluation/blend_test.py`, 50% model + 50% ADP-to-points curve fit
walk-forward on earlier seasons only, so 2022-2025) is not shipped as the recommender's input. It may still be right for *displayed* point projections.
**Why:** accuracy improves: top-150 RMSE QB 91.3 -> 85.2, RB 77.3 -> 73.5, WR 66.9 -> 65.0, TE 48.5 -> 48.2; top-150 Spearman +0.03 to +0.06 at every position
(still below plain ADP: QB 0.30 vs 0.33, TE 0.37 vs 0.40); the +14% bias on "risers" (ADP rank better than last-year output rank) falls to +3.5%. But in the
simulator (2022-2025, 60 seeds, identical opponents; position RMSE in the files scaled by the blend's RMSE ratio) `need` falls from 2188.8 (+40 over ADP) to
2176.9 (+28): paired -12 +/- 3 at noise x1, -40 +/- 5 at x2, neutral in 2022-2023 and -27 / -18 in 2024 / 2025; `value` -12 +/- 3. The old position-first
`windowed` rule gains +15, which is why it looked fine in aggregate.
**Untested explanation:** the recommender's edge comes from where the model differs from ADP, and the reach cost already holds it near ADP, so projections that
already lean toward ADP leave it less independent signal; the isotonic curve also flattens the spread between players, which VOR, tiers and bench option value use.
**Caveat:** only weight 0.5 was run. A smaller weight on the curve was not tried. The 2021 season is excluded (no earlier season to fit the curve).
Rejected earlier: shipping the blend (2026-10-21 entry, which found 0.7-1.7% lower RMSE with a leave-one-season-out curve that saw the future).

## 2026-10-25 — Simulator opponents no longer depend on the projections; headline re-measured (+42, was +48)
**Decision:** `OpponentBot.Create` draws each opponent's per-player bias in player-id order instead of pool order (`OpponentBotTests`).
**Why:** pool order is sorted by VOR, so any change to the projections reassigned the random draws between players and gave the same seed different opponents.
The first blend comparison moved plain ADP (which never reads projections) by 24 points; after the fix ADP is 2148.8 vs 2149.2 across the two files.
Every earlier simulator number had a different, equally valid random realization of the opponents. Re-run (100 seeds, 2021-2025, noise x1, weekly scoring):
ADP 2157.5, `windowed` -28 +/- 3, `value` +20 +/- 2, `need` +42 +/- 2 (was +34 / +48 over ADP 2164), `need` ahead of ADP in all five seasons; noise x0.5 +49, x2 +16
(break-even is a little above x2). Order and signs unchanged. Seed-cluster SEs are ~30% larger than the draft-level ones because drafts in a seed share opponents.
The cost-of-waiting sweep, re-run: w = 0.1 .. 2 gives +1 .. +5 over `need`, rising with w, leave-one-season-out +3 +/- 2 (was +0 +/- 1); still not adopted.

## 2026-10-25 — Prior-season weekly volatility tested as a model feature: not adopted (QB/TE null, WR +0.01 is below the detectable gap)
**Decision:** the `volatility` group (weekly SD, SD per point of mean, share of 20+ PPR weeks, prior season, >= 4 games) stays in `ADVANCED_GROUPS` as a
tested candidate but is in no position's model. Run with `advanced_features.py volatility`, 10 seeds, top-150 Spearman, 2021-2025. User chose this after
the risk-predictability study showed a weak upside-only QB/TE effect.
**Why:** QB 0.310 -> 0.301 (-0.009; the random-noise control gave -0.009), TE 0.403 -> 0.395 (-0.008; noise -0.007), so the hypothesis behind the test fails.
RB +0.003 (noise -0.001). WR 0.510 -> 0.521 (+0.012, better in 10/10 seeds, RMSE -0.6, noise control +0.002): consistent across training seeds but under the
~0.03 gap that 5 test seasons can detect, and seeds only measure training randomness, so it is dropped under the standing rule.
**Open:** WR is the one cell worth a second look if more test seasons exist (2026 results in Phase 3); an a-priori reason for volatility to help WR but not QB/TE
is missing, which argues for caution.

## 2026-10-25 — Player-level risk is not predictable from prior-season weekly volatility (adaptive risk has no signal)
**Decision:** no per-player risk field is exported to the projection files. `src/evaluation/risk_predictability.py` tested whether prior-season weekly
SD, CV, boom rate (>= 20 pts), bust rate (<= 5 pts) and games missed predict the next season's miss from the model projection (absolute, downside,
upside) and its weekly SD, as partial Spearman after removing projection level and games played; 720 player-seasons (top 150 by ADP, >= 6 prior games,
2021-2025). User chose the predictability check before building any risk component.
**Why:** RB and WR (most of the picks) show nothing: |r| <= 0.08 on every miss target, signs flip across seasons (2-4 of 5 agree). Games missed predicts
nothing anywhere. Only QB and TE show anything: prior SD vs upside +0.20 (QB) and +0.18 (TE), TE weekly-SD persistence +0.27; the effect is on the upside
side (the model under-projects volatile QBs/TEs), not the downside that a "floor" rule would protect, and with about 140 players per position (SE about
0.1) and 80 correlations tested, a few at 2 SE are expected by chance.
**Alternative kept open:** the user also chose a league-finish metric (head-to-head weekly matchups) as the objective under which risk could matter;
not built yet. Without a player-level signal, adaptive risk would be a position-only rule (QB spread is larger than TE's), which the position RMSE already encodes.

## 2026-10-22 — Cost of waiting (VONA bonus) tested and not adopted; `need` stays the default
**Decision:** `WaitSettings` adds w x E[max(0, value - best same-position player who lasts to my next pick)] to the `need` score (survival =
Normal CDF of (ADP - next pick) / (2 + 0.16 x ADP); alternatives are everyone still available, not the 4-sigma window, which is measured at the current
pick and hid them; independent survivals, best alternative first). Default is off (`wait` null); `tune-wait` sweeps w. User chose this over a
two-step lookahead and a tier-count rule.
**Why not adopted (weekly scoring, rules on, 40 seeds, noise x1, 2400 drafts per arm):** need 2208 (+43 over ADP 2165); w = 0.1 / 0.25 / 0.5 / 1 / 2 gives
2209 / 2211 / 2211 / 2210 / 2211, i.e. +1 to +3 with a paired SE of about 4 against ADP and no trend in w; leave-one-season-out gain over need +0 +/- 1.
It is not a no-op: it changes 8/320 picks at w = 0.5 and 17/320 at w = 2 (2024 probe), mostly round 4-10: a scarce QB/TE or RB a little earlier,
or one of two near-equal WRs. The reach cost (lambda 1000) already pins the drafter near ADP, and lineup gain is measured over replacement level, so
scarcity is mostly priced already.
**Known simplification:** an alternative's value is measured against the current roster, not the roster after taking the candidate. *(Corrected 2026-10-25: for the "I wait" branch the current
roster is the right one, since without him on it the later pick is valued without him; the after-pick roster would measure taking him and then the alternative, a different quantity.
The real simplification is the one-pick horizon.)*
**Next:** position safety is the same signal (survival to my next pick), so expect the same null; try it only inside a different framing (e.g. when the
reach cost is relaxed). Test: `WaitTests`.

## 2026-10-22 — Bench value settled: structural weights + option value over the waiver level + dead-pick exclusion is the default `need`
**Decision:** `NeedSettings.Default` is now `Option`: lineup gain, plus the k-th-backup weight P(Binomial(S, q) >= k) (q = 0.23) times the option value
E[max(0, X - waiver)] of the part of the player that does not start (X ~ Normal(projection, position RMSE), waiver = best undrafted projection
at the position, capped at replacement), and any player with zero lineup gain AND zero backup weight is a dead pick (score offset -1,000,000, so
he is chosen only if nothing else exists). `NoBench` (lineup gain only) remains as a comparison arm. User choice: waiver level + option value.
**Why / results (weekly scoring, 40 seeds, calibrated noise):** rules lifted for the drafter: option q=0.23 2210 (+94 over ADP 2115) vs no bench 2167
(+52) vs value 2155 (+40); structural-without-option 2207, so the option value itself adds ~3 (noise) and the structural weights plus the
dead-pick exclusion carry the gain; q hardly matters (0.15 / 0.23 / 0.35: 2210 / 2210 / 2207); flat weights do not help (flat 0.25 2163, flat
option 2153 and 2116). Beats no-bench in every configuration: rules on +16 (2208 vs 2192), season-total scoring +20, noise x0.5 +56, x2 +16, x3 +10
(all vs ADP-relative same arms), and wins all five seasons with the rules lifted (+73 / +26 / +30 / +24 / +60). Default full backtest (100 seeds,
rules on, noise x1): need 2212 (+48 +/- 2.3, wins every season) vs value 2198 (+34), ADP 2164. Edge over ADP vs opponent noise (rules lifted): +49 at
x2, -26 at x3, so break-even is about x2.5 the calibrated noise. Leave-one-season-out over all arms: +14 +/- 28 vs no bench, +66 +/- 42 vs ADP.
**Roster construction (rules lifted, 2024 / 2025):** QBs per team 2.0 / 2.2 (ADP 3.8 / 4.4), TEs 2.0 / 2.0, RBs 5.0 / 4.8, WRs 7.0 / 6.9; the earlier
version drafted 3.6-4.5 QBs. The first cause I tested was wrong: a gentler reach cost (lambda 10-300) did not change the QB count. Opponents cap
QB/TE at 2, so surplus QBs and TEs slide past their ADP and look free to a reach-averse drafter, and by round 15 every candidate is worth about 0;
only an explicit "this player can never be needed" signal stops the third QB.
**Caveats:** the option-value term assumes a normal projection error and a crude waiver level; late picks are lottery tickets the point
projection cannot rank well; weekly lineups are hindsight-optimal.

## 2026-10-22 — Position-specific bench value explored; weekly-lineup scoring added; the structural rule alone is harmless but cannot act
**Decision:** (1) rosters are now scored by the best lineup each week from actual weekly PPR (backtest files carry an optional
`weekly_ppr`, 18 weeks, null where the player did not play; it sums exactly to `actual_ppr` for all 10,044 player-seasons), because season
totals cannot see depth. `--season-totals true` keeps the old scoring. (2) `NeedSettings.Structural` implements the user-approved structural
bench rule: with q = P(a starter is out in a given week) = 0.23 (draftable players missed 3.1 of 17 games, nearly equal across QB 2.9, RB 3.2,
WR 3.1, TE 3.1, plus one bye in 18) and S = the slots a backup could fill (QB 1, TE 1, RB 2 + FLEX, WR 3 + FLEX), the k-th backup is worth
P(Binomial(S, q) >= k) of his non-lineup VOR: first backup QB/TE 0.23, second 0, first RB 0.54, first WR 0.65.
**Why the user asked:** the season-total sim could not value depth, and the roster-need recommender drafted 2-3 backup QBs/TEs in a mock
draft, which is bad roster construction; beta = 0 winning looked like an artifact of how we scored, not evidence depth is worthless.
**Results (weekly scoring, 40 seeds, rules lifted for the drafter):** need with no bench value 2167 (+52 +/- 4 over ADP 2115), structural
q=0.15 / 0.23 / 0.35: 2165 / 2165 / 2163, scale x0.5 and x2: 2165 / 2162, flat 0.25: 2163, `value`: 2155. Held-out gain of the best arm
over no bench: -2 +/- 2. Depth is worth almost nothing in aggregate even with weekly lineups. Baselines under weekly scoring (100 seeds, rules
on, noise x1): ADP 2164, VOR -118, old recommender -326, windowed -33, value +34, need +35 (season totals were +27 / +30): every conclusion
survives, edges slightly larger.
**What it did NOT fix:** with the rules lifted, need and the structural rule still draft 3.6 QBs and 2.6 TEs per team (ADP 3.8 / 2.6). Cause
(seen in a mock draft): VOR is measured against starter-level replacement (e.g. the 13th QB), so by round 11 every remaining player has VOR <= 0;
every bench candidate is worth 0, the k-th-backup weights multiply 0, and the pick falls back to the reach cost, i.e. ADP order. A third QB
(weight 0.00) is still taken because nothing else scores above 0.
**Open options (resolved in the entry above):** value a bench player against the WAIVER level (best undrafted player at the position, which is much higher for QB/TE than
for RB/WR) with an option-value term E[max(0, X - waiver)], X ~ N(projection, position RMSE), times the k-th-backup weight; or a tie-break
that prefers positions with a larger weight among zero-value candidates; or hard caps. **Rejected so far:** fitting four per-position bench
fractions on the season-total sim (it returns zeros). **See:** `LineupScorer.ScoreWeekly`, `NeedSettings.Weight`, `tune-bench`.

## 2026-10-22 — Roster need (Phase 4 step 2): lineup gain over replacement, no bench value; makes the recommender self-sufficient
**Decision:** the `need` variant values a player at the points he adds to the team's best lineup (1 QB / 2 RB / 3 WR / 1 TE / 1 FLEX,
open slots filled by replacement-level "ghosts", so a first RB is worth his full VOR and a redundant QB is worth 0), plus a bench
fraction beta of the part of his VOR that does not improve the lineup, minus the same reach cost. Provisional default beta = 0, lambda
1000, cap 4 sigma. beta = 1 reproduces the plain single-score recommender (`value`), so the sweep includes the previous step as its control.
**Why (40 seeds, calibrated noise x1, 15 arms):** two setups, as the user asked. Simulator rules ON (caps of 2 QB / 2 TE, forced starters
after round 10, for every drafter): need b=0 1820 vs value 1816 vs ADP 1796, no measurable difference (leave-one-season-out -3 +/- 10),
because the rules already supply the discipline. Rules LIFTED for the drafter only: ADP 1770, value 1789 (it stacks redundant players),
need b=0 1811 (+41 +/- 4 over ADP): need recovers 20 of the 27 points the rules were worth, so it is self-sufficient (leave-one-season-out
+10 +/- 11 vs value, +30 +/- 29 vs ADP). The result is monotone in beta (0 > 0.1 > 0.25 > 0.5 > 1), i.e. bench value hurts in the sim.
**Robustness (rules lifted):** need is +44 / +41 / +48 / +26 over ADP at opponent noise x0.5 / x1 / x1.5 / x2 and -4 at x3 (break-even about
x2.9 of the calibrated noise), against value's +34 / +20 / +7 / -32 / -110: need roughly doubles the noise margin (x1.65 -> x2.9).
With rules on, full backtest (100 seeds, noise x1): need 1827 (+30 +/- 2) vs value 1823 (+27), ADP 1796.
**Product caveat:** with beta = 0, late bench picks have no value and fall back to ADP order, so an unconstrained mock draft still takes
2-3 backup QBs/TEs. The sim is indifferent to that (season-total scoring has no bye weeks or injuries); position-specific bench values were
rejected as four more parameters on five seasons. **Rejected:** a ramp by round (the lineup gain is already ~VOR early and ~0 late),
hard position rules inside the recommender. **See:** `LineupValue.cs`, `ValueRecommender.cs`, `tune-need`.

## 2026-10-21 — Opponent noise calibrated against real drafts: bias SD = 1 + 0.12 x ADP (was 1 + 0.10 x ADP)
**Decision:** the simulator's opponent bias SD default is now 1 pick + 0.12 per ADP slot. This supersedes the earlier "cannot be
calibrated" note in the simulator-design entry and the noise caveat in the single-score entry; ADP/VOR/recommender baselines were rerun.
**How the sim was compared with reality:** Fantasy Football Calculator's public ADP API (`src/data/ffc_scraper.py`, cached in
`data/raw/ffc`) reports, per player, the mean pick and the SD of his pick across 1,371-8,470 real 12-team PPR mock drafts per season
(2021-2025, all in the days before the opener). That SD (about 0.108 x ADP: 1.1 picks at ADP 3, 3.0 at 18, 5.4 at 48, 9.5 at 102, the
same every year) is compared with the SD of each player's pick across seeded all-bot simulated drafts (`calibrate-noise`), by ADP
bucket. The BIAS parameter is not the observable: the realized pick spread comes out of 11 independent biases plus availability, so
the old setting (1 + 0.1 x ADP) produced only 0.84x the real spread (1.02x at the top, 0.75x deep). A grid fit (`fit-noise`) over base
and slope gave 1 + 0.12 x ADP, within 0.90-1.06x of real in every bucket (rms log ratio 0.074 vs 0.197). The cross-platform SD
(0.16 x ADP) used earlier was NOT the right target: it mixes platform quirks with draft-to-draft spread.
**Effect (100 seeds, noise x1 = calibrated):** ADP 1796, pure VOR -122, old recommender -294, windowed -59, single-score `value`
+27 +/- 2 (wins 4 of 5 seasons; 2025 is -10). The lambda plateau is wide (lambda 400 and up: +16 to +23; best 1000). The edge fades
with opponent noise: +22 at x1.25, +12 at x1.5, -7 at x1.75, -19 at x2, so break-even is about 1.65x the calibrated noise, a margin
larger than the fit error (~7-20%).
**Caveats:** FFC drafters are hobbyists in mock lobbies (some auto-drafting), not necessarily your league; real drafters also reach
for positional needs, which the bots only imitate through caps. The calibration fixes spread, not correlated behavior (runs).
**Rejected:** keeping a guessed noise; matching the bias parameter to the cross-platform SD. **See:** `NoiseCalibration.cs`.

## 2026-10-21 — Single-score recommender (Phase 4 step 1): beats everything but ADP is not beaten robustly
**Decision:** the position-first step is replaced, as a new `value` variant beside the old ones, by one score across all players:
score = projected VOR (points over replacement) - lambda x z^2 (reach cost in points, z in sigmas past the pick, sigma = 2 + 0.16 x
pick) with the same far cap at 4 sigma. The old rank and ADP-gap terms (position-relative) and the injury-risk penalty are dropped;
roster need is NOT in it yet (step 2, measured separately). Provisional default lambda = 1000, cap 4.
**Why / results (5 seasons x 12 slots x 60-100 seeds):** lambda sweep at opponent noise x1: 0 -> 1689 (-104 vs ADP), 10 -> 1757, 100 ->
1793 (ADP), 400 -> 1810, 1000 -> 1814 (+21 +/- 3, beats ADP in 4 of 5 seasons; 2025 is -36), 10000 -> 1803, infinity -> 1799 (+6).
At the default over 100 seeds: +31 / +25 / -1 vs ADP at noise x0.5 / x1 / x2 (windowed -57 / -59 / -66, old recommender -271 / -288 /
-315). Leave-one-season-out: +16 +/- 22 vs ADP, +80 +/- 45 vs windowed.
**Robustness caveat (superseded by the calibration entry above, which puts the real noise near x1 and the break-even near x1.65):** the edge depends on the simulator's opponents following ADP closely. At noise x2 (closer to the
measured platform spread, 0.16 x ADP vs the x1 assumption 1 + 0.1 x ADP) the best lambda is infinity and the gain is +3 +/- 3; at x4
every lambda loses ~91 points to ADP. The model's VOR adds nothing beyond ADP when players slide at random, consistent with Phase 1.
So: a large improvement over the old recommender (+300), not yet a robust edge over plain ADP. The optimal lambda is so high that
a player one pick past his ADP is penalized ~100 points, much stricter than the user's intuition that reaching is not strictly bad.
**Next:** roster need as its own step; calibrate the opponent noise (the biggest unknown); lambda is only meaningful relative to it.
**See:** `ValueRecommender.cs`, `tune-value --noise`, `draft --recommender value`.

## 2026-10-21 — Fixed: playoff weeks in expected-points features; dead `passing_cpoe_delta` column
**Decision:** `build_xfp_features` keeps regular-season weeks only (<= 17 through 2020, <= 18 from 2021); `passing_cpoe_delta` is
dropped from the RB/WR/TE models. Found while explaining points-over-expected; the user asked to fix mistakes as they are found.
**Why / effect:** playoff rows were ~3% of `ff_opportunity`, so `xfp_ppr_prev`, `xfp_pg_prev` and `fp_over_exp_prev` were inflated for
playoff teams, inconsistent with every other (regular-season) feature. Full rebuild (pipeline, OOS, benchmark, predict, vor, export):
no measurable change (see STATUS.md). Unit test `test_xfp_features_ignore_playoff_weeks`; the integrity test now recomputes xfp on
regular-season weeks. **Not decided:** whether to build efficiency-rate / volume-sustainability features (see the Robinson case study
in STATUS.md); the user is only exploring.

## 2026-10-21 — 2025 investigation: the recommender's position rule, not the model, drives the big swings
**Decision:** treat the recommender's position step (scarcity = unfilled league slots / players in the best tier) as the thing
to replace in Phase 4; the model's player ranking is fine and roughly ADP-neutral.
**Why:** windowed lost 243 points to ADP in 2025 (1549 vs 1792). (1) The model was not worse that year: Spearman vs actual in the
top 150 was 0.451 model vs 0.379 ADP, edge-vs-market correlation +0.13, RMSE 78.8 vs ADP-curve 77.0 (same gap as 2022/2024).
(2) 2025 was a positional outlier: the first 12 RBs by ADP averaged 293 actual points (215-258 other years), 5 boomed; RB minus WR
was +72 (others -52 to +14); 4 of the top 12 WRs busted; early QBs fell 98 under the ADP curve. (3) With tiers this small every
position has one player in its best tier, so scarcity just picks the position with the most unfilled slots (WR, 3 slots), so
windowed drafts 2.7 RBs and 9.3 WRs per team (ADP: 5.4 and 6.6) and its rounds 1-3 average 174 actual points vs 262.
(4) Decomposition, mean starter points per season (2021..2025): ADP 1801/1747/1780/1846/1802; windowed 1813/1676/1833/1882/1556;
recommender chooses the position and ADP the player 1874/1595/1787/1931/1578; ADP chooses the position and the recommender the
player 1795/1793/1813/1792/1768 (mean 1792 vs ADP 1795). The position rule reproduces the swings; the player rule alone never
strays far from ADP. So the 5-season mean deficit is a high-variance WR-heavy bet that paid in 2021/2023/2024 and lost in 2022/2025.
**Model miss, smaller:** McCaffrey (ADP 8, flagged after a 4-game season) was projected 169 and scored 417, about 49 of the points.
**Caveat:** 5 seasons; the RB-WR gap and windowed's result agree in 4 of 5 years (2022 does not fit). **See:** `diagnose`,
`decompose` (`PickDiagnostics.cs`).

## 2026-10-21 — Reach control: soft penalty on ADP reach plus a far hard cap (provisional default l=0.3, cap 4 sigma)
**Decision:** the recommender gets an optional `ReachSettings`. A player whose ADP is later than the current pick is a reach of
z = (ADP - pick) / sigma(pick) with sigma = 2 + 0.16 x pick; the score loses lambda x z^2; players past `cap` sigma leave the
pool for BOTH the position step and the player step (a position with nobody left cannot be chosen). Slid players (ADP before the
pick) are never penalized. Added as a variant (`windowed`) beside the untouched baseline (`recommender`).
**Why:** the user saw the first pick recommend ADP 70-112 players at pick 6 (the `value_gap` term is itself a bonus for late
ADP) and wanted a window that widens later in the draft, but a hard border would rule out a player the model loves that sits just
outside it. The spread is measured: cross-platform SD of ADP (ESPN, Sleeper, NFL, RTSports... in the cached FantasyPros pages,
2021-2025) is 0.8 picks at ADP 1-6, 4.5 at 24-36, 14 at 84-120, 29 at 160-200, about 0.16 x ADP. That is a lower bound for the
spread inside one draft, which is a second reason for a soft penalty (a too-tight sigma costs little).
**Sweep (30 seeds x 12 slots x 5 seasons, noise x1, 30 arms):** baseline recommender 1547; the cap alone (lambda 0) 1672-1730;
cap plus penalty 1724-1760, best around lambda 0.1-0.3, cap 3-4, with or without the gap term; plain ADP 1792. A plateau, not a
peak. Leave-one-season-out gain over the baseline +154 +/- 69; still -90 +/- 48 vs ADP because the chosen arm changes by fold.
At the default (100 seeds, noise x0.5 / x1 / x2): windowed 1743 / 1755 / 1788 vs ADP 1772 / 1796 / 1853 (-28 / -41 / -66 +/- 3).
By season at noise x1 it beats ADP in 2021 (+23), 2023 (+52), 2024 (+39) and loses in 2022 (-75) and 2025 (-243).
**Rejected:** a hard band (cliff; the user's Barkley example), round-based steps, shrinking projections toward ADP (bigger change).
**Open:** it still does not beat ADP; 2025 is a large miss; the position step still loops (see the mock-draft entry). The
spread constants and the default are unvalidated. The simulator's opponent noise (1 + 0.1 x ADP) is below the measured
cross-platform spread (0.16 x ADP) and probably too tame. **See:** `ReachSettings`, `ReachTuning.cs`, `tune-reach`.

## 2026-10-21 — Mock draft tool; it exposed that the recommender drafts quarterbacks without end
**Decision:** added `draft` (interactive mock draft, past seasons only, simulated opponents, reasoning shown each turn). It
exposes the recommender's scarcity numbers and score components through `BaselineRecommender.ChoosePosition` and
`Candidate.RankTerm/GapTerm/Penalty`; behavior is unchanged (simulator result identical before and after).
**What it showed (2024, slot 6, always taking its #1):** the recommender takes 7 QBs (rounds 8, 9, 11, 13-16) and 2 TEs. The
simulator's cap of 2 QBs hid this by turning those picks into best-VOR fallbacks, so the simulated "recommender" is already
better than the raw one. At pick 6 every position has one player in its best tier, so "scarcity" is just unfilled league slots
per position and WR wins; it then takes an ADP-78 WR (K.Allen) over A.St. Brown (ADP 6) and Jefferson (VOR 124).
**See:** `csharp/src/DraftBot.Sim/MockDraft.cs`, `MockDraftTests.cs`.

## 2026-10-21 — Regret per round: hindsight mostly measures luck; foresight shows where strategies deviate
**Decision:** regret is reported three ways per pick, against the best LEGAL available player (roster rules respected): hindsight
actual points, hindsight over replacement (actual minus the position's actual-points replacement level, same FLEX rule), and
foresight projected VOR. Only the strategy's own picks count. CSV: `data/processed/sim_regret.csv`.
**Why / what it showed (noise x1, mean per draft):** hindsight regret is ~120-230 points per pick in every round, even round
16, because the best available player in hindsight is always some breakout; it separates the recommender (2751 total) from
ADP (2487) and VOR (2411) but not ADP from VOR, even though ADP scores 100 points more. Use it for early-round comparisons, not
as a headline. Foresight: VOR is 0 by construction, ADP gives up 38 VOR per pick (608 total), the recommender 259 total with
52 in round 1 and ~0 by round 14, so its damage is early reaching. **Rejected:** a single regret definition; foresight alone
(says nothing about outcomes), hindsight alone (luck).

## 2026-10-21 — Tier threshold k = 0.10 (was 0.20): gap-based tiers show no real cliff signal
**Decision:** default tier threshold is 0.10 x position RMSE (about 13 tiers per position, largest tier 34% of the pool).
**Why:** `tune-tiers` scores each k by adjusted R2 of actual points on tier labels MINUS the same score for equal-size tiers
of the same count (raw adjusted R2 just rises as tiers get finer, so it cannot pick k). Leave-one-season-out picks k = 0.03
(~26 tiers per position, about 1.5 players each), gain over 0.20 +0.13 +/- 0.08, negative in 2 of 5 held-out seasons, so not
a usable tier count. At usable counts (4-8 tiers, k 0.15-0.25) gap tiers do WORSE than equal-size tiers (k = 0.20: -0.12)
because they leave one giant tail tier (79% of players); only TE shows a consistent cliff signal (+0.06 at k 0.10-0.25). At
k = 0.10 the advantage is about zero (+0.014), and the recommender gains ~40 points over 0.20 (1547 vs 1511 at noise x1);
anything <= 0.10 gives the same gain, none closes the 250-point gap to ADP. User chose 0.10 over the procedure's 0.03.
**Rejected:** per-position k (more search space than 5 seasons support), 0.03, keeping 0.20.
**Open:** projection-gap tiers are not clearly better than quantile tiers; Phase 4 can test equal-size or capped-size tiers.

## 2026-10-21 — Phase 2 baseline: plain ADP beats pure VOR and the current recommender
**Decision:** Phase 4 must beat plain ADP drafting, not the old recommender (which is the floor, not the bar).
**Why:** 5 backtest seasons x 12 draft slots x 100 opponent seeds (6,000 drafts per strategy per noise level), same opponents
for every strategy. Mean starter points / mean league finish of 12 at opponent noise x1: ADP 1796 / 5.8, pure VOR 1694 / 7.7
(-102 +/- 3), current recommender 1547 / 10.3 (-249 +/- 3) (1511 / 10.9, -284, before the tier threshold moved to 0.10); the
order held at noise x0.5 and x2. VOR beat ADP in 2021 and 2022
but lost by 237 in 2023, so VOR vs ADP is season-dependent. The recommender's half-weight on ADP minus VOR rank rewards
reaching for players the model likes (traced: TE with ADP 257 in round 5). Python does the same: first recommendation on the live data is a TE
(H.Henry, ADP 162). This agrees with Phase 1: the model does not beat ADP, so disagreeing with ADP costs points.
**Caveats:** SEs treat drafts as independent; the opponent noise scale is a guess (hence the x0.5/x1/x2 sweep); lineups use
season totals, not weekly. **See:** `csharp/src/DraftBot.Sim`, `data/processed/sim_baseline.csv`.

## 2026-10-21 — Projection file: JSON, pure model, backtests share the live schema
**Decision:** C# reads `projections_<season>_v1.json` (header + players). `projected_ppr` is the pure model (or the ADP-curve
estimate for market rows). Each backtest season is exported in the same schema plus `actual_ppr`, with the ADP-curve rows
fit leaving that season out.
**Why:** JSON needs no NuGet package and carries file-level metadata (schema version, per-position RMSE); the roadmap
diagram already said JSON. Pure model first so the 50/50 model+curve blend (0.7-1.7% lower RMSE) can be tested in the
simulator as a clean change. Same schema means the simulator runs the code the app ships.
**Rejected:** Parquet via Parquet.Net, CSV, shipping the blend now, a separate backtest schema.
**Schema fixes made on the way:** the doc defined `injury_flag` as `games < 13 and games_delta < -5`, but the code's
`injury_flag` (used by the recommender) is a durability flag (average under 15 games over >= 2 qualifying seasons; 40-50% of
the pool carries it) and the doc's rule was the `availability_flag`. The file now carries the durability flag; C# derives
availability from `games` / `games_delta`. Backtest flags are recomputed point-in-time and match the live pipeline's flags
on all 256 modeled players. Teams with no club on file (pre-draft rookies `TBD`, unsigned `FA`, `-`) export as `FA`.

## 2026-10-21 — Backtest pool: ADP rank <= 300, zero-game players score 0
**Decision:** the backtest pool is the ADP-ranked skill players (~233-245 per season); rookies and unmodeled players are
included as `market_estimate` rows; a drafted player with no stats row (injured all year) scores 0 instead of being dropped.
**Why:** mirrors the live advisor table. Dropping zero-game players removes busts like Michael Thomas (ADP 75, 2021) and Joe
Mixon (ADP 76, 2025) and makes simulated rosters score higher than real ones (0-6 players per season). **Rejected:** the
Phase 1 benchmark's rule of excluding unscoreable players (right for ranking metrics, wrong for a drafter's roster).

## 2026-10-21 — Simulator design: per-opponent bias, noise sweep, season-total lineups
**Decision:** each opponent draws a fixed bias per player ~ N(0, 1 + 0.1 x ADP) once and picks the best ADP + bias among
legal players; every drafter has position caps (2 QB, 2 TE) and must fill open starter slots after round 10. Rosters are
scored by the best lineup from actual season PPR; strategies face identical opponents (seeded by seed and team).
**Why:** a personal bias models teams that like a player more than consensus, without per-pick randomness washing it out. We
have only mean ADP, so the spread cannot be calibrated; the experiment reruns at half and double the noise. Season totals
need only data we have. **Rejected:** per-pick Gaussian noise, fixed SD, weekly lineups (bye weeks and injuries, needs a
weekly export; can be added behind the same scorer).

## 2026-10-21 — Replacement level by greedy FLEX fill, tiers by RMSE-scaled dropoff
**Decision:** dedicated starters = teams x slots; the league's FLEX slots go to the best remaining RB/WR/TE by projection;
replacement is the first non-starter. Tiers are per position: a new tier starts where the projection drops by more than
0.2 x that position's RMSE (live file tier sizes: QB 5/18/16/2, RB 2/1/1/9/76, WR 2/2/1/118, TE 1/4/4/28/7/3). Later changed to 0.10, see
the tier-threshold entry above.
**Why:** adapts to any slot counts. For the default league it gives 12 QB / 30 RB / 42 WR / 12 TE starters, so replacement is
the 31st RB and 43rd WR, one deeper than the old hardcoded RB 30 / WR 42 (which treated the 30th RB as replacement while
QB 13 / TE 13 were first non-starters). The 0.2 was untuned and ended in one very large last tier at RB and WR. **Rejected:** fixed FLEX split, bench-aware replacement, anchored bands, Jenks natural breaks.
**Port notes:** the recommender keeps its Python quirks (FLEX counts as filled once the RB/WR/TE core slots fill; per-bench
count off by one until then); the only change is that no FLEX need appears when the league has no FLEX slot.

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
- **Week 1 line as a preseason team-strength signal** (user may try later): the Week 1 spread/total, already in the
  schedule data, is the closest legitimate preseason market number (the old full-season average leaked). Test it for
  QB first. Expected value is low for RB/WR/TE: even the leaky in-season total was worth only +0.007 to +0.027
  there (QB: 0.61 leaky vs 0.23 prior-season). Preseason win totals would need a new data source (not in nflverse)
  and overlap with what ADP already prices. Rank it below coaching tendencies.
- **Coaching tendencies** (head-coach pass-over-expected, pace, 4th-down aggression, using the coach's prior team's
  tendency when the HC changes): the user wants to scope it carefully before any work. Only head coaches are public.
