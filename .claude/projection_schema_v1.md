# Projection File Schema — v1

**Status:** Implemented in Phase 2 (`src/data/export_projections.py`, validated by `check_projection_file` in `validate.py`)
**Contract:** Python writes this file; C# reads it. Neither side needs to know the other's internals.

---

## File

`projections_<season>_v1.json`, saved to `data/processed/` locally; the live file is published as a GitHub Release asset.

- **Live file** (`kind: "live"`): next season's projections, e.g. `projections_2026_v1.json`. ADP is the Underdog CSV.
- **Backtest files** (`kind: "backtest"`): one per held-out season 2021–2025. Projections are walk-forward (out of
  sample), ADP is FantasyPros (day before the opener), and every player carries `actual_ppr` for the simulator.
  Same schema as the live file, so the simulator runs the code path the app ships.

Strict JSON (no `NaN`; missing values are `null`).

## Header

| Field | Type | Notes |
|-------|------|-------|
| `schema_version` | string | Literal `"v1"`. C# refuses a file it does not understand. |
| `kind` | string | `"live"` or `"backtest"`. |
| `season` | int | The season being projected (2026 for the live file). |
| `adp_source` | string | `"underdog"` (live) or `"fantasypros"` (backtest). The two price positions differently. |
| `position_rmse` | object | Walk-forward RMSE per position, `{QB, RB, WR, TE}` (QB 84.28, RB 58.86, WR 53.48, TE 38.69 as of 2026-10; 5-seed mean over test seasons 2021–2025). Used for ceiling/floor and tier thresholds in C#. |
| `generated_utc`, `git_commit` | string | Provenance. |
| `players` | array | One object per player, below. |

## Player fields

| Field | Type | Notes |
|-------|------|-------|
| `player_id` | string | GSIS ID (nflverse). Primary key. Players with no GSIS ID get a synthetic `market:<name>` ID (always `market_estimate: true`). |
| `player_name` | string | Display name. |
| `position` | string | One of `QB`, `RB`, `WR`, `TE`. |
| `team` | string | Most recent team, nflverse spelling. `"FA"` = no team on file (pre-draft rookie, unsigned veteran, unknown). |
| `projected_ppr` | float | Projected full-season PPR points. Pure model output (no ADP blend), or the ADP-curve estimate when `market_estimate`. |
| `projected_half`, `projected_standard` | float\|null | Always `null` in v1 (Phase 3). |
| `games` | int | Games played in the most recent qualifying season (the season before `season`). |
| `games_delta` | int | Change in games vs the season before that. C# derives the availability adjustment from `games < 13 AND games_delta < -5`. |
| `adp` | float | ADP from `adp_source`. Present for every player the exporter writes (the pool is the ADP-ranked players); readers still treat `null` as unranked. |
| `injury_flag` | bool | Durability flag: averaged under 15 games over their qualifying seasons (>= 2 seasons of >= 4 games) before `season`. The recommender's risk penalty reads this. Always `false` for market-estimate rows. |
| `market_estimate` | bool | `true` if the projection is the ADP-derived fallback (rookies, anyone the model cannot score). |
| `actual_ppr` | float\|null | Backtest files only: the player's actual season PPR (`0` if they never played). `null` in live files. |
| `weekly_ppr` | array(18) | Backtest files only, optional: regular-season PPR for weeks 1-18, `null` where the player did not play (bye, injury, inactive). Sums to `actual_ppr`; the simulator uses it for weekly lineup scoring. Absent in live files. |

---

## Constraints

- One row per player. No duplicates on `player_id`.
- Positions limited to QB / RB / WR / TE. K and DST excluded.
- `projected_ppr` is always present and finite.
- Pool = players ranked by ADP (about 300 in the live file, ADP rank <= 300 in backtests).
- Backtest `actual_ppr` is never `null`. Players drafted but with no stats row (injured all year) score `0`, not dropped.

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| v1 | 2026-10 | Initial schema, drafted in Phase 0 as parquet + CSV. Finalized in Phase 2 as JSON with a header: `underdog_adp` became `adp` + header `adp_source`; `position_rmse` and `schema_version` moved from per-row to the header; added `kind`, `season`, `actual_ppr`, optional backtest `weekly_ppr`; `injury_flag` redefined to match the code (durability flag; the old "games < 13" rule is the availability adjustment, now derived in C#); `team` may be `"FA"`. |

---

## Future Fields (deferred)

- `projected_receptions` — needed for accurate half/standard derivation
- `team_context_tier` — depth-chart rank within team (Phase 3 feature work)
