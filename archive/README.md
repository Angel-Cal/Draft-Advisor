# archive/

Code that is finished with: experiments whose question is answered, options the simulator rejected, and the Python advisor the C# side replaced.
It stays here so `LOG.md` entries can still point at the code behind a decision. Nothing in this folder is built, collected by pytest or listed in `.claude/CODEMAP.md`,
and most of it no longer compiles or imports against the current code.

**To rerun something here**, check out the last commit where it was live and run it there: `15f5baa` (branch `app-build`, 2026-11-04) for everything
moved in the 2026-11-05 refactor (LOG.md, "Refactor: concluded experiments archived"). Older files (`python/cli.py`, `python/simulator.py`, `python/vbd.py`) predate that.

| Folder | What | Why it is here |
|---|---|---|
| `csharp/Sim/` | `ReachTuning` (every `tune-*` sweep), `ArmSweep`, `ReachTrace` (`trace-reach`, `stability-reach`), `PickDiagnostics` (`diagnose`, `decompose`), `ScaleDiagnostics`, `SurvivalCalibration`, `TierTuning`, and the slot-arm summaries cut from `Experiment` | Each sweep chose or rejected a setting; the result is in LOG.md. `world-sweep` is the live harness for new arms. |
| `csharp/Core/` | `Rollout`, `SurvivalSampler` (simulated survival), `ByeSchedule` (bye-week cover) | Rejected advisor terms. Their options were also removed from `NeedSettings`, `WaitSettings`, `ReachSettings` and `ValueCandidate`: starter option, bye cover, lookahead, horizon, standardized mixing, active rounds/positions, survival spread, simulated opponents, alternative-reach modes, survival-scaled reach cost, free zone in sigmas, gap-term switch. |
| `csharp/Tests/` | The tests of the above (`RemovedTests.cs` holds methods cut from live test files) | They test archived code. |
| `python/evaluation/` | 27 one-off studies (short-season fixes, QB studies, ablations, gap attribution, handcuffs, ...) | Concluded; kept in `src/evaluation/` are only the pipeline steps, the 2026 pre-registration's scoring code (incl. `gap_attribution`) and its imports, the planned 2026 reruns (`rb_premium`, `rb_wr_stability`) and the `world_sweep` driver. |
| `python/draft/`, `python/tests/` | The Phase 1 Python advisor (`advisor`, `draft_state`, `recommender`, `roster`) and its tests; the ceiling/floor/tier/value-gap columns `vor.py` computed for it | Superseded by `csharp/src/DraftBot.Core`. `vor.py` itself lives on as `src/data/advisor_table.py`. |
| `plan.txt` | The original Python advisor spec | Describes the superseded advisor. |
