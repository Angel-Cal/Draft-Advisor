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

### Phase 0: Housekeeping (Nov 2026)
- [ ] Fix `config/settings.yaml` (3 WR, 8 bench, no K/DST, correct seasons)
- [ ] Fix README drift (`recommend.py` vs `recommender.py`, Vegas totals claim)
- [ ] Move dead scaffolds (`vbd.py`, `simulator.py`, `app/cli.py`) to an `archive/` folder or delete
- [ ] Draft projection file schema v1

### Phase 1: Evaluation data (Nov to Dec 2026)
- [ ] Check how far back nflverse/ffverse historical FantasyPros ECR goes (possible ADP stand-in)
- [ ] Wayback Machine ADP scraper for remaining gaps: use the CDX API, one consistent snapshot date per year (closest to Sept 1), one parser per site layout era
- [ ] Save walk-forward out-of-sample predictions in `train.py` instead of discarding them
- [ ] Export one season file per held-out season: OOS projections + that year's ADP + actual points
- [ ] First benchmark: my projections vs ADP on held-out seasons

### Phase 2: C# core and simulator (Dec 2026 to Jan 2027)
- [ ] Solution with `DraftBot.Core`, `DraftBot.Sim`, test project
- [ ] League settings model; replacement level, VOR, per-position tiers (by value dropoff, not global quantiles)
- [ ] Draft state (snake order, all rosters, pool)
- [ ] Port the current recommender as the baseline
- [ ] Simulator: opponents draft by ADP plus noise with basic roster constraints; score rosters with actual points
- [ ] Baseline results for pure ADP, pure VOR and current recommender

### Phase 3: Model v2 (Jan to Feb 2027, after the 2026 regular season ends)
- [ ] Grade 2026 projections and recommendations against real 2026 results
- [ ] Pull 2026 data, retrain
- [ ] Team-context features (target/rush/snap rank within team, QB quality on receivers, team pass rate and pace), all lagged, joined on the player's **current** team so free-agency and trade moves are reflected
- [ ] Half-PPR and standard targets
- [ ] ADP-to-points fallback curve for rookies and missing players

### Phase 4: Recommender v2 (Feb to Apr 2027)
- [ ] Single score across all available players (replaces position-first selection)
- [ ] Add components one at a time; keep each only if the simulator shows improvement:
  - roster need (nonlinear, ramps up mid-draft)
  - tier cliff / cost of waiting until next pick
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
- Vegas implied totals as a feature
- Component-stat projections for custom scoring
- Archetype-based RMSE splits for ceiling/floor (from plan.txt V2 list)
