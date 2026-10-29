# DraftBot

Fantasy football draft assistant. Python (research, runs locally) trains LightGBM projections and exports versioned JSON files;
C# (.NET 9, the product) reads only those files and does all draft-time logic: VOR, tiers, recommender, draft state, simulator.
Contract between the two: `.claude/projection_schema_v1.md`.

## Where to look first

- `.claude/CODEMAP.md`: every source file with its public classes/functions and what they do, grouped by directory (`## csharp/src/DraftBot.Core/` etc.).
  Grep it for a name or concept, or read only the directory section you need, before searching or opening source files.
- `.claude/STATUS.md`, section "Hand-off": current state, settled decisions, next candidates.
- `.claude/LOG.md`: why each decision was made (read the relevant entry, not the whole file). `.claude/ROADMAP.md`: phases and goals.

## Layout

- `src/data` scrape, clean, validate, export JSON | `src/features` feature engineering | `src/models` train/predict |
  `src/evaluation` benchmarks and ablations | `src/draft` the old Python advisor (superseded by C#; `vor.py` and `market_fallback.py` are still used by the pipeline)
- `csharp/src/DraftBot.Core` draft logic | `csharp/src/DraftBot.Sim` simulator and CLI (`Program.cs` lists the commands) | `csharp/src/DraftBot.App` app screens (Razor) | `csharp/src/DraftBot.Desktop` WPF host | `csharp/tests`
- `archive/` dead code; `data/` is generated (gitignored), large, and should not be read wholesale

## Commands

- Python tests: `venv/Scripts/python -m pytest -q` | C# tests: `cd csharp && dotnet test`
- Pipeline order and every Sim command: `.claude/STATUS.md`, section "Pipeline: how to rebuild everything"
- After adding, renaming or re-documenting code: `venv/Scripts/python tools/gen_codemap.py` (`--check` reports a stale map)

## Conventions

- Document public C# members with `/// <summary>` and Python functions with docstrings; the first sentence feeds the code map.
- Log decisions that rejected an alternative or changed results in `.claude/LOG.md`; update STATUS.md's hand-off when the state changes.
