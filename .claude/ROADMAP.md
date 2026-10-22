# DraftBot Roadmap (Oct 2026 to Aug 2027)

**Created:** 2026-10-20
**Target:** usable for my real draft in August 2027
**Companion docs:** `STATUS.md` (current state), `plan.txt` (original advisor spec)

---

## Goals

1. **A tool I can hand to friends and beginners** that helps them make better picks and explains why.
2. **Portfolio piece** showing both halves of my stack: Python/ML research and a .NET desktop product.
3. **Long term:** projections with real predictive power, meaning they rank players better than the market (ADP) does.

Out of scope: weekly projections and in-season tools (too noisy to be useful), Mac support (Windows only for now), web hosting.

---

## Architecture Decisions

**Python is the research side.** Data, features, training and evaluation run locally. The output is a versioned projection file. Python does not run on users' machines.

**C# is the product.** All draft-time logic (VOR, tiers, recommender, draft state, simulator) lives in .NET. The simulator and the desktop app share the same core library, so the code that gets evaluated is the code friends actually run.

```
Python (local)                        C# solution
-----------------                     ------------------------------
scraper / pipeline                    DraftBot.Core     (league settings, draft state,
features / train / predict   ---->                       VOR, tiers, recommender)
  exports:                  JSON      DraftBot.Sim      (console simulator, backtests)
  - projections_<year>_vN             DraftBot.Desktop  (WPF + BlazorWebView UI)
  - season files (backtest)
```

**The projection file schema is the contract.** Define and version it early. Python writes it; C# never needs to know how it was made. Minimum fields: player id, name, position, team, projected points per scoring format (PPR / half / standard), games, per-position RMSE, ADP, flags (availability, rookie/market estimate).

**League settings drive the math in C#.** Replacement levels, VOR, tiers and ceiling/floor are computed from each user's team count and roster slots instead of hardcoded constants.

**Distribution.** Self-contained single-file publish on GitHub Releases. Velopack for auto-updates. New projection files published as release assets; app checks for updates on launch. Unsigned for now (users click "More info, Run anyway" on SmartScreen); revisit code signing later.

**Scoring formats.** PPR, half-PPR and standard only. They differ only by receptions, so either train the same pipeline on each target or add a receptions model. Custom scoring (TE premium, 6pt pass TD) would need component-stat projections; deferred. Superflex/2QB is roster-only and needs no model change.

**Rookies.** No college model for now. Fall back to an ADP-to-points curve fit per position from historical season files, flagged as "market estimate, no NFL data." Same fallback covers any veteran the model misses.

---

## Success Metrics

**Projections:** on each held-out season, compare rank correlation (Spearman) of my projections vs actual points against ADP vs actual points, overall and per position, and within the top ~150 (the draftable range). Beating ADP is the bar.

**Recommender:** in simulated drafts scored with actual season stats, compare starter points and simulated league finish against baseline bots (pure ADP, pure VOR, current recommender). Track regret (best available pick value minus chosen pick value) per round.

---

## Phases

### Phase 0: Housekeeping (done 2026-10)
- [x] Fix `config/settings.yaml` (3 WR, 8 bench, no K/DST, correct seasons)
- [x] Fix README drift (`recommend.py` vs `recommender.py`, Vegas totals claim)
- [x] Move dead scaffolds (`vbd.py`, `simulator.py`, `app/cli.py`) to an `archive/` folder or delete
- [x] Draft projection file schema v1 (`.claude/projection_schema_v1.md`; the exporter itself is not written yet, see Phase 2)

### Phase 1: Evaluation data (done 2026-10)
- [x] ~~Check nflverse/ffverse historical ECR~~ Skipped by decision: the user chose scraped historical ADP over expert rankings.
- [x] Wayback Machine ADP scraper (`src/data/adp_scraper.py`): FantasyPros PPR consensus ADP, 2021–2025, snapshot closest to (and not after) the day before each season's opener; one CSV per season in `data/external/adp_<year>.csv`. (Fantasy Football Calculator was tried and rejected.)
- [x] Walk-forward out-of-sample predictions (`src/evaluation/oos_predictions.py`, 5 seeds; kept separate from `train.py`)
- [x] One season file per held-out season: `data/processed/season_<year>.parquet` (OOS projections + actuals) joined to `adp_<year>.csv` on `player_id`
- [x] First benchmark (`src/evaluation/benchmark.py`): the model trails ADP on top-150 Spearman at every position (QB −0.10, RB −0.05, WR −0.06, TE −0.01), beats a last-year-PPR baseline everywhere, and matches ADP's ranking over all players for RB/WR/TE. Numbers and caveats in `STATUS.md`.

Also done in Phase 1 (unplanned, but it changed the results): fixed a target-season leak in `implied_total` and several silent data bugs; built a validation layer, feature manifest, run manifest, integrity tests, pre-commit hook and CI workflow; ablated ~12 feature ideas (two survived: RB vacated volume and QB attempt share, plus the process features in `STATUS.md`).

### Phase 2: C# core and simulator (done 2026-10; planned Dec 2026 to Jan 2027)
- [x] Python projection exporter (`src/data/export_projections.py`): `projections_<season>_v1.json` for the live season plus one backtest file per held-out season 2021-2025 (same schema + `actual_ppr`), validated by `validate.py`. Schema finalized as JSON in `.claude/projection_schema_v1.md`
- [x] Solution `csharp/DraftBot.sln` with `DraftBot.Core`, `DraftBot.Sim`, `DraftBot.Tests` (net9.0, xUnit)
- [x] League settings model; replacement level (greedy FLEX fill), VOR, per-position tiers by value dropoff (new tier where the projection drops by more than 0.10 x position RMSE; tuned in Phase 2 follow-up, see `LOG.md`)
- [x] Draft state (snake order, all rosters, pool)
- [x] Port the current recommender as the baseline (same rules, new inputs; not output-identical to Python because VOR and tiers changed)
- [x] Simulator: opponents draft by ADP plus a per-opponent bias per player, with position caps and forced starter fill; rosters scored with actual points (best lineup each week from weekly PPR; season totals available via `--season-totals`)
- [x] Baseline results for pure ADP, pure VOR and the current recommender. **Plain ADP wins; the current recommender is last** (numbers in `STATUS.md` and `LOG.md`)
- [x] Regret per round (hindsight actual, hindsight over replacement, foresight VOR) added to the simulator

### Phase 3: Model v2 (Jan to Feb 2027, after the 2026 regular season ends)
- [ ] Grade 2026 projections and recommendations against real 2026 results
- [ ] Pull 2026 data, retrain
- [x] Team-context features: done early, in Phase 1. Joined on the player's current (start-of-season roster) team and lagged. Only survivors are in the model; team pass rate/pace/EPA, QB quality on receivers, depth ranks within team and OL features all tested null (see `STATUS.md`). Remaining here: re-check with 2026 data
- [ ] Half-PPR and standard targets
- [x] ADP-to-points fallback curve for rookies and missing players: done in Phase 1 (`src/draft/market_fallback.py`, rows flagged `market_estimate`)

### Phase 4: Recommender v2 (Feb to Apr 2027; started early, 2026-10)
- [x] Single score across all available players (replaces position-first selection): `value` variant = VOR minus an ADP-reach cost (done 2026-10-21, see `LOG.md`). Roster need and bench value then made it the `need` recommender, +48 over ADP in the simulator
- [ ] Add components one at a time; keep each only if the simulator shows improvement:
  - roster need (nonlinear, ramps up mid-draft): done 2026-10-22 as marginal lineup gain over replacement plus position-specific bench value (structural k-th-backup weights, option value over the waiver level, dead-pick exclusion), see `LOG.md`
  - tier cliff / cost of waiting until next pick (not started)
  - position safety (P(player survives to my next pick) from teams picking in between)
  - run detection (continuous intensity)
  - adaptive risk by round (floor early, ceiling mid, variance late)
- [ ] Reasoning strings that explain each recommendation in plain language for beginners

### Phase 5: Desktop app (Apr to Jun 2027)
- [ ] WPF + BlazorWebView shell
- [ ] League setup screen (teams, roster slots, scoring format, draft slot)
- [ ] Draft board: available players, my roster, all rosters, top recommendations with reasoning
- [ ] Live sync with Sleeper's public read-only draft picks API (poll by draft id)
- [ ] Manual entry mode for ESPN/Yahoo, with fuzzy name search and bulk paste
- [ ] Projection file update check

### Phase 6: Release (Jul 2027)
- [ ] Final 2027 projections after the NFL draft, free agency and camps settle
- [ ] Current ADP refresh
- [ ] Velopack release on GitHub
- [ ] Beta with friends via mock drafts; fix what confuses them
- [ ] Portfolio write-up: approach, benchmark vs ADP, simulator results, screenshots

### August 2027: Real draft

---

## Open Questions / Deferred
- Current-season ADP source for 2027 (currently a manual Underdog CSV via 4for4)
- Code signing
- Real rookie model (college production, draft capital, landing spot), post-August
- Coaching tendencies (head-coach pass-over-expected, pace, 4th-down aggression): deferred, needs scoping
- Vegas implied totals: in the model as the team's PRIOR-season total only (the season's own lines leaked results); a true preseason line source would need a new data feed
- Component-stat projections for custom scoring
- Archetype-based RMSE splits for ceiling/floor (from plan.txt V2 list)
